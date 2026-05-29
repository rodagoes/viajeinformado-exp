from django.db import models


class TipoCambio(models.Model):
    fecha = models.DateField(
        unique=True,
        db_index=True,
        verbose_name="Fecha"
    )
    moneda_origen = models.CharField(
        max_length=3,
        default="USD",
        verbose_name="Moneda origen"
    )
    moneda_destino = models.CharField(
        max_length=3,
        default="PEN",
        verbose_name="Moneda destino"
    )
    compra = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="Precio compra"
    )
    venta = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="Precio venta"
    )
    fuente = models.CharField(
        max_length=120,
        default="SUNAT/SBS - Decolecta",
        verbose_name="Fuente"
    )
    respuesta_api = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Respuesta API"
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )
    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Creado en"
    )
    actualizado_en = models.DateTimeField(
        auto_now=True,
        verbose_name="Actualizado en"
    )

    class Meta:
        verbose_name = "Tipo de cambio"
        verbose_name_plural = "Tipos de cambio"
        ordering = ["-fecha", "-actualizado_en"]

    def __str__(self):
        return f"{self.fecha} | USD/PEN venta S/. {self.venta}"

    @classmethod
    def vigente(cls):
        return cls.objects.filter(
            activo=True
        ).order_by(
            "-fecha",
            "-actualizado_en"
        ).first()
