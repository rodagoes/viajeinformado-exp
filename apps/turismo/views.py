import re
from urllib.parse import quote

from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch

from .models import (
    CategoriaLugarTuristico,
    ServicioLugarTuristico,
    LugarTuristico,
    ImagenLugarTuristico,
)


def listado_lugares(request):
    qs = LugarTuristico.objects.filter(activo=True).select_related(
        'categoria_principal', 'distrito', 'localidad'
    ).prefetch_related(
        Prefetch(
            'servicios',
            queryset=ServicioLugarTuristico.objects.filter(activo=True).order_by('nombre')
        )
    )

    # Categorías usadas en los lugares activos
    categorias_ids = list(
        LugarTuristico.objects.filter(activo=True)
        .exclude(categoria_principal__isnull=True)
        .values_list('categoria_principal_id', flat=True)
        .distinct()
    )
    categorias = CategoriaLugarTuristico.objects.filter(
        activo=True, id__in=categorias_ids
    ).order_by('nombre')

    # Parámetros GET
    q              = request.GET.get('q', '').strip()
    categoria_id   = request.GET.get('categoria', '').strip()
    dificultad_sel = request.GET.get('dificultad', '').strip()
    tipo_costo_sel = request.GET.get('tipo_costo', '').strip()
    orden          = request.GET.get('orden', '').strip()

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
    if orden == 'nombre_asc':
        qs = qs.order_by('nombre', 'id')
    elif orden == 'nombre_desc':
        qs = qs.order_by('-nombre', 'id')
    elif orden == 'precio_asc':
        qs = qs.order_by('precio_desde', 'precio_hasta', 'nombre', 'id')
    elif orden == 'precio_desc':
        qs = qs.order_by('-precio_hasta', '-precio_desde', 'nombre', 'id')
    else:
        qs = qs.order_by('-destacado', 'nombre', 'id')

    # Paginación: 9 por página (3×3)
    paginator   = Paginator(qs, 9)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    # Opciones preparadas para templates
    categorias_opciones = [
        {'id': c.id, 'nombre': c.nombre, 'selected': str(c.id) == categoria_id}
        for c in categorias
    ]

    dificultad_opciones = [
        {'value': '',         'label': 'Dificultad', 'selected': dificultad_sel == ''},
        {'value': 'facil',    'label': 'Fácil',      'selected': dificultad_sel == 'facil'},
        {'value': 'moderada', 'label': 'Moderada',   'selected': dificultad_sel == 'moderada'},
        {'value': 'dificil',  'label': 'Difícil',    'selected': dificultad_sel == 'dificil'},
    ]

    tipo_costo_opciones = [
        {'value': '',          'label': 'Costo',     'selected': tipo_costo_sel == ''},
        {'value': 'gratis',    'label': 'Gratis',    'selected': tipo_costo_sel == 'gratis'},
        {'value': 'pagado',    'label': 'Pagado',    'selected': tipo_costo_sel == 'pagado'},
        {'value': 'consultar', 'label': 'Consultar', 'selected': tipo_costo_sel == 'consultar'},
    ]

    opciones_orden = [
        {'value': '',            'label': 'Seleccione',          'selected': orden == ''},
        {'value': 'nombre_asc',  'label': 'Nombre A–Z',          'selected': orden == 'nombre_asc'},
        {'value': 'nombre_desc', 'label': 'Nombre Z–A',          'selected': orden == 'nombre_desc'},
        {'value': 'precio_asc',  'label': 'Menor a Mayor Precio', 'selected': orden == 'precio_asc'},
        {'value': 'precio_desc', 'label': 'Mayor a Menor Precio', 'selected': orden == 'precio_desc'},
    ]

    context = {
        'page_obj'            : page_obj,
        'titulo'              : 'Lugares Turísticos de Huánuco',
        'subtitulo'           : 'Descubre los mejores atractivos naturales, históricos y culturales de la región.',
        'q'                   : q,
        'categoria_sel'       : categoria_id,
        'dificultad_sel'      : dificultad_sel,
        'tipo_costo_sel'      : tipo_costo_sel,
        'orden_sel'           : orden,
        'categorias_opciones' : categorias_opciones,
        'dificultad_opciones' : dificultad_opciones,
        'tipo_costo_opciones' : tipo_costo_opciones,
        'opciones_orden'      : opciones_orden,
        'total_resultados'    : paginator.count,
    }

    return render(request, 'turismo/listado-lugares-turisticos.html', context)


def detalle_lugar(request, slug):
    lugar = get_object_or_404(
        LugarTuristico.objects.filter(activo=True).select_related(
            'categoria_principal', 'distrito', 'localidad'
        ).prefetch_related(
            Prefetch(
                'categorias_secundarias',
                queryset=CategoriaLugarTuristico.objects.filter(activo=True).order_by('nombre')
            ),
            Prefetch(
                'servicios',
                queryset=ServicioLugarTuristico.objects.filter(activo=True).order_by('nombre')
            ),
            Prefetch(
                'imagenes',
                queryset=ImagenLugarTuristico.objects.filter(activo=True).order_by('orden', 'id')
            ),
        ),
        slug=slug
    )

    # Imágenes para el carrusel
    media_items = []
    urls_vistas = set()
    for img in lugar.imagenes.all():
        if img.imagen and img.imagen.url not in urls_vistas:
            media_items.append({
                'url'   : img.imagen.url,
                'alt'   : img.texto_alt or img.titulo or lugar.nombre,
                'titulo': img.titulo,
            })
            urls_vistas.add(img.imagen.url)

    # Google Maps — misma lógica de prioridad que establecimientos
    def coord_str(value):
        return format(value, 'f') if value is not None else ''

    latitud      = coord_str(lugar.latitud)
    longitud     = coord_str(lugar.longitud)
    embed_code   = (lugar.embed_maps or '').strip()
    maps_url_raw = (lugar.maps_url or '').strip()

    direccion_partes = [
        lugar.direccion,
        str(lugar.distrito) if lugar.distrito else '',
        str(lugar.localidad) if lugar.localidad else '',
        'Huánuco', 'Perú',
    ]
    direccion_texto = ', '.join([p for p in direccion_partes if p])

    # Extraer el src del iframe (acepta código completo o solo la URL)
    embed_src = ''
    if embed_code:
        match = re.search(r'src=["\']([^"\']+)["\']', embed_code)
        if match:
            embed_src = match.group(1)
        elif embed_code.startswith('https://'):
            embed_src = embed_code

    # Prioridad para embed_url (mapa visual):
    # 1. embed_maps  → pin con nombre real (sin API key)
    # 2. lat/lng     → lugar no indexado en Google Maps
    # 3. dirección   → fallback textual
    if embed_src:
        embed_url = embed_src
    elif latitud and longitud:
        embed_url = f'https://www.google.com/maps?q={quote(latitud + "," + longitud)}&z=16&hl=es&output=embed'
    elif direccion_texto:
        embed_url = f'https://www.google.com/maps?q={quote(direccion_texto)}&z=15&hl=es&output=embed'
    else:
        embed_url = ''

    # Prioridad para open_url (botón "Abrir en Google Maps"):
    # 1. maps_url    → ficha exacta del lugar
    # 2. lat/lng     → centrar mapa en coordenadas
    # 3. dirección   → búsqueda textual
    if maps_url_raw:
        open_url = maps_url_raw
    elif latitud and longitud:
        open_url = f'https://www.google.com/maps/search/?api=1&query={quote(latitud + "," + longitud)}'
    elif direccion_texto:
        open_url = f'https://www.google.com/maps/search/?api=1&query={quote(direccion_texto)}'
    else:
        open_url = ''

    # Prioridad para route_url (botón "Cómo llegar"):
    # Extraer !3d/!4d de maps_url para el pin exacto; fallback a @lat,lng o dirección.
    coords_from_url = ''
    if maps_url_raw:
        match_3d4d = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', maps_url_raw)
        if match_3d4d:
            coords_from_url = f'{match_3d4d.group(1)},{match_3d4d.group(2)}'
        else:
            match_at = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', maps_url_raw)
            if match_at:
                coords_from_url = f'{match_at.group(1)},{match_at.group(2)}'

    if coords_from_url:
        route_url = f'https://www.google.com/maps/dir/?api=1&destination={quote(coords_from_url)}'
    elif latitud and longitud:
        route_url = f'https://www.google.com/maps/dir/?api=1&destination={quote(latitud + "," + longitud)}'
    elif direccion_texto:
        route_url = f'https://www.google.com/maps/dir/?api=1&destination={quote(direccion_texto)}'
    else:
        route_url = ''

    context = {
        'lugar'           : lugar,
        'media_items'     : media_items,
        'media_count'     : len(media_items),
        'embed_url'       : embed_url,
        'open_url'        : open_url,
        'route_url'       : route_url,
        'direccion_texto' : direccion_texto,
        'latitud'         : latitud,
        'longitud'        : longitud,
    }

    return render(request, 'turismo/detalle-lugar-turistico.html', context)
