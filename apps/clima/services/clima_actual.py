"""
Cliente y normalizador de Open-Meteo para la pantalla Planifica → Clima y
temporadas. Concentra toda la comunicación con el proveedor externo: la
vista y el template solo conocen la estructura normalizada devuelta por
`obtener_clima_actual(ciudad_slug)`.

El servicio es agnóstico a la ciudad concreta: recibe la configuración
(coordenadas, nombre) desde ``apps.clima.ubicaciones`` y reutiliza toda la
lógica (endpoint, timeout, normalización, mapeo de estados, caché,
respaldo) para cualquier ciudad soportada.

Open-Meteo no requiere API key.
"""
import logging
from datetime import datetime

import requests
from django.core.cache import cache

from ..ubicaciones import ciudad_valida, obtener_ciudad

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SEGUNDOS = 5

CACHE_TTL_RECIENTE = 60 * 15
CACHE_TTL_ULTIMO_VALIDO = 60 * 60 * 6

CAMPOS_ACTUALES = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "is_day",
)

# Código WMO -> (texto legible, estado interno usado por el CSS/ícono).
# https://open-meteo.com/en/docs (tabla "WMO Weather interpretation codes")
CODIGOS_WMO = {
    0: ("Despejado", "soleado"),
    1: ("Mayormente despejado", "mayormente-despejado"),
    2: ("Parcialmente nublado", "parcialmente-nublado"),
    3: ("Nublado", "nublado"),
    45: ("Neblina", "neblina"),
    48: ("Neblina con escarcha", "neblina"),
    51: ("Llovizna ligera", "llovizna"),
    53: ("Llovizna moderada", "llovizna"),
    55: ("Llovizna intensa", "llovizna"),
    56: ("Llovizna helada ligera", "llovizna"),
    57: ("Llovizna helada intensa", "llovizna"),
    61: ("Lluvia ligera", "lluvia"),
    63: ("Lluvia moderada", "lluvia"),
    65: ("Lluvia intensa", "lluvia-intensa"),
    66: ("Lluvia helada ligera", "lluvia"),
    67: ("Lluvia helada intensa", "lluvia-intensa"),
    71: ("Nevada ligera", "nieve"),
    73: ("Nevada moderada", "nieve"),
    75: ("Nevada intensa", "nieve"),
    77: ("Granos de nieve", "nieve"),
    80: ("Chubascos ligeros", "lluvia"),
    81: ("Chubascos moderados", "lluvia"),
    82: ("Chubascos intensos", "lluvia-intensa"),
    85: ("Chubascos de nieve ligeros", "nieve"),
    86: ("Chubascos de nieve intensos", "nieve"),
    95: ("Tormenta eléctrica", "tormenta"),
    96: ("Tormenta con granizo ligero", "tormenta"),
    99: ("Tormenta con granizo intenso", "tormenta"),
}
ESTADO_DESCONOCIDO = ("Condición variable", "variable")
ESTADO_PREDETERMINADO = "variable"


def _mapear_codigo_wmo(codigo):
    return CODIGOS_WMO.get(codigo, ESTADO_DESCONOCIDO)


class ClimaAPIError(Exception):
    """Error controlado al consultar o interpretar la respuesta de Open-Meteo."""


def cache_key_reciente(ciudad_slug):
    return f"clima:{ciudad_slug}:actual"


def cache_key_ultimo_valido(ciudad_slug):
    return f"clima:{ciudad_slug}:ultimo_valido"


def _config_disponible(ciudad):
    return bool(ciudad["latitud"] and ciudad["longitud"])


def _respuesta_no_disponible(ciudad, respaldo=None):
    if respaldo:
        datos = dict(respaldo)
        datos["es_respaldo"] = True
        return datos
    return {
        "disponible": False,
        "es_respaldo": False,
        "ciudad_slug": ciudad["slug"],
        "temperatura_c": None,
        "sensacion_c": None,
        "humedad_pct": None,
        "viento_kph": None,
        "probabilidad_lluvia_pct": None,
        "precipitacion_mm": None,
        "nubosidad_pct": None,
        "estado_texto": None,
        "estado_slug": ESTADO_PREDETERMINADO,
        "es_dia": True,
        "actualizado_local": None,
        "hora_dato": None,
        "ubicacion": ciudad["nombre_completo"],
        "fuente": "Open-Meteo",
    }


def _numero(valor, decimales=None):
    """Convierte de forma segura a número. Nunca degrada un valor ausente a 0."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return round(numero, decimales) if decimales is not None else round(numero)


def _formatear_hora_local(hora_texto):
    try:
        momento = datetime.strptime(hora_texto, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None
    hora_12 = momento.hour % 12 or 12
    periodo = "a. m." if momento.hour < 12 else "p. m."
    return f"{hora_12}:{momento.minute:02d} {periodo}"


def _normalizar(payload, ciudad):
    current = payload.get("current")
    if not isinstance(current, dict):
        logger.warning("proveedor=open-meteo ciudad=%s estado=sin_current", ciudad["slug"])
        raise ClimaAPIError("La respuesta de Open-Meteo no contiene 'current'.")

    temperatura_c = _numero(current.get("temperature_2m"), 1)
    if temperatura_c is None:
        logger.warning("proveedor=open-meteo ciudad=%s estado=sin_temperatura", ciudad["slug"])
        raise ClimaAPIError("La respuesta de Open-Meteo no contiene una temperatura válida.")

    estado_texto, estado_slug = _mapear_codigo_wmo(current.get("weather_code"))

    try:
        es_dia = bool(int(current.get("is_day")))
    except (TypeError, ValueError):
        es_dia = True

    return {
        "disponible": True,
        "es_respaldo": False,
        "ciudad_slug": ciudad["slug"],
        "temperatura_c": temperatura_c,
        "sensacion_c": _numero(current.get("apparent_temperature"), 1),
        "humedad_pct": _numero(current.get("relative_humidity_2m")),
        "viento_kph": _numero(current.get("wind_speed_10m"), 1),
        "probabilidad_lluvia_pct": _numero(current.get("precipitation_probability")),
        "precipitacion_mm": _numero(current.get("precipitation"), 1),
        "nubosidad_pct": _numero(current.get("cloud_cover")),
        "estado_texto": estado_texto,
        "estado_slug": estado_slug,
        "es_dia": es_dia,
        "actualizado_local": _formatear_hora_local(current.get("time")),
        "hora_dato": current.get("time"),
        "ubicacion": ciudad["nombre_completo"],
        "fuente": "Open-Meteo",
    }


def _consultar_open_meteo(ciudad):
    params = {
        "latitude": ciudad["latitud"],
        "longitude": ciudad["longitud"],
        "current": ",".join(CAMPOS_ACTUALES),
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "timezone": "America/Lima",
        "forecast_days": 1,
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT_SEGUNDOS)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "proveedor=open-meteo ciudad=%s estado=%s", ciudad["slug"], exc.__class__.__name__
        )
        raise ClimaAPIError("Fallo de red al consultar Open-Meteo.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("proveedor=open-meteo ciudad=%s estado=json_invalido", ciudad["slug"])
        raise ClimaAPIError("Respuesta JSON inválida de Open-Meteo.") from exc

    return _normalizar(payload, ciudad)


def obtener_clima_actual(ciudad_slug=None):
    """
    Estructura normalizada del clima actual de la ciudad indicada
    ("huanuco" o "tingo-maria"; cualquier otro valor cae a "huanuco").

    Orden: caché reciente (15 min) -> Open-Meteo -> último resultado válido
    en caché (6 h) como respaldo -> `disponible=False` si no hay nada.
    La caché es independiente por ciudad: nunca se reutiliza entre ellas.
    """
    ciudad_slug = ciudad_valida(ciudad_slug)
    ciudad = obtener_ciudad(ciudad_slug)

    clave_reciente = cache_key_reciente(ciudad_slug)
    clave_ultimo_valido = cache_key_ultimo_valido(ciudad_slug)

    reciente = cache.get(clave_reciente)
    if reciente:
        return reciente

    if not _config_disponible(ciudad):
        return _respuesta_no_disponible(ciudad, cache.get(clave_ultimo_valido))

    try:
        datos = _consultar_open_meteo(ciudad)
    except ClimaAPIError:
        return _respuesta_no_disponible(ciudad, cache.get(clave_ultimo_valido))

    cache.set(clave_reciente, datos, CACHE_TTL_RECIENTE)
    cache.set(clave_ultimo_valido, datos, CACHE_TTL_ULTIMO_VALIDO)
    return datos
