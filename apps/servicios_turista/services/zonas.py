"""
Resolución de zona (distrito) para Planifica → Servicios útiles.

apps.ubicaciones sigue siendo la única fuente territorial: no se crea aquí
ninguna tabla ni modelo de zona/ciudad nuevo. Este módulo solo resuelve, en
presentación, qué distrito mostrar por defecto y con qué nombre público
(ej. "RUPA-RUPA" -> "Tingo María"), sin tocar los datos guardados.
"""
from apps.ubicaciones.models import Distrito

# Zona mostrada por defecto cuando no se pide ninguna por querystring o
# cuando la solicitada no existe/no tiene servicios activos.
ZONA_PREDETERMINADA_SLUG = "huanuco"

# Valor sentinela del <select> para "ver todas las zonas a la vez" (no
# corresponde a ningún Distrito real, se maneja aparte en la vista).
ZONA_TODAS_SLUG = "todas"
NOMBRE_ZONA_TODAS = "Todas las zonas"

# Excepción explícita de nombre público por zona: el distrito oficial no
# siempre es el nombre por el que el turista conoce el lugar (caso
# RUPA-RUPA / Tingo María, confirmado en la auditoría). Se listan también
# las demás zonas del proyecto con su forma correctamente tildada, en vez
# de derivarla automáticamente de nombre_oficial (que en BD está en
# mayúsculas y sin tildes) o de intentar adivinar la capital distrital de
# cada una, lo que podría producir resultados no deseados.
NOMBRES_PUBLICOS_ZONA = {
    "huanuco": "Huánuco",
    "amarilis": "Amarilis",
    "pillco-marca": "Pillco Marca",
    "ambo": "Ambo",
    "rupa-rupa": "Tingo María",
}


def nombre_publico_zona(distrito):
    """Nombre que ve el turista para este distrito. Cae al nombre oficial
    del distrito (tal cual está en BD) si no hay una excepción registrada."""
    return NOMBRES_PUBLICOS_ZONA.get(distrito.slug, distrito.nombre_oficial)


def obtener_zonas_con_servicios():
    """Distritos activos que tienen al menos un ServicioTurista activo,
    limitados al departamento de Huánuco (alcance actual del proyecto,
    ver auditoría: Distrito.slug no es único a nivel global)."""
    return (
        Distrito.objects.filter(
            activo=True,
            servicios_turista__activo=True,
            provincia__departamento__slug="huanuco",
        )
        .distinct()
        .select_related("provincia", "provincia__departamento")
        .order_by("provincia__nombre_oficial", "nombre_oficial")
    )


def resolver_zona(slug=None):
    """Resuelve la zona solicitada; cae de forma segura a la predeterminada
    (Huánuco) y, si esta tampoco tiene servicios, a la primera zona
    disponible. Un slug inválido nunca produce 404: simplemente se ignora."""
    zonas = list(obtener_zonas_con_servicios())
    if slug:
        for zona in zonas:
            if zona.slug == slug:
                return zona
    for zona in zonas:
        if zona.slug == ZONA_PREDETERMINADA_SLUG:
            return zona
    return zonas[0] if zonas else None
