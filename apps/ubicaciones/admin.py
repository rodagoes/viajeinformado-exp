from django.contrib import admin
from .models import Departamento, Provincia, Distrito, Localidad

@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = ('nombre_oficial', 'codigo_inei', 'activo', 'creado')
    search_fields = ('nombre_oficial', 'codigo_inei')
    list_filter = ('activo',)
    prepopulated_fields = {'slug': ('nombre_oficial',)}

@admin.register(Provincia)
class ProvinciaAdmin(admin.ModelAdmin):
    list_display = ('nombre_oficial', 'departamento', 'capital', 'superficie_km2', 'altitud_m', 'codigo_inei', 'activo')
    search_fields = ('nombre_oficial', 'codigo_inei', 'departamento__nombre_oficial', 'capital')
    list_filter = ('activo', 'departamento')
    prepopulated_fields = {'slug': ('nombre_oficial',)}
    autocomplete_fields = ('departamento',)

@admin.register(Distrito)
class DistritoAdmin(admin.ModelAdmin):
    list_display = ('nombre_oficial', 'provincia', 'departamento_relacionado', 'codigo_inei', 'codigo_api', 'api_id', 'activo')
    search_fields = ('nombre_oficial', 'codigo_inei', 'codigo_api', 'provincia__nombre_oficial', 'provincia__departamento__nombre_oficial')
    list_filter = ('activo', 'provincia__departamento', 'provincia')
    prepopulated_fields = {'slug': ('nombre_oficial',)}
    autocomplete_fields = ('provincia',)

    def departamento_relacionado(self, obj):
        return obj.provincia.departamento
    departamento_relacionado.short_description = 'Departamento'

@admin.register(Localidad)
class LocalidadAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'distrito', 'provincia_relacionada', 'departamento_relacionado', 'activo')
    search_fields = ('nombre', 'distrito__nombre_oficial', 'distrito__provincia__nombre_oficial', 'distrito__provincia__departamento__nombre_oficial')
    list_filter = ('activo', 'tipo', 'distrito__provincia__departamento', 'distrito__provincia', 'distrito')
    prepopulated_fields = {'slug': ('nombre',)}
    autocomplete_fields = ('distrito',)

    def provincia_relacionada(self, obj):
        return obj.distrito.provincia
    provincia_relacionada.short_description = 'Provincia'

    def departamento_relacionado(self, obj):
        return obj.distrito.provincia.departamento
    departamento_relacionado.short_description = 'Departamento'
