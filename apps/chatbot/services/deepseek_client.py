"""
Proveedor DeepSeek (Responses API, stateless) sobre httpx. Solo conoce HTTP,
la serialización de la petición, el parsing de la respuesta (texto,
function calls, usage), el balance y la traducción de errores. No toca ORM,
no crea conversaciones, no renderiza. Django es la fuente de verdad del
historial: cada petición lleva el contexto completo (no hay
previous_response_id).
"""
import json
import logging

import httpx
from django.conf import settings

from ..models import Mensaje
from .llm_client import (
    ChatbotNoConfigurado,
    ProveedorIAError,
    ProveedorIARateLimit,
    ProveedorIATimeout,
)
from .tool_schemas import declaraciones_funcion

logger = logging.getLogger(__name__)

NOMBRE = "deepseek"
BASE_URL = "https://api.deepseek.com"
RUTA_RESPONSES = "/responses"
RUTA_BALANCE = "/user/balance"
# Un solo nivel para todas las rondas de un turno: con thinking + tools,
# DeepSeek exige recibir de vuelta el reasoning previo y cambiar el esfuerzo
# a mitad de interacción rompe esa continuidad (HTTP 400).
REASONING_EFFORT = "low"

_ROL = {Mensaje.Rol.USUARIO: "user", Mensaje.Rol.ASISTENTE: "assistant"}

# Campos que se reenvían de cada output item al continuar la ronda. Solo los
# soportados como input item por la Responses API de DeepSeek; nunca `id`,
# `status` ni otras propiedades internas de la respuesta.
_CAMPOS_ECO = {
    "reasoning": ("content", "summary", "encrypted_content"),
    "function_call": ("call_id", "name", "arguments"),
    "message": ("role", "content"),
}


def declaraciones_deepseek():
    return declaraciones_funcion()


def _api_key():
    key = settings.CHATBOT_DEEPSEEK_API_KEY
    if not key:
        raise ChatbotNoConfigurado("CHATBOT_DEEPSEEK_API_KEY no configurada")
    return key


def _solicitar(metodo, ruta, cuerpo=None):
    headers = {"Authorization": f"Bearer {_api_key()}", "Accept": "application/json"}
    try:
        respuesta = httpx.request(
            metodo,
            f"{BASE_URL}{ruta}",
            json=cuerpo,
            headers=headers,
            timeout=int(settings.CHATBOT_AI_TIMEOUT_MS) / 1000,
        )
    except httpx.TimeoutException as exc:
        raise ProveedorIATimeout("timeout del proveedor de IA") from exc
    except httpx.HTTPError as exc:
        raise ProveedorIAError(type(exc).__name__) from exc
    return _procesar(respuesta)


def _error_resumido(respuesta):
    """(error_type, error_code) cortos y seguros para el log; nunca el `message`
    (puede citar payload) ni el cuerpo bruto."""
    try:
        error = respuesta.json().get("error")
    except (ValueError, AttributeError):
        return None, None
    if not isinstance(error, dict):
        return None, None
    return (
        str(error.get("type") or "")[:60] or None,
        str(error.get("code") or "")[:60] or None,
    )


def _procesar(respuesta):
    # Nunca el cuerpo bruto en las excepciones: solo clase/status.
    status = respuesta.status_code
    if status in (401, 403):
        raise ChatbotNoConfigurado(f"DeepSeek rechazó las credenciales (status={status})")
    if status == 402:
        raise ChatbotNoConfigurado("DeepSeek: saldo insuficiente (status=402)")
    if status == 429:
        logger.debug("chatbot_ai_rate_limit modelo=%s", settings.CHATBOT_DEEPSEEK_MODEL)
        raise ProveedorIARateLimit("RateLimit status=429")
    if status >= 400:
        exc = ProveedorIAError(f"HTTPStatusError status={status}")
        exc.status = status
        exc.error_type, exc.error_code = _error_resumido(respuesta)
        raise exc
    try:
        datos = respuesta.json()
    except ValueError as exc:
        raise ProveedorIAError("respuesta no JSON") from exc
    if not isinstance(datos, dict):
        raise ProveedorIAError("respuesta inválida")
    return datos


def _parsear_argumentos(bruto):
    """Responses API envía `arguments` como JSON string. Inválido → None (no se ejecuta)."""
    if bruto in (None, ""):
        return {}
    if isinstance(bruto, dict):
        return bruto
    try:
        valor = json.loads(bruto)
    except (TypeError, ValueError):
        return None
    return valor if isinstance(valor, dict) else None


def _item_eco(item):
    """Copia de un output item con solo los campos reenviables (ver _CAMPOS_ECO)."""
    tipo = item.get("type")
    campos = _CAMPOS_ECO.get(tipo)
    if campos is None:
        return None
    eco = {"type": tipo}
    for campo in campos:
        if item.get(campo) is not None:
            eco[campo] = item[campo]
    return eco


def _normalizar(datos):
    """
    → ({"texto", "tool_calls", "usage"}, items_eco). `items_eco` conserva, en
    orden, reasoning + message + function_call de esta respuesta: es lo que
    la siguiente ronda del mismo turno debe reenviar (API stateless).
    """
    salida = datos.get("output")
    if not isinstance(salida, list):
        raise ProveedorIAError("respuesta sin output")
    textos, tool_calls, items_eco = [], [], []
    for item in salida:
        if not isinstance(item, dict):
            continue
        eco = _item_eco(item)
        if eco is not None:
            items_eco.append(eco)
        if item.get("type") == "message":
            for parte in item.get("content") or []:
                if isinstance(parte, dict) and parte.get("type") == "output_text":
                    textos.append(parte.get("text") or "")
        elif item.get("type") == "function_call":
            tool_calls.append({
                "id": item.get("call_id"),
                "name": item.get("name"),
                "arguments": _parsear_argumentos(item.get("arguments")),
            })
    uso = datos.get("usage") or {}
    usage = {
        "input_tokens": uso.get("input_tokens"),
        "output_tokens": uso.get("output_tokens"),
        "cached_tokens": (uso.get("input_tokens_details") or {}).get("cached_tokens"),
        "reasoning_tokens": (uso.get("output_tokens_details") or {}).get("reasoning_tokens"),
    }
    logger.info(
        "deepseek modelo=%s respuesta=%s tokens_entrada=%s tokens_salida=%s tokens_cache=%s",
        settings.CHATBOT_DEEPSEEK_MODEL, datos.get("id"),
        usage["input_tokens"], usage["output_tokens"], usage["cached_tokens"],
    )
    texto = "\n".join(t for t in textos if t) or None
    return {"texto": texto, "tool_calls": tool_calls, "usage": usage}, items_eco


def _mensajes(historial, contenido):
    items = [{"role": _ROL[m["rol"]], "content": m["contenido"]} for m in historial]
    items.append({"role": "user", "content": contenido})
    return items


def _responses(entrada, system_instruction, ronda):
    # Stateless: cada ronda reenvía instructions, tools y reasoning config;
    # nunca previous_response_id / conversation / store.
    cuerpo = {
        "model": settings.CHATBOT_DEEPSEEK_MODEL,
        "instructions": system_instruction,
        "input": entrada,
        "tools": declaraciones_deepseek(),
        "tool_choice": "auto",
        "reasoning": {"effort": REASONING_EFFORT},
    }
    try:
        datos = _solicitar("POST", RUTA_RESPONSES, cuerpo)
    except ProveedorIAError as exc:
        # Solo métricas de forma y el error resumido: nunca payload, historial,
        # instructions, tool outputs ni reasoning.
        logger.warning(
            "deepseek_http_error modelo=%s ronda=%s status=%s error_type=%s error_code=%s "
            "num_input_items=%s num_tool_calls=%s",
            settings.CHATBOT_DEEPSEEK_MODEL, ronda, getattr(exc, "status", None),
            getattr(exc, "error_type", None), getattr(exc, "error_code", None),
            len(entrada), sum(1 for i in entrada if i.get("type") == "function_call"),
        )
        raise
    return _normalizar(datos)


# --- Contrato neutral de proveedor (usado por chatbot_service) -------------
# El estado vive solo durante procesar_turno(): {"system", "entrada", "ronda"}.
# `entrada` acumula historial Django + mensaje actual + los output items de
# cada ronda (reasoning/message/function_call) + los function_call_output.
# Nunca se persiste (Django reconstruye el contexto en el siguiente turno).

def iniciar_turno(system_instruction, historial, contenido):
    entrada = _mensajes(historial, contenido)
    respuesta, items_eco = _responses(entrada, system_instruction, 1)
    estado = {"system": system_instruction, "entrada": entrada + items_eco, "ronda": 1}
    return estado, respuesta


def continuar_turno(estado, resultados):
    # Cada function_call_output se empareja con el call_id de su function_call
    # original (ya reenviada dentro de estado["entrada"]).
    salidas = [
        {
            "type": "function_call_output",
            "call_id": r["call_id"],
            "output": json.dumps(r["result"], ensure_ascii=False, default=str),
        }
        for r in resultados
    ]
    entrada = estado["entrada"] + salidas
    estado["ronda"] += 1
    respuesta, items_eco = _responses(entrada, estado["system"], estado["ronda"])
    estado["entrada"] = entrada + items_eco
    return estado, respuesta


def consultar_balance():
    """GET /user/balance normalizado. Solo diagnóstico backend; nunca imprime la key."""
    datos = _solicitar("GET", RUTA_BALANCE)
    return {
        "is_available": bool(datos.get("is_available")),
        "balance_infos": [
            {
                "currency": info.get("currency"),
                "total_balance": info.get("total_balance"),
                "granted_balance": info.get("granted_balance"),
                "topped_up_balance": info.get("topped_up_balance"),
            }
            for info in (datos.get("balance_infos") or [])
            if isinstance(info, dict)
        ],
    }
