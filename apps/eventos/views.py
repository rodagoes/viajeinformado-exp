import logging
from collections import Counter
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.ubicaciones.models import Distrito, Provincia

from .forms import PromocionarEventoForm, ReportarProblemaEventoForm
from .models import (
    MES_CHOICES, CategoriaEvento, Evento, RecomendacionEvento, TagExperiencia,
    ocurrencia_anual_en_rango, ocurrencia_anual_relevante,
    ocurrencia_pascua_en_rango, ocurrencia_pascua_relevante,
    ocurrencia_relativa_en_rango, ocurrencia_relativa_relevante,
)

logger = logging.getLogger(__name__)

POR_PAGINA = 6
# 14 días (2 semanas) en vez de 7 (R2): en mobile ya no hay flechas — el
# selector se navega solo por swipe — así que una ventana más larga evita
# que quede corta/vacía apenas se libera el espacio de las flechas.
DIAS_VENTANA_SELECTOR = 14
CUANDO_VALORES = ("hoy", "manana", "fin_de_semana", "esta_semana")
DIAS_SEMANA_ABREV = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]

# Iconos propios por tag de Experiencia (R3): el modelo solo tiene
# `icono_bootstrap` (fuente de iconos genérica para todo el admin), así que
# el mapeo específico de estos 8 SVGs vive aquí en vez de forzar una
# migración de esquema para un set fijo y ya conocido de archivos.
ICONOS_EXPERIENCIA = {
    "aventura": "aventura-iconovi.svg",
    "cultura": "cultura-iconovi.svg",
    "familias": "familia-iconovi.svg",
    "fotografia": "fotografia-iconovi.svg",
    "gastronomia": "gastronomia-iconovi.svg",
    "naturaleza": "naturaleza-iconovi.svg",
    "ninos": "ninos-iconovi.svg",
    "vida-nocturna": "nocturna-iconovi.svg",
}

MESES_ABREV = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}
MESES_NOMBRE = dict(MES_CHOICES)
ORDEN_SEMANA_NOMBRE = dict(Evento.ORDEN_SEMANA_CHOICES)
DIA_SEMANA_NOMBRE = dict(Evento.DIA_SEMANA_CHOICES)
PASCUA_NOMBRE = dict(Evento.PASCUA_OFFSET_CHOICES)


def _parsear_fecha(valor):
    """Devuelve un date válido o None. Nunca lanza excepción (ver E3 sección 13)."""
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _semana_actual(hoy):
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    return lunes, domingo


def _rango_para_cuando(cuando, hoy):
    if cuando == "hoy":
        return hoy, hoy
    if cuando == "manana":
        manana = hoy + timedelta(days=1)
        return manana, manana
    if cuando == "fin_de_semana":
        lunes, domingo = _semana_actual(hoy)
        return lunes + timedelta(days=5), domingo
    if cuando == "esta_semana":
        return _semana_actual(hoy)
    return None, None


def _ocurrencia_contextual(evento, hoy, rango):
    """
    (inicio, fin) para un evento recurrente (anual_fija/anual_relativa/
    pascua_relativa): si hay un filtro temporal activo (`rango` =
    (fecha_desde, fecha_hasta)), la ocurrencia que realmente solapó con ese
    rango — no la "vigente/próxima respecto a hoy" (B4). Sin rango, o si el
    evento no es recurrente, cae al comportamiento de siempre.

    Única fuente de verdad reutilizada por `_ordenar_por_fecha_relevante`,
    `fecha_card` y `estado_card` para que card/modal/orden nunca muestren
    ocurrencias distintas entre sí.
    """
    if evento.tipo_fecha == "anual_fija":
        if rango:
            resultado = ocurrencia_anual_en_rango(
                evento.dia_inicio_anual, evento.mes_inicio_anual,
                evento.dia_fin_anual, evento.mes_fin_anual, *rango,
            )
            if resultado:
                return resultado
        inicio, fin, _en_curso = ocurrencia_anual_relevante(
            evento.dia_inicio_anual, evento.mes_inicio_anual,
            evento.dia_fin_anual, evento.mes_fin_anual, hoy,
        )
        return inicio, fin

    if evento.tipo_fecha == "anual_relativa":
        if rango:
            resultado = ocurrencia_relativa_en_rango(
                evento.orden_semana_relativa, evento.dia_semana_relativa,
                evento.mes_relativa, evento.dia_ancla_relativa, *rango,
            )
            if resultado:
                return resultado
        inicio, fin, _en_curso = ocurrencia_relativa_relevante(
            evento.orden_semana_relativa, evento.dia_semana_relativa,
            evento.mes_relativa, evento.dia_ancla_relativa, hoy,
        )
        return inicio, fin

    if evento.tipo_fecha == "pascua_relativa":
        if rango:
            resultado = ocurrencia_pascua_en_rango(evento.offset_dias_pascua, *rango)
            if resultado:
                return resultado
        inicio, fin, _en_curso = ocurrencia_pascua_relevante(evento.offset_dias_pascua, hoy)
        return inicio, fin

    return None


def _ordenar_por_fecha_relevante(queryset, hoy, rango=None):
    """
    Única fuente de verdad para ordenar exacta/rango/anual_fija por su
    fecha relevante ascendente (en curso primero, luego futuros).
    Reutilizada tanto para listados con filtro temporal activo (pasando
    `rango` para B4) como para el Grupo 1 del listado general (sin rango).
    """
    con_clave = []
    for evento in queryset:
        contextual = _ocurrencia_contextual(evento, hoy, rango)
        inicio = contextual[0] if contextual else evento.fecha_inicio
        con_clave.append((inicio, evento))
    con_clave.sort(key=lambda par: par[0])
    return [evento for _fecha, evento in con_clave]


def _construir_querystring(get_params, **cambios):
    """Copia el querystring actual, aplica cambios (None = eliminar clave) y quita 'page'."""
    datos = get_params.copy()
    datos.pop("page", None)
    for clave, valor in cambios.items():
        if valor is None:
            datos.pop(clave, None)
        else:
            datos[clave] = valor
    return datos.urlencode()


def _ventana_paginas(pagina_actual, total_paginas, tamano):
    """Ventana centrada de como máximo `tamano` números de página alrededor
    de `pagina_actual` (paginador V2.1, sección 6). Con pocas páginas
    (`total_paginas <= tamano`) devuelve todas, sin inventar números que no
    existen (sección 15). Se usa dos veces por request con distinto
    `tamano` (3 para mobile, 5 para desktop) — el resultado con `tamano`
    menor siempre queda contenido en el de `tamano` mayor porque ambos
    comparten el mismo centrado/recorte, lo que permite renderizar una
    única lista (la de desktop) y marcar cuáles de esos números pertenecen
    también a la ventana mobile, sin duplicar el `<ul>` del paginador."""
    if total_paginas <= tamano:
        return list(range(1, total_paginas + 1))
    mitad = tamano // 2
    if pagina_actual <= mitad + 1:
        inicio = 1
    elif pagina_actual >= total_paginas - mitad:
        inicio = total_paginas - tamano + 1
    else:
        inicio = pagina_actual - mitad
    return list(range(inicio, inicio + tamano))


def _fecha_texto(dia, mes):
    """'24 de diciembre': nunca incluye año (R28) — el usuario ya sabe a qué
    año se refiere por el filtro que aplicó, mostrarlo solo genera confusión."""
    return f"{dia} de {MESES_NOMBRE[mes].lower()}"


def _fecha_texto_con_anio(dia, mes, anio):
    """'12 de septiembre de 2026': variante con año, solo para 'Se celebra'
    en el modal (a diferencia de fecha_card/_fecha_texto, que nunca lo
    muestran — ahí sigue rigiendo R28)."""
    return f"{dia} de {MESES_NOMBRE[mes].lower()} de {anio}"


def _rango_fecha_texto(dia_inicio, mes_inicio, dia_fin, mes_fin):
    inicio = _fecha_texto(dia_inicio, mes_inicio)
    if dia_fin and mes_fin and (dia_fin, mes_fin) != (dia_inicio, mes_inicio):
        return f"{inicio} - {_fecha_texto(dia_fin, mes_fin)}"
    return inicio


def _hora_texto(hora):
    horas12 = hora.hour % 12 or 12
    sufijo = "a. m." if hora.hour < 12 else "p. m."
    return f"{horas12}:{hora.minute:02d} {sufijo}"


def _regla_relativa_texto(evento):
    """'Segundo domingo de enero' / 'Primer viernes después del 15 de agosto'."""
    orden = ORDEN_SEMANA_NOMBRE.get(evento.orden_semana_relativa, "").lower()
    dia_semana = DIA_SEMANA_NOMBRE.get(evento.dia_semana_relativa, "").lower()
    mes = MESES_NOMBRE.get(evento.mes_relativa, "").lower()
    texto = f"{orden} {dia_semana}".strip().capitalize()
    if evento.dia_ancla_relativa:
        return f"{texto} después del {evento.dia_ancla_relativa} de {mes}"
    return f"{texto} de {mes}"


def fecha_card(evento, hoy, rango=None):
    """{'principal': ..., 'nota': ...} listo para mostrar en card y modal, sin fabricar fechas.
    Con `rango` (filtro temporal activo), los tipos recurrentes muestran la
    ocurrencia que hizo match con ese rango en vez de la próxima genérica (B4)."""
    if evento.tipo_fecha == "exacta":
        principal = _fecha_texto(evento.fecha_inicio.day, evento.fecha_inicio.month) if evento.fecha_inicio else ""
        return {"principal": principal, "nota": ""}

    if evento.tipo_fecha == "rango":
        if evento.fecha_inicio and evento.fecha_fin:
            principal = _rango_fecha_texto(
                evento.fecha_inicio.day, evento.fecha_inicio.month,
                evento.fecha_fin.day, evento.fecha_fin.month,
            )
        else:
            principal = ""
        return {"principal": principal, "nota": ""}

    if evento.tipo_fecha == "anual_fija":
        if not (evento.dia_inicio_anual and evento.mes_inicio_anual):
            return {"principal": "", "nota": ""}
        principal = _rango_fecha_texto(
            evento.dia_inicio_anual, evento.mes_inicio_anual,
            evento.dia_fin_anual, evento.mes_fin_anual,
        )
        return {"principal": principal, "nota": "Cada año"}

    if evento.tipo_fecha == "anual_relativa":
        if not (evento.orden_semana_relativa and evento.dia_semana_relativa is not None and evento.mes_relativa):
            return {"principal": "", "nota": ""}
        inicio, _fin = _ocurrencia_contextual(evento, hoy, rango)
        return {"principal": _fecha_texto(inicio.day, inicio.month), "nota": f"{_regla_relativa_texto(evento)} · Cada año"}

    if evento.tipo_fecha == "pascua_relativa":
        if evento.offset_dias_pascua is None:
            return {"principal": "", "nota": ""}
        inicio, _fin = _ocurrencia_contextual(evento, hoy, rango)
        nombre_dia = PASCUA_NOMBRE.get(evento.offset_dias_pascua, "")
        return {"principal": _fecha_texto(inicio.day, inicio.month), "nota": f"{nombre_dia} · Fecha móvil"}

    if evento.tipo_fecha == "mes_aproximado":
        nombre_mes = MESES_NOMBRE.get(evento.mes_aproximado, "").upper()
        anio = evento.anio_aproximado or ""
        return {"principal": f"{nombre_mes} {anio}".strip(), "nota": "Fecha exacta por confirmar"}

    return {"principal": "Fecha por confirmar", "nota": ""}


def celebracion_resumen(evento):
    """Texto para 'Se celebra:' en el modal (R74, sección 30): a diferencia de
    fecha_card (ocurrencia contextual, para la card/listado) y de estado_card,
    esto explica cuándo se celebra NORMALMENTE la festividad — la regla en sí,
    nunca una ocurrencia/año calculado. Por eso no recibe `hoy` ni `rango`: la
    responsabilidad del modal ya no es "qué ocurrencia hizo match" (eso sigue
    siendo trabajo de fecha_card/estado_card para la card, ver B4), sino
    "cómo se celebra esta tradición", que es siempre la misma frase sin
    importar la fecha de hoy."""
    if evento.tipo_fecha == "exacta":
        if not evento.fecha_inicio:
            return ""
        return _fecha_texto_con_anio(evento.fecha_inicio.day, evento.fecha_inicio.month, evento.fecha_inicio.year)

    if evento.tipo_fecha == "rango":
        if not (evento.fecha_inicio and evento.fecha_fin):
            return ""
        inicio, fin = evento.fecha_inicio, evento.fecha_fin
        if fin == inicio:
            return _fecha_texto_con_anio(inicio.day, inicio.month, inicio.year)
        if inicio.year == fin.year:
            if inicio.month == fin.month:
                return f"{inicio.day} – {fin.day} de {MESES_NOMBRE[inicio.month].lower()} de {inicio.year}"
            return (
                f"{_fecha_texto(inicio.day, inicio.month)} – "
                f"{_fecha_texto_con_anio(fin.day, fin.month, fin.year)}"
            )
        return (
            f"{_fecha_texto_con_anio(inicio.day, inicio.month, inicio.year)} – "
            f"{_fecha_texto_con_anio(fin.day, fin.month, fin.year)}"
        )

    if evento.tipo_fecha == "anual_fija":
        if not (evento.dia_inicio_anual and evento.mes_inicio_anual):
            return ""
        if evento.dia_fin_anual and evento.mes_fin_anual:
            return (
                f"{_fecha_texto(evento.dia_inicio_anual, evento.mes_inicio_anual)} – "
                f"{_fecha_texto(evento.dia_fin_anual, evento.mes_fin_anual)}"
            )
        return f"Cada {_fecha_texto(evento.dia_inicio_anual, evento.mes_inicio_anual)}"

    if evento.tipo_fecha == "anual_relativa":
        if not (evento.orden_semana_relativa and evento.dia_semana_relativa is not None and evento.mes_relativa):
            return ""
        regla = _regla_relativa_texto(evento)
        return f"Cada {regla[0].lower()}{regla[1:]}"

    if evento.tipo_fecha == "pascua_relativa":
        if evento.offset_dias_pascua is None:
            return ""
        nombre_dia = PASCUA_NOMBRE.get(evento.offset_dias_pascua, "")
        return f"Cada {nombre_dia}"

    if evento.tipo_fecha == "mes_aproximado":
        if not evento.mes_aproximado:
            return ""
        nombre_mes = MESES_NOMBRE.get(evento.mes_aproximado, "").lower()
        anio = evento.anio_aproximado or ""
        return f"Durante {nombre_mes} de {anio}".strip()

    return "Fecha por confirmar"


def horario_card_texto(evento):
    if evento.tipo_horario == "exacta":
        return _hora_texto(evento.hora_inicio) if evento.hora_inicio else ""
    if evento.tipo_horario == "rango":
        if evento.hora_inicio and evento.hora_fin:
            return f"{_hora_texto(evento.hora_inicio)} – {_hora_texto(evento.hora_fin)}"
        return ""
    if evento.tipo_horario == "todo_el_dia":
        return "Todo el día"
    if evento.tipo_horario == "variable":
        return "Horarios variables"
    if evento.tipo_horario == "por_confirmar":
        return "Horario por confirmar"
    return ""  # no_aplica: sin línea de horario


def ubicacion_card_texto(evento):
    """Prioridad: lugar > ámbito regional > descripcion_ubicacion > localidad > distrito > provincia efectiva."""
    if evento.lugar:
        return evento.lugar
    if evento.tipo_ubicacion == "ambito_general" and not evento.distrito_id and not evento.provincia_id:
        if evento.descripcion_ubicacion:
            return f"Región Huánuco — {evento.descripcion_ubicacion}"
        return "Región Huánuco"
    if evento.descripcion_ubicacion:
        return evento.descripcion_ubicacion
    if evento.localidad:
        return evento.localidad.nombre
    if evento.distrito:
        return evento.distrito.nombre_oficial
    if evento.provincia:
        return f"Provincia de {evento.provincia.nombre_oficial}"
    return ""


def costo_card_texto(evento):
    if evento.tipo_costo == "gratis":
        return "Gratuito"
    if evento.tipo_costo == "pagado":
        if evento.precio_desde and evento.precio_hasta:
            return f"S/ {evento.precio_desde} – S/ {evento.precio_hasta}"
        if evento.precio_desde:
            return f"Desde S/ {evento.precio_desde}"
        return "Consultar"
    if evento.tipo_costo == "consultar":
        return "Consultar"
    return ""  # no_aplica: se omite u opcional en el template


def estado_card(evento, hoy, rango=None):
    """Prioridad: cancelado/reprogramado (administrativos) sobre lo calculado.
    "Hoy"/"En curso" siempre se evalúan contra `hoy` real (B4: es un hecho
    global, no depende del filtro), pero usando la ocurrencia contextual
    cuando hay un filtro temporal activo, para no contradecir la fecha
    mostrada en la card/modal."""
    if evento.estado == "cancelado":
        return "Cancelado"
    if evento.estado == "reprogramado":
        return "Reprogramado"
    if evento.tipo_fecha in ("mes_aproximado", "por_confirmar"):
        return "Fecha por confirmar"
    campos_recurrentes_completos = (
        (evento.tipo_fecha == "anual_fija" and evento.dia_inicio_anual and evento.mes_inicio_anual)
        or (
            evento.tipo_fecha == "anual_relativa"
            and evento.orden_semana_relativa and evento.dia_semana_relativa is not None and evento.mes_relativa
        )
        or (evento.tipo_fecha == "pascua_relativa" and evento.offset_dias_pascua is not None)
    )
    if campos_recurrentes_completos:
        contextual = _ocurrencia_contextual(evento, hoy, rango)
        if not contextual:
            return None
        inicio, fin = contextual
        if inicio <= hoy <= fin:
            return "Hoy" if inicio == fin == hoy else "En curso"
        return None
    if evento.tipo_fecha in ("exacta", "rango") and evento.fecha_inicio:
        fin = evento.fecha_fin or evento.fecha_inicio
        if evento.fecha_inicio <= hoy <= fin:
            return "Hoy" if evento.fecha_inicio == fin == hoy else "En curso"
    return None


def tarjeta_para(evento, hoy, rango=None):
    """Datos ya formateados para la card (E4, sección 16) — nada de descripción larga aquí."""
    return {
        "evento": evento,
        "fecha": fecha_card(evento, hoy, rango),
        "horario": horario_card_texto(evento),
        "ubicacion": ubicacion_card_texto(evento),
        "costo": costo_card_texto(evento),
        "estado": estado_card(evento, hoy, rango),
        # Misma regla que "recurrente" en datos_modal_para (única fuente de verdad).
        "recurrente": evento.tipo_fecha in ("anual_fija", "anual_relativa", "pascua_relativa"),
    }


def _icono_archivo_tag(tag):
    """Mismo mapeo que ya usa el filtro (ICONOS_EXPERIENCIA + static()), aquí
    reutilizado para el payload del modal en vez de duplicarlo en JS (R74,
    sección 23)."""
    archivo = ICONOS_EXPERIENCIA.get(tag.slug)
    return static(f"assets/img/eventos/{archivo}") if archivo else ""


def _icono_archivo_url(nombre_archivo):
    """Resuelve la URL estática de un SVG propio de Recomendaciones (R6-R13
    del encargo V3): el campo solo guarda el nombre del archivo (validado
    en el modelo), nunca la ruta completa — la carpeta base ya es conocida."""
    return static(f"assets/img/eventos/{nombre_archivo}") if nombre_archivo else ""


def datos_modal_para(evento, hoy, rango=None):
    """
    Solo información pública (V4/E4 sección 26). NUNCA incluir notas,
    url_fuente, fecha_verificacion ni publico_objetivo.
    Reutiliza el prefetch de tags_experiencia/imagenes/recomendaciones_detalle
    vía .all() para no disparar N+1 (filtrar con .filter() invalidaría el
    prefetch_related — el filtrado de activos/orden ya viene resuelto por el
    Prefetch con queryset propio armado en listado_eventos()).
    """
    galeria_activa = sorted(
        (img for img in evento.imagenes.all() if img.activo),
        key=lambda img: (img.orden, img.id),
    )
    recomendaciones_estructuradas = [
        {
            "titulo": reco.titulo,
            "descripcion": reco.descripcion,
            "icono_archivo": _icono_archivo_url(reco.icono_archivo),
            "icono_bootstrap": reco.icono_bootstrap,
        }
        for reco in evento.recomendaciones_detalle.all()
    ]
    return {
        "id": evento.id,
        "slug": evento.slug,
        "nombre": evento.nombre,
        "categoria": evento.categoria_principal.nombre,
        "fecha": fecha_card(evento, hoy, rango),
        "fecha_detalle": celebracion_resumen(evento),
        "ubicacion": ubicacion_card_texto(evento),
        "costo": costo_card_texto(evento),
        "estado": estado_card(evento, hoy, rango),
        "recurrente": evento.tipo_fecha in ("anual_fija", "anual_relativa", "pascua_relativa"),
        "tags": [
            {"nombre": tag.nombre, "icono_bootstrap": tag.icono_bootstrap, "icono_archivo": _icono_archivo_tag(tag)}
            for tag in evento.tags_experiencia.all()
        ],
        "descripcion": evento.descripcion,
        "contexto_cultural": evento.contexto_cultural,
        # Fallback legacy (R74, sección 46): si no hay recomendaciones
        # estructuradas, el modal cae al texto libre de siempre.
        "recomendaciones_items": recomendaciones_estructuradas,
        "recomendaciones": "" if recomendaciones_estructuradas else evento.recomendaciones,
        "organizador": evento.organizador,
        "telefono": evento.telefono,
        "whatsapp": evento.whatsapp,
        "correo": evento.correo,
        "sitio_web": evento.sitio_web,
        "facebook": evento.facebook,
        "instagram": evento.instagram,
        "imagen_principal": evento.imagen_principal.url if evento.imagen_principal else "",
        "texto_alt_imagen": evento.texto_alt_imagen or evento.nombre,
        "galeria": [
            {"imagen": img.imagen.url, "texto_alt": img.texto_alt or evento.nombre}
            for img in galeria_activa
        ],
    }


def listado_eventos(request):
    hoy = timezone.localdate()
    # Copia mutable desde el inicio: 'costo' ya no es un filtro público (R3,
    # sección 13 — la web sigue en desarrollo y no queremos un filtro
    # invisible que el usuario no pueda controlar desde la UI), así que se
    # descarta de una vez de `get`, la fuente de la que salen todos los
    # enlaces de navegación de abajo (quick filters, selector de días,
    # paginación). Un ?costo=gratis manual nunca vuelve a aparecer ni a filtrar.
    get = request.GET.copy()
    get.pop("costo", None)
    # `semana` ya no es generado por la UI (B2: las flechas del calendario son
    # 100% cliente, nunca tocan el backend/URL) — un ?semana= residual de una
    # URL vieja se ignora aquí mismo y así nunca se propaga a ningún enlace
    # nuevo (querystrings de abajo), sin necesidad de repetir `semana=None`
    # en cada _construir_querystring (mismo patrón que 'costo' arriba).
    get.pop("semana", None)

    # --- filtros no temporales ---
    categoria_slug = get.get("categoria", "").strip()
    provincia_slug = get.get("provincia", "").strip()
    distrito_slug = get.get("distrito", "").strip()

    # Tags de Experiencia (B3): se resuelven aquí (no más abajo) para poder
    # normalizar `tags_slugs` contra los slugs realmente activos antes de
    # filtrar — duplicados se descartan y un slug inválido/manipulado se
    # ignora, mismo criterio que ya se usa para `distrito` (R1.2).
    tags_experiencia = list(TagExperiencia.objects.filter(activo=True).order_by("nombre"))
    tags_activos_slugs = {tag.slug for tag in tags_experiencia}
    tags_slugs = list(dict.fromkeys(t for t in get.getlist("tags") if t in tags_activos_slugs))

    # Distrito y Provincia son datos independientes en el modelo (Alternativa A,
    # ver Evento.clean()), así que el backend es la única autoridad real sobre
    # a qué provincia pertenece cada distrito: si llega un ?distrito= que no
    # existe, o que no pertenece a la ?provincia= indicada, se ignora en vez
    # de tratar la combinación como válida (R1.2). El <select> de distrito en
    # el template ya no ofrece esas opciones (R1.1), pero una URL manual debe
    # quedar igual de protegida.
    distritos = list(Distrito.objects.filter(activo=True).select_related("provincia").order_by("nombre_oficial"))
    if distrito_slug:
        distrito_valido = any(
            d.slug == distrito_slug and (not provincia_slug or d.provincia.slug == provincia_slug)
            for d in distritos
        )
        if not distrito_valido:
            distrito_slug = ""
            get.pop("distrito", None)

    base = (
        Evento.objects.publicados()
        .select_related("categoria_principal", "provincia", "distrito", "localidad")
        .prefetch_related(
            "categorias_secundarias", "tags_experiencia", "imagenes",
            Prefetch(
                "recomendaciones_detalle",
                queryset=RecomendacionEvento.objects.filter(activo=True).order_by("orden", "id"),
            ),
        )
    )

    requiere_distinct = False

    # AND entre tags seleccionados (B3): el evento debe tener TODOS los tags
    # elegidos, no solo alguno (antes `__in` producía OR). Se anota ANTES que
    # cualquier filtro con JOIN que duplique filas (categoría OR más abajo):
    # el COUNT(DISTINCT ...) se agrupa por evento, así que sigue siendo
    # correcto aunque después se agreguen más joins — pero antes evita
    # cualquier ambigüedad de GROUP BY entre dos annotate/distinct distintos.
    if tags_slugs:
        base = base.annotate(
            _tags_coincidentes=Count(
                "tags_experiencia", filter=Q(tags_experiencia__slug__in=tags_slugs), distinct=True,
            )
        ).filter(_tags_coincidentes=len(tags_slugs))

    if categoria_slug:
        base = base.filter(
            Q(categoria_principal__slug=categoria_slug) | Q(categorias_secundarias__slug=categoria_slug)
        )
        requiere_distinct = True

    # Un evento de ámbito regional (ambito_general sin provincia/distrito) aplica a
    # cualquier filtro territorial: su ámbito contiene cualquier provincia o distrito.
    es_regional = Q(tipo_ubicacion="ambito_general", provincia__isnull=True, distrito__isnull=True)

    if provincia_slug:
        base = base.filter(
            Q(provincia__slug=provincia_slug) | Q(distrito__provincia__slug=provincia_slug) | es_regional
        )

    if distrito_slug:
        base = base.filter(Q(distrito__slug=distrito_slug) | es_regional)

    if requiere_distinct:
        base = base.distinct()

    # --- filtro temporal: ?fecha= tiene prioridad sobre ?cuando= ---
    fecha_param = _parsear_fecha(get.get("fecha", ""))
    cuando = get.get("cuando", "").strip()
    if cuando not in CUANDO_VALORES:
        cuando = ""

    if fecha_param:
        fecha_desde = fecha_hasta = fecha_param
    elif cuando:
        fecha_desde, fecha_hasta = _rango_para_cuando(cuando, hoy)
    else:
        fecha_desde = fecha_hasta = None

    if fecha_desde and fecha_hasta:
        # B4: con un filtro temporal activo, la card/modal/orden deben usar
        # la ocurrencia que realmente solapó con este rango, no la "vigente/
        # próxima respecto a hoy" — se propaga como `rango` hasta el render.
        rango = (fecha_desde, fecha_hasta)
        eventos = _ordenar_por_fecha_relevante(base.que_solapan(fecha_desde, fecha_hasta), hoy, rango)
    else:
        rango = None
        # Listado general: 3 grupos (V4, sección 13/23-26).
        grupo1_qs = base.filter(
            Q(tipo_fecha__in=["anual_fija", "anual_relativa", "pascua_relativa"])
            | (
                Q(tipo_fecha__in=["exacta", "rango"])
                & (Q(fecha_fin__gte=hoy) | Q(fecha_fin__isnull=True, fecha_inicio__gte=hoy))
            )
        )
        grupo1 = _ordenar_por_fecha_relevante(grupo1_qs, hoy)
        grupo2 = list(base.filter(tipo_fecha="mes_aproximado").order_by("anio_aproximado", "mes_aproximado"))
        grupo3 = list(base.filter(tipo_fecha="por_confirmar").order_by("nombre"))
        eventos = grupo1 + grupo2 + grupo3

    paginator = Paginator(eventos, POR_PAGINA)
    page_obj = paginator.get_page(get.get("page"))

    # --- selector horizontal de 14 días ---
    # Ancla: ?fecha= elegida > hoy. Las flechas (B2) ya no generan ni leen
    # `semana` — desplazan la ventana 100% en cliente (JS), sin request ni
    # cambio de URL; el filtro de resultados se decide arriba exclusivamente
    # con `fecha`/`cuando`, nunca con el desplazamiento visual del selector.
    ancla = fecha_param or hoy
    dias_selector = []
    for i in range(DIAS_VENTANA_SELECTOR):
        dia = ancla + timedelta(days=i)
        dias_selector.append({
            "fecha": dia,
            # Mes abreviado por card (E1): la ventana puede repartirse entre
            # dos meses (ej. Ago29-Sep04) — cada card lleva su propio mes.
            "mes_abrev": MESES_ABREV[dia.month].upper(),
            "dia_semana": DIAS_SEMANA_ABREV[dia.weekday()],
            "numero": dia.day,
            "es_hoy": dia == hoy,
            "activo": dia == fecha_param,
            "querystring": _construir_querystring(get, fecha=dia.isoformat(), cuando=None),
        })

    # Título fijo "Calendario - <año>" arriba del selector: ya no intenta
    # adivinar el mes dominante de la ventana (ambiguo, ver arriba) — cada
    # card resuelve eso por su cuenta. El año sí es dinámico (el que domina
    # la ventana visible, relevante solo en el borde dic/ene). El JS del
    # desplazamiento client-side (B2) recalcula esto mismo al mover la
    # ventana, con la misma regla de "año más frecuente".
    anio_selector = Counter(d["fecha"].year for d in dias_selector).most_common(1)[0][0]
    calendario_label = f"Calendario - {anio_selector}"

    # Un quick filter es una NUEVA selección temporal: limpia `fecha` para que
    # la franja de días no quede anclada en una ventana ajena a la selección (E5).
    querystrings_cuando = {
        valor: _construir_querystring(get, cuando=valor, fecha=None) for valor in CUANDO_VALORES
    }
    # Base para los hrefs que el JS del selector recalcula al desplazar la
    # ventana (B2): mismos filtros reales, sin fecha/cuando/page.
    querystring_todos = _construir_querystring(get, cuando=None, fecha=None)
    querystring_paginacion = _construir_querystring(get)

    # Ventana de números del paginador (V2.1): se renderiza una sola lista
    # (la de desktop, hasta 5 números) y cada número lleva marcado si
    # también pertenece a la ventana mobile (hasta 3) — el template solo
    # oculta con CSS los que no, evitando duplicar el `<ul>` completo.
    ventana_mobil = set(_ventana_paginas(page_obj.number, page_obj.paginator.num_pages, 3))
    paginas_paginador = [
        {"numero": i, "solo_desktop": i not in ventana_mobil}
        for i in _ventana_paginas(page_obj.number, page_obj.paginator.num_pages, 5)
    ]

    # Solo se serializan los eventos de la página actual (6 máx.), nunca todo el sistema.
    tarjetas = [tarjeta_para(evento, hoy, rango) for evento in page_obj.object_list]
    datos_modal = [datos_modal_para(evento, hoy, rango) for evento in page_obj.object_list]

    # Fuente para el <select> de distrito dependiente de provincia (R1.1/R1.4):
    # se arma en Django a partir de la misma lista ya cargada arriba, sin
    # petición adicional ni duplicar el ubigeo a mano en JS. "__todos__" cubre
    # el caso "Provincia = Todas", que sigue permitiendo elegir cualquier
    # distrito directamente (R1.5).
    distritos_por_provincia = {"__todos__": [{"slug": d.slug, "nombre": d.nombre_oficial} for d in distritos]}
    for d in distritos:
        distritos_por_provincia.setdefault(d.provincia.slug, []).append({"slug": d.slug, "nombre": d.nombre_oficial})

    # SVG propio por tag (R3): se resuelve con `static()` (no concatenación
    # de string en el template) para respetar el manifest de collectstatic
    # si algún día se activa hashing de archivos estáticos en producción.
    # (`tags_experiencia` ya se cargó arriba, junto con la normalización de
    # `tags_slugs` — se reutiliza en vez de repetir la misma query.)
    for tag in tags_experiencia:
        archivo = ICONOS_EXPERIENCIA.get(tag.slug)
        tag.icono_archivo_evento = static(f"assets/img/eventos/{archivo}") if archivo else ""

    # `page` no cuenta como filtro (es paginación); `semana` ya ni siquiera
    # llega hasta aquí (se descarta al inicio de la vista). `fecha`/`cuando`
    # comparten un único slot temporal porque son mutuamente excluyentes por
    # construcción (elegir uno limpia el otro, ver arriba).
    cantidad_filtros_activos = sum(1 for f in (
        categoria_slug, provincia_slug, distrito_slug,
        bool(tags_slugs), bool(fecha_param or cuando),
    ) if f)

    contexto = {
        "page_obj": page_obj,
        "eventos": page_obj.object_list,
        "tarjetas": tarjetas,
        "datos_modal": datos_modal,
        "hoy": hoy,
        "dias_selector": dias_selector,
        "calendario_label": calendario_label,
        "ancla_selector": ancla,
        "querystrings_cuando": querystrings_cuando,
        "querystring_todos": querystring_todos,
        "querystring_paginacion": querystring_paginacion,
        "paginas_paginador": paginas_paginador,
        "cuando_activo": cuando,
        "fecha_activa": fecha_param,
        "filtros_activos": {
            "categoria": categoria_slug,
            "provincia": provincia_slug,
            "distrito": distrito_slug,
            "tags": tags_slugs,
        },
        "cantidad_filtros_activos": cantidad_filtros_activos,
        "hay_filtros_activos": cantidad_filtros_activos > 0,
        "categorias": CategoriaEvento.objects.filter(activo=True).order_by("nombre"),
        "provincias": Provincia.objects.filter(activo=True).order_by("nombre_oficial"),
        "distritos": distritos,
        "distritos_por_provincia": distritos_por_provincia,
        "tags_experiencia": tags_experiencia,
        # Para volver exactamente a esta vista (con filtros/página) tras
        # enviar el CTA "Promociona tu evento"/"Reportar un problema" (R22).
        "ruta_actual": request.get_full_path(),
    }
    return render(request, "eventos/agenda-eventos.html", contexto)


def _redirigir_a_next(request, fallback_name="eventos:listado_eventos"):
    """Vuelve a `next` (querystring/filtros preservados, R22) solo si es un
    destino del propio sitio — nunca a un host externo (R6, open redirect)."""
    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(
        url=destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return HttpResponseRedirect(destino)
    return HttpResponseRedirect(reverse(fallback_name))


@require_POST
def promocionar_evento(request):
    """CTA "Promociona tu evento" (R5): solo envía un correo al equipo para
    su revisión manual — nunca publica un Evento automáticamente (R18)."""
    form = PromocionarEventoForm(request.POST)

    if not form.is_valid():
        if request.POST.get("website"):
            # Honeypot activado: rechazo neutro, sin revelar que se detectó spam (R16).
            return _redirigir_a_next(request)
        messages.error(request, "No pudimos enviar tu propuesta: revisa los datos e inténtalo de nuevo.")
        return _redirigir_a_next(request)

    datos = form.cleaned_data
    tipo_evento_label = dict(form.fields["tipo_evento"].choices).get(datos["tipo_evento"], datos["tipo_evento"])
    pagina_origen = request.build_absolute_uri(request.POST.get("next") or reverse("eventos:listado_eventos"))
    cuerpo = (
        f"Nombre del evento: {datos['nombre_evento']}\n"
        f"Tipo de evento: {tipo_evento_label}\n"
        f"Descripción:\n{datos['descripcion_evento']}\n\n"
        f"Correo del remitente: {datos['correo']}\n"
        f"Fecha/hora de recepción: {timezone.localtime():%d/%m/%Y %H:%M}\n"
        f"Página de origen: {pagina_origen}\n"
    )

    email = EmailMessage(
        subject=f"[Viaje Informado] Nueva propuesta de evento — {datos['nombre_evento']}",
        body=cuerpo,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[settings.EVENTOS_CONTACT_EMAIL],
        reply_to=[datos["correo"]],
    )
    try:
        email.send(fail_silently=False)
    except Exception:
        logger.exception("No se pudo enviar el correo de propuesta de evento (promocionar_evento)")
        messages.error(request, "No pudimos enviar tu solicitud en este momento. Inténtalo nuevamente en unos minutos.")
        return _redirigir_a_next(request)

    messages.success(request, "Gracias. Recibimos tu propuesta y será revisada por el equipo de Viaje Informado.")
    return _redirigir_a_next(request)


@require_POST
def reportar_problema_evento(request):
    """CTA "Reportar un problema" (R8), mismo patrón que
    apps.emergencias.views.ReportarProblemaEmergenciasView pero con
    POST/redirect/GET normal en vez de fetch/JSON (R20)."""
    form = ReportarProblemaEventoForm(request.POST)

    if not form.is_valid():
        if request.POST.get("website"):
            return _redirigir_a_next(request)
        messages.error(request, "No pudimos enviar tu reporte: revisa los datos e inténtalo de nuevo.")
        return _redirigir_a_next(request)

    datos = form.cleaned_data
    pagina_origen = request.build_absolute_uri(request.POST.get("next") or reverse("eventos:listado_eventos"))
    cuerpo = (
        f"Nombre del problema: {datos['nombre_problema']}\n"
        f"Descripción:\n{datos['descripcion_problema']}\n\n"
        f"Fecha/hora de recepción: {timezone.localtime():%d/%m/%Y %H:%M}\n"
        f"Página de origen: {pagina_origen}\n"
    )

    email = EmailMessage(
        subject=f"[Viaje Informado] Reporte en Eventos — {datos['nombre_problema']}",
        body=cuerpo,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[settings.EVENTOS_CONTACT_EMAIL],
    )
    try:
        email.send(fail_silently=False)
    except Exception:
        logger.exception("No se pudo enviar el correo de reporte de Eventos (reportar_problema_evento)")
        messages.error(request, "No pudimos enviar tu solicitud en este momento. Inténtalo nuevamente en unos minutos.")
        return _redirigir_a_next(request)

    messages.success(request, "Gracias por ayudarnos a mantener la información actualizada. Revisaremos tu reporte.")
    return _redirigir_a_next(request)
