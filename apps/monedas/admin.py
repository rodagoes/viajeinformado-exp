from django.contrib import admin

from .models import TipoCambio


@admin.register(TipoCambio)
class TipoCambioAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "moneda_origen",
        "moneda_destino",
        "compra",
        "venta",
        "fuente",
        "activo",
        "actualizado_en",
    )
    list_filter = (
        "activo",
        "moneda_origen",
        "moneda_destino",
        "fuente",
    )
    search_fields = (
        "fecha",
        "fuente",
    )
    readonly_fields = (
        "respuesta_api",
        "creado_en",
        "actualizado_en",
    )
    ordering = (
        "-fecha",
        "-actualizado_en",
    )
