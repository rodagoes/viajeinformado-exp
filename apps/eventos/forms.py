from django import forms
from django.utils.translation import gettext, gettext_lazy

from .models import CategoriaEvento


class PromocionarEventoForm(forms.Form):
    """CTA "Promociona tu evento" (sección 5): solo recolecta lo mínimo para
    que el equipo evalúe la propuesta por correo — no crea nada en la base
    de datos (YAGNI, ver R17: sin tabla/migración en esta primera versión)."""

    nombre_evento = forms.CharField(label=gettext_lazy("Nombre del evento"), max_length=160)
    tipo_evento = forms.ChoiceField(label=gettext_lazy("Tipo de evento"), choices=())
    descripcion_evento = forms.CharField(
        label=gettext_lazy("Describe brevemente tu evento"), widget=forms.Textarea, max_length=2000
    )
    correo = forms.EmailField(label=gettext_lazy("Ingresa tu correo electrónico"), max_length=254)
    # Honeypot (R16): campo oculto por CSS que un humano nunca completa.
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categorias = CategoriaEvento.objects.filter(activo=True).order_by("nombre")
        self.fields["tipo_evento"].choices = (
            [("", gettext("Selecciona una opción"))]
            + [(cat.slug, cat.nombre) for cat in categorias]
            + [("otro", gettext("Otro"))]
        )

    def clean_website(self):
        valor = self.cleaned_data.get("website")
        if valor:
            raise forms.ValidationError("Spam detectado.")
        return valor


class ReportarProblemaEventoForm(forms.Form):
    """CTA "Reportar un problema" (sección 8), mismo patrón que
    apps.emergencias.forms.ReportarProblemaForm."""

    nombre_problema = forms.CharField(label=gettext_lazy("Nombre del problema"), max_length=160)
    descripcion_problema = forms.CharField(
        label=gettext_lazy("Describe el problema"), widget=forms.Textarea, max_length=1500
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        valor = self.cleaned_data.get("website")
        if valor:
            raise forms.ValidationError("Spam detectado.")
        return valor
