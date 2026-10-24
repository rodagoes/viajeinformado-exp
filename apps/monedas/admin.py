from django.contrib import admin

from .models import TipoCambio


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — TipoCambioAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
TIPO_CAMBIO_COLUMNAS_ADMIN = (
    "fecha",
    "moneda_origen",
    "moneda_destino",
    "compra",
    "venta",
    "fuente",
    "activo",
    "actualizado_en",
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
TIPO_CAMBIO_FILTROS_ADMIN = (
    "activo",
    "moneda_origen",
    "moneda_destino",
    "fuente",
)
# ==========================================================================


@admin.register(TipoCambio)
class TipoCambioAdmin(admin.ModelAdmin):
    list_display = TIPO_CAMBIO_COLUMNAS_ADMIN
    list_filter = TIPO_CAMBIO_FILTROS_ADMIN
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
