from django.db.models import Prefetch, Q
from django.urls import reverse

from apps.gastronomia.models import IngredienteClavePlato, PlatoEstablecimiento, PlatoTipico

from . import (
    DEFAULT_LIMIT,
    normalizar_limit,
    resultado_item,
    resultado_lista,
    validar_bool,
    validar_choice,
    validar_texto,
    validar_texto_obligatorio,
)

# Aspecto concreto que pregunta el turista sobre un plato. Encontrar el plato
# no basta: solo hay evidencia si el dato pedido existe en la BD. Preparación
# y origen no tienen campo propio → nunca hay evidencia interna (el
# orquestador degrada a fuentes oficiales C5 o a no_evidence).
ASPECTO_CHOICES = [
    ("ingredientes", "Ingredientes"),
    ("descripcion", "Qué es / descripción"),
    ("preparacion", "Preparación"),
    ("origen", "Origen / historia"),
]
_CAMPO_ASPECTO = {"ingredientes": "ingredientes", "descripcion": "descripcion_corta"}


def evidencia_aspecto(items, aspecto):
    campo = _CAMPO_ASPECTO.get(aspecto)
    return bool(campo) and any(i.get(campo) for i in items)


def _base():
    return (
        PlatoTipico.objects.filter(activo=True, categoria__activo=True)
        .select_related("categoria")
        .prefetch_related(
            Prefetch("ingredientes", queryset=IngredienteClavePlato.objects.filter(activo=True))
        )
    )


def _resumen(plato):
    # No existe vista de detalle por plato: solo se enlazan rutas reales.
    return {
        "id": plato.pk,
        "nombre": plato.nombre,
        "slug": plato.slug,
        "categoria": plato.categoria.nombre,
        "categoria_slug": plato.categoria.slug,
        "es_plato_bandera": plato.es_plato_bandera,
        "descripcion_corta": plato.descripcion_corta,
        "ingredientes": [i.nombre for i in plato.ingredientes.all()],
        "url_listado": reverse("gastronomia:platos_tipicos"),
        "url_donde_comer": f"{reverse('establecimientos:listado_restaurantes')}?plato={plato.slug}",
    }


def buscar_platos(q=None, categoria=None, es_plato_bandera=None, aspecto=None, limit=None):
    limit = normalizar_limit(limit)
    q = validar_texto(q, "q")
    categoria = validar_texto(categoria, "categoria")
    es_plato_bandera = validar_bool(es_plato_bandera, "es_plato_bandera")
    aspecto = validar_choice(aspecto, "aspecto", ASPECTO_CHOICES)

    qs = _base()
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(descripcion_corta__icontains=q))
    if categoria:
        qs = qs.filter(categoria__slug=categoria)
    if es_plato_bandera is not None:
        qs = qs.filter(es_plato_bandera=es_plato_bandera)

    qs = qs.order_by("-es_plato_bandera", "orden", "nombre", "id")[:limit]
    items = [_resumen(p) for p in qs]
    extra = {}
    if aspecto:
        extra = {"aspecto": aspecto, "evidencia_suficiente": evidencia_aspecto(items, aspecto)}
    return resultado_lista("buscar_platos", items, **extra)


def obtener_plato(slug, aspecto=None):
    slug = validar_texto_obligatorio(slug, "slug")
    aspecto = validar_choice(aspecto, "aspecto", ASPECTO_CHOICES)
    plato = _base().filter(slug=slug).first()
    if plato is None:
        return resultado_item("obtener_plato", None)

    disponibilidad = (
        PlatoEstablecimiento.objects.filter(
            plato=plato, activo=True, establecimiento__activo=True
        )
        .select_related("establecimiento")
        .order_by("-establecimiento__destacado", "establecimiento__nombre")[:DEFAULT_LIMIT]
    )
    item = _resumen(plato)
    item["restaurantes"] = [
        {
            "id": d.establecimiento.pk,
            "nombre": d.establecimiento.nombre,
            "slug": d.establecimiento.slug,
            "url": d.establecimiento.get_absolute_url(),
        }
        for d in disponibilidad
    ]
    resultado = resultado_item("obtener_plato", item)
    if aspecto:
        resultado.update({"aspecto": aspecto, "evidencia_suficiente": evidencia_aspecto([item], aspecto)})
    return resultado
