from django.core.validators import RegexValidator
from django.db import models

numero_tel_validator = RegexValidator(
    regex=r"^\+?\d+$",
    message="Usa solo dígitos y, opcionalmente, un '+' inicial (formato compatible con enlaces tel:).",
)

color_marca_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Usa un color hexadecimal de 6 dígitos, ej. #D64545.",
)


class ZonaAtencionEmergencia(models.Model):
    distrito = models.OneToOneField(
        "ubicaciones.Distrito",
        on_delete=models.PROTECT,
        related_name="zona_emergencia",
    )
    nombre_publico = models.CharField(
        max_length=120,
        blank=True,
        help_text="Denominación reconocible para el turista, si difiere del nombre oficial del distrito.",
    )
    slug = models.SlugField(max_length=140, unique=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Zona de atención de emergencia"
        verbose_name_plural = "Zonas de atención de emergencia"
        ordering = ["orden", "nombre_publico", "distrito__nombre_oficial"]

    def __str__(self):
        return self.nombre_visible

    @property
    def nombre_visible(self):
        return self.nombre_publico or self.distrito.nombre_oficial

    @property
    def provincia(self):
        return self.distrito.provincia


class ContactoEmergencia(models.Model):
    AMBITO_NACIONAL = "nacional"
    AMBITO_LOCAL = "local"

    AMBITOS = (
        (AMBITO_NACIONAL, "Nacional"),
        (AMBITO_LOCAL, "Local"),
    )

    CATEGORIAS = (
        ("policia", "Policía"),
        ("bomberos", "Bomberos"),
        ("salud", "Salud"),
        ("turismo", "Policía de Turismo"),
        ("serenazgo", "Serenazgo"),
        ("municipal", "Municipal"),
        ("otro", "Otro"),
    )

    ambito = models.CharField(max_length=20, choices=AMBITOS, db_index=True)
    categoria = models.CharField(max_length=30, choices=CATEGORIAS)
    nombre = models.CharField(max_length=160)
    descripcion = models.CharField(max_length=240, blank=True)
    color_marca = models.CharField(
        max_length=7,
        blank=True,
        validators=[color_marca_validator],
        help_text="Color representativo de la institución (ej. #D64545). Si se deja vacío, se usa un color por defecto según la categoría.",
    )
    logo = models.ImageField(
        upload_to="emergencias/logos/",
        blank=True,
        help_text="Logo o emblema de la institución, mostrado en la esquina superior de la tarjeta.",
    )
    numero_visible = models.CharField(
        max_length=40,
        help_text="Formato para mostrar en pantalla. Admite espacios, paréntesis o guiones.",
    )
    numero_tel = models.CharField(
        max_length=30,
        validators=[numero_tel_validator],
        help_text="Formato normalizado para href=\"tel:...\". Solo dígitos y '+' inicial opcional.",
    )
    es_24_horas = models.BooleanField(default=False)
    horario = models.CharField(
        max_length=160,
        blank=True,
        help_text="Se usa solo cuando 'Atiende 24 horas' está desactivado.",
    )
    fuente_nombre = models.CharField(max_length=180, blank=True)
    fuente_url = models.URLField(blank=True)
    fecha_verificacion = models.DateField(null=True, blank=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True, db_index=True)
    zonas = models.ManyToManyField(
        ZonaAtencionEmergencia,
        blank=True,
        related_name="contactos",
    )

    class Meta:
        verbose_name = "Contacto de emergencia"
        verbose_name_plural = "Contactos de emergencia"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    @property
    def horario_texto(self):
        if self.es_24_horas:
            return "Atención 24/7"
        return self.horario


class NumeroContactoAdicional(models.Model):
    """Números extra de un contacto (ej. fijo + móvil) además del
    numero_visible/numero_tel principal, que se sigue usando para los
    botones de Llamar/Copiar."""

    contacto = models.ForeignKey(
        ContactoEmergencia,
        on_delete=models.CASCADE,
        related_name="numeros_adicionales",
    )
    etiqueta = models.CharField(
        max_length=40,
        blank=True,
        help_text="Ej. Móvil, Central, WhatsApp. Opcional.",
    )
    numero_visible = models.CharField(
        max_length=40,
        help_text="Formato para mostrar en pantalla. Admite espacios, paréntesis o guiones.",
    )
    numero_tel = models.CharField(
        max_length=30,
        validators=[numero_tel_validator],
        help_text="Formato normalizado para href=\"tel:...\". Solo dígitos y '+' inicial opcional.",
    )
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Número adicional de contacto"
        verbose_name_plural = "Números adicionales de contacto"
        ordering = ["orden", "id"]

    def __str__(self):
        return f"{self.etiqueta or 'Número'}: {self.numero_visible}"
