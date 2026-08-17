"""
Construcción de URLs de Google Maps a partir de coordenadas/dirección/URL de
ficha, sin API key (solo enlaces públicos + iframe embed).

Extraído de la lógica que existía duplicada en
``apps.establecimientos.views.detalle_establecimiento`` (build_sucursal_mapa)
y ``apps.turismo.views.detalle_lugar`` — ambas construían embed_url/open_url
/route_url con la misma prioridad. La única diferencia real entre ellas era
el nivel de zoom del embed, por eso queda como parámetro en vez de fijarlo.
"""
import re
from urllib.parse import quote


def coord_a_texto(valor):
    """Decimal de coordenada -> texto con punto decimal (nunca coma), listo
    para una URL de Google Maps. None/'' -> ''."""
    if valor is None or valor == "":
        return ""
    return format(valor, "f")


def _extraer_embed_src(embed_maps):
    embed_maps = (embed_maps or "").strip()
    if not embed_maps:
        return ""
    match = re.search(r'src=["\']([^"\']+)["\']', embed_maps)
    if match:
        return match.group(1)
    if embed_maps.startswith("https://"):
        return embed_maps
    return ""


def _extraer_coords_de_maps_url(maps_url):
    if not maps_url:
        return ""
    match_3d4d = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", maps_url)
    if match_3d4d:
        return f"{match_3d4d.group(1)},{match_3d4d.group(2)}"
    match_at = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", maps_url)
    if match_at:
        return f"{match_at.group(1)},{match_at.group(2)}"
    return ""


def construir_urls_mapa(
    *,
    latitud="",
    longitud="",
    direccion_mapa="",
    maps_url="",
    embed_maps="",
    zoom_coordenadas=17,
    zoom_direccion=17,
):
    """Devuelve (embed_url, open_url, route_url).

    Prioridad (igual en los tres casos, en línea con establecimientos y
    turismo antes de esta extracción):
        embed_url  -> embed_maps  > lat/lng > dirección
        open_url   -> maps_url    > lat/lng > dirección
        route_url  -> coords en maps_url (!3d!4d o @lat,lng) > lat/lng > dirección

    ``latitud``/``longitud`` deben venir ya formateadas con punto decimal
    (ver ``coord_a_texto``). Sin API key: son URLs públicas de Google Maps.
    """
    maps_url = (maps_url or "").strip()
    embed_src = _extraer_embed_src(embed_maps)

    if embed_src:
        embed_url = embed_src
    elif latitud and longitud:
        embed_url = (
            f"https://www.google.com/maps?q={quote(latitud + ',' + longitud)}"
            f"&z={zoom_coordenadas}&hl=es&output=embed"
        )
    elif direccion_mapa:
        embed_url = (
            f"https://www.google.com/maps?q={quote(direccion_mapa)}"
            f"&z={zoom_direccion}&hl=es&output=embed"
        )
    else:
        embed_url = ""

    if maps_url:
        open_url = maps_url
    elif latitud and longitud:
        open_url = f"https://www.google.com/maps/search/?api=1&query={quote(latitud + ',' + longitud)}"
    elif direccion_mapa:
        open_url = f"https://www.google.com/maps/search/?api=1&query={quote(direccion_mapa)}"
    else:
        open_url = ""

    coords_from_url = _extraer_coords_de_maps_url(maps_url)
    if coords_from_url:
        route_url = f"https://www.google.com/maps/dir/?api=1&destination={quote(coords_from_url)}"
    elif latitud and longitud:
        route_url = f"https://www.google.com/maps/dir/?api=1&destination={quote(latitud + ',' + longitud)}"
    elif direccion_mapa:
        route_url = f"https://www.google.com/maps/dir/?api=1&destination={quote(direccion_mapa)}"
    else:
        route_url = ""

    return embed_url, open_url, route_url
