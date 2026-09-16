import json
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .services import chatbot_service, llm_client, quick_actions

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "chatbot:ratelimit"


def _error(codigo, status=400):
    return JsonResponse({"ok": False, "error": codigo}, status=status)


def _session_key(request):
    session = request.session
    # Una cookie con sesión caducada trae session_key pero no existe en BD: se recrea
    if not session.session_key or not session.exists(session.session_key):
        session.create()
    return session.session_key


def _rate_limit_key(request):
    # Identidad real del turista (usuario o sesión), nunca IP ni nada del payload.
    if request.user.is_authenticated:
        return f"{_CACHE_PREFIX}:user:{request.user.pk}"
    return f"{_CACHE_PREFIX}:session:{_session_key(request)}"


def _excede_rate_limit(clave):
    """Ventana fija simple sobre django.core.cache. Fail-open: si el backend
    de cache falla, se loguea y se permite la request (nunca 500 al turista
    por un problema de cache)."""
    try:
        cache.add(clave, 0, timeout=settings.CHATBOT_RATE_LIMIT_WINDOW_SECONDS)
        contador = cache.incr(clave)
    except Exception:
        logger.warning("chatbot_rate_limit_cache_error", exc_info=True)
        return False
    return contador > settings.CHATBOT_RATE_LIMIT_REQUESTS


def _serializar_mensaje(mensaje):
    datos = {
        "id": mensaje.pk,
        "rol": mensaje.rol,
        "contenido": mensaje.contenido,
        "tipo_fuente": mensaje.tipo_fuente or None,
        "creado": mensaje.creado.isoformat(),
    }
    # Extensión backward-compatible: nunca se persiste, solo viaja en esta
    # respuesta HTTP (ver chatbot_service._persistir_turno).
    presentacion = getattr(mensaje, "presentacion", None)
    if presentacion:
        datos["presentacion"] = presentacion
    return datos


@require_POST
def enviar_mensaje(request):
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return _error("json_invalido")
    if not isinstance(payload, dict):
        return _error("json_invalido")

    # Exactamente uno: mensaje (texto libre → IA) o accion (acción rápida → sin IA)
    if ("mensaje" in payload) == ("accion" in payload):
        return _error("payload_invalido")

    if "accion" in payload:
        accion = payload["accion"]
        try:
            quick_actions.resolver(accion)
        except quick_actions.AccionInvalida:
            return _error("accion_invalida")

        def operacion(conversacion):
            return chatbot_service.procesar_accion(conversacion, accion)
    else:
        try:
            contenido = chatbot_service.normalizar_mensaje(payload.get("mensaje"))
        except chatbot_service.MensajeInvalido as exc:
            return _error(exc.codigo)

        def operacion(conversacion):
            return chatbot_service.procesar_turno(conversacion, contenido)

    # Solo una request bien formada (payload válido, acción/mensaje válidos)
    # consume cupo: un JSON inválido o una acción desconocida no cuenta.
    if _excede_rate_limit(_rate_limit_key(request)):
        return _error("demasiadas_solicitudes", 429)

    if request.user.is_authenticated:
        conversacion = chatbot_service.obtener_o_crear_conversacion(usuario=request.user)
    else:
        conversacion = chatbot_service.obtener_o_crear_conversacion(
            session_key=_session_key(request)
        )

    inicio = time.perf_counter()

    def _resultado(status):
        # Métrica operativa mínima del turno HTTP: nunca contenido/reasoning/payload.
        logger.info(
            "chatbot_request conversacion=%s http_status=%s success=%s ms=%.0f",
            conversacion.pk, status, status == 200, (time.perf_counter() - inicio) * 1000,
        )
        return status

    try:
        _, respuesta = operacion(conversacion)
    except llm_client.ChatbotNoConfigurado as exc:
        logger.warning("Pillco Bot no disponible: %s", exc)
        return _error("chatbot_no_disponible", _resultado(503))
    except llm_client.ProveedorIATimeout:
        logger.warning("timeout del proveedor de IA conversacion=%s", conversacion.pk)
        return _error("proveedor_ia_timeout", _resultado(504))
    except llm_client.ProveedorIARateLimit:
        # El límite es del proyecto/proveedor, no del turista: indisponibilidad temporal
        logger.warning("chatbot_ai_rate_limit conversacion=%s", conversacion.pk)
        return _error("chatbot_no_disponible", _resultado(503))
    except (llm_client.ProveedorIAError, chatbot_service.OrquestacionError) as exc:
        logger.warning("fallo del proveedor de IA conversacion=%s: %s", conversacion.pk, exc)
        return _error("proveedor_ia_error", _resultado(502))
    except Exception:
        logger.exception("error interno del chatbot conversacion=%s", conversacion.pk)
        return _error("error_interno", _resultado(500))

    _resultado(200)
    return JsonResponse(
        {
            "ok": True,
            "conversation_id": conversacion.pk,
            "respuesta": _serializar_mensaje(respuesta),
        }
    )
