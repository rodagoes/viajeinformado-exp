from django.db import models

from apps.establecimientos.models import Establecimiento


class CategoriaPlatoTipico(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Categoría de plato típico"
        verbose_name_plural = "Categorías de platos típicos"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class PlatoTipico(models.Model):
    categoria = models.ForeignKey(
        CategoriaPlatoTipico,
        related_name="platos",
        on_delete=models.PROTECT,
        verbose_name="Categoría"
    )
    nombre = models.CharField(max_length=160)
    slug = models.SlugField(max_length=200, unique=True)
    descripcion_corta = models.CharField(
        max_length=255,
        blank=True,
        help_text="Descripción breve del plato. Evita párrafos largos."
    )
    imagen = models.ImageField(upload_to="gastronomia/platos/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)
    es_plato_bandera = models.BooleanField(
        default=False,
        verbose_name="Plato bandera",
        help_text="Márcalo si es uno de los platos representativos de Huánuco."
    )
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    establecimientos = models.ManyToManyField(
        Establecimiento,
        through="PlatoEstablecimiento",
        related_name="platos_tipicos",
        blank=True,
    )

    class Meta:
        verbose_name = "Plato típico"
        verbose_name_plural = "Platos típicos"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class IngredienteClavePlato(models.Model):
    plato = models.ForeignKey(PlatoTipico, related_name="ingredientes", on_delete=models.CASCADE)
    nombre = models.CharField(max_length=80)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Ingrediente clave"
        verbose_name_plural = "Ingredientes clave"
        ordering = ["plato__nombre", "orden", "id"]
        constraints = [
            models.UniqueConstraint(fields=["plato", "nombre"], name="unique_ingrediente_por_plato"),
        ]

    def __str__(self):
        return f"{self.plato.nombre} - {self.nombre}"


class PlatoEstablecimiento(models.Model):
    plato = models.ForeignKey(PlatoTipico, related_name="disponibilidad", on_delete=models.CASCADE)
    establecimiento = models.ForeignKey(
        Establecimiento,
        related_name="platos_disponibles",
        on_delete=models.CASCADE,
        limit_choices_to={"tipo": "restaurante"},
    )
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Plato disponible en establecimiento"
        verbose_name_plural = "Platos disponibles en establecimientos"
        ordering = ["establecimiento__nombre", "plato__nombre"]
        constraints = [
            models.UniqueConstraint(fields=["plato", "establecimiento"], name="unique_plato_por_establecimiento"),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.establecimiento_id and self.establecimiento.tipo != "restaurante":
            raise ValidationError({
                "establecimiento": "Solo se pueden asociar platos típicos a establecimientos de tipo restaurante."
            })

    def __str__(self):
        return f"{self.establecimiento.nombre} - {self.plato.nombre}"
