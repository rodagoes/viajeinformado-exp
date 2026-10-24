from django.contrib import admin
from modeltranslation.admin import TranslationAdmin, TranslationStackedInline, TranslationTabularInline

from .models import CategoriaPlatoTipico, PlatoTipico, IngredienteClavePlato, PlatoEstablecimiento


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — CategoriaPlatoTipicoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
CATEGORIA_PLATO_TIPICO_COLUMNAS_ADMIN = ("nombre", "orden", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
CATEGORIA_PLATO_TIPICO_FILTROS_ADMIN = ("activo",)
# ==========================================================================


@admin.register(CategoriaPlatoTipico)
class CategoriaPlatoTipicoAdmin(TranslationAdmin):
    list_display = CATEGORIA_PLATO_TIPICO_COLUMNAS_ADMIN
    list_filter = CATEGORIA_PLATO_TIPICO_FILTROS_ADMIN
    search_fields = ("nombre",)
    ordering = ("orden", "nombre")
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ("creado", "actualizado")

    fieldsets = (
        ("Información principal", {
            "fields": ("nombre", "slug", "orden")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )


class IngredienteClavePlatoInline(TranslationTabularInline):
    model = IngredienteClavePlato
    extra = 1
    fields = ("nombre", "orden", "activo")
    ordering = ("orden", "id")


class RestauranteDondeSeOfreceInline(admin.TabularInline):
    model = PlatoEstablecimiento
    fk_name = "plato"
    extra = 1
    fields = ("establecimiento", "activo")
    autocomplete_fields = ("establecimiento",)
    verbose_name = "Restaurante"
    verbose_name_plural = "RESTAURANTES DONDE SE OFRECE"


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — PlatoTipicoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
PLATO_TIPICO_COLUMNAS_ADMIN = ("nombre", "categoria", "es_plato_bandera", "orden", "activo", "actualizado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
PLATO_TIPICO_FILTROS_ADMIN = ("activo", "categoria", "es_plato_bandera")
# ==========================================================================


@admin.register(PlatoTipico)
class PlatoTipicoAdmin(TranslationAdmin):
    list_display = PLATO_TIPICO_COLUMNAS_ADMIN
    list_filter = PLATO_TIPICO_FILTROS_ADMIN
    search_fields = ("nombre", "descripcion_corta")
    ordering = ("orden", "nombre")
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ("categoria",)
    readonly_fields = ("creado", "actualizado")
    inlines = [IngredienteClavePlatoInline, RestauranteDondeSeOfreceInline]

    fieldsets = (
        ("Información principal", {
            "fields": ("categoria", "nombre", "slug", "descripcion_corta")
        }),
        ("Multimedia", {
            "fields": ("imagen", "texto_alt_imagen")
        }),
        ("Configuración", {
            "fields": ("es_plato_bandera", "orden", "activo", "creado", "actualizado")
        }),
    )


# PlatoEstablecimiento no se registra como ModelAdmin independiente: se administra
# de forma contextual mediante los inlines de arriba (PlatoTipico) y de
# apps.establecimientos.admin (Establecimiento). Así no aparece como listado
# global en el índice de Gastronomía, pero sigue siendo la única fuente de verdad.
