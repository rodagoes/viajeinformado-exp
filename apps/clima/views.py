from django.views.generic import TemplateView

from .services.clima_actual import obtener_clima_actual
from .ubicaciones import ciudad_valida, listar_ciudades, obtener_ciudad


class ClimaTemporadasView(TemplateView):
    template_name = "clima/clima_temporadas.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ciudad_slug = ciudad_valida(self.request.GET.get("ciudad"))

        context["ciudad"] = obtener_ciudad(ciudad_slug)
        context["ciudades"] = listar_ciudades()
        context["clima"] = obtener_clima_actual(ciudad_slug)
        return context
