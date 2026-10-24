from django.contrib import admin
from .models import Departamento, Provincia, Distrito, Localidad
from .admin_filtros import DistritoDependienteFilter, ProvinciaDependienteFilter

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — DepartamentoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
DEPARTAMENTO_COLUMNAS_ADMIN = ('nombre_oficial', 'codigo_inei', 'activo', 'creado')

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
DEPARTAMENTO_FILTROS_ADMIN = ('activo',)
# ==========================================================================


@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = DEPARTAMENTO_COLUMNAS_ADMIN
    search_fields = ('nombre_oficial', 'codigo_inei')
    list_filter = DEPARTAMENTO_FILTROS_ADMIN
    prepopulated_fields = {'slug': ('nombre_oficial',)}

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — ProvinciaAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
PROVINCIA_COLUMNAS_ADMIN = ('nombre_oficial', 'departamento', 'capital', 'superficie_km2', 'altitud_m', 'codigo_inei', 'activo')

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
PROVINCIA_FILTROS_ADMIN = ('activo', 'departamento')
# ==========================================================================


@admin.register(Provincia)
class ProvinciaAdmin(admin.ModelAdmin):
    list_display = PROVINCIA_COLUMNAS_ADMIN
    search_fields = ('nombre_oficial', 'codigo_inei', 'departamento__nombre_oficial', 'capital')
    list_filter = PROVINCIA_FILTROS_ADMIN
    prepopulated_fields = {'slug': ('nombre_oficial',)}
    autocomplete_fields = ('departamento',)

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — DistritoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
DISTRITO_COLUMNAS_ADMIN = ('nombre_oficial', 'provincia', 'departamento_relacionado', 'codigo_inei', 'codigo_api', 'api_id', 'activo')

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
DISTRITO_FILTROS_ADMIN = ('activo', 'provincia__departamento', 'provincia')
# ==========================================================================


@admin.register(Distrito)
class DistritoAdmin(admin.ModelAdmin):
    list_display = DISTRITO_COLUMNAS_ADMIN
    search_fields = ('nombre_oficial', 'codigo_inei', 'codigo_api', 'provincia__nombre_oficial', 'provincia__departamento__nombre_oficial')
    list_filter = DISTRITO_FILTROS_ADMIN
    prepopulated_fields = {'slug': ('nombre_oficial',)}
    autocomplete_fields = ('provincia',)

    def departamento_relacionado(self, obj):
        return obj.provincia.departamento
    departamento_relacionado.short_description = 'Departamento'

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — LocalidadAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
LOCALIDAD_COLUMNAS_ADMIN = ('nombre', 'tipo', 'distrito', 'provincia_relacionada', 'departamento_relacionado', 'activo')

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
LOCALIDAD_FILTROS_ADMIN = ('activo', 'tipo', 'distrito__provincia__departamento', ('distrito__provincia', ProvinciaDependienteFilter), ('distrito', DistritoDependienteFilter))
# ==========================================================================


@admin.register(Localidad)
class LocalidadAdmin(admin.ModelAdmin):
    list_display = LOCALIDAD_COLUMNAS_ADMIN
    search_fields = ('nombre', 'distrito__nombre_oficial', 'distrito__provincia__nombre_oficial', 'distrito__provincia__departamento__nombre_oficial')
    list_filter = LOCALIDAD_FILTROS_ADMIN
    prepopulated_fields = {'slug': ('nombre',)}
    autocomplete_fields = ('distrito',)

    def provincia_relacionada(self, obj):
        return obj.distrito.provincia
    provincia_relacionada.short_description = 'Provincia'

    def departamento_relacionado(self, obj):
        return obj.distrito.provincia.departamento
    departamento_relacionado.short_description = 'Departamento'
