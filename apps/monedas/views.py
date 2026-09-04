from django.views.generic import TemplateView

from .models import TipoCambio


def _formatear_tasa(valor):
    """Recorta ceros finales innecesarios sin caer en notación científica."""
    texto = f"{valor:.4f}".rstrip("0").rstrip(".")
    entero, _, decimales = texto.partition(".")
    decimales = decimales.ljust(2, "0")
    return f"{entero}.{decimales}"


class TipoCambioView(TemplateView):
    template_name = "monedas/tipo_cambio.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        tipo_cambio = TipoCambio.vigente()
        context["tipo_cambio_disponible"] = tipo_cambio is not None

        if tipo_cambio is not None:
            context["compra_txt"] = _formatear_tasa(tipo_cambio.compra)
            context["venta_txt"] = _formatear_tasa(tipo_cambio.venta)
            context["compra_raw"] = str(tipo_cambio.compra)
            context["venta_raw"] = str(tipo_cambio.venta)
            context["fecha_tipo_cambio_txt"] = tipo_cambio.fecha.strftime("%d/%m/%Y")

        return context
