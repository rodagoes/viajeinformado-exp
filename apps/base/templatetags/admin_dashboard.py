"""Cards de resumen del inicio del Admin (solo lectura; un aggregate por card)."""
from django.apps import apps
from django.contrib import admin
from django.db.models import Count, Q
from django.template import Library
from django.urls import reverse
from django.utils.http import urlencode

register = Library()

# (título, icono Bootstrap, modelo, filtro del modelo). Cuenta registros `activo` (lo que ve el sitio público).
CARDS = (
    ("Restaurantes", "bi-shop", "establecimientos.Establecimiento", {"tipo": "restaurante"}),
    ("Alojamientos", "bi-building", "establecimientos.Establecimiento", {"tipo": "alojamiento"}),
    ("Lugares turísticos", "bi-compass", "turismo.LugarTuristico", {}),
    ("Eventos", "bi-calendar-event", "eventos.Evento", {}),
    ("Platos típicos", "bi-egg-fried", "gastronomia.PlatoTipico", {}),
)


@register.inclusion_tag("admin/includes/dashboard_cards.html", takes_context=True)
def dashboard_cards(context):
    request = context["request"]
    cards = []
    for titulo, icono, etiqueta, filtro in CARDS:
        modelo = apps.get_model(etiqueta)
        model_admin = admin.site._registry.get(modelo)
        if model_admin is None or not model_admin.has_view_permission(request):
            continue
        datos = modelo.objects.filter(**filtro).aggregate(
            activos=Count("pk", filter=Q(activo=True)), total=Count("pk"),
        )
        meta = modelo._meta
        consulta = urlencode({**{f"{k}__exact": v for k, v in filtro.items()}, "activo__exact": 1})
        cards.append({
            "titulo": titulo, "icono": icono, "activos": datos["activos"],
            "inactivos": datos["total"] - datos["activos"],
            "url": f"{reverse(f'admin:{meta.app_label}_{meta.model_name}_changelist')}?{consulta}",
        })
    return {"cards": cards}
