from django.views.generic import RedirectView, TemplateView

from apps.metricas.services.publico import cifras_home

from .models import HomeHeroSlide
from .publico import obtener_config

class HomeView(TemplateView):
    template_name = 'base/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hero_slides"] = HomeHeroSlide.objects.filter(activo=True).order_by("orden", "id")
        context["metricas_home"] = self._metricas_home(self.request)
        return context

    @staticmethod
    def _metricas_home(request):
        """Solo cifras: {viajeros, viajeros_texto, ...}. Vacío (sin sección) si el interruptor está OFF o no hay datos."""
        if not obtener_config(request).mostrar_metricas_home:
            return {}
        datos = cifras_home()
        if datos is None:
            return {}
        return {**datos, **{f"{k}_texto": f"{v:,}" for k, v in datos.items()}}

class PrivacidadView(TemplateView):
    template_name = 'base/privacidad.html'

class TerminosView(TemplateView):
    template_name = 'base/terminos.html'

class HistoriaView(TemplateView):
    template_name = 'base/historia.html'

class ContactoView(TemplateView):
    template_name = 'base/contacto.html'

class LoginVisualView(RedirectView):
    # El antiguo preview visual ahora redirige al login funcional de apps.accounts
    pattern_name = 'accounts:login'
