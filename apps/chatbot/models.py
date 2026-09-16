from django.conf import settings
from django.db import models


class Conversacion(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversaciones_chatbot",
    )
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    ultima_actividad = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conversación"
        verbose_name_plural = "Conversaciones"
        indexes = [
            models.Index(fields=["usuario", "-ultima_actividad"]),
            models.Index(fields=["session_key", "-ultima_actividad"]),
        ]

    def __str__(self):
        propietario = self.usuario or self.session_key or "anónimo"
        return f"Conversación {self.pk} ({propietario})"


class Mensaje(models.Model):
    class Rol(models.TextChoices):
        USUARIO = "usuario", "Usuario"
        ASISTENTE = "asistente", "Asistente"

    class TipoFuente(models.TextChoices):
        INTERNAL = "internal", "Interno"
        EXTERNAL_TRUSTED = "external_trusted", "Externo confiable"
        MIXED = "mixed", "Mixto"
        NO_EVIDENCE = "no_evidence", "Sin evidencia"

    conversacion = models.ForeignKey(
        Conversacion, on_delete=models.CASCADE, related_name="mensajes"
    )
    rol = models.CharField(max_length=20, choices=Rol.choices)
    contenido = models.TextField()
    tipo_fuente = models.CharField(
        max_length=20, choices=TipoFuente.choices, blank=True
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mensaje"
        verbose_name_plural = "Mensajes"
        ordering = ["creado", "id"]

    def __str__(self):
        return f"{self.get_rol_display()} — {self.contenido[:50]}"
