from django.contrib import admin

from .models import Conversacion, Mensaje


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — ConversacionAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
CONVERSACION_COLUMNAS_ADMIN = ("id", "usuario", "session_key", "creado", "ultima_actividad")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
CONVERSACION_FILTROS_ADMIN = ("usuario",)
# ==========================================================================


@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = CONVERSACION_COLUMNAS_ADMIN
    list_filter = CONVERSACION_FILTROS_ADMIN


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — MensajeAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
MENSAJE_COLUMNAS_ADMIN = ("id", "conversacion", "rol", "tipo_fuente", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
MENSAJE_FILTROS_ADMIN = ("rol", "tipo_fuente")
# ==========================================================================


@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = MENSAJE_COLUMNAS_ADMIN
    list_filter = MENSAJE_FILTROS_ADMIN
