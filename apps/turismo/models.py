from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from PIL import Image, ImageSequence, UnidentifiedImageError
from apps.ubicaciones.models import Distrito, Localidad

TIPO_ICONO_CHOICES = (
    ("bootstrap", "Bootstrap Icon"),
    ("imagen", "Imagen / SVG / GIF"),
    ("lottie", "Lottie JSON"),
)

TIPO_COSTO_CHOICES = (
    ("gratis", "Gratis"),
    ("pagado", "Pagado"),
    ("consultar", "Consultar"),
)

DIFICULTAD_CHOICES = (
    ("no_aplica", "No aplica"),
    ("facil", "Fácil"),
    ("moderada", "Moderada"),
    ("dificil", "Difícil"),
)

TIPO_MEDIA_CHOICES = (
    ("imagen", "Imagen / GIF"),
    ("video", "Video externo"),
    ("video_archivo", "Video MP4"),
)

class CategoriaLugarTuristico(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)

    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(max_length=80, blank=True, help_text="Ejemplo: bi-geo-alt-fill, bi-tree-fill, bi-bank")
    icono_archivo = models.FileField(upload_to="turismo/categorias/iconos/", blank=True, help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons.")

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Categoría de lugar turístico"
        verbose_name_plural = "Categorías de lugares turísticos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class ServicioLugarTuristico(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)

    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(max_length=80, blank=True, help_text="Ejemplo: bi-p-square-fill, bi-person-wheelchair, bi-binoculars-fill")
    icono_archivo = models.FileField(upload_to="turismo/servicios/iconos/", blank=True, help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons.")

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Servicio de lugar turístico"
        verbose_name_plural = "Servicios de lugares turísticos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class LugarTuristico(models.Model):
    categoria_principal = models.ForeignKey(
        CategoriaLugarTuristico,
        on_delete=models.PROTECT,
        related_name="lugares_principales",
        verbose_name="Categoría principal"
    )
    categorias_secundarias = models.ManyToManyField(
        CategoriaLugarTuristico,
        related_name="lugares_secundarios",
        blank=True,
        verbose_name="Categorías secundarias"
    )
    servicios = models.ManyToManyField(
        ServicioLugarTuristico,
        related_name="lugares",
        blank=True,
        verbose_name="Servicios disponibles"
    )

    nombre = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    descripcion_corta = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)
    historia = models.TextField(blank=True, help_text="Información histórica o cultural del lugar, si aplica.")
    imagen_historia = models.ImageField(
        upload_to="turismo/lugares/historia/",
        blank=True,
        help_text="Imagen antigua o histórica del lugar. Ejemplo: foto antigua de la plaza."
    )
    texto_alt_imagen_historia = models.CharField(
        max_length=180,
        blank=True,
        help_text="Texto alternativo para la imagen histórica."
    )

    distrito = models.ForeignKey(Distrito, on_delete=models.PROTECT, related_name="lugares_turisticos")
    localidad = models.ForeignKey(Localidad, on_delete=models.SET_NULL, null=True, blank=True, related_name="lugares_turisticos")
    direccion = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    embed_maps = models.TextField(
        blank=True,
        help_text="Pega el código iframe completo de Google Maps o solo la URL src. Se usa para el mapa visual (gratuito, sin API key)."
    )
    maps_url = models.TextField(
        blank=True,
        help_text="URL larga de la ficha del lugar en Google Maps. Conservar las coordenadas !3d y !4d para generar la ruta precisa en Cómo llegar."
    )

    horario_visita = models.CharField(max_length=180, blank=True)
    tipo_costo = models.CharField(max_length=20, choices=TIPO_COSTO_CHOICES, default="consultar")
    precio_desde = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Precio desde", help_text="Monto mínimo referencial en soles, si aplica.")
    precio_hasta = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Precio hasta", help_text="Monto máximo referencial en soles, si aplica.")
    tiempo_visita_estimado = models.CharField(max_length=120, blank=True, help_text="Ejemplo: 1 hora, medio día, 2 horas.")
    dificultad = models.CharField(max_length=20, choices=DIFICULTAD_CHOICES, default="no_aplica")
    recomendaciones = models.TextField(blank=True, help_text="Consejos para el turista: ropa, horario ideal, clima, seguridad, etc.")
    como_llegar = models.TextField(blank=True, help_text="Indicaciones generales para llegar al lugar.")

    imagen_principal = models.ImageField(upload_to="turismo/lugares/principales/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)

    destacado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lugar turístico"
        verbose_name_plural = "Lugares turísticos"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["distrito", "nombre"],
                name="unique_lugar_nombre_distrito"
            )
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        if self.precio_desde is not None and self.precio_hasta is not None:
            if self.precio_hasta < self.precio_desde:
                raise ValidationError("El precio hasta no puede ser menor que el precio desde.")


class ImagenLugarTuristico(models.Model):
    lugar = models.ForeignKey(LugarTuristico, on_delete=models.CASCADE, related_name="imagenes")
    tipo_media = models.CharField(
        max_length=20,
        choices=TIPO_MEDIA_CHOICES,
        default="imagen",
        verbose_name="Tipo de multimedia"
    )
    imagen = models.ImageField(
        upload_to="turismo/lugares/galeria/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["jpg", "jpeg", "png", "webp", "gif"]
            )
        ],
        help_text="Imagen del lugar turístico. Permite JPG, JPEG, PNG, WEBP o GIF. Si es GIF, máximo 15 segundos."
    )
    video_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="URL de YouTube, Vimeo u otro video externo. Requerida cuando el tipo es Video externo."
    )
    video_archivo = models.FileField(
        upload_to="turismo/lugares/videos/",
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["mp4"])],
        help_text="Archivo MP4 del lugar turístico. Úsalo solo cuando el tipo sea Video MP4."
    )
    titulo = models.CharField(max_length=160, blank=True)
    descripcion = models.TextField(blank=True, help_text="Descripción breve opcional para la galería.")
    texto_alt = models.CharField(max_length=180, blank=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Multimedia de lugar turístico"
        verbose_name_plural = "Multimedia de lugares turísticos"
        ordering = ["lugar__nombre", "orden", "id"]

    def __str__(self):
        if self.titulo:
            return self.titulo
        return f"{self.get_tipo_media_display()} de {self.lugar.nombre}"

    def _validar_gif_animado(self):
        if not self.imagen:
            return

        nombre_archivo = (self.imagen.name or "").lower()

        if not nombre_archivo.endswith(".gif"):
            return

        archivo = getattr(self.imagen, "file", self.imagen)
        posicion_inicial = None

        try:
            if hasattr(archivo, "tell"):
                posicion_inicial = archivo.tell()
            if hasattr(archivo, "seek"):
                archivo.seek(0)

            imagen = Image.open(archivo)

            if not getattr(imagen, "is_animated", False):
                return

            duracion_ms = sum(
                frame.info.get("duration", 0)
                for frame in ImageSequence.Iterator(imagen)
            )

            if duracion_ms > 15000:
                raise ValidationError({
                    "imagen": "El GIF no debe superar los 15 segundos de duración."
                })
        except UnidentifiedImageError as exc:
            raise ValidationError({
                "imagen": "No se pudo validar el GIF. Verifica que sea una imagen válida."
            }) from exc
        finally:
            try:
                if hasattr(archivo, "seek"):
                    archivo.seek(posicion_inicial or 0)
            except Exception:
                pass

    def clean(self):
        errores = {}

        if self.tipo_media == "imagen":
            if not self.imagen:
                errores["imagen"] = "Debes subir una imagen cuando el tipo de multimedia es Imagen / GIF."
            if self.video_url:
                errores["video_url"] = "Si el tipo es Imagen / GIF, no debes ingresar una URL de video."
            if self.video_archivo:
                errores["video_archivo"] = "Si el tipo es Imagen / GIF, no debes subir un archivo MP4."

            if not errores:
                self._validar_gif_animado()

        elif self.tipo_media == "video":
            if not self.video_url:
                errores["video_url"] = "Debes ingresar una URL cuando el tipo de multimedia es Video externo."
            if self.imagen:
                errores["imagen"] = "Si el tipo es Video externo, no debes subir una imagen."
            if self.video_archivo:
                errores["video_archivo"] = "Si el tipo es Video externo, no debes subir un archivo MP4."

        elif self.tipo_media == "video_archivo":
            if not self.video_archivo:
                errores["video_archivo"] = "Debes subir un archivo MP4 cuando el tipo de multimedia es Video MP4."
            if self.imagen:
                errores["imagen"] = "Si el tipo es Video MP4, no debes subir una imagen."
            if self.video_url:
                errores["video_url"] = "Si el tipo es Video MP4, no debes ingresar una URL externa."

        if errores:
            raise ValidationError(errores)

class RecomendacionLugarTuristico(models.Model):
    lugar = models.ForeignKey(
        LugarTuristico,
        on_delete=models.CASCADE,
        related_name="recomendaciones_items",
        verbose_name="Lugar turístico"
    )
    titulo = models.CharField(
        max_length=140,
        help_text="Título corto del consejo. Ejemplo: Mejor horario para visitar."
    )
    descripcion = models.TextField(
        help_text="Detalle breve de la recomendación. Evita textos largos; idealmente 1 o 2 líneas."
    )
    icono_bootstrap = models.CharField(
        max_length=80,
        blank=True,
        default="bi bi-check-circle",
        help_text="Ejemplo: bi bi-camera, bi bi-shield-check, bi bi-sunrise"
    )
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Recomendación de lugar turístico"
        verbose_name_plural = "Recomendaciones de lugares turísticos"
        ordering = ["lugar__nombre", "orden", "id"]

    def __str__(self):
        return f"{self.titulo} — {self.lugar.nombre}"
