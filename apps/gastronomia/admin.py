from django.contrib import admin

from .models import CategoriaPlatoTipico, PlatoTipico, IngredienteClavePlato, PlatoEstablecimiento


@admin.register(CategoriaPlatoTipico)
class CategoriaPlatoTipicoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden", "activo", "creado")
    list_filter = ("activo",)
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


class IngredienteClavePlatoInline(admin.TabularInline):
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


@admin.register(PlatoTipico)
class PlatoTipicoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "categoria", "es_plato_bandera", "orden", "activo", "actualizado")
    list_filter = ("activo", "categoria", "es_plato_bandera")
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
