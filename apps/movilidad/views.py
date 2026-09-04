from django.views.generic import TemplateView

from .services.como_llegar import (
    obtener_consejos_aereos,
    obtener_consejos_terrestres,
    obtener_rutas_aereas,
    obtener_rutas_terrestres,
)
from .services.tarifas_taxi import (
    obtener_consejos_movilidad,
    obtener_transportes_con_tarifas,
)


class TarifasTaxiView(TemplateView):
    template_name = "movilidad/tarifas_taxi.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["transportes"] = obtener_transportes_con_tarifas()
        context["consejos"] = obtener_consejos_movilidad()
        return context


class ComoLlegarView(TemplateView):
    template_name = "movilidad/como_llegar.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["rutas_terrestres"] = obtener_rutas_terrestres()
        context["rutas_aereas"] = obtener_rutas_aereas()
        context["consejos_terrestres"] = obtener_consejos_terrestres()
        context["consejos_aereos"] = obtener_consejos_aereos()
        return context
