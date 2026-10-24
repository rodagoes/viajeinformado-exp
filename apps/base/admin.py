from django.contrib import admin
from modeltranslation.admin import TranslationAdmin, TranslationStackedInline, TranslationTabularInline
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from .models import ConfiguracionPublica, HomeHeroSlide, Sponsor


admin.site.site_header = "Administración Viaje Informado"
admin.site.site_title = "Viaje Informado"
admin.site.index_title = "Panel de administración"


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — HomeHeroSlideAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
HOME_HERO_SLIDE_COLUMNAS_ADMIN = ['etiqueta', 'titulo_principal', 'titulo_resaltado', 'tipo_archivo', 'orden', 'activo']

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
HOME_HERO_SLIDE_FILTROS_ADMIN = ['activo', 'tipo_archivo']
# ==========================================================================


@admin.register(HomeHeroSlide)
class HomeHeroSlideAdmin(TranslationAdmin):
    list_display = HOME_HERO_SLIDE_COLUMNAS_ADMIN
    list_editable = ['orden', 'activo']
    search_fields = ['titulo_principal', 'etiqueta', 'descripcion']
    list_filter = HOME_HERO_SLIDE_FILTROS_ADMIN
    
    fieldsets = (
        ('Textos', {
            'fields': ('etiqueta', 'titulo_principal', 'titulo_resaltado', 'descripcion')
        }),
        ('Multimedia', {
            'fields': ('tipo_archivo', 'archivo', 'poster_video', 'texto_alt')
        }),
        ('Configuración', {
            'fields': ('orden', 'activo', 'intervalo_ms')
        }),
    )


# ==========================================================================
# CONFIGURACIÓN PÚBLICA (interruptores del sitio) — fila única
# ==========================================================================
@admin.register(ConfiguracionPublica)
class ConfiguracionPublicaAdmin(admin.ModelAdmin):
    fields = ("mostrar_metricas_home", "mostrar_sponsors_footer")

    def has_add_permission(self, request):
        return False  # la fila única se crea sola

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # No hay lista: se abre directamente la única configuración.
        return redirect(reverse("admin:base_configuracionpublica_change", args=[ConfiguracionPublica.cargar().pk]))

    def response_post_save_change(self, request, obj):
        return redirect(reverse("admin:base_configuracionpublica_change", args=[obj.pk]))


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — SponsorAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
SPONSOR_COLUMNAS_ADMIN = ["nombre", "vista_previa", "orden", "activo"]

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
SPONSOR_FILTROS_ADMIN = ["activo"]
# ==========================================================================


@admin.register(Sponsor)
class SponsorAdmin(admin.ModelAdmin):
    list_display = SPONSOR_COLUMNAS_ADMIN
    list_editable = ["orden", "activo"]
    list_filter = SPONSOR_FILTROS_ADMIN
    search_fields = ["nombre"]
    fields = ("nombre", "logo", "url", "orden", "activo")

    @admin.display(description="Logo")
    def vista_previa(self, obj):
        if not obj.logo:
            return "—"
        return format_html('<img src="{}" alt="" style="height:32px;max-width:96px;object-fit:contain">', obj.logo.url)
