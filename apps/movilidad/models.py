from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

TIPO_ICONO_CHOICES = [
    ("bootstrap", "Bootstrap Icon"),
    ("imagen", "Imagen / SVG / GIF"),
    ("lottie", "Lottie JSON"),
]

class CategoriaMovilidad(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)
    
    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(max_length=80, blank=True, help_text="Ejemplo: bi-car-front-fill, bi-bus-front-fill, bi-signpost-2-fill")
    icono_archivo = models.FileField(upload_to="movilidad/categorias/iconos/", blank=True, help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons.")

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Categoría de movilidad"
        verbose_name_plural = "Categorías de movilidad"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class ServicioMovilidad(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)
    
    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(max_length=80, blank=True, help_text="Ejemplo: bi-whatsapp, bi-credit-card-fill, bi-suitcase-fill")
    icono_archivo = models.FileField(upload_to="movilidad/servicios/iconos/", blank=True, help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons.")

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Servicio de movilidad"
        verbose_name_plural = "Servicios de movilidad"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class OperadorMovilidad(models.Model):
    TIPO_OPERADOR_CHOICES = [
        ("taxi", "Taxi"),
        ("taxi_turistico", "Taxi turístico"),
        ("transporte_publico", "Transporte público"),
        ("colectivo", "Colectivo"),
        ("bus", "Bus / empresa de transporte"),
        ("movilidad_privada", "Movilidad privada"),
        ("agencia", "Agencia / operador turístico"),
        ("otro", "Otro"),
    ]

    tipo_operador = models.CharField(max_length=30, choices=TIPO_OPERADOR_CHOICES, default="otro")
    nombre = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    descripcion_corta = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)

    servicios = models.ManyToManyField(ServicioMovilidad, related_name="operadores", blank=True)

    distrito = models.ForeignKey('ubicaciones.Distrito', related_name="operadores_movilidad", on_delete=models.PROTECT, null=True, blank=True)
    localidad = models.ForeignKey('ubicaciones.Localidad', related_name="operadores_movilidad", on_delete=models.SET_NULL, null=True, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    telefono = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(blank=True)
    sitio_web = models.URLField(blank=True)
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)

    imagen_principal = models.ImageField(upload_to="movilidad/operadores/principales/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)

    destacado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Operador de movilidad"
        verbose_name_plural = "Operadores de movilidad"
        ordering = ["tipo_operador", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["distrito", "nombre"],
                name="unique_operador_movilidad_nombre_distrito"
            )
        ]

    def __str__(self):
        return self.nombre


class RutaMovilidad(models.Model):
    TIPO_COSTO_CHOICES = [
        ("gratis", "Gratis"),
        ("pagado", "Pagado"),
        ("consultar", "Consultar"),
    ]

    DIFICULTAD_CHOICES = [
        ("no_aplica", "No aplica"),
        ("facil", "Fácil"),
        ("moderada", "Moderada"),
        ("dificil", "Difícil"),
    ]

    categoria_principal = models.ForeignKey(CategoriaMovilidad, related_name="rutas_principales", on_delete=models.PROTECT, verbose_name="Categoría principal")
    categorias_secundarias = models.ManyToManyField(CategoriaMovilidad, related_name="rutas_secundarias", blank=True, verbose_name="Categorías secundarias")
    servicios = models.ManyToManyField(ServicioMovilidad, related_name="rutas", blank=True, verbose_name="Servicios / facilidades")
    operador = models.ForeignKey(OperadorMovilidad, related_name="rutas", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Operador asociado")

    nombre = models.CharField(max_length=180, help_text="Ejemplo: Plaza de Armas a Kotosh")
    slug = models.SlugField(max_length=200, unique=True)
    descripcion_corta = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)

    origen_distrito = models.ForeignKey('ubicaciones.Distrito', related_name="rutas_origen_movilidad", on_delete=models.PROTECT, null=True, blank=True)
    origen_localidad = models.ForeignKey('ubicaciones.Localidad', related_name="rutas_origen_movilidad", on_delete=models.SET_NULL, null=True, blank=True)
    origen_texto = models.CharField(max_length=180, blank=True, help_text="Ejemplo: Plaza de Armas, Terminal terrestre, Centro de Huánuco.")

    destino_distrito = models.ForeignKey('ubicaciones.Distrito', related_name="rutas_destino_movilidad", on_delete=models.PROTECT, null=True, blank=True)
    destino_localidad = models.ForeignKey('ubicaciones.Localidad', related_name="rutas_destino_movilidad", on_delete=models.SET_NULL, null=True, blank=True)
    destino_texto = models.CharField(max_length=180, blank=True, help_text="Ejemplo: Kotosh, Cueva de las Lechuzas, Huánuco Pampa.")

    punto_partida = models.CharField(max_length=255, blank=True, help_text="Dónde tomar la movilidad o referencia de inicio.")
    punto_llegada = models.CharField(max_length=255, blank=True, help_text="Referencia del punto de llegada.")
    indicaciones = models.TextField(blank=True, help_text="Explicación práctica de cómo llegar.")
    duracion_estimada = models.CharField(max_length=120, blank=True, help_text="Ejemplo: 10 minutos, 30 minutos, 2 horas.")
    distancia_km = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, help_text="Distancia aproximada en kilómetros.")
    frecuencia = models.CharField(max_length=160, blank=True, help_text="Ejemplo: cada 10 minutos, según disponibilidad, previa reserva.")
    horario_referencial = models.CharField(max_length=180, blank=True, help_text="Ejemplo: Lunes a domingo, 6:00 a. m. - 8:00 p. m.")

    tipo_costo = models.CharField(max_length=20, choices=TIPO_COSTO_CHOICES, default="consultar")
    precio_desde = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Precio desde", help_text="Tarifa mínima referencial en soles.")
    precio_hasta = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Precio hasta", help_text="Tarifa máxima referencial en soles.")

    dificultad = models.CharField(max_length=20, choices=DIFICULTAD_CHOICES, default="no_aplica")
    recomendaciones = models.TextField(blank=True, help_text="Consejos para el turista: negociar tarifa, evitar horarios inseguros, llevar efectivo, etc.")
    advertencias = models.TextField(blank=True, help_text="Alertas o precauciones importantes.")

    imagen_principal = models.ImageField(upload_to="movilidad/rutas/principales/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)

    destacado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ruta de movilidad"
        verbose_name_plural = "Rutas de movilidad"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["nombre"],
                name="unique_ruta_movilidad_nombre"
            )
        ]

    def clean(self):
        super().clean()
        if self.precio_desde and self.precio_hasta and self.precio_hasta < self.precio_desde:
            raise ValidationError({'precio_hasta': "El precio hasta no puede ser menor que el precio desde."})

    def __str__(self):
        return self.nombre


class ImagenRutaMovilidad(models.Model):
    ruta = models.ForeignKey(RutaMovilidad, related_name="imagenes", on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to="movilidad/rutas/galeria/")
    titulo = models.CharField(max_length=160, blank=True)
    texto_alt = models.CharField(max_length=180, blank=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Imagen de ruta de movilidad"
        verbose_name_plural = "Imágenes de rutas de movilidad"
        ordering = ["ruta__nombre", "orden", "id"]

    def __str__(self):
        if self.titulo:
            return self.titulo
        return f"Imagen de {self.ruta.nombre}"


class TransportePublico(models.Model):
    """
    Medio de transporte urbano mostrado en la pantalla Tarifas de Taxi
    (Planifica). Deliberadamente independiente de RutaMovilidad /
    OperadorMovilidad: hoy solo necesita una tarifa mínima referencial,
    no zonas, horarios ni operadores.
    """

    nombre = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    nombre_alternativo = models.CharField(max_length=100, blank=True)
    descripcion = models.CharField(max_length=255)

    imagen = models.ImageField(upload_to="movilidad/transportes/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)

    tarifa_minima = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Tarifa mínima referencial",
        help_text="Precio mínimo referencial expresado en soles.",
    )

    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Transporte público"
        verbose_name_plural = "Transportes públicos"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class ConsejoMovilidad(models.Model):
    """Consejo mostrado en el bloque "Consejos para el viajero" de Tarifas de Taxi."""

    texto = models.CharField(max_length=255)
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Consejo de movilidad"
        verbose_name_plural = "Consejos de movilidad"
        ordering = ["orden", "id"]

    def __str__(self):
        return self.texto
