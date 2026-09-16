"""
Proveedor Gemini (google-genai, Interactions API). Solo conoce el cliente,
la API key (settings del servidor, nunca el frontend), el timeout, la
configuración de generación, la traducción de errores del proveedor y la
normalización al contrato neutral que usa chatbot_service. No toca ORM ni
request. También define las excepciones comunes a todos los proveedores.
"""
import json
import logging

import httpx
from django.conf import settings
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from . import context_builder
from .gemini_tools import declaraciones_gemini

try:
    # Deuda técnica del SDK 2.23.0: la jerarquía de errores de Interactions
    # (APITimeoutError, APIStatusError, ...) no tiene ruta pública
    # (google.genai._interactions no existe) y no hereda de genai.errors.
    # Se aísla aquí, con fallback público (httpx / genai.errors) si la ruta
    # privada desaparece.
    from google.genai._gaos.lib import compat_errors as _errores_interactions
except ImportError:  # pragma: no cover
    _errores_interactions = None

logger = logging.getLogger(__name__)

NOMBRE = "gemini"
PROVEEDOR_SOPORTADO = NOMBRE
# Interactions API se sirve bajo v1beta (validado en vivo con gemini-3.6-flash).
API_VERSION = "v1beta"
THINKING_LEVELS = ("minimal", "low", "medium", "high")
ESTADOS_FALLIDOS = ("failed", "cancelled", "budget_exceeded", "incomplete")

# Única política de reintentos: la del SDK, explícita. En el puente de
# Interactions `attempts` se traduce a número de REINTENTOS (no de intentos
# totales): attempts=1 → 1 reintento → 2 solicitudes como máximo, con espera
# breve. Sin esto el SDK hacía 4 solicitudes y un 429 podía tardar ~80 s.
RETRY_ATTEMPTS = 1
RETRY_INITIAL_DELAY = 1.0  # segundos
RETRY_MAX_DELAY = 2.0  # segundos

ERRORES_TIMEOUT = (httpx.TimeoutException, TimeoutError)
ERRORES_PROVEEDOR = (genai_errors.APIError, httpx.HTTPError)
if _errores_interactions is not None:
    ERRORES_TIMEOUT = (_errores_interactions.APITimeoutError,) + ERRORES_TIMEOUT
    ERRORES_PROVEEDOR = (_errores_interactions.APIError,) + ERRORES_PROVEEDOR


class ChatbotNoConfigurado(Exception):
    """Falta o es inválida la configuración del proveedor; el chatbot no está disponible."""


class ProveedorIAError(Exception):
    """Fallo controlado del proveedor de IA."""


class ProveedorIATimeout(ProveedorIAError):
    pass


class ProveedorIARateLimit(ProveedorIAError):
    """Cuota o rate limit del proveedor (429): indisponibilidad temporal."""


_cache = {"config": None, "cliente": None}


def _configuracion():
    proveedor = settings.CHATBOT_AI_PROVIDER
    if proveedor != PROVEEDOR_SOPORTADO:
        raise ChatbotNoConfigurado(f"proveedor no soportado: {proveedor}")
    if not settings.CHATBOT_AI_API_KEY:
        raise ChatbotNoConfigurado("CHATBOT_AI_API_KEY no configurada")
    return (settings.CHATBOT_AI_API_KEY, int(settings.CHATBOT_AI_TIMEOUT_MS))


def opciones_http(timeout_ms):
    return types.HttpOptions(
        api_version=API_VERSION,
        timeout=timeout_ms,
        retry_options=types.HttpRetryOptions(
            attempts=RETRY_ATTEMPTS,
            initial_delay=RETRY_INITIAL_DELAY,
            max_delay=RETRY_MAX_DELAY,
        ),
    )


def obtener_cliente():
    config = _configuracion()
    if _cache["config"] != config:
        api_key, timeout_ms = config
        _cache["cliente"] = genai.Client(api_key=api_key, http_options=opciones_http(timeout_ms))
        _cache["config"] = config
    return _cache["cliente"]


def _es_rate_limit(exc):
    return 429 in (getattr(exc, "status_code", None), getattr(exc, "code", None))


def _retry_after(exc):
    respuesta = getattr(exc, "response", None)
    headers = getattr(respuesta, "headers", None)
    return headers.get("retry-after") if headers else None


def configuracion_generacion():
    """generation_config común a TODAS las rondas de una interacción."""
    nivel = settings.CHATBOT_AI_THINKING_LEVEL
    if nivel not in THINKING_LEVELS:
        raise ChatbotNoConfigurado(
            f"CHATBOT_AI_THINKING_LEVEL inválido: {nivel!r} (valores: {', '.join(THINKING_LEVELS)})"
        )
    return {"tool_choice": "auto", "thinking_level": nivel}


def _descripcion_segura(exc):
    # Nunca el mensaje bruto: puede arrastrar URL/headers de la petición.
    return f"{type(exc).__name__} status={getattr(exc, 'status_code', None)}"


def _registrar_uso(interaccion, modelo):
    uso = getattr(interaccion, "usage", None)
    if uso is None:
        return
    logger.info(
        "gemini modelo=%s interaccion=%s tokens_entrada=%s tokens_salida=%s tokens_total=%s",
        modelo,
        getattr(interaccion, "id", None),
        getattr(uso, "total_input_tokens", None),
        getattr(uso, "total_output_tokens", None),
        getattr(uso, "total_tokens", None),
    )


def crear_interaccion(**parametros):
    cliente = obtener_cliente()
    modelo = settings.CHATBOT_AI_MODEL
    try:
        interaccion = cliente.interactions.create(model=modelo, **parametros)
    except ERRORES_TIMEOUT as exc:
        raise ProveedorIATimeout("timeout del proveedor de IA") from exc
    except ERRORES_PROVEEDOR as exc:
        if _es_rate_limit(exc):
            logger.debug("chatbot_ai_rate_limit modelo=%s retry_after=%s", modelo, _retry_after(exc))
            raise ProveedorIARateLimit(_descripcion_segura(exc)) from exc
        raise ProveedorIAError(_descripcion_segura(exc)) from exc
    _registrar_uso(interaccion, modelo)
    return interaccion


# --- Contrato neutral de proveedor (usado por chatbot_service) -------------

def _normalizar(interaccion):
    """Interaction del SDK → {texto, tool_calls, usage}; sin objetos SDK fuera de aquí."""
    if interaccion.status in ESTADOS_FALLIDOS:
        raise ProveedorIAError(f"interaccion {interaccion.status}")
    tool_calls = [
        {"id": paso.id, "name": paso.name, "arguments": paso.arguments or {}}
        for paso in (interaccion.steps or [])
        if getattr(paso, "type", None) == "function_call"
    ]
    uso = getattr(interaccion, "usage", None)
    return {
        "texto": interaccion.output_text,
        "tool_calls": tool_calls,
        "usage": {
            "input_tokens": getattr(uso, "total_input_tokens", None),
            "output_tokens": getattr(uso, "total_output_tokens", None),
            "cached_tokens": getattr(uso, "total_cached_tokens", None),
            "reasoning_tokens": getattr(uso, "total_thought_tokens", None),
        },
    }


def iniciar_turno(system_instruction, historial, contenido):
    # tools/system_instruction/generation_config son interaction-scoped:
    # se reenvían íntegros en cada ronda, también con previous_interaction_id.
    configuracion = {
        "system_instruction": system_instruction,
        "tools": declaraciones_gemini(),
        "generation_config": configuracion_generacion(),
    }
    interaccion = crear_interaccion(
        input=context_builder.construir_input(historial, contenido), **configuracion
    )
    estado = {"configuracion": configuracion, "interaccion_id": interaccion.id}
    return estado, _normalizar(interaccion)


def continuar_turno(estado, resultados):
    pasos = [
        {
            "type": "function_result",
            "call_id": r["call_id"],
            "name": r["name"],
            "result": json.dumps(r["result"], ensure_ascii=False),
            "is_error": r["is_error"],
        }
        for r in resultados
    ]
    interaccion = crear_interaccion(
        input=pasos,
        previous_interaction_id=estado["interaccion_id"],
        **estado["configuracion"],
    )
    estado["interaccion_id"] = interaccion.id
    return estado, _normalizar(interaccion)
