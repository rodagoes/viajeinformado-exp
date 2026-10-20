"""
Mapa, apertura y ruta de una sede a partir de lo que cargó el administrador.

Nada se consulta por red ni se extrae de Google (sin scraping, sin API key): solo se
validan los datos pegados y se interpretan los patrones de texto conocidos de sus URL.
Cada resultado lleva una *precisión* para que el Admin diga con honestidad qué tan
fiable es el destino:

  ficha_admin          ficha/iframe pegado por el administrador (se muestra tal cual)
  place_id             Place ID de Google presente en la URL (ruta documentada)
  pin_admin            coordenadas del pin escritas por el administrador
  pin_ficha            pin dentro de la URL de la ficha (patrón !8m2!3d..!4d..)
  referencial          centro del iframe; NO se asegura que sea el pin
  direccion_aproximada geocodificación de la dirección (puede caer en otro lugar)
  no_determinable      hay ficha pero no se puede calcular una ruta exacta

`@lat,lng` (centro de la vista) y `!3d!4d` sueltos NO se usan para ninguna ruta.
Los enlaces cortos se abren, pero no se consideran ruta exacta.
"""
import html
import math
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, unquote, urlsplit

from django.utils.translation import get_language

from apps.base.services.mapas import construir_urls_mapa, coord_a_texto

from .zonas import nombre_publico_zona

HOSTS_GOOGLE = {"www.google.com", "google.com", "www.google.com.pe", "google.com.pe", "maps.google.com"}
HOSTS_EMBED = {"www.google.com", "google.com", "www.google.com.pe", "google.com.pe"}
HOSTS_CORTOS = {"maps.app.goo.gl", "goo.gl"}
ATRIBUTOS_IFRAME = {
    "src", "width", "height", "style", "allowfullscreen", "loading", "referrerpolicy", "title", "frameborder",
}
MAX_LONGITUD = 4000

UMBRAL_PIN_M = 200       # pin de la ficha vs. coordenadas del administrador
UMBRAL_IFRAME_M = 2000   # solo si falta el identificador de ficha: el centro del iframe es el de la VISTA (puede
                         # quedar a cientos de metros del pin, p. ej. 520 m con zoom 17)

ETIQUETAS = {
    "ficha_admin": "Ficha indicada por el administrador (no validada contra Google)",
    "place_id": "Place ID de Google (ruta documentada)",
    "pin_admin": "Coordenadas del pin ingresadas por el administrador",
    "pin_ficha": "Pin incluido en la URL de la ficha",
    "referencial": "Coordenada referencial (centro del iframe; no es seguro que sea el pin)",
    "direccion_aproximada": "Dirección aproximada (puede ubicar otro lugar)",
    "no_determinable": "Ruta exacta no determinable: se abre la ficha",
    "": "Sin datos",
}
RUTAS_EXACTAS = {"place_id", "pin_admin", "pin_ficha"}

_PIN_FICHA_RE = re.compile(r"!8m2!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)")
_CENTRO_IFRAME_RE = re.compile(r"!2d(-?\d{1,3}\.\d+)!3d(-?\d{1,2}\.\d+)")
_PLACE_ID_RE = re.compile(r"^ChIJ[\w-]{10,}$")
_FEATURE_ID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)")


class _IframeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.iframes, self.extra = [], False

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            self.iframes.append(attrs)
        else:
            self.extra = True

    def handle_endtag(self, tag):
        if tag != "iframe":
            self.extra = True

    def handle_data(self, data):
        if data.strip():
            self.extra = True


def _url_https(texto, hosts):
    """urlsplit si es https, sin credenciales ni puerto raro y host permitido; si no, None."""
    if not texto or len(texto) > MAX_LONGITUD or re.search(r"[\s<>\"']", texto):
        return None
    try:
        partes = urlsplit(texto)
        host, puerto = partes.hostname, partes.port
    except ValueError:
        return None
    if partes.scheme != "https" or partes.username or partes.password or puerto not in (None, 443):
        return None
    return partes if host in hosts else None


def validar_embed(crudo):
    """(src, error). Acepta el <iframe> completo de «Insertar un mapa» o solo su URL."""
    crudo = (crudo or "").strip()
    if not crudo:
        return "", ""
    if crudo.startswith("<"):
        analizador = _IframeParser()
        try:
            analizador.feed(crudo)
            analizador.close()
        except Exception:
            return "", "El código de inserción no se pudo leer. Pegue el <iframe> tal como lo entrega Google Maps."
        if len(analizador.iframes) != 1 or analizador.extra:
            return "", "Pegue únicamente el código <iframe> de Google Maps (sin otro texto ni etiquetas)."
        atributos = analizador.iframes[0]
        nombres = [n.lower() for n, _ in atributos]
        if len(nombres) != len(set(nombres)) or set(nombres) - ATRIBUTOS_IFRAME:
            return "", "El <iframe> contiene atributos no permitidos. Copie de nuevo el código desde «Compartir → Insertar un mapa»."
        src = next((v or "" for n, v in atributos if n.lower() == "src"), "")
    else:
        src = html.unescape(crudo)
    partes = _url_https(src, HOSTS_EMBED)
    if partes is None or not (
        partes.path.startswith("/maps/embed") or (partes.path == "/maps" and "output=embed" in partes.query)
    ):
        return "", "El mapa debe ser una URL https://www.google.com/maps/embed… de Google Maps."
    return src, ""


def iframe_canonico(src):
    """<iframe> limpio con solo atributos permitidos (lo que se guarda tras validar)."""
    return (
        f'<iframe src="{html.escape(src, quote=True)}" width="600" height="450" style="border:0;" '
        'allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>'
    )


def validar_maps_url(crudo):
    """(url, tipo, error): tipo 'larga' (google.com/maps…) o 'corta' (maps.app.goo.gl…)."""
    crudo = html.unescape((crudo or "").strip())
    if not crudo:
        return "", "", ""
    partes = _url_https(crudo, HOSTS_GOOGLE | HOSTS_CORTOS)
    if partes is not None:
        if partes.hostname == "maps.google.com" or (partes.hostname in HOSTS_GOOGLE and partes.path.startswith("/maps")):
            return crudo, "larga", ""
        if partes.hostname == "maps.app.goo.gl" and len(partes.path) > 1:
            return crudo, "corta", ""
        if partes.hostname == "goo.gl" and partes.path.startswith("/maps"):
            return crudo, "corta", ""
    return "", "", "La URL debe ser un enlace https de Google Maps (google.com/maps… o maps.app.goo.gl…)."


def _coords(par):
    lat, lng = par
    if -90 <= float(lat) <= 90 and -180 <= float(lng) <= 180:
        return lat, lng
    return None


def pin_de_ficha(url):
    """(lat, lng) del pin declarado en la ficha (!8m2!3d..!4d..), o None."""
    m = _PIN_FICHA_RE.search(url or "")
    return _coords(m.groups()) if m else None


def centro_de_iframe(src):
    """(lat, lng) centro del mapa del iframe (!2d lng !3d lat): solo REFERENCIAL."""
    m = _CENTRO_IFRAME_RE.search(src or "")
    return _coords((m.group(2), m.group(1))) if m else None


def place_id_de_url(url):
    consulta = parse_qs(urlsplit(url or "").query)
    for clave in ("query_place_id", "destination_place_id"):
        for valor in consulta.get(clave, []):
            if _PLACE_ID_RE.match(valor):
                return valor
    return None


def feature_id(texto):
    """Identificador hexadecimal de la ficha (!1s0x…:0x…) en una URL o en el pb de un iframe.
    NO es un Place ID: solo sirve para saber si dos fuentes hablan del mismo lugar."""
    m = _FEATURE_ID_RE.search(unquote(texto or ""))
    if not m:
        return None
    ident = (m.group(1).lower(), m.group(2).lower())
    return None if int(ident[0], 16) == 0 and int(ident[1], 16) == 0 else ident


def distancia_m(a, b):
    lat1, lng1, lat2, lng2 = (math.radians(float(x)) for x in (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def _con_consulta(url):
    # El JS añade «&travelmode=…» a la ruta: la URL debe tener ya una consulta.
    return url if "?" in url else f"{url}?hl={(get_language() or 'es')[:2]}"


def _urls(lat="", lng="", direccion=""):
    return construir_urls_mapa(latitud=lat, longitud=lng, direccion_mapa=direccion)


def evaluar_conflictos(src, url, tipo, admin):
    """(hay_conflicto, mensajes, misma_ficha) entre iframe, URL de la ficha y coordenadas del administrador.
    Misma lógica para el resolver y para la validación del formulario (que bloquea el guardado)."""
    mensajes = []
    pin = pin_de_ficha(url) if tipo == "larga" else None
    centro = centro_de_iframe(src)
    if pin and admin and distancia_m(pin, admin) > UMBRAL_PIN_M:
        mensajes.append("Las coordenadas escritas y el pin de la URL de la ficha apuntan a lugares distintos. Revise cuál es el correcto.")
    fid_url, fid_iframe = (feature_id(url) if tipo == "larga" else None), feature_id(src)
    misma_ficha = bool(fid_url and fid_iframe and fid_url == fid_iframe)
    if fid_url and fid_iframe and not misma_ficha:
        mensajes.append("El mapa incrustado y la URL son de fichas distintas (identificadores diferentes). Revise que ambos sean de la misma sede.")
    elif not misma_ficha and centro and (pin or admin) and distancia_m(centro, pin or admin) > UMBRAL_IFRAME_M:
        mensajes.append("El mapa incrustado y la URL/coordenadas apuntan a lugares muy distintos. Revise que ambos sean de la misma sede.")
    return bool(mensajes), mensajes, misma_ficha


def resolver_mapa(sede):
    """Decide embed/apertura/ruta de la sede y explica con qué fiabilidad."""
    avisos = []
    src, error_embed = validar_embed(sede.embed_maps)
    url, tipo, error_url = validar_maps_url(sede.maps_url)
    if error_embed:
        avisos.append(f"Código de inserción ignorado: {error_embed}")
    if error_url:
        avisos.append(f"URL de la ficha ignorada: {error_url}")

    admin = None
    if sede.latitud is not None and sede.longitud is not None:
        admin = (coord_a_texto(sede.latitud), coord_a_texto(sede.longitud))
    pin = pin_de_ficha(url) if tipo == "larga" else None
    centro = centro_de_iframe(src)
    place_id = place_id_de_url(url)
    calle = (sede.direccion or "").strip()
    zona = nombre_publico_zona(sede.distrito) if sede.distrito_id else ""
    direccion = ", ".join(p for p in (calle, zona, "Perú") if p) if calle else ""

    conflicto, avisos_conflicto, misma_ficha = evaluar_conflictos(src, url, tipo, admin)
    avisos += avisos_conflicto

    # --- mapa incrustado
    if src:
        embed, f_embed = src, "ficha_admin"
    elif not conflicto and pin:
        embed, f_embed = _urls(*pin)[0], "pin_ficha"
    elif not conflicto and admin:
        embed, f_embed = _urls(*admin)[0], "pin_admin"
    elif direccion:
        embed, f_embed = _urls(direccion=direccion)[0], "direccion_aproximada"
    else:
        embed, f_embed = "", ""

    # --- abrir ubicación
    if url:
        abrir, f_abrir = url, "ficha_admin"
    elif not conflicto and admin:
        abrir, f_abrir = _urls(*admin)[1], "pin_admin"
    elif not conflicto and centro:
        abrir, f_abrir = _urls(*centro)[1], "referencial"
    elif direccion:
        abrir, f_abrir = _urls(direccion=direccion)[1], "direccion_aproximada"
    else:
        abrir, f_abrir = "", ""

    # --- ruta
    if place_id and not conflicto:
        ruta = ("https://www.google.com/maps/dir/?api=1&destination=" + quote(sede.nombre_publico)
                + "&destination_place_id=" + place_id)
        f_ruta = "place_id"
    elif not conflicto and admin:
        ruta, f_ruta = _urls(*admin)[2], "pin_admin"
    elif not conflicto and pin:
        ruta, f_ruta = _urls(*pin)[2], "pin_ficha"
    elif url:
        ruta, f_ruta = _con_consulta(url), "no_determinable"
    elif not conflicto and centro:
        ruta, f_ruta = _urls(*centro)[2], "referencial"
    elif direccion:
        ruta, f_ruta = _urls(direccion=direccion)[2], "direccion_aproximada"
    else:
        ruta, f_ruta = "", ""

    # --- avisos y estado
    if tipo == "corta":
        avisos.append("Enlace corto: abre la ficha, pero no permite calcular una ruta exacta. Pegue la URL larga (barra de direcciones) o ingrese las coordenadas del pin.")
    elif url and not pin and not admin and not place_id:
        avisos.append("La URL de la ficha no incluye un pin reconocible: «Cómo llegar» abrirá la ficha. Ingrese las coordenadas del pin para una ruta exacta.")
    if src and not url and not admin:
        avisos.append("Solo hay código de inserción: el mapa muestra la ficha, pero «Abrir mapa» y «Cómo llegar» solo pueden usar una referencia aproximada. Pegue la URL de la ficha o ingrese las coordenadas del pin.")
    if not (src or url or admin) and direccion:
        avisos.append("Solo hay dirección: el mapa y la ruta son aproximados y podrían ubicar otro lugar. Pegue la ficha de Google Maps de esta sede.")

    hay_mapa = bool(embed or abrir or ruta)
    if not hay_mapa:
        estado = "sin_datos"
    elif conflicto:
        estado = "conflicto"
    elif f_ruta in RUTAS_EXACTAS:
        estado = "completo"
    elif src or url:
        estado = "parcial"
    else:
        estado = "aproximado"
    return {
        "hay_mapa": hay_mapa, "embed_url": embed, "open_url": abrir, "route_url": ruta,
        "fuentes": {"embed": f_embed, "open": f_abrir, "route": f_ruta},
        "precision": f_ruta, "estado": estado, "conflicto": conflicto, "avisos": avisos,
        "tipo_url": tipo, "pin_ficha": pin, "centro_iframe": centro, "misma_ficha": misma_ficha,
    }
