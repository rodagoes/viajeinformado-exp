from django.db.models import Q
from django.utils.text import slugify

from apps.servicios_turista.services.zonas import nombre_publico_zona
from apps.ubicaciones.models import Departamento, Distrito, Localidad, Provincia

from . import (
    decimal_str,
    normalizar_limit,
    resultado_lista,
    validar_choice,
    validar_texto_obligatorio,
)

TIPOS = ("departamento", "provincia", "distrito", "localidad")
TIPO_CHOICES = [(tipo, tipo) for tipo in TIPOS]


def _coincide(q, campo_nombre):
    """icontains sobre el nombre y, si el texto slugifica a algo, sobre el slug
    (así "Huánuco" encuentra "HUANUCO"/"huanuco" aunque la BD no tenga tildes)."""
    condicion = Q(**{f"{campo_nombre}__icontains": q})
    slug_q = slugify(q)
    if slug_q:
        condicion |= Q(slug__icontains=slug_q)
    return condicion


def _consultas(q):
    return {
        "departamento": Departamento.objects.filter(activo=True).filter(_coincide(q, "nombre_oficial")),
        "provincia": (
            Provincia.objects.filter(activo=True)
            .select_related("departamento")
            .filter(_coincide(q, "nombre_oficial") | Q(capital__icontains=q))
        ),
        "distrito": (
            Distrito.objects.filter(activo=True)
            .select_related("provincia__departamento")
            .filter(_coincide(q, "nombre_oficial"))
        ),
        "localidad": (
            Localidad.objects.filter(activo=True)
            .select_related("distrito__provincia__departamento")
            .filter(_coincide(q, "nombre"))
        ),
    }


def _serializar(tipo, obj):
    if tipo == "departamento":
        return {"tipo": tipo, "id": obj.pk, "nombre": obj.nombre_oficial, "slug": obj.slug}
    if tipo == "provincia":
        return {
            "tipo": tipo,
            "id": obj.pk,
            "nombre": obj.nombre_oficial,
            "slug": obj.slug,
            "capital": obj.capital,
            "departamento": obj.departamento.nombre_oficial,
        }
    if tipo == "distrito":
        return {
            "tipo": tipo,
            "id": obj.pk,
            "nombre": obj.nombre_oficial,
            "nombre_publico": nombre_publico_zona(obj),
            "slug": obj.slug,
            "provincia": obj.provincia.nombre_oficial,
            "provincia_slug": obj.provincia.slug,
            "departamento": obj.provincia.departamento.nombre_oficial,
        }
    distrito = obj.distrito
    return {
        "tipo": tipo,
        "id": obj.pk,
        "nombre": obj.nombre,
        "slug": obj.slug,
        "tipo_localidad": obj.tipo,
        "distrito": distrito.nombre_oficial,
        "distrito_slug": distrito.slug,
        "provincia": distrito.provincia.nombre_oficial,
        "provincia_slug": distrito.provincia.slug,
        "departamento": distrito.provincia.departamento.nombre_oficial,
        "latitud": decimal_str(obj.latitud),
        "longitud": decimal_str(obj.longitud),
    }


def buscar_ubicaciones(q, tipo=None, limit=None):
    q = validar_texto_obligatorio(q, "q")
    tipo = validar_choice(tipo, "tipo", TIPO_CHOICES)
    limit = normalizar_limit(limit)

    consultas = _consultas(q)
    items = []
    for nombre_tipo in TIPOS:
        if tipo and tipo != nombre_tipo:
            continue
        restantes = limit - len(items)
        if restantes <= 0:
            break
        items.extend(_serializar(nombre_tipo, obj) for obj in consultas[nombre_tipo][:restantes])
    return resultado_lista("buscar_ubicaciones", items)
