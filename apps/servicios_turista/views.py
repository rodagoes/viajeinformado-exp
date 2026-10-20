from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import render
from django.utils.translation import gettext, gettext_lazy

from apps.base.services.mapas import coord_a_texto

from .models import CategoriaServicioTurista, ContactoServicioTurista, SedeServicioTurista
from .services.contactos import contactos_de_sede, telefono_llamar
from .services.mapas_sede import resolver_mapa
from .services.zonas import (
    NOMBRE_ZONA_TODAS,
    ZONA_TODAS_SLUG,
    nombre_publico_zona,
    obtener_zonas_con_servicios,
    resolver_zona,
)

ENLACES_OFICIALES_CONFIG = [
    ("sitio_web", gettext_lazy("Sitio web oficial"), "bi-globe2"),
    ("facebook", gettext_lazy("Facebook oficial"), "bi-facebook"),
    ("instagram", gettext_lazy("Instagram oficial"), "bi-instagram"),
]


def _texto_disponibilidad(sede):
    """'Atención 24 h' si corresponde; si no, el horario tal cual está
    guardado. Nunca se calcula un estado ABIERTO/CERRADO en tiempo real:
    no hay horario estructurado suficiente para garantizarlo."""
    if sede.disponibilidad == "veinticuatro_horas":
        return gettext("Atención 24 h")
    return sede.horario_atencion or ""


def _contactos_modal(sede):
    """Contactos de la sede (precedencia y deduplicación en services.contactos)."""
    return [
        {"etiqueta": c["etiqueta"], "valor": c["valor"], "valor_tel": c["valor_tel"]}
        for c in contactos_de_sede(sede)
    ]


def _enlaces_oficiales(servicio):
    """Enlaces oficiales de la entidad (sitio_web/facebook/instagram). Lista
    vacía si no hay ninguno: la pill del modal desaparece por completo."""
    enlaces = []
    for campo, label, icono in ENLACES_OFICIALES_CONFIG:
        url = getattr(servicio, campo)
        if url:
            enlaces.append({"tipo": campo, "url": url, "label": label, "icono": icono})
    return enlaces


def _datos_mapa(sede):
    """Datos para el panel "Cómo llegar", o None si no hay nada que mostrar (en
    ese caso la card no debe ofrecer un botón que no funcionaría). La fuente de
    cada enlace y su fiabilidad las decide services.mapas_sede.resolver_mapa."""
    mapa = resolver_mapa(sede)
    if not mapa["hay_mapa"]:
        return None
    return {
        "nombre": sede.nombre_publico,
        "direccion": (sede.direccion or "").strip(),
        "latitud": coord_a_texto(sede.latitud),
        "longitud": coord_a_texto(sede.longitud),
        "open_url": mapa["open_url"],
        "route_url": mapa["route_url"],
        "embed_url": mapa["embed_url"],
        "precision": mapa["precision"],
    }


def _tarjeta_servicio(sede):
    """Una tarjeta por sede; su id (pk de la sede) es el que usa el JS."""
    servicio = sede.servicio
    imagen = servicio.imagen_principal

    return {
        "id": sede.id,
        "nombre": sede.nombre_publico,
        "categoria": servicio.categoria_principal.nombre if servicio.categoria_principal_id else "",
        "descripcion_corta": servicio.descripcion_corta,
        "direccion": sede.direccion,
        "disponibilidad_texto": _texto_disponibilidad(sede),
        "telefono_tel": telefono_llamar(sede),
        "contactos": _contactos_modal(sede),
        "enlaces": _enlaces_oficiales(servicio),
        "imagen_url": imagen.url if imagen else "",
        "imagen_alt": servicio.texto_alt_imagen or sede.nombre_publico,
        "mapa": _datos_mapa(sede),
    }


def servicios_utiles(request):
    zona_slug = request.GET.get("zona", "").strip()
    categoria_slug = request.GET.get("categoria", "").strip()

    zonas_con_servicios = list(obtener_zonas_con_servicios())

    mostrar_todas = zona_slug == ZONA_TODAS_SLUG
    zona = None if mostrar_todas else resolver_zona(zona_slug or None)

    zonas_opciones = [
        {"slug": ZONA_TODAS_SLUG, "nombre": NOMBRE_ZONA_TODAS, "selected": mostrar_todas},
    ] + [
        {
            "slug": z.slug,
            "nombre": nombre_publico_zona(z),
            "selected": zona is not None and z.slug == zona.slug,
        }
        for z in zonas_con_servicios
    ]

    # Sedes visibles: sede activa Y entidad activa. Acotado a la zona resuelta,
    # a TODAS las zonas con servicios activos (mismo alcance de departamento que
    # obtener_zonas_con_servicios), o vacío si todavía no hay ninguna.
    sedes_activas = SedeServicioTurista.objects.filter(activo=True, servicio__activo=True)
    if mostrar_todas:
        qs_zona = sedes_activas.filter(distrito__provincia__departamento__slug="huanuco")
    elif zona is not None:
        qs_zona = sedes_activas.filter(distrito=zona)
    else:
        qs_zona = SedeServicioTurista.objects.none()

    # Categorías disponibles: solo las que tienen servicios activos en la
    # zona actual, igual que hace establecimientos con las suyas.
    categorias_principales_ids = qs_zona.values_list("servicio__categoria_principal_id", flat=True)
    categorias_secundarias_ids = qs_zona.exclude(
        servicio__categorias_secundarias__isnull=True
    ).values_list("servicio__categorias_secundarias__id", flat=True)
    categorias_ids = list(categorias_principales_ids) + list(categorias_secundarias_ids)

    categorias = list(
        CategoriaServicioTurista.objects.filter(
            activo=True, id__in=categorias_ids
        ).distinct().order_by("nombre")
    )

    # Se resuelve por separado de "categorias" (que solo lista categorías
    # CON resultados en esta zona): si la categoría pedida existe pero no
    # tiene servicios aquí, el filtro debe seguir aplicándose e ir al
    # estado vacío, no ignorarse silenciosamente y mostrar todo.
    categoria_actual = None
    if categoria_slug:
        categoria_actual = CategoriaServicioTurista.objects.filter(
            slug=categoria_slug, activo=True
        ).first()

    categorias_opciones = [
        {
            "slug": c.slug,
            "nombre": c.nombre,
            "tipo_icono": c.tipo_icono,
            "icono_bootstrap": c.icono_bootstrap,
            "icono_archivo_url": c.icono_archivo.url if c.icono_archivo else "",
            "selected": categoria_actual is not None and c.id == categoria_actual.id,
        }
        for c in categorias
    ]

    activos = ContactoServicioTurista.objects.filter(activo=True)
    qs = qs_zona.select_related("servicio__categoria_principal", "distrito").prefetch_related(
        Prefetch("contactos", queryset=activos),
        Prefetch("servicio__contactos", queryset=activos),
    ).order_by("servicio__categoria_principal__nombre", "servicio__nombre", "nombre", "id")
    if categoria_actual is not None:
        qs = qs.filter(
            Q(servicio__categoria_principal=categoria_actual)
            | Q(servicio__categorias_secundarias=categoria_actual)
        ).distinct()

    paginator = Paginator(qs, 6)
    page_obj = paginator.get_page(request.GET.get("page"))

    tarjetas = [_tarjeta_servicio(sede) for sede in page_obj]
    tarjetas_con_mapa = [t for t in tarjetas if t["mapa"] is not None]

    context = {
        "zona_actual": zona,
        "zona_actual_slug": ZONA_TODAS_SLUG if mostrar_todas else (zona.slug if zona else ""),
        "zona_actual_nombre": NOMBRE_ZONA_TODAS if mostrar_todas else (nombre_publico_zona(zona) if zona else ""),
        "zonas_opciones": zonas_opciones,
        "hay_zonas": bool(zonas_con_servicios),
        "categoria_actual": categoria_actual,
        "categorias_opciones": categorias_opciones,
        "page_obj": page_obj,
        "total_resultados": paginator.count,
        "tarjetas": tarjetas,
        "tarjetas_con_mapa": tarjetas_con_mapa,
        "hay_resultados": bool(paginator.count),
    }

    return render(request, "servicios_turista/servicios_utiles.html", context)
