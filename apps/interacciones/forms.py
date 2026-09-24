from django import forms

from .models import Resena
from django.utils.translation import gettext_lazy


class ResenaForm(forms.ModelForm):
    class Meta:
        model = Resena
        fields = ["valoracion", "comentario"]
        widgets = {
            "comentario": forms.Textarea(attrs={
                "maxlength": 500,
                "rows": 4,
                "class": "form-control",
                "placeholder": gettext_lazy("Cuéntanos qué te pareció (opcional)"),
            }),
        }

    def clean_comentario(self):
        return self.cleaned_data.get("comentario", "").strip()
