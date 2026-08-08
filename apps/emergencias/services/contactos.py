"""
Lógica de datos para la pantalla Planifica → Emergencias.

Mantiene la vista y el template libres de consultas: resolución de zona,
agrupación por provincia y filtrado de contactos nacionales/locales.
"""
from itertools import groupby

import segno

from ..models import ContactoEmergencia, ZonaAtencionEmergencia

# Zona mostrada por defecto cuando no se pide ninguna zona por querystring
# o cuando la solicitada no existe/está inactiva.
ZONA_PREDETERMINADA_SLUG = "huanuco"


def obtener_zonas_activas():
    """Zonas activas, con el distrito/provincia/departamento precargados."""
    return (
        ZonaAtencionEmergencia.objects.filter(activo=True)
        .select_related("distrito", "distrito__provincia", "distrito__provincia__departamento")
        .order_by("distrito__provincia__nombre_oficial", "orden", "nombre_publico")
    )


def resolver_zona(slug=None):
    """Resuelve la zona solicitada; cae de forma segura a la predeterminada
    y, si esta tampoco existe, a la primera zona activa disponible."""
    zonas = list(obtener_zonas_activas())
    if slug:
        for zona in zonas:
            if zona.slug == slug:
                return zona
    for zona in zonas:
        if zona.slug == ZONA_PREDETERMINADA_SLUG:
            return zona
    return zonas[0] if zonas else None


def zonas_agrupadas_por_provincia():
    """Zonas activas agrupadas por provincia, en el orden ya aplicado por
    obtener_zonas_activas() (provincia, luego orden de zona)."""
    zonas = list(obtener_zonas_activas())
    return [
        {"provincia": provincia, "zonas": list(items)}
        for provincia, items in groupby(zonas, key=lambda zona: zona.distrito.provincia)
    ]


def obtener_contactos_nacionales():
    return list(
        ContactoEmergencia.objects.filter(
            activo=True, ambito=ContactoEmergencia.AMBITO_NACIONAL
        ).order_by("orden", "nombre")
    )


def obtener_contactos_locales(zona):
    if zona is None:
        return []
    return list(
        ContactoEmergencia.objects.filter(
            activo=True, ambito=ContactoEmergencia.AMBITO_LOCAL, zonas=zona
        )
        .prefetch_related("numeros_adicionales")
        .order_by("orden", "nombre")
    )


def obtener_ultima_verificacion(contactos):
    """Fecha de verificación más antigua entre los contactos visibles: es la
    lectura más honesta ("todo lo mostrado fue revisado al menos desde esta
    fecha"), en vez de la más reciente que sobreestimaría la vigencia de los
    contactos verificados hace más tiempo."""
    fechas = [c.fecha_verificacion for c in contactos if c.fecha_verificacion]
    return min(fechas) if fechas else None


def generar_qr_data_uri(url):
    """SVG de un QR apuntando a `url`, embebido como data URI (sin servicio
    externo de terceros)."""
    qr = segno.make(url, error="m")
    return qr.svg_data_uri(scale=4, border=2, dark="#002D89", light="#FFFFFF")
