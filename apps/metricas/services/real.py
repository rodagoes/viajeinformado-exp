"""Seguimiento REAL server-side: visitante, sesión analítica, páginas vistas y eventos.

Reglas de diseño
- Todo queda detrás de settings.METRICAS_REAL_HABILITADAS.
- Cookies propias: `vi_vid` (visitante, 1 año) y `vi_sid` (sesión analítica, 30 min de inactividad), ambas
  HttpOnly + SameSite=Lax (+ Secure fuera de DEBUG). La sesión analítica NO es la sesión de Django.
- No se guarda IP, user-agent, URL de referrer, querystring ni texto del chatbot.
- Un fallo de métricas jamás debe romper la funcionalidad principal: los puntos de entrada públicos
  (`registrar_pagina_vista`, `registrar_evento_real`, `aplicar_cookies`) capturan y registran los errores.
- Duración: `duracion_seg` es el TIEMPO VISIBLE aproximado que reporta el navegador (metricas.js: heartbeat cada 30 s,
  visibilitychange y pagehide) y SOLO lo modifica `registrar_tiempo_visible`. Los hits del servidor (páginas, eventos)
  solo mueven `fin` (= última actividad conocida): no suman tiempo, así que no hay doble conteo ni se cuenta el tiempo
  con la pestaña oculta. Una sesión sin señal del navegador (JavaScript bloqueado) queda con duración 0.
  Protección contra inflación: máximo por envío, la duración nunca supera el tiempo real transcurrido desde `inicio` y
  hay un tope absoluto por sesión. No es engagement time de GA4 (que usa otros criterios): son aproximaciones distintas.
- Limitación conocida: dos primeras peticiones simultáneas sin cookies pueden crear dos visitantes/sesiones.
"""
import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Greatest, Least
from django.utils import timezone

from apps.metricas.choices import OrigenDato, TipoInteraccion
from apps.metricas.models import EventoMetrica, SesionMetrica, VisitanteMetrica

from .clasificacion import clasificar_dispositivo, clasificar_fuente, es_bot

logger = logging.getLogger(__name__)

COOKIE_VISITANTE = "vi_vid"
COOKIE_SESION = "vi_sid"
VIDA_COOKIE_VISITANTE = 365 * 24 * 3600
INACTIVIDAD_SESION = timedelta(minutes=30)
MAX_INCREMENTO_SEG = 60  # por envío (el cliente reporta cada 30 s)
MAX_DURACION_SESION_SEG = 2 * 3600  # tope absoluto de tiempo visible acumulable por sesión
REAL = OrigenDato.REAL
_TIPOS_VALIDOS = set(TipoInteraccion.values)

# No son páginas de contenido del sitio.
PREFIJOS_EXCLUIDOS = (
    "/admin/", "/static/", "/media/", "/metricas/", "/chatbot/", "/i18n/", "/favicon.ico", "/robots.txt",
    "/health", "/healthz", "/ping",
)


def habilitado():
    return bool(getattr(settings, "METRICAS_REAL_HABILITADAS", False))


def ahora():
    return timezone.now()


# ---------------------------------------------------------------- contexto por request

class _Contexto:
    """Estado del seguimiento durante UNA petición (evita repetir consultas y duplicar cookies)."""

    def __init__(self):
        self.visitante = None
        self.sesion = None
        self.sesion_resuelta = False
        self.cookies = {}  # nombre -> (valor, max_age)


def _contexto(request):
    ctx = getattr(request, "_metricas", None)
    if ctx is None:
        ctx = request._metricas = _Contexto()
    return ctx


def _usuario(request):
    usuario = getattr(request, "user", None)
    return usuario if usuario is not None and usuario.is_authenticated else None


def seguimiento_permitido(request):
    """False para staff/superusuarios autenticados (su navegación no es de turistas) y bots."""
    usuario = _usuario(request)
    if usuario is not None and (usuario.is_staff or usuario.is_superuser):
        return False
    return not es_bot(request.META.get("HTTP_USER_AGENT", ""))


def _uuid_cookie(request, nombre):
    try:
        return uuid.UUID(request.COOKIES.get(nombre, ""))
    except (ValueError, AttributeError, TypeError):
        return None


# ---------------------------------------------------------------- visitante

def obtener_o_crear_visitante_real(request, crear=True):
    """Visitante REAL de la petición (cookie `vi_vid`); lo crea si falta o la cookie es inválida.

    Con `crear=False` solo busca: devuelve None (sin crear nada ni dejar cookies) si no hay un visitante válido.

    - `primera_visita` = fecha local de Lima de la creación.
    - Usuario autenticado (no staff): se vincula `usuario` y `es_registrado=True` si el visitante aún no
      tenía usuario. Si el visitante ya está vinculado a OTRO usuario (mismo navegador, otra cuenta) NO se
      mezclan identidades: el visitante conserva a su primer usuario y se registra un aviso. No hay fusión
      de visitantes entre cookies o dispositivos en esta fase.
    """
    ctx = _contexto(request)
    if ctx.visitante is not None:
        return ctx.visitante
    usuario = _usuario(request)
    registrado = usuario is not None and not usuario.is_staff
    visitante = None
    cookie = _uuid_cookie(request, COOKIE_VISITANTE)
    if cookie is not None:
        visitante = VisitanteMetrica.objects.filter(uuid=cookie, origen=REAL).first()
    if visitante is None and not crear:
        return None
    if visitante is None:
        visitante = VisitanteMetrica.objects.create(
            origen=REAL, es_registrado=registrado, usuario=usuario if registrado else None,
            primera_visita=timezone.localdate(ahora()),
        )
    elif registrado:
        if visitante.usuario_id is None:
            VisitanteMetrica.objects.filter(pk=visitante.pk).update(usuario=usuario, es_registrado=True)
            visitante.usuario, visitante.es_registrado = usuario, True
        elif visitante.usuario_id != usuario.pk:
            logger.info("metricas: visitante %s ya vinculado a otro usuario; no se mezclan identidades", visitante.uuid)
    ctx.visitante = visitante
    ctx.cookies[COOKIE_VISITANTE] = (str(visitante.uuid), VIDA_COOKIE_VISITANTE)
    return visitante


# ---------------------------------------------------------------- sesión analítica

def obtener_sesion_vigente(request, visitante):
    """Sesión analítica activa (cookie `vi_sid`, del mismo visitante y con < 30 min de inactividad) o None. No crea."""
    ctx = _contexto(request)
    if ctx.sesion_resuelta:
        return ctx.sesion
    ctx.sesion_resuelta = True
    cookie = _uuid_cookie(request, COOKIE_SESION)
    if cookie is not None:
        sesion = SesionMetrica.objects.filter(uuid=cookie, visitante=visitante, origen=REAL).first()
        if sesion is not None and ahora() - (sesion.fin or sesion.inicio) <= INACTIVIDAD_SESION:
            ctx.sesion = sesion
    return ctx.sesion


def _renovar_cookie_sesion(request, sesion):
    _contexto(request).cookies[COOKIE_SESION] = (str(sesion.uuid), int(INACTIVIDAD_SESION.total_seconds()))


def _tocar_sesion(sesion, momento, paginas=0):
    """Marca actividad: `fin` no retrocede (Greatest) y las páginas se suman de forma atómica (F).
    No toca `duracion_seg`: el tiempo visible lo aporta solo el navegador (ver registrar_tiempo_visible)."""
    SesionMetrica.objects.filter(pk=sesion.pk).update(
        paginas_vistas=F("paginas_vistas") + paginas,
        fin=Greatest(F("fin"), Value(momento)),
    )


def _crear_sesion(request, visitante, momento):
    fecha = timezone.localdate(momento)
    fuente, host = clasificar_fuente(
        request.META.get("HTTP_REFERER", ""), request.get_host(),
        request.GET.get("utm_source", ""), request.GET.get("utm_medium", ""),
    )
    return SesionMetrica.objects.create(
        visitante=visitante, origen=REAL, fecha=fecha, inicio=momento, fin=momento, paginas_vistas=1,
        duracion_seg=0, fuente=fuente, referrer_host=host[:255],
        dispositivo=clasificar_dispositivo(request.META.get("HTTP_USER_AGENT", "")),
        idioma=(getattr(request, "LANGUAGE_CODE", None) or settings.LANGUAGE_CODE)[:8],
        es_nueva=visitante.primera_visita == fecha,
    )


def pagina_elegible(request, response):
    """GET público con respuesta 200 HTML, sin redirects/errores, ni rutas internas, ni staff, ni bots."""
    if request.method != "GET" or response.status_code != 200 or getattr(response, "streaming", False):
        return False
    if not response.get("Content-Type", "").startswith("text/html"):
        return False
    if request.path.startswith(PREFIJOS_EXCLUIDOS):
        return False
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return False
    destino = request.headers.get("Sec-Fetch-Dest")  # fetch, iframe, prefetch…: no son páginas vistas
    if destino and destino != "document":
        return False
    if request.headers.get("Sec-Purpose", "").startswith("prefetch") or request.headers.get("Purpose") == "prefetch":
        return False
    return seguimiento_permitido(request)


def registrar_pagina_vista(request):
    """Cuenta una página vista (crea visitante y sesión si hace falta). Devuelve la SesionMetrica o None.

    La primera página de una sesión nace con paginas_vistas=1 y no se vuelve a sumar en la misma petición.
    """
    try:
        momento = ahora()
        with transaction.atomic():
            visitante = obtener_o_crear_visitante_real(request)
            sesion = obtener_sesion_vigente(request, visitante)
            ctx = _contexto(request)
            if sesion is None:
                sesion = ctx.sesion = _crear_sesion(request, visitante, momento)
            else:
                _tocar_sesion(sesion, momento, paginas=1)
        _renovar_cookie_sesion(request, sesion)
        return sesion
    except Exception:
        logger.exception("metricas: no se pudo registrar la página vista")
        return None


# ---------------------------------------------------------------- tiempo visible

def registrar_tiempo_visible(request, segundos):
    """Suma `segundos` de tiempo visible a la sesión analítica vigente. True si se registró, False si no hay sesión.

    - Nunca crea visitantes ni sesiones, y no revive una sesión expirada (la siguiente navegación crea una nueva).
    - Atómico en la BD: nueva duración = máx(actual, mín(actual + segundos, tiempo transcurrido desde `inicio`, tope)).
      Así nunca decrece, nunca supera el reloj real y un cliente no puede inflarla libremente.
    - También cuenta como actividad: mueve `fin` (y el endpoint renueva la cookie `vi_sid`).
    """
    visitante = obtener_o_crear_visitante_real(request, crear=False)
    if visitante is None:
        return False
    sesion = obtener_sesion_vigente(request, visitante)
    if sesion is None:
        return False
    momento = ahora()
    tope = min(MAX_DURACION_SESION_SEG, max(0, int((momento - sesion.inicio).total_seconds())))
    entero = models.IntegerField()
    SesionMetrica.objects.filter(pk=sesion.pk).update(
        duracion_seg=Greatest(
            F("duracion_seg"),
            Least(F("duracion_seg") + segundos, Value(tope, output_field=entero), output_field=entero),
            output_field=entero,
        ),
        fin=Greatest(F("fin"), Value(momento)),
    )
    _renovar_cookie_sesion(request, sesion)
    return True


# ---------------------------------------------------------------- eventos

MAX_CLAVE_META, MAX_VALOR_META, MAX_ITEMS_META = 20, 40, 6


def meta_segura(meta):
    """Solo pares clave:valor cortos y simples (str/int/bool); lo demás se descarta."""
    resultado = {}
    for clave, valor in (meta or {}).items():
        if len(resultado) >= MAX_ITEMS_META:
            break
        if isinstance(clave, str) and isinstance(valor, (str, int, bool)) and len(clave) <= MAX_CLAVE_META:
            resultado[clave] = valor[:MAX_VALOR_META] if isinstance(valor, str) else valor
    return resultado


def registrar_evento_real(request, tipo, entidad_tipo="", entidad_id=None, meta=None, click_id=None):
    """Registra un EventoMetrica REAL. Devuelve el evento, o None si no corresponde o si algo falla.

    - No crea sesiones ni suma páginas: si hay sesión vigente la asocia y la extiende; si no, `sesion` queda NULL.
    - Con `click_id` repetido devuelve el evento ya existente (idempotente).
    - Nunca lanza excepciones hacia el llamador.
    """
    if not habilitado():
        return None
    try:
        if tipo not in _TIPOS_VALIDOS or not seguimiento_permitido(request):
            return None
        momento = ahora()
        with transaction.atomic():
            if click_id is not None:
                existente = EventoMetrica.objects.filter(click_id=click_id).first()
                if existente is not None:
                    return existente
            visitante = obtener_o_crear_visitante_real(request)
            sesion = obtener_sesion_vigente(request, visitante)
            if sesion is not None:
                _tocar_sesion(sesion, momento)
                _renovar_cookie_sesion(request, sesion)
            return EventoMetrica.objects.create(
                sesion=sesion, visitante=visitante, origen=REAL, tipo=tipo, fecha=timezone.localdate(momento),
                entidad_tipo=(entidad_tipo or "")[:30], entidad_id=entidad_id, meta=meta_segura(meta),
                click_id=click_id,
            )
    except Exception:
        logger.exception("metricas: no se pudo registrar el evento %s", tipo)
        return None


def limite_eventos_por_minuto():
    return getattr(settings, "METRICAS_LIMITE_EVENTOS_POR_MINUTO", 30)


def excede_limite_eventos(visitante):
    """True si el visitante ya registró el máximo de eventos en el último minuto.

    Protección ligera contra abuso del endpoint, basada en la BD (sirve igual con varios workers, no usa
    LocMemCache ni IP). Un uso humano normal queda muy por debajo: un clic por acción explícita.
    """
    desde = ahora() - timedelta(seconds=60)
    return EventoMetrica.objects.filter(visitante=visitante, creado__gte=desde).count() >= limite_eventos_por_minuto()


def actualizar_meta_evento(evento, **cambios):
    """Agrega claves cortas al `meta` de un evento ya creado (p. ej. el resultado técnico). Nunca lanza."""
    if evento is None:
        return
    try:
        meta = meta_segura({**(evento.meta or {}), **cambios})
        EventoMetrica.objects.filter(pk=evento.pk).update(meta=meta)
        evento.meta = meta
    except Exception:
        logger.exception("metricas: no se pudo actualizar el evento %s", getattr(evento, "pk", None))


# ---------------------------------------------------------------- cookies

def aplicar_cookies(request, response):
    """Escribe en la respuesta las cookies que el seguimiento dejó pendientes. Nunca lanza."""
    try:
        ctx = getattr(request, "_metricas", None)
        if ctx is None:
            return
        for nombre, (valor, vida) in ctx.cookies.items():
            response.set_cookie(
                nombre, valor, max_age=vida, path="/", httponly=True, samesite="Lax", secure=not settings.DEBUG,
            )
    except Exception:
        logger.exception("metricas: no se pudieron escribir las cookies")
