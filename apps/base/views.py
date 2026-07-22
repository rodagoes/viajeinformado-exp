from django.views.generic import RedirectView, TemplateView
from .models import HomeHeroSlide

class HomeView(TemplateView):
    template_name = 'base/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "inicio"
        context["hero_slides"] = HomeHeroSlide.objects.filter(activo=True).order_by("orden", "id")
        return context

class PrivacidadView(TemplateView):
    template_name = 'base/privacidad.html'

class TerminosView(TemplateView):
    template_name = 'base/terminos.html'

class ContactoView(TemplateView):
    template_name = 'base/contacto.html'

class LoginVisualView(RedirectView):
    # El antiguo preview visual ahora redirige al login funcional de apps.accounts
    pattern_name = 'accounts:login'
