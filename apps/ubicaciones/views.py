from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from .models import Provincia


def provincia_detalle(request, slug):
    provincia = get_object_or_404(Provincia, slug=slug, activo=True)
    distritos = list(
        provincia.distritos.filter(activo=True)
        .order_by("nombre_oficial")
        .values_list("nombre_oficial", flat=True)
    )
    return JsonResponse({
        "slug": provincia.slug,
        "capital": provincia.capital,
        "superficie_km2": provincia.superficie_km2,
        "altitud_m": provincia.altitud_m,
        "distritos": distritos,
    })
