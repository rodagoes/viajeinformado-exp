from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch
from urllib.parse import quote

from .models import (
    ContactoSucursalEstablecimiento,
    Establecimiento,
    CategoriaEstablecimiento,
    ImagenEstablecimiento,
    RecomendacionEstablecimiento,
    ServicioEstablecimiento,
    SucursalEstablecimiento,
)


def get_listado_context(request, tipo_establecimiento, titulo, subtitulo):
    """
    Contexto reutilizable para listados públicos de restaurantes y alojamientos.
    """

    # Queryset base por tipo y estado activo
    base_qs = Establecimiento.objects.filter(
        tipo=tipo_establecimiento,
        activo=True
    )

    # Categorías disponibles SOLO para el tipo actual:
    # restaurantes -> categorías de restaurantes
    # alojamientos -> categorías de alojamientos
    categorias_principales_ids = base_qs.exclude(
        categoria_principal__isnull=True
    ).values_list(
        "categoria_principal_id",
        flat=True
    )

    categorias_secundarias_ids = base_qs.exclude(
        categorias_secundarias__isnull=True
    ).values_list(
        "categorias_secundarias__id",
        flat=True
    )

    categorias_ids = list(categorias_principales_ids) + list(categorias_secundarias_ids)

    categorias = CategoriaEstablecimiento.objects.filter(
        activo=True,
        id__in=categorias_ids
    ).distinct().order_by("nombre")

    # Prefetch para sucursales activas.
    # Primero intenta traer la sucursal principal y luego las demás.
    sucursales_prefetch = Prefetch(
        "sucursales",
        queryset=SucursalEstablecimiento.objects.filter(
            activo=True
        ).order_by(
            "-es_principal",
            "id"
        )
    )

    qs = base_qs.select_related(
        "categoria_principal"
    ).prefetch_related(
        sucursales_prefetch
    )

    # Parámetros GET
    q = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "").strip()
    orden = request.GET.get("orden", "").strip()

    # Filtro por nombre
    if q:
        qs = qs.filter(nombre__icontains=q)

    # Filtro por categoría
    if categoria_id.isdigit():
        qs = qs.filter(
            Q(categoria_principal_id=categoria_id) |
            Q(categorias_secundarias__id=categoria_id)
        ).distinct()

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
        # Orden predeterminado
        qs = qs.order_by("id")

    # Paginación: 6 resultados por página
    paginator = Paginator(qs, 6)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Opciones de categorías preparadas para el template.
    # Así evitamos usar comparaciones tipo categoria_sel == c.id dentro del HTML.
    categorias_opciones = []
    for categoria in categorias:
        categorias_opciones.append({
            "id": categoria.id,
            "nombre": categoria.nombre,
            "selected": str(categoria.id) == categoria_id,
        })

    # Opciones de orden preparadas para el template.
    # Así el select muestra correctamente la opción seleccionada.
    opciones_orden = [
        {
            "value": "",
            "label": "Seleccione",
            "selected": orden == "",
        },
        {
            "value": "nombre_asc",
            "label": "Nombre Ascendente",
            "selected": orden == "nombre_asc",
        },
        {
            "value": "nombre_desc",
            "label": "Nombre Descendente",
            "selected": orden == "nombre_desc",
        },
        {
            "value": "precio_asc",
            "label": "Menor a Mayor Precio",
            "selected": orden == "precio_asc",
        },
        {
            "value": "precio_desc",
            "label": "Mayor a Menor Precio",
            "selected": orden == "precio_desc",
        },
    ]

    context = {
        "page_obj": page_obj,
        "titulo": titulo,
        "subtitulo": subtitulo,
        "tipo": tipo_establecimiento,
        "q": q,
        "categoria_sel": categoria_id,
        "orden_sel": orden,
        "categorias": categorias,
        "categorias_opciones": categorias_opciones,
        "opciones_orden": opciones_orden,
        "total_resultados": paginator.count,

        # Switcher de apartados
        "es_restaurante": tipo_establecimiento == "restaurante",
        "es_alojamiento": tipo_establecimiento == "alojamiento",
    }

    return context


def listado_restaurantes(request):
    context = get_listado_context(
        request,
        "restaurante",
        "Descubre los mejores restaurantes de Huánuco",
        "Encuentra los lugares más deliciosos para disfrutar de la gastronomía local."
    )
    return render(request, "establecimientos/listado_establecimientos.html", context)


def listado_alojamientos(request):
    context = get_listado_context(
        request,
        "alojamiento",
        "Descubre los mejores alojamientos de Huánuco",
        "Encuentra el lugar perfecto para descansar y disfrutar de tu estadía."
    )
    return render(request, "establecimientos/listado_establecimientos.html", context)


def detalle_establecimiento(request, tipo_establecimiento, slug):
    """
    Vista pública de detalle para restaurantes y alojamientos.

    Prepara datos existentes para:
    - Hero / carrusel visual.
    - Contactos reales.
    - Sucursal principal.
    - Dirección para mapa.
    - Diferenciación visual entre restaurante y alojamiento.
    """

    sucursales_prefetch = Prefetch(
        "sucursales",
        queryset=SucursalEstablecimiento.objects.filter(
            activo=True
        ).select_related(
            "distrito",
            "localidad"
        ).prefetch_related(
            Prefetch(
                "contactos",
                queryset=ContactoSucursalEstablecimiento.objects.filter(
                    activo=True
                ).order_by(
                    "-es_principal",
                    "orden",
                    "id"
                )
            )
        ).order_by(
            "-es_principal",
            "nombre",
            "id"
        )
    )

    establecimiento = get_object_or_404(
        Establecimiento.objects.filter(
            activo=True,
            tipo=tipo_establecimiento
        ).select_related(
            "categoria_principal"
        ).prefetch_related(
            Prefetch(
                "categorias_secundarias",
                queryset=CategoriaEstablecimiento.objects.filter(
                    activo=True
                ).order_by("nombre")
            ),
            Prefetch(
                "servicios",
                queryset=ServicioEstablecimiento.objects.filter(
                    activo=True
                ).order_by("nombre")
            ),
            Prefetch(
                "imagenes",
                queryset=ImagenEstablecimiento.objects.filter(
                    activo=True
                ).order_by("orden", "id")
            ),
            Prefetch(
                "recomendaciones",
                queryset=RecomendacionEstablecimiento.objects.filter(
                    activo=True
                ).order_by("orden", "id")
            ),
            sucursales_prefetch
        ),
        slug=slug
    )

    # Sucursales ordenadas: principal primero.
    sucursales = list(establecimiento.sucursales.all())
    sucursal_principal = sucursales[0] if sucursales else None

    # Contactos principales.
    # Orden de prioridad:
    # 1. Contacto guardado directamente en Establecimiento.
    # 2. Contacto guardado en Sucursal.
    # 3. Contacto adicional registrado en ContactoSucursalEstablecimiento.
    contacto_whatsapp = establecimiento.whatsapp
    contacto_telefono = establecimiento.telefono
    contacto_correo = establecimiento.correo

    for sucursal in sucursales:
        if not contacto_whatsapp and sucursal.whatsapp:
            contacto_whatsapp = sucursal.whatsapp

        if not contacto_telefono and sucursal.telefono:
            contacto_telefono = sucursal.telefono

        if not contacto_correo and sucursal.correo:
            contacto_correo = sucursal.correo

        for contacto in sucursal.contactos.all():
            if not contacto_whatsapp and contacto.tipo_contacto == "whatsapp":
                contacto_whatsapp = contacto.valor

            if not contacto_telefono and contacto.tipo_contacto in [
                "telefono",
                "celular",
                "reservas",
                "atencion_cliente",
            ]:
                contacto_telefono = contacto.valor

            if not contacto_correo and contacto.tipo_contacto == "correo":
                contacto_correo = contacto.valor

    # Imágenes para el carrusel del detalle.
    # Solo usamos las imágenes registradas en "Imágenes de establecimientos".
    # La imagen principal del establecimiento queda reservada para el listado.
    media_items = []
    urls_agregadas = set()

    for imagen in establecimiento.imagenes.all():
        if imagen.imagen and imagen.imagen.url not in urls_agregadas:
            media_items.append({
                "url": imagen.imagen.url,
                "alt": imagen.texto_alt or imagen.titulo or establecimiento.nombre,
                "titulo": imagen.titulo,
            })
            urls_agregadas.add(imagen.imagen.url)

    # Datos preparados para Google Maps.
    # Importante: las coordenadas se formatean con punto decimal para evitar que
    # Google Maps reciba valores localizados con coma, por ejemplo -9,9320000.
    def coord_to_string(value):
        if value is None:
            return ""
        return format(value, "f")

    def build_sucursal_mapa(sucursal):
        direccion = sucursal.direccion or ""
        referencia = sucursal.referencia or ""
        horario = sucursal.horario_atencion or ""
        distrito = str(sucursal.distrito) if sucursal.distrito else ""
        localidad = str(sucursal.localidad) if sucursal.localidad else ""
        latitud = coord_to_string(sucursal.latitud)
        longitud = coord_to_string(sucursal.longitud)

        direccion_partes = [direccion, distrito, localidad, "Huánuco", "Perú"]
        direccion_mapa = ", ".join([parte for parte in direccion_partes if parte])

        if latitud and longitud:
            maps_query = f"{latitud},{longitud}"
        else:
            maps_query = direccion_mapa

        maps_query_encoded = quote(maps_query)

        return {
            "id": sucursal.id,
            "nombre": sucursal.nombre or "Local principal",
            "label": "Local principal" if sucursal.es_principal else "Sucursal",
            "tab_label": "Local principal" if sucursal.es_principal else sucursal.nombre,
            "direccion": direccion,
            "referencia": referencia,
            "horario": horario,
            "distrito": distrito,
            "localidad": localidad,
            "latitud": latitud,
            "longitud": longitud,
            "es_principal": sucursal.es_principal,
            "maps_query": maps_query,
            "maps_query_encoded": maps_query_encoded,
            "open_url": f"https://www.google.com/maps/search/?api=1&query={maps_query_encoded}" if maps_query else "",
            "route_url": f"https://www.google.com/maps/dir/?api=1&destination={maps_query_encoded}" if maps_query else "",
            "embed_url": f"https://www.google.com/maps?q={maps_query_encoded}&z=17&hl=es&output=embed" if maps_query else "",
        }

    sucursales_mapa = [build_sucursal_mapa(sucursal) for sucursal in sucursales]
    sucursal_mapa_principal = sucursales_mapa[0] if sucursales_mapa else None
    direccion_mapa = sucursal_mapa_principal["maps_query"] if sucursal_mapa_principal else ""

    # Recomendaciones Top 3 para la sección "Sobre el establecimiento".
    recomendaciones = list(establecimiento.recomendaciones.all()[:3])

    # Carta pública para restaurantes: PDF interno primero; URL externa como alternativa.
    carta_publica_url = ""
    if tipo_establecimiento == "restaurante":
        if establecimiento.carta_pdf:
            carta_publica_url = establecimiento.carta_pdf.url
        elif establecimiento.carta_url:
            carta_publica_url = establecimiento.carta_url

    context = {
        "establecimiento": establecimiento,
        "es_restaurante": tipo_establecimiento == "restaurante",
        "es_alojamiento": tipo_establecimiento == "alojamiento",

        # Datos preparados para el detalle
        "sucursales": sucursales,
        "sucursal_principal": sucursal_principal,
        "sucursales_mapa": sucursales_mapa,
        "sucursal_mapa_principal": sucursal_mapa_principal,
        "contacto_whatsapp": contacto_whatsapp,
        "contacto_telefono": contacto_telefono,
        "contacto_correo": contacto_correo,
        "media_items": media_items,
        "media_items_count": len(media_items),
        "direccion_mapa": direccion_mapa,
        "recomendaciones": recomendaciones,
        "carta_publica_url": carta_publica_url,

        # URL de retorno
        "volver_url_name": "establecimientos:listado_restaurantes"
        if tipo_establecimiento == "restaurante"
        else "establecimientos:listado_alojamientos",
    }

    return render(request, "establecimientos/detalle_establecimiento.html", context)

