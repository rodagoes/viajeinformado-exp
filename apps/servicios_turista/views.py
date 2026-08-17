import re

from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import render

from apps.base.services.mapas import coord_a_texto, construir_urls_mapa

from .models import CategoriaServicioTurista, ContactoServicioTurista, ServicioTurista
from .services.zonas import (
    NOMBRE_ZONA_TODAS,
    ZONA_TODAS_SLUG,
    nombre_publico_zona,
    obtener_zonas_con_servicios,
    resolver_zona,
)

TELEFONO_LIMPIO_RE = re.compile(r"[^\d+]")

# Tipos de ContactoServicioTurista pensados para llamar/tel:. No se usa
# para decidir qué mostrar (eso lo hace _es_telefonico según el valor),
# solo queda documentado el catálogo real del modelo.
ENLACES_OFICIALES_CONFIG = [
    ("sitio_web", "Sitio web oficial", "bi-globe2"),
    ("facebook", "Facebook oficial", "bi-facebook"),
    ("instagram", "Instagram oficial", "bi-instagram"),
]


def _texto_disponibilidad(servicio):
    """'Atención 24 h' si corresponde; si no, el horario tal cual está
    guardado. Nunca se calcula un estado ABIERTO/CERRADO en tiempo real:
    no hay horario estructurado suficiente para garantizarlo."""
    if servicio.disponibilidad == "veinticuatro_horas":
        return "Atención 24 h"
    return servicio.horario_atencion or ""


def _telefono_tel(telefono):
    """Normaliza a solo dígitos y '+' inicial, listo para href="tel:...".
    Presentación pura: no se agrega ningún campo nuevo al modelo."""
    if not telefono:
        return ""
    return TELEFONO_LIMPIO_RE.sub("", telefono)


def _es_telefonico(valor):
    """Un valor de contacto "parece" un teléfono si tiene suficientes
    dígitos, sin importar el tipo_contacto elegido en el Admin (evita
    asumir que solo "telefono"/"celular" son llamables)."""
    return len(re.sub(r"\D", "", valor or "")) >= 6


def _clave_dedup_contacto(valor):
    """Clave para no repetir el mismo contacto dos veces (ej. "(062)
    512400" y "062512400"): por dígitos si es telefónico, por texto si
    no (correos, etc.). No modifica el valor guardado en BD."""
    if _es_telefonico(valor):
        return _telefono_tel(valor)
    return valor.strip().lower()


def _contactos_modal(servicio):
    """Consolida ContactoServicioTurista.objects (ya prefetcheados y
    activos) con ServicioTurista.telefono como fallback general,
    deduplicando por número/valor."""
    vistos = set()
    resultado = []

    for contacto in servicio.contactos.all():
        valor = (contacto.valor or "").strip()
        if not valor:
            continue
        clave = _clave_dedup_contacto(valor)
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append({
            "etiqueta": contacto.etiqueta,
            "valor": valor,
            "valor_tel": _telefono_tel(valor) if _es_telefonico(valor) else "",
        })

    telefono_general = (servicio.telefono or "").strip()
    if telefono_general:
        clave = _clave_dedup_contacto(telefono_general)
        if clave not in vistos:
            resultado.append({
                "etiqueta": "",
                "valor": telefono_general,
                "valor_tel": _telefono_tel(telefono_general),
            })

    return resultado


def _telefono_llamar(servicio):
    """Teléfono para el botón "Llamar" (solo móvil): contacto principal
    llamable primero, luego el primer contacto llamable por orden, y
    ServicioTurista.telefono como último fallback."""
    contactos_llamables = [c for c in servicio.contactos.all() if _es_telefonico(c.valor)]

    principal = next((c for c in contactos_llamables if c.es_principal), None)
    if principal:
        return _telefono_tel(principal.valor)

    if contactos_llamables:
        return _telefono_tel(contactos_llamables[0].valor)

    return _telefono_tel(servicio.telefono)


def _enlaces_oficiales(servicio):
    """Enlaces oficiales presentes (sitio_web/facebook/instagram). Lista
    vacía si no hay ninguno: la pill del modal desaparece por completo."""
    enlaces = []
    for campo, label, icono in ENLACES_OFICIALES_CONFIG:
        url = getattr(servicio, campo)
        if url:
            enlaces.append({"tipo": campo, "url": url, "label": label, "icono": icono})
    return enlaces


def _datos_mapa(servicio):
    """Datos para el panel "Cómo llegar", o None si no hay ni coordenadas
    ni dirección (en ese caso la card no debe ofrecer un botón que no
    funcionaría)."""
    latitud = coord_a_texto(servicio.latitud)
    longitud = coord_a_texto(servicio.longitud)
    direccion = (servicio.direccion or "").strip()

    if not (latitud and longitud) and not direccion and not (servicio.embed_maps or servicio.maps_url):
        return None

    zona_nombre = nombre_publico_zona(servicio.distrito) if servicio.distrito_id else ""
    direccion_partes = [direccion, zona_nombre, "Perú"]
    direccion_mapa = ", ".join(parte for parte in direccion_partes if parte)

    embed_url, open_url, route_url = construir_urls_mapa(
        latitud=latitud,
        longitud=longitud,
        direccion_mapa=direccion_mapa,
        maps_url=(servicio.maps_url or "").strip(),
        embed_maps=servicio.embed_maps or "",
        zoom_coordenadas=17,
        zoom_direccion=17,
    )

    return {
        "nombre": servicio.nombre,
        "direccion": direccion,
        "latitud": latitud,
        "longitud": longitud,
        "open_url": open_url,
        "route_url": route_url,
        "embed_url": embed_url,
    }


def _tarjeta_servicio(servicio):
    imagen = servicio.imagen_principal

    return {
        "id": servicio.id,
        "nombre": servicio.nombre,
        "categoria": servicio.categoria_principal.nombre if servicio.categoria_principal_id else "",
        "descripcion_corta": servicio.descripcion_corta,
        "direccion": servicio.direccion,
        "disponibilidad_texto": _texto_disponibilidad(servicio),
        "telefono_tel": _telefono_llamar(servicio),
        "contactos": _contactos_modal(servicio),
        "enlaces": _enlaces_oficiales(servicio),
        "imagen_url": imagen.url if imagen else "",
        "imagen_alt": servicio.texto_alt_imagen or servicio.nombre,
        "mapa": _datos_mapa(servicio),
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

    # Queryset acotado a la zona resuelta, a TODAS las zonas con servicios
    # activos (mismo alcance de departamento que obtener_zonas_con_servicios),
    # o vacío si no hay ninguna zona con servicios activos todavía.
    if mostrar_todas:
        qs_zona = ServicioTurista.objects.filter(
            activo=True, distrito__provincia__departamento__slug="huanuco"
        )
    elif zona is not None:
        qs_zona = ServicioTurista.objects.filter(activo=True, distrito=zona)
    else:
        qs_zona = ServicioTurista.objects.none()

    # Categorías disponibles: solo las que tienen servicios activos en la
    # zona actual, igual que hace establecimientos con las suyas.
    categorias_principales_ids = qs_zona.exclude(
        categoria_principal__isnull=True
    ).values_list("categoria_principal_id", flat=True)
    categorias_secundarias_ids = qs_zona.exclude(
        categorias_secundarias__isnull=True
    ).values_list("categorias_secundarias__id", flat=True)
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

    qs = qs_zona.select_related("categoria_principal", "distrito").prefetch_related(
        Prefetch(
            "contactos",
            queryset=ContactoServicioTurista.objects.filter(activo=True).order_by(
                "-es_principal", "orden", "id"
            ),
        )
    ).order_by("categoria_principal__nombre", "nombre")
    if categoria_actual is not None:
        qs = qs.filter(
            Q(categoria_principal=categoria_actual)
            | Q(categorias_secundarias=categoria_actual)
        ).distinct()

    paginator = Paginator(qs, 6)
    page_obj = paginator.get_page(request.GET.get("page"))

    tarjetas = [_tarjeta_servicio(servicio) for servicio in page_obj]
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
