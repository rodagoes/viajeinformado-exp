from django.core.mail import send_mail
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from .forms import ReportarProblemaForm
from .services.contactos import (
    generar_qr_data_uri,
    obtener_contactos_locales,
    obtener_contactos_nacionales,
    obtener_ultima_verificacion,
    resolver_zona,
    zonas_agrupadas_por_provincia,
)

DESTINATARIO_REPORTES = "viajeinformadohuanuco@gmail.com"


class EmergenciasView(TemplateView):
    template_name = "emergencias/emergencias.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "planifica"

        zona_actual = resolver_zona(self.request.GET.get("zona") or None)
        contactos_nacionales = obtener_contactos_nacionales()
        contactos_locales = obtener_contactos_locales(zona_actual)

        context["zona_actual"] = zona_actual
        context["zonas_agrupadas"] = zonas_agrupadas_por_provincia()
        context["contactos_nacionales"] = contactos_nacionales
        context["contactos_locales"] = contactos_locales
        context["ultima_verificacion"] = obtener_ultima_verificacion(
            contactos_nacionales + contactos_locales
        )
        context["qr_data_uri"] = (
            generar_qr_data_uri(
                self.request.build_absolute_uri(f"{self.request.path}?zona={zona_actual.slug}")
            )
            if zona_actual is not None
            else None
        )
        return context


class ReportarProblemaEmergenciasView(View):
    """Recibe el formulario del modal "Reportar un problema" (fetch/JSON) y
    reenvía el contenido por correo; no hay vista de éxito propia porque el
    modal maneja el feedback en el cliente."""

    def post(self, request, *args, **kwargs):
        form = ReportarProblemaForm(request.POST)

        if not form.is_valid():
            if request.POST.get("sitio_web"):
                return JsonResponse({"ok": True})
            return JsonResponse({"ok": False, "errores": form.errors}, status=400)

        send_mail(
            subject=f"[Viaje Informado] Reporte: {form.cleaned_data['titulo']}",
            message=(
                f"{form.cleaned_data['descripcion']}\n\n"
                "---\nEnviado desde el formulario de la página de Emergencias."
            ),
            from_email=None,
            recipient_list=[DESTINATARIO_REPORTES],
        )
        return JsonResponse({"ok": True})
