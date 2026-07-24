from django.contrib import admin

from .models import CodigoOTP, PerfilUsuario


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ('user', 'nombres_apellidos', 'rol', 'verificado', 'creado_en')
    list_filter = ('rol', 'verificado')
    search_fields = ('user__username', 'user__email', 'nombres_apellidos')
    readonly_fields = ('creado_en', 'actualizado_en', 'username_actualizado_en')


@admin.register(CodigoOTP)
class CodigoOTPAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'proposito', 'creado_en', 'expira_en', 'usado', 'intentos')
    list_filter = ('proposito', 'usado')
    search_fields = ('usuario__username', 'usuario__email')
    readonly_fields = ('otp_hash', 'creado_en', 'expira_en', 'usado', 'intentos', 'ultimo_reenvio', 'fecha_uso')

    def has_add_permission(self, request):
        return False
