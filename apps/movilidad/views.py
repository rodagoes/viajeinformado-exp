from django.views.generic import TemplateView

from .services.tarifas_taxi import (
    obtener_consejos_movilidad,
    obtener_transportes_con_tarifas,
)


class TarifasTaxiView(TemplateView):
    template_name = "movilidad/tarifas_taxi.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "planifica"
        context["transportes"] = obtener_transportes_con_tarifas()
        context["consejos"] = obtener_consejos_movilidad()
        return context
