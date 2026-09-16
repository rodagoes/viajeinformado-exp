from django.db.models import Prefetch, Q

from apps.turismo.models import (
    DIFICULTAD_CHOICES,
    TIPO_COSTO_CHOICES,
    CategoriaLugarTuristico,
    LugarTuristico,
    RecomendacionLugarTuristico,
    ServicioLugarTuristico,
)

from . import (
    decimal_str,
    kwargs_ubicacion,
    normalizar_limit,
    resultado_item,
    resultado_lista,
    ubicacion_de,
    validar_bool,
    validar_choice,
    validar_texto,
    validar_texto_obligatorio,
)


def _base():
    return LugarTuristico.objects.filter(activo=True).select_related(
        "categoria_principal", "distrito__provincia", "localidad"
    )


def _resumen(lugar):
    return {
        "id": lugar.pk,
        "nombre": lugar.nombre,
        "slug": lugar.slug,
        "descripcion_corta": lugar.descripcion_corta,
        "categoria": lugar.categoria_principal.nombre,
        "categoria_slug": lugar.categoria_principal.slug,
        **ubicacion_de(lugar.distrito, lugar.localidad),
        "direccion": lugar.direccion,
        "tipo_costo": lugar.tipo_costo,
        "precio_desde": decimal_str(lugar.precio_desde),
        "precio_hasta": decimal_str(lugar.precio_hasta),
        "horario_visita": lugar.horario_visita,
        "dificultad": lugar.dificultad,
        "destacado": lugar.destacado,
        "url": lugar.get_absolute_url(),
    }


def buscar_lugares(
    q=None,
    categoria=None,
    distrito=None,
    provincia=None,
    tipo_costo=None,
    dificultad=None,
    destacado=None,
    limit=None,
):
    limit = normalizar_limit(limit)
    q = validar_texto(q, "q")
    categoria = validar_texto(categoria, "categoria")
    tipo_costo = validar_choice(tipo_costo, "tipo_costo", TIPO_COSTO_CHOICES)
    dificultad = validar_choice(dificultad, "dificultad", DIFICULTAD_CHOICES)
    destacado = validar_bool(destacado, "destacado")
    filtros_ubicacion = kwargs_ubicacion(distrito, provincia)

    qs = _base()
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) | Q(descripcion_corta__icontains=q) | Q(descripcion__icontains=q)
        )
    if categoria:
        qs = qs.filter(
            Q(categoria_principal__slug=categoria) | Q(categorias_secundarias__slug=categoria)
        ).distinct()
    if filtros_ubicacion:
        qs = qs.filter(**filtros_ubicacion)
    if tipo_costo:
        qs = qs.filter(tipo_costo=tipo_costo)
    if dificultad:
        qs = qs.filter(dificultad=dificultad)
    if destacado is not None:
        qs = qs.filter(destacado=destacado)

    qs = qs.order_by("-destacado", "nombre", "id")[:limit]
    return resultado_lista("buscar_lugares", [_resumen(lugar) for lugar in qs])


def obtener_lugar(slug):
    slug = validar_texto_obligatorio(slug, "slug")
    lugar = (
        _base()
        .prefetch_related(
            Prefetch(
                "categorias_secundarias",
                queryset=CategoriaLugarTuristico.objects.filter(activo=True),
            ),
            Prefetch("servicios", queryset=ServicioLugarTuristico.objects.filter(activo=True)),
            Prefetch(
                "recomendaciones_items",
                queryset=RecomendacionLugarTuristico.objects.filter(activo=True),
            ),
        )
        .filter(slug=slug)
        .first()
    )
    if lugar is None:
        return resultado_item("obtener_lugar", None)

    item = _resumen(lugar)
    item.update(
        {
            "descripcion": lugar.descripcion,
            "categorias_secundarias": [c.nombre for c in lugar.categorias_secundarias.all()],
            "servicios": [s.nombre for s in lugar.servicios.all()],
            "tiempo_visita_estimado": lugar.tiempo_visita_estimado,
            "como_llegar": lugar.como_llegar,
            "recomendaciones": lugar.recomendaciones,
            "recomendaciones_items": [
                {"titulo": r.titulo, "descripcion": r.descripcion}
                for r in lugar.recomendaciones_items.all()
            ],
            "referencia": lugar.referencia,
            "latitud": decimal_str(lugar.latitud),
            "longitud": decimal_str(lugar.longitud),
            "maps_url": lugar.maps_url,
        }
    )
    return resultado_item("obtener_lugar", item)
