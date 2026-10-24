"""Clasificación en memoria de bots, dispositivo y fuente de tráfico. Funciones puras.

Privacidad: el user-agent y el referrer completos se analizan aquí y se DESCARTAN; solo el resultado
(categoría) y el host externo del referrer salen de estas funciones.
"""
import re
from urllib.parse import urlsplit

from apps.metricas.choices import DispositivoAcceso, FuenteTrafico

# Filtro mínimo y conservador (no es un sistema anti-bot). Un UA vacío NO se considera bot.
_PATRON_BOT = re.compile(r"bot|crawler|spider|slurp|headless|wget|curl", re.IGNORECASE)


def es_bot(user_agent):
    return bool(user_agent and _PATRON_BOT.search(user_agent))


def clasificar_dispositivo(user_agent):
    """MOVIL, TABLET o ESCRITORIO a partir del user-agent (sin guardarlo). Sin UA: ESCRITORIO."""
    ua = (user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua or "kindle" in ua or "silk/" in ua or ("android" in ua and "mobile" not in ua):
        return DispositivoAcceso.TABLET
    if "mobi" in ua or any(clave in ua for clave in ("iphone", "ipod", "android", "windows phone", "blackberry")):
        return DispositivoAcceso.MOVIL
    return DispositivoAcceso.ESCRITORIO


_BUSCADORES = {
    "google", "bing", "duckduckgo", "yahoo", "ecosia", "baidu", "yandex", "brave", "startpage", "qwant", "ask",
}
# Respuestas de login OAuth (allauth): no son búsquedas.
_NO_ORGANICOS = {"accounts.google.com"}
_REDES = {
    "facebook", "instagram", "twitter", "tiktok", "youtube", "whatsapp", "linkedin", "pinterest", "reddit",
    "telegram", "threads",
}
_REDES_HOST = {"t.co", "x.com", "fb.com", "wa.me", "lnkd.in", "youtu.be"}
_MEDIOS_PAGADOS_O_CAMPANA = {"cpc", "ppc", "paid", "paidsearch", "display", "banner", "email", "newsletter", "sms"}
_MEDIOS_SOCIALES = {"social", "social-network", "social-media", "sm"}


def _host(url):
    """Host en minúsculas y sin puerto de una URL; '' si no es una URL con host."""
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _etiquetas(host):
    return set(host.split("."))


def clasificar_fuente(referrer, host_propio, utm_source="", utm_medium=""):
    """(fuente, referrer_host) de una sesión que COMIENZA.

    Reglas, en orden:
    1. UTM reconocible (se analiza en memoria y no se guarda): medio social -> SOCIAL; medio 'organic' ->
       ORGANICO; medio 'referral' -> REFERIDO; medios de campaña (cpc, email…) -> OTROS; UTM no
       reconocible sin referrer externo -> OTROS.
    2. Sin referrer, o con referrer del propio sitio -> DIRECTO. Un enlace interno que abre una sesión
       nueva (p. ej. se volvió a la pestaña tras 30 min) no es una adquisición: es DIRECTO y no guarda host.
    3. Buscador conocido -> ORGANICO; red social conocida -> SOCIAL; cualquier otro host externo -> REFERIDO.
    `referrer_host` solo se devuelve para referrers externos (nunca la URL completa).
    """
    host = _host(referrer)
    propio = (host_propio or "").split(":")[0].lower()
    externo = bool(host) and host != propio
    host_guardado = host if externo else ""

    medio, origen = (utm_medium or "").strip().lower(), (utm_source or "").strip().lower()
    if medio or origen:
        if medio in _MEDIOS_SOCIALES or origen in _REDES:
            return FuenteTrafico.SOCIAL, host_guardado
        if medio == "organic":
            return FuenteTrafico.ORGANICO, host_guardado
        if medio == "referral":
            return FuenteTrafico.REFERIDO, host_guardado
        if medio in _MEDIOS_PAGADOS_O_CAMPANA or not externo:
            return FuenteTrafico.OTROS, host_guardado

    if not externo:
        return FuenteTrafico.DIRECTO, ""
    etiquetas = _etiquetas(host)
    if host in _NO_ORGANICOS:
        return FuenteTrafico.REFERIDO, host_guardado
    if etiquetas & _BUSCADORES:
        return FuenteTrafico.ORGANICO, host_guardado
    if etiquetas & _REDES or host in _REDES_HOST:
        return FuenteTrafico.SOCIAL, host_guardado
    return FuenteTrafico.REFERIDO, host_guardado
