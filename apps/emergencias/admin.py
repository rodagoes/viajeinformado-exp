from datetime import date, timedelta

from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import ContactoEmergencia, NumeroContactoAdicional, ZonaAtencionEmergencia

DIAS_VERIFICACION_ANTIGUA = 90


class ContactoEmergenciaForm(forms.ModelForm):
    class Meta:
        model = ContactoEmergencia
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("ambito") == ContactoEmergencia.AMBITO_LOCAL
            and not cleaned_data.get("zonas")
        ):
            raise forms.ValidationError(
                "Un contacto local debe tener al menos una zona asociada antes de publicarse."
            )
        return cleaned_data


class NumeroContactoAdicionalInline(admin.TabularInline):
    model = NumeroContactoAdicional
    extra = 1
    fields = ["etiqueta", "numero_visible", "numero_tel", "orden"]


@admin.register(ZonaAtencionEmergencia)
class ZonaAtencionEmergenciaAdmin(admin.ModelAdmin):
    list_display = ["nombre_publico_o_distrito", "distrito", "provincia_relacionada", "slug", "orden", "activo"]
    list_editable = ["orden", "activo"]
    search_fields = ["nombre_publico", "distrito__nombre_oficial", "distrito__provincia__nombre_oficial"]
    list_filter = ["activo", "distrito__provincia"]
    prepopulated_fields = {"slug": ("nombre_publico",)}
    autocomplete_fields = ["distrito"]
    ordering = ["orden", "nombre_publico"]

    def nombre_publico_o_distrito(self, obj):
        return obj.nombre_visible
    nombre_publico_o_distrito.short_description = "Nombre público"

    def provincia_relacionada(self, obj):
        return obj.distrito.provincia
    provincia_relacionada.short_description = "Provincia"


@admin.register(ContactoEmergencia)
class ContactoEmergenciaAdmin(admin.ModelAdmin):
    form = ContactoEmergenciaForm
    inlines = [NumeroContactoAdicionalInline]
    list_display = [
        "nombre", "ambito", "categoria", "numero_visible", "es_24_horas",
        "fecha_verificacion", "aviso_verificacion", "activo", "orden",
    ]
    list_editable = ["orden", "activo"]
    search_fields = ["nombre", "descripcion", "numero_visible", "numero_tel", "fuente_nombre"]
    list_filter = ["ambito", "categoria", "zonas", "es_24_horas", "activo", "fecha_verificacion"]
    filter_horizontal = ["zonas"]
    ordering = ["orden", "nombre"]

    fieldsets = (
        ("Clasificación", {"fields": ("ambito", "categoria", "zonas")}),
        ("Información principal", {"fields": ("nombre", "descripcion")}),
        ("Marca", {
            "fields": ("color_marca", "logo"),
            "description": "Personaliza el color y el logo de esta institución en la tarjeta. Si se dejan vacíos, se usa un color por defecto según la categoría.",
        }),
        ("Contacto", {"fields": ("numero_visible", "numero_tel", "es_24_horas", "horario")}),
        ("Verificación", {"fields": ("fuente_nombre", "fuente_url", "fecha_verificacion")}),
        ("Configuración", {"fields": ("orden", "activo")}),
    )

    def aviso_verificacion(self, obj):
        if not obj.fuente_nombre and not obj.fuente_url:
            return format_html('<span style="color:#b91c1c;">Sin fuente</span>')
        if not obj.fecha_verificacion:
            return format_html('<span style="color:#b45309;">Sin fecha de verificación</span>')
        if obj.fecha_verificacion < date.today() - timedelta(days=DIAS_VERIFICACION_ANTIGUA):
            return format_html('<span style="color:#b45309;">Verificación antigua</span>')
        return format_html('<span style="color:#15803d;">OK</span>')
    aviso_verificacion.short_description = "Verificación"
