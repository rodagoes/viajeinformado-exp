from django.contrib import admin
from modeltranslation.admin import TranslationAdmin, TranslationStackedInline, TranslationTabularInline
from .models import HomeHeroSlide


admin.site.site_header = "Administración Viaje Informado"
admin.site.site_title = "Viaje Informado"
admin.site.index_title = "Panel de administración"


@admin.register(HomeHeroSlide)
class HomeHeroSlideAdmin(TranslationAdmin):
    list_display = ['etiqueta', 'titulo_principal', 'titulo_resaltado', 'tipo_archivo', 'orden', 'activo']
    list_editable = ['orden', 'activo']
    search_fields = ['titulo_principal', 'etiqueta', 'descripcion']
    list_filter = ['activo', 'tipo_archivo']
    
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