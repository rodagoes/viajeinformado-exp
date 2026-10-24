from django.contrib import admin

from .models import CodigoOTP, PerfilUsuario


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — PerfilUsuarioAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
PERFIL_USUARIO_COLUMNAS_ADMIN = ('user', 'nombres_apellidos', 'rol', 'verificado', 'creado_en')

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
PERFIL_USUARIO_FILTROS_ADMIN = ('rol', 'verificado')
# ==========================================================================


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = PERFIL_USUARIO_COLUMNAS_ADMIN
    list_filter = PERFIL_USUARIO_FILTROS_ADMIN
    search_fields = ('user__username', 'user__email', 'nombres_apellidos')
    readonly_fields = ('creado_en', 'actualizado_en', 'username_actualizado_en')


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — CodigoOTPAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
CODIGO_O_T_P_COLUMNAS_ADMIN = ('usuario', 'proposito', 'creado_en', 'expira_en', 'usado', 'intentos')

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
CODIGO_O_T_P_FILTROS_ADMIN = ('proposito', 'usado')
# ==========================================================================


@admin.register(CodigoOTP)
class CodigoOTPAdmin(admin.ModelAdmin):
    list_display = CODIGO_O_T_P_COLUMNAS_ADMIN
    list_filter = CODIGO_O_T_P_FILTROS_ADMIN
    search_fields = ('usuario__username', 'usuario__email')
    readonly_fields = ('otp_hash', 'creado_en', 'expira_en', 'usado', 'intentos', 'ultimo_reenvio', 'fecha_uso')

    def has_add_permission(self, request):
        return False
