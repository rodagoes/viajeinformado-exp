from django.db import models
from django.db.models import Q

TIPO_ICONO_CHOICES = [
    ("bootstrap", "Bootstrap Icon"),
    ("imagen", "Imagen / SVG / GIF"),
    ("lottie", "Lottie JSON"),
]

class CategoriaServicioTurista(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)
    
    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(max_length=80, blank=True, help_text="Ejemplo: bi-capsule, bi-hospital, bi-bank, bi-shield-fill")
    icono_archivo = models.FileField(upload_to="servicios_turista/categorias/iconos/", blank=True, help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons.")

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Categoría de servicio útil"
        verbose_name_plural = "Categorías de servicios útiles"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class ServicioTurista(models.Model):
    TIPO_ATENCION_CHOICES = [
        ("presencial", "Presencial"),
        ("telefonica", "Telefónica"),
        ("virtual", "Virtual"),
        ("mixta", "Mixta"),
    ]

    DISPONIBILIDAD_CHOICES = [
        ("horario", "Horario específico"),
        ("veinticuatro_horas", "24 horas"),
        ("emergencia", "Emergencia"),
        ("consultar", "Consultar"),
    ]

    categoria_principal = models.ForeignKey(CategoriaServicioTurista, related_name="servicios_principales", on_delete=models.PROTECT, verbose_name="Categoría principal")
    categorias_secundarias = models.ManyToManyField(CategoriaServicioTurista, related_name="servicios_secundarios", blank=True, verbose_name="Categorías secundarias")

    nombre = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    descripcion_corta = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)

    distrito = models.ForeignKey('ubicaciones.Distrito', related_name="servicios_turista", on_delete=models.PROTECT, null=True, blank=True)
    localidad = models.ForeignKey('ubicaciones.Localidad', related_name="servicios_turista", on_delete=models.SET_NULL, null=True, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    embed_maps = models.TextField(
        blank=True,
        verbose_name="Código embed de Google Maps",
        help_text=(
            "Pega aquí el código &lt;iframe&gt; completo que te da Google Maps en "
            "'Compartir → Insertar un mapa'. Muestra el pin con el nombre real "
            "del servicio. Déjalo vacío si no aparece en Google Maps."
        ),
    )
    maps_url = models.TextField(
        blank=True,
        verbose_name="URL de la ficha en Google Maps",
        help_text=(
            "Pega aquí la URL de la ficha del negocio en Google Maps. Se usa "
            "para los botones 'Abrir mapa' y 'Cómo llegar'. Déjalo vacío si no "
            "aparece en Google Maps."
        ),
    )

    tipo_atencion = models.CharField(max_length=20, choices=TIPO_ATENCION_CHOICES, default="presencial")
    disponibilidad = models.CharField(max_length=30, choices=DISPONIBILIDAD_CHOICES, default="consultar")
    horario_atencion = models.CharField(max_length=180, blank=True, help_text="Ejemplo: Lunes a domingo: 8:00 a. m. - 10:00 p. m. o Atención 24 horas.")

    telefono = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(blank=True)
    sitio_web = models.URLField(blank=True)
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)

    recomendaciones = models.TextField(blank=True, help_text="Consejos para el turista: llevar DNI, confirmar horario, acudir en emergencia, etc.")
    notas = models.TextField(blank=True, help_text="Información adicional interna o pública.")

    imagen_principal = models.ImageField(upload_to="servicios_turista/principales/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)

    destacado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Servicio útil para turista"
        verbose_name_plural = "Servicios útiles para turistas"
        ordering = ["categoria_principal__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["distrito", "nombre"],
                name="unique_servicio_turista_nombre_distrito"
            )
        ]

    def __str__(self):
        return self.nombre


class ContactoServicioTurista(models.Model):
    TIPO_CONTACTO_CHOICES = [
        ("telefono", "Teléfono"),
        ("celular", "Celular"),
        ("whatsapp", "WhatsApp"),
        ("correo", "Correo"),
        ("emergencia", "Emergencia"),
        ("informes", "Informes"),
        ("atencion_cliente", "Atención al cliente"),
        ("administracion", "Administración"),
        ("otro", "Otro"),
    ]

    servicio = models.ForeignKey(ServicioTurista, related_name="contactos", on_delete=models.CASCADE)
    tipo_contacto = models.CharField(max_length=30, choices=TIPO_CONTACTO_CHOICES)
    etiqueta = models.CharField(max_length=80, blank=True, help_text="Ejemplo: Central, Emergencias, Informes, Atención al cliente.")
    valor = models.CharField(max_length=120, help_text="Número, correo o dato de contacto.")
    es_principal = models.BooleanField(default=False)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contacto de servicio útil"
        verbose_name_plural = "Contactos de servicios útiles"
        ordering = ["servicio__nombre", "orden", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["servicio", "valor"],
                name="unique_contacto_servicio_turista_valor"
            ),
            models.UniqueConstraint(
                fields=["servicio", "tipo_contacto"],
                condition=Q(es_principal=True),
                name="unique_contacto_principal_tipo_servicio_turista"
            )
        ]

    def __str__(self):
        if self.etiqueta:
            return f"{self.etiqueta} - {self.valor}"
        return f"{self.get_tipo_contacto_display()} - {self.valor}"


class ImagenServicioTurista(models.Model):
    servicio = models.ForeignKey(ServicioTurista, related_name="imagenes", on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to="servicios_turista/galeria/")
    titulo = models.CharField(max_length=160, blank=True)
    texto_alt = models.CharField(max_length=180, blank=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Imagen de servicio útil"
        verbose_name_plural = "Imágenes de servicios útiles"
        ordering = ["servicio__nombre", "orden", "id"]

    def __str__(self):
        if self.titulo:
            return self.titulo
        return f"Imagen de {self.servicio.nombre}"
