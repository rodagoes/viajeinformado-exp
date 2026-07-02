import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import quote

from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch

from apps.monedas.models import TipoCambio
from .models import (
    CategoriaLugarTuristico,
    ServicioLugarTuristico,
    LugarTuristico,
    ImagenLugarTuristico,
    RecomendacionLugarTuristico,
)


def listado_lugares(request):
    qs = LugarTuristico.objects.filter(activo=True).select_related(
        "categoria_principal", "distrito", "localidad"
    ).prefetch_related(
        Prefetch(
            "servicios",
            queryset=ServicioLugarTuristico.objects.filter(activo=True).order_by("nombre")
        )
    )

    # Categorías usadas en los lugares activos
    categorias_ids = list(
        LugarTuristico.objects.filter(activo=True)
        .exclude(categoria_principal__isnull=True)
        .values_list("categoria_principal_id", flat=True)
        .distinct()
    )
    categorias = CategoriaLugarTuristico.objects.filter(
        activo=True, id__in=categorias_ids
    ).order_by("nombre")

    # Parámetros GET
    q = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "").strip()
    dificultad_sel = request.GET.get("dificultad", "").strip()
    tipo_costo_sel = request.GET.get("tipo_costo", "").strip()
    orden = request.GET.get("orden", "").strip()

    # Filtros
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) | Q(descripcion_corta__icontains=q)
        )

    if categoria_id.isdigit():
        qs = qs.filter(
            Q(categoria_principal_id=categoria_id) |
            Q(categorias_secundarias__id=categoria_id)
        ).distinct()

    if dificultad_sel:
        qs = qs.filter(dificultad=dificultad_sel)

    if tipo_costo_sel:
        qs = qs.filter(tipo_costo=tipo_costo_sel)

    # Ordenamiento
    if orden == "nombre_asc":
        qs = qs.order_by("nombre", "id")
    elif orden == "nombre_desc":
        qs = qs.order_by("-nombre", "id")
    elif orden == "precio_asc":
        qs = qs.order_by("precio_desde", "precio_hasta", "nombre", "id")
    elif orden == "precio_desc":
        qs = qs.order_by("-precio_hasta", "-precio_desde", "nombre", "id")
    else:
        qs = qs.order_by("-destacado", "nombre", "id")

    # Paginación: 9 por página (3×3)
    paginator = Paginator(qs, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Opciones preparadas para templates
    categorias_opciones = [
        {"id": c.id, "nombre": c.nombre, "selected": str(c.id) == categoria_id}
        for c in categorias
    ]

    dificultad_opciones = [
        {"value": "", "label": "Dificultad", "selected": dificultad_sel == ""},
        {"value": "facil", "label": "Fácil", "selected": dificultad_sel == "facil"},
        {"value": "moderada", "label": "Moderada", "selected": dificultad_sel == "moderada"},
        {"value": "dificil", "label": "Difícil", "selected": dificultad_sel == "dificil"},
    ]

    tipo_costo_opciones = [
        {"value": "", "label": "Costo", "selected": tipo_costo_sel == ""},
        {"value": "gratis", "label": "Gratis", "selected": tipo_costo_sel == "gratis"},
        {"value": "pagado", "label": "Pagado", "selected": tipo_costo_sel == "pagado"},
        {"value": "consultar", "label": "Consultar", "selected": tipo_costo_sel == "consultar"},
    ]

    opciones_orden = [
        {"value": "", "label": "Seleccione", "selected": orden == ""},
        {"value": "nombre_asc", "label": "Nombre A–Z", "selected": orden == "nombre_asc"},
        {"value": "nombre_desc", "label": "Nombre Z–A", "selected": orden == "nombre_desc"},
        {"value": "precio_asc", "label": "Menor a Mayor Precio", "selected": orden == "precio_asc"},
        {"value": "precio_desc", "label": "Mayor a Menor Precio", "selected": orden == "precio_desc"},
    ]

    context = {
        "page_obj": page_obj,
        "titulo": "Lugares Turísticos de Huánuco",
        "subtitulo": "Descubre los mejores atractivos naturales, históricos y culturales de la región.",
        "q": q,
        "categoria_sel": categoria_id,
        "dificultad_sel": dificultad_sel,
        "tipo_costo_sel": tipo_costo_sel,
        "orden_sel": orden,
        "categorias_opciones": categorias_opciones,
        "dificultad_opciones": dificultad_opciones,
        "tipo_costo_opciones": tipo_costo_opciones,
        "opciones_orden": opciones_orden,
        "total_resultados": paginator.count,
    }

    return render(request, "turismo/listado-lugares-turisticos.html", context)


def _decimal_or_none(value):
    if value in (None, ""):
        return None

    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _convertir_pen_a_usd(monto_pen, tipo_cambio):
    monto = _decimal_or_none(monto_pen)

    if monto is None or not tipo_cambio or not tipo_cambio.venta:
        return None

    venta = Decimal(tipo_cambio.venta)
    if venta <= 0:
        return None

    return (monto / venta).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format_decimal_dot(value, decimals=".2f"):
    if value is None:
        return ""
    return format(value, decimals)


def detalle_lugar(request, slug):
    lugar = get_object_or_404(
        LugarTuristico.objects.filter(activo=True).select_related(
            "categoria_principal",
            "distrito__provincia",
            "distrito__provincia__departamento",
            "localidad",
        ).prefetch_related(
            Prefetch(
                "categorias_secundarias",
                queryset=CategoriaLugarTuristico.objects.filter(activo=True).order_by("nombre")
            ),
            Prefetch(
                "servicios",
                queryset=ServicioLugarTuristico.objects.filter(activo=True).order_by("nombre")
            ),
            Prefetch(
                "imagenes",
                queryset=ImagenLugarTuristico.objects.filter(activo=True).order_by("orden", "id")
            ),
            Prefetch(
                "recomendaciones_items",
                queryset=RecomendacionLugarTuristico.objects.filter(activo=True).order_by("orden", "id")
            ),
        ),
        slug=slug
    )

    # Multimedia para galería y visor.
    media_items = []
    urls_vistas = set()

    for item in lugar.imagenes.all():
        if item.tipo_media == "video":
            video_url = (item.video_url or "").strip()
            if video_url and video_url not in urls_vistas:
                media_items.append({
                    "kind": "video",
                    "url": video_url,
                    "alt": item.titulo or lugar.nombre,
                    "titulo": item.titulo,
                    "descripcion": item.descripcion,
                })
                urls_vistas.add(video_url)
            continue

        if item.tipo_media == "video_archivo":
            if item.video_archivo and item.video_archivo.url not in urls_vistas:
                media_items.append({
                    "kind": "video_archivo",
                    "url": item.video_archivo.url,
                    "alt": item.texto_alt or item.titulo or lugar.nombre,
                    "titulo": item.titulo,
                    "descripcion": item.descripcion,
                })
                urls_vistas.add(item.video_archivo.url)
            continue

        if item.imagen and item.imagen.url not in urls_vistas:
            image_data = {
                "kind": "imagen",
                "url": item.imagen.url,
                "alt": item.texto_alt or item.titulo or lugar.nombre,
                "titulo": item.titulo,
                "descripcion": item.descripcion,
            }
            media_items.append(image_data)
            urls_vistas.add(item.imagen.url)

    # Imagen histórica: prioridad campo dedicado; fallback a primera imagen de galería o imagen principal.
    primera_imagen_galeria = next(
        (item for item in media_items if item.get("kind") == "imagen"),
        None
    )

    historia_imagen = None
    if lugar.imagen_historia:
        historia_imagen = {
            "url": lugar.imagen_historia.url,
            "alt": lugar.texto_alt_imagen_historia or f"Imagen histórica de {lugar.nombre}",
        }
    elif primera_imagen_galeria:
        historia_imagen = primera_imagen_galeria
    elif lugar.imagen_principal:
        historia_imagen = {
            "url": lugar.imagen_principal.url,
            "alt": lugar.texto_alt_imagen or lugar.nombre,
        }

    # Google Maps — misma lógica de prioridad que establecimientos.
    def coord_str(value):
        return format(value, "f") if value is not None else ""

    latitud = coord_str(lugar.latitud)
    longitud = coord_str(lugar.longitud)
    embed_code = (lugar.embed_maps or "").strip()
    maps_url_raw = (lugar.maps_url or "").strip()

    provincia_nombre = ""
    distrito_nombre = ""
    departamento_nombre = ""

    if lugar.distrito:
        distrito_nombre = lugar.distrito.nombre_oficial
        if lugar.distrito.provincia:
            provincia_nombre = lugar.distrito.provincia.nombre_oficial
            if lugar.distrito.provincia.departamento:
                departamento_nombre = lugar.distrito.provincia.departamento.nombre_oficial

    # Dirección visual: solo el campo Dirección registrado en la BD.
    # Para Google Maps se mantiene una consulta completa interna, sin mostrarla al usuario.
    direccion_texto = (lugar.direccion or "").strip()
    direccion_maps_partes = [
        lugar.direccion,
        distrito_nombre,
        provincia_nombre,
        departamento_nombre or "Huánuco",
        "Perú",
    ]
    direccion_maps_texto = ", ".join([p for p in direccion_maps_partes if p])

    ubicacion_resumen = " - ".join([p for p in [provincia_nombre, distrito_nombre] if p])

    # Extraer el src del iframe (acepta código completo o solo la URL)
    embed_src = ""
    if embed_code:
        match = re.search(r"src=[\"']([^\"']+)[\"']", embed_code)
        if match:
            embed_src = match.group(1)
        elif embed_code.startswith("https://"):
            embed_src = embed_code

    # Prioridad para embed_url (mapa visual):
    # 1. embed_maps  → pin con nombre real (sin API key)
    # 2. lat/lng     → lugar no indexado en Google Maps
    # 3. dirección   → fallback textual
    if embed_src:
        embed_url = embed_src
    elif latitud and longitud:
        embed_url = f"https://www.google.com/maps?q={quote(latitud + ',' + longitud)}&z=16&hl=es&output=embed"
    elif direccion_maps_texto:
        embed_url = f"https://www.google.com/maps?q={quote(direccion_maps_texto)}&z=15&hl=es&output=embed"
    else:
        embed_url = ""

    # Prioridad para open_url (botón "Abrir en Google Maps"):
    # 1. maps_url    → ficha exacta del lugar
    # 2. lat/lng     → centrar mapa en coordenadas
    # 3. dirección   → búsqueda textual
    if maps_url_raw:
        open_url = maps_url_raw
    elif latitud and longitud:
        open_url = f"https://www.google.com/maps/search/?api=1&query={quote(latitud + ',' + longitud)}"
    elif direccion_maps_texto:
        open_url = f"https://www.google.com/maps/search/?api=1&query={quote(direccion_maps_texto)}"
    else:
        open_url = ""

    # Prioridad para route_url (botón "Cómo llegar"):
    # Extraer !3d/!4d de maps_url para el pin exacto; fallback a @lat,lng o dirección.
    coords_from_url = ""
    if maps_url_raw:
        match_3d4d = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", maps_url_raw)
        if match_3d4d:
            coords_from_url = f"{match_3d4d.group(1)},{match_3d4d.group(2)}"
        else:
            match_at = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", maps_url_raw)
            if match_at:
                coords_from_url = f"{match_at.group(1)},{match_at.group(2)}"

    if coords_from_url:
        route_url = f"https://www.google.com/maps/dir/?api=1&destination={quote(coords_from_url)}"
    elif latitud and longitud:
        route_url = f"https://www.google.com/maps/dir/?api=1&destination={quote(latitud + ',' + longitud)}"
    elif direccion_maps_texto:
        route_url = f"https://www.google.com/maps/dir/?api=1&destination={quote(direccion_maps_texto)}"
    else:
        route_url = ""

    recomendaciones_items = list(lugar.recomendaciones_items.all())

    # Conversión referencial PEN → USD para entrada pagada.
    tipo_cambio_vigente = TipoCambio.vigente()
    precio_desde_usd = _convertir_pen_a_usd(lugar.precio_desde, tipo_cambio_vigente)
    precio_hasta_usd = _convertir_pen_a_usd(lugar.precio_hasta, tipo_cambio_vigente)

    entrada_usd_disponible = bool(
        lugar.tipo_costo == "pagado" and tipo_cambio_vigente and (
            precio_desde_usd is not None or precio_hasta_usd is not None
        )
    )

    context = {
        "lugar": lugar,
        "media_items": media_items,
        "media_count": len(media_items),
        "historia_imagen": historia_imagen,
        "embed_url": embed_url,
        "open_url": open_url,
        "route_url": route_url,
        "direccion_texto": direccion_texto,
        "direccion_maps_texto": direccion_maps_texto,
        "recomendaciones_items": recomendaciones_items,
        "ubicacion_resumen": ubicacion_resumen,
        "provincia_nombre": provincia_nombre,
        "distrito_nombre": distrito_nombre,
        "latitud": latitud,
        "longitud": longitud,
        "tipo_cambio_vigente": tipo_cambio_vigente,
        "tipo_cambio_venta_txt": (
            _format_decimal_dot(tipo_cambio_vigente.venta, ".2f")
            if tipo_cambio_vigente else ""
        ),
        "fecha_tipo_cambio_txt": (
            tipo_cambio_vigente.fecha.strftime("%d-%m-%Y")
            if tipo_cambio_vigente and tipo_cambio_vigente.fecha else ""
        ),
        "precio_desde_usd_txt": _format_decimal_dot(precio_desde_usd, ".2f"),
        "precio_hasta_usd_txt": _format_decimal_dot(precio_hasta_usd, ".2f"),
        "entrada_usd_disponible": entrada_usd_disponible,
    }

    return render(request, "turismo/detalle-lugar-turistico.html", context)
