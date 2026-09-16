from django.contrib import admin

from .models import Conversacion, Mensaje


@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = ("id", "usuario", "session_key", "creado", "ultima_actividad")
    list_filter = ("usuario",)


@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = ("id", "conversacion", "rol", "tipo_fuente", "creado")
    list_filter = ("rol", "tipo_fuente")
