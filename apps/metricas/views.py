import logging
import re
import uuid

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import translation
from django.views.decorators.http import require_POST
from django.views.i18n import set_language

from .choices import TipoInteraccion
from .services.entidades import TIPOS_FRONTEND, validar_evento_frontend
from .services.real import (
    MAX_INCREMENTO_SEG,
    excede_limite_eventos,
    habilitado,
    obtener_o_crear_visitante_real,
    registrar_evento_real,
    registrar_tiempo_visible,
    seguimiento_permitido,
)

logger = logging.getLogger(__name__)


def _idioma_soportado(codigo):
    try:
        return translation.get_supported_language_variant(codigo)
    except LookupError:
        return None


def cambiar_idioma(request):
    """Envoltorio de django.views.i18n.set_language: mismo comportamiento y respuesta, más la métrica.

    Cuenta `idioma_cambiado` solo si Django efectivamente fijó una cookie de idioma soportado DISTINTO del
    idioma que estaba activo (ES→ES, EN→EN, GET o idioma inválido no cuentan).
    """
    anterior = _idioma_soportado(getattr(request, "LANGUAGE_CODE", None) or translation.get_language())
    response = set_language(request)
    cookie = response.cookies.get(settings.LANGUAGE_COOKIE_NAME)
    nuevo = _idioma_soportado(cookie.value) if cookie is not None else None
    if nuevo and anterior and nuevo != anterior:
        registrar_evento_real(request, TipoInteraccion.IDIOMA_CAMBIADO, meta={"de": anterior, "a": nuevo})
    return response


MAX_CAMPO = 100


@require_POST
def registrar_evento_frontend(request):
    """Recibe eventos de interacción enviados por metricas.js (formulario corto, compatible con sendBeacon).

    - CSRF: el token viaja en el cuerpo (`csrfmiddlewaretoken`); CsrfViewMiddleware lo valida (sin csrf_exempt).
    - Respuestas mínimas y sin detalles internos: 204 = aceptado o ignorado en silencio (seguimiento apagado, staff,
      bots, visitante desconocido); 400 = petición inválida; 429 = demasiados eventos.
    - Solo se aceptan los tipos de frontend; chatbot, favoritos e idioma se registran únicamente en el servidor.
    - Un clic legítimo ocurre en una página ya vista, así que el visitante ya existe: no se crean visitantes aquí
      (impide inundar la BD con visitantes nuevos sin guardar IP). Tampoco se crean sesiones ni páginas vistas.
    """
    if not habilitado() or not seguimiento_permitido(request):
        return HttpResponse(status=204)
    datos = request.POST
    tipo = datos.get("tipo", "")[:MAX_CAMPO]
    click_id = None
    if datos.get("click_id"):
        try:
            click_id = uuid.UUID(datos["click_id"][:MAX_CAMPO])
        except ValueError:
            return JsonResponse({"ok": False}, status=400)
    if tipo not in TIPOS_FRONTEND:
        return JsonResponse({"ok": False}, status=400)
    visitante = obtener_o_crear_visitante_real(request, crear=False)
    if visitante is None:
        return HttpResponse(status=204)
    validado = validar_evento_frontend(
        tipo, datos.get("via", "")[:MAX_CAMPO], datos.get("entidad_tipo", "")[:MAX_CAMPO],
        datos.get("entidad_id", "")[:MAX_CAMPO], datos.get("entidad_slug", "")[:MAX_CAMPO],
        datos.get("modo", "")[:MAX_CAMPO],
    )
    if validado is None:
        return JsonResponse({"ok": False}, status=400)
    if excede_limite_eventos(visitante):
        return JsonResponse({"ok": False}, status=429)
    entidad_tipo, entidad_id, meta = validado
    registrar_evento_real(request, tipo, entidad_tipo=entidad_tipo, entidad_id=entidad_id, meta=meta, click_id=click_id)
    return HttpResponse(status=204)


@require_POST
def registrar_duracion(request):
    """Recibe el tiempo visible (en segundos enteros) que reporta metricas.js: heartbeat, ocultar pestaña o pagehide.

    - CSRF en el cuerpo (como /metricas/evento/), sin csrf_exempt. Respuestas mínimas.
    - 204: registrado o ignorado en silencio (seguimiento apagado, staff, bots).
    - 400: `segundos` no es un entero de 1 a MAX_INCREMENTO_SEG (el cliente no puede enviar valores libres).
    - 410: no hay visitante o sesión analítica vigente. No se crea ni se revive nada; metricas.js deja de enviar
      heartbeats en esa página y la próxima navegación normal abrirá una sesión nueva.
    - El cliente no manda ids ni marcas de tiempo: visitante y sesión salen de las cookies y el servidor acota el
      incremento con el reloj real (ver registrar_tiempo_visible).
    """
    if not habilitado() or not seguimiento_permitido(request):
        return HttpResponse(status=204)
    bruto = request.POST.get("segundos", "")
    if not re.fullmatch(r"[0-9]{1,3}", bruto) or not 1 <= int(bruto) <= MAX_INCREMENTO_SEG:
        return JsonResponse({"ok": False}, status=400)
    try:
        registrado = registrar_tiempo_visible(request, int(bruto))
    except Exception:
        logger.exception("metricas: no se pudo registrar el tiempo visible")
        return HttpResponse(status=204)  # un fallo analítico nunca rompe la navegación ni detiene al cliente
    return HttpResponse(status=204 if registrado else 410)
