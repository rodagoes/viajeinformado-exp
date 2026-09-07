from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models


class Favorito(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favoritos",
    )
    establecimiento = models.ForeignKey(
        "establecimientos.Establecimiento", on_delete=models.CASCADE,
        null=True, blank=True, related_name="favoritos",
    )
    lugar_turistico = models.ForeignKey(
        "turismo.LugarTuristico", on_delete=models.CASCADE,
        null=True, blank=True, related_name="favoritos",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="favorito_un_solo_recurso",
                condition=(
                    models.Q(establecimiento__isnull=False, lugar_turistico__isnull=True)
                    | models.Q(establecimiento__isnull=True, lugar_turistico__isnull=False)
                ),
            ),
            models.UniqueConstraint(fields=["usuario", "establecimiento"], name="unique_favorito_establecimiento"),
            models.UniqueConstraint(fields=["usuario", "lugar_turistico"], name="unique_favorito_lugar"),
        ]
        ordering = ["-creado"]
        verbose_name = "Favorito"
        verbose_name_plural = "Favoritos"

    @property
    def recurso(self):
        return self.establecimiento or self.lugar_turistico

    def __str__(self):
        return f"{self.usuario.username} → {self.recurso}"


class Resena(models.Model):
    ESTADO_PUBLICADO = "publicado"
    ESTADO_OCULTO = "oculto"
    ESTADOS = [(ESTADO_PUBLICADO, "Publicado"), (ESTADO_OCULTO, "Oculto")]
    VALORACIONES = [(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5")]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="resenas",
    )
    establecimiento = models.ForeignKey(
        "establecimientos.Establecimiento", on_delete=models.CASCADE,
        null=True, blank=True, related_name="resenas",
    )
    lugar_turistico = models.ForeignKey(
        "turismo.LugarTuristico", on_delete=models.CASCADE,
        null=True, blank=True, related_name="resenas",
    )
    valoracion = models.PositiveSmallIntegerField(choices=VALORACIONES)
    comentario = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    estado = models.CharField(max_length=20, choices=ESTADOS, default=ESTADO_PUBLICADO)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="resena_un_solo_recurso",
                condition=(
                    models.Q(establecimiento__isnull=False, lugar_turistico__isnull=True)
                    | models.Q(establecimiento__isnull=True, lugar_turistico__isnull=False)
                ),
            ),
            models.CheckConstraint(
                name="resena_valoracion_1_5",
                condition=models.Q(valoracion__gte=1, valoracion__lte=5),
            ),
            models.UniqueConstraint(fields=["usuario", "establecimiento"], name="unique_resena_establecimiento"),
            models.UniqueConstraint(fields=["usuario", "lugar_turistico"], name="unique_resena_lugar"),
        ]
        ordering = ["-creado"]
        verbose_name = "Reseña"
        verbose_name_plural = "Reseñas"

    @property
    def recurso(self):
        return self.establecimiento or self.lugar_turistico

    def __str__(self):
        return f"{self.usuario.username} → {self.recurso} ({self.valoracion}★)"
