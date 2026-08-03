"""
Configuración centralizada de las ciudades disponibles en "Clima y
temporadas". Único lugar que conoce los nombres de settings de coordenadas;
el servicio y la vista solo trabajan con el slug validado.
"""
from django.conf import settings

CIUDAD_PREDETERMINADA = "huanuco"
_ORDEN_CIUDADES = ("huanuco", "tingo-maria")


def _configuraciones():
    # Se lee settings en cada llamada (no en una constante de módulo) para
    # que override_settings en tests surta efecto de inmediato.
    return {
        "huanuco": {
            "slug": "huanuco",
            "nombre": "Huánuco",
            "nombre_completo": "Huánuco (Ciudad)",
            "latitud": settings.CLIMA_HUANUCO_LATITUD,
            "longitud": settings.CLIMA_HUANUCO_LONGITUD,
        },
        "tingo-maria": {
            "slug": "tingo-maria",
            "nombre": "Tingo María",
            "nombre_completo": "Tingo María (Ciudad)",
            "latitud": settings.CLIMA_TINGO_MARIA_LATITUD,
            "longitud": settings.CLIMA_TINGO_MARIA_LONGITUD,
        },
    }


def ciudad_valida(valor):
    """Lista blanca: cualquier valor fuera de _ORDEN_CIUDADES cae a la predeterminada."""
    return valor if valor in _ORDEN_CIUDADES else CIUDAD_PREDETERMINADA


def obtener_ciudad(slug):
    return _configuraciones()[ciudad_valida(slug)]


def listar_ciudades():
    configuraciones = _configuraciones()
    return [configuraciones[slug] for slug in _ORDEN_CIUDADES]
