import calendar
import datetime

from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from apps.eventos.models import (
    Evento,
    RecomendacionEvento,
    TagExperiencia,
    ocurrencia_anual_en_rango,
    ocurrencia_anual_relevante,
    ocurrencia_pascua_en_rango,
    ocurrencia_pascua_relevante,
    ocurrencia_relativa_en_rango,
    ocurrencia_relativa_relevante,
)

from . import (
    ArgumentoInvalido,
    decimal_str,
    fecha_iso,
    normalizar_limit,
    resultado_item,
    resultado_lista,
    validar_bool,
    validar_choice,
    validar_fecha,
    validar_lista_texto,
    validar_texto,
    validar_texto_obligatorio,
)

TIPOS_APROXIMADOS = ("mes_aproximado", "por_confirmar")

# ponytail: se evalúan hasta 200 eventos para ordenarlos por ocurrencia en
# Python (igual que hace apps.eventos.views); paginar si el catálogo crece.
MAX_EVALUADOS = 200


def _mes_en_rango(evento, fecha_desde, fecha_hasta):
    if not (evento.mes_aproximado and evento.anio_aproximado):
        return False
    ultimo_dia = calendar.monthrange(evento.anio_aproximado, evento.mes_aproximado)[1]
    inicio = datetime.date(evento.anio_aproximado, evento.mes_aproximado, 1)
    fin = datetime.date(evento.anio_aproximado, evento.mes_aproximado, ultimo_dia)
    return inicio <= fecha_hasta and fin >= fecha_desde


def _ocurrencia(evento, hoy, rango):
    """
    (inicio, fin) de la ocurrencia relevante: la que solapa el rango pedido
    o, sin rango, la vigente/próxima respecto a `hoy`. Reutiliza los helpers
    de recurrencia de apps.eventos.models. None para 'por_confirmar'.
    """
    tipo = evento.tipo_fecha
    if tipo in ("exacta", "rango"):
        return evento.fecha_inicio, evento.fecha_fin or evento.fecha_inicio
    if tipo == "anual_fija":
        args = (
            evento.dia_inicio_anual, evento.mes_inicio_anual,
            evento.dia_fin_anual, evento.mes_fin_anual,
        )
        en_rango = ocurrencia_anual_en_rango(*args, *rango) if rango else None
        return en_rango or ocurrencia_anual_relevante(*args, hoy)[:2]
    if tipo == "anual_relativa":
        args = (
            evento.orden_semana_relativa, evento.dia_semana_relativa,
            evento.mes_relativa, evento.dia_ancla_relativa,
        )
        en_rango = ocurrencia_relativa_en_rango(*args, *rango) if rango else None
        return en_rango or ocurrencia_relativa_relevante(*args, hoy)[:2]
    if tipo == "pascua_relativa":
        en_rango = ocurrencia_pascua_en_rango(evento.offset_dias_pascua, *rango) if rango else None
        return en_rango or ocurrencia_pascua_relevante(evento.offset_dias_pascua, hoy)[:2]
    if tipo == "mes_aproximado" and evento.mes_aproximado and evento.anio_aproximado:
        ultimo_dia = calendar.monthrange(evento.anio_aproximado, evento.mes_aproximado)[1]
        return (
            datetime.date(evento.anio_aproximado, evento.mes_aproximado, 1),
            datetime.date(evento.anio_aproximado, evento.mes_aproximado, ultimo_dia),
        )
    return None


def _con_relaciones(qs):
    return qs.select_related(
        "categoria_principal", "distrito__provincia", "provincia", "localidad"
    ).prefetch_related(
        Prefetch("tags_experiencia", queryset=TagExperiencia.objects.filter(activo=True))
    )


def _resumen(evento, ocurrencia):
    inicio, fin = ocurrencia or (None, None)
    provincia = evento.distrito.provincia if evento.distrito_id else evento.provincia
    return {
        "id": evento.pk,
        "nombre": evento.nombre,
        "slug": evento.slug,
        "descripcion_corta": evento.descripcion_corta,
        "categoria": evento.categoria_principal.nombre,
        "categoria_slug": evento.categoria_principal.slug,
        "tags": [t.nombre for t in evento.tags_experiencia.all()],
        "estado": evento.estado,
        "tipo_fecha": evento.tipo_fecha,
        "fecha_inicio": fecha_iso(inicio),
        "fecha_fin": fecha_iso(fin),
        "mes_aproximado": evento.mes_aproximado,
        "anio_aproximado": evento.anio_aproximado,
        "tipo_horario": evento.tipo_horario,
        "hora_inicio": fecha_iso(evento.hora_inicio),
        "hora_fin": fecha_iso(evento.hora_fin),
        "modalidad": evento.modalidad,
        "tipo_ubicacion": evento.tipo_ubicacion,
        "lugar": evento.lugar,
        "direccion": evento.direccion,
        "descripcion_ubicacion": evento.descripcion_ubicacion,
        "distrito": evento.distrito.nombre_oficial if evento.distrito_id else None,
        "distrito_slug": evento.distrito.slug if evento.distrito_id else None,
        "provincia": provincia.nombre_oficial if provincia else None,
        "localidad": evento.localidad.nombre if evento.localidad_id else None,
        "tipo_costo": evento.tipo_costo,
        "precio_desde": decimal_str(evento.precio_desde),
        "precio_hasta": decimal_str(evento.precio_hasta),
        "destacado": evento.destacado,
        "url_listado": reverse("eventos:listado_eventos"),
    }


def _clave_orden(par):
    ocurrencia, evento = par
    inicio = ocurrencia[0] if ocurrencia else datetime.date.max
    return inicio, evento.nombre


def buscar_eventos(
    q=None,
    categoria=None,
    provincia=None,
    distrito=None,
    tipo_costo=None,
    tags=None,
    fecha_desde=None,
    fecha_hasta=None,
    incluir_aproximados=None,
    limit=None,
):
    """
    Eventos publicados. Con rango de fechas usa Evento.objects.que_solapan()
    (exacta/rango/anual_*/pascua_relativa). `incluir_aproximados` añade
    'mes_aproximado' (si su mes solapa el rango) y 'por_confirmar'; por
    defecto es True sin rango y False con rango.
    """
    limit = normalizar_limit(limit)
    q = validar_texto(q, "q")
    categoria = validar_texto(categoria, "categoria")
    provincia = validar_texto(provincia, "provincia")
    distrito = validar_texto(distrito, "distrito")
    tipo_costo = validar_choice(tipo_costo, "tipo_costo", Evento.TIPO_COSTO_CHOICES)
    tags = validar_lista_texto(tags, "tags")
    fecha_desde = validar_fecha(fecha_desde, "fecha_desde")
    fecha_hasta = validar_fecha(fecha_hasta, "fecha_hasta")
    incluir_aproximados = validar_bool(incluir_aproximados, "incluir_aproximados")

    if fecha_desde and not fecha_hasta:
        fecha_hasta = fecha_desde
    if fecha_hasta and not fecha_desde:
        fecha_desde = fecha_hasta
    if fecha_desde and fecha_hasta < fecha_desde:
        raise ArgumentoInvalido("fecha_hasta", "no puede ser anterior a fecha_desde")
    rango = (fecha_desde, fecha_hasta) if fecha_desde else None
    if incluir_aproximados is None:
        incluir_aproximados = rango is None

    qs = Evento.objects.publicados()
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(descripcion_corta__icontains=q))
    if categoria:
        qs = qs.filter(
            Q(categoria_principal__slug=categoria) | Q(categorias_secundarias__slug=categoria)
        ).distinct()
    if provincia:
        qs = qs.filter(Q(provincia__slug=provincia) | Q(distrito__provincia__slug=provincia))
    if distrito:
        qs = qs.filter(distrito__slug=distrito)
    if tipo_costo:
        qs = qs.filter(tipo_costo=tipo_costo)
    if tags:
        qs = qs.filter(tags_experiencia__slug__in=tags).distinct()

    if rango:
        ids = list(qs.que_solapan(*rango).values_list("id", flat=True))
        if incluir_aproximados:
            ids += [
                e.id for e in qs.filter(tipo_fecha="mes_aproximado") if _mes_en_rango(e, *rango)
            ]
            ids += list(qs.filter(tipo_fecha="por_confirmar").values_list("id", flat=True))
        qs = Evento.objects.filter(id__in=ids)
    elif not incluir_aproximados:
        qs = qs.exclude(tipo_fecha__in=TIPOS_APROXIMADOS)

    hoy = timezone.localdate()
    eventos = _con_relaciones(qs).order_by("nombre", "id")[:MAX_EVALUADOS]
    pares = sorted(((_ocurrencia(e, hoy, rango), e) for e in eventos), key=_clave_orden)
    return resultado_lista(
        "buscar_eventos", [_resumen(e, ocurrencia) for ocurrencia, e in pares[:limit]]
    )


def obtener_evento(slug):
    slug = validar_texto_obligatorio(slug, "slug")
    evento = (
        _con_relaciones(Evento.objects.publicados())
        .prefetch_related(
            Prefetch(
                "recomendaciones_detalle",
                queryset=RecomendacionEvento.objects.filter(activo=True),
            )
        )
        .filter(slug=slug)
        .first()
    )
    if evento is None:
        return resultado_item("obtener_evento", None)

    item = _resumen(evento, _ocurrencia(evento, timezone.localdate(), None))
    item.update(
        {
            "descripcion": evento.descripcion,
            "contexto_cultural": evento.contexto_cultural,
            "recomendaciones": evento.recomendaciones,
            "recomendaciones_detalle": [
                {"titulo": r.titulo, "descripcion": r.descripcion}
                for r in evento.recomendaciones_detalle.all()
            ],
            "organizador": evento.organizador,
            "telefono": evento.telefono,
            "whatsapp": evento.whatsapp,
            "correo": evento.correo,
            "sitio_web": evento.sitio_web,
            "referencia": evento.referencia,
            "latitud": decimal_str(evento.latitud),
            "longitud": decimal_str(evento.longitud),
        }
    )
    return resultado_item("obtener_evento", item)
