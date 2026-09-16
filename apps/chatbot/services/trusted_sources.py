"""
Allowlist centralizada de fuentes externas confiables. Solo se acepta como
evidencia una URL https cuyo hostname sea exactamente un dominio permitido o
un subdominio suyo (nunca `"gob.pe" in url`).
"""
from urllib.parse import urlparse

DOMINIOS_CONFIABLES = (
    "gob.pe",           # instituciones públicas peruanas (MINCETUR, GORE, SENAMHI, BCRP, PNP...)
    "peru.travel",      # portal oficial de PROMPERÚ
    "ytuqueplanes.com",  # turismo interno, vinculado a PROMPERÚ
)

# Preferencias de búsqueda por herramienta (solo orientan al buscador; la
# confianza siempre la decide es_url_confiable()).
_TURISMO = ("regionhuanuco.gob.pe", "peru.travel", "ytuqueplanes.com")
DOMINIOS_PREFERIDOS = {
    "buscar_lugares": _TURISMO,
    "obtener_lugar": _TURISMO,
    "buscar_eventos": _TURISMO,
    "obtener_evento": _TURISMO,
    "buscar_platos": _TURISMO,
    "obtener_plato": _TURISMO,
    "consultar_clima": ("senamhi.gob.pe",),
    "consultar_tipo_cambio": ("bcrp.gob.pe",),
    "consultar_emergencias": ("gob.pe",),
}


def dominio(url):
    try:
        host = urlparse(url.strip()).hostname
    except (ValueError, AttributeError):
        return None
    return host.rstrip(".") if host else None


def es_url_confiable(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").rstrip(".")
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in DOMINIOS_CONFIABLES)
