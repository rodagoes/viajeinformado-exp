import os
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import models
from PIL import Image, ImageOps

HERO_ANCHO_MAX = 2000
HERO_CALIDAD_WEBP = 85  # q75 ensuciaba la textura fina y los móviles amplían la imagen ~1,7x
HERO_ASPECTO_MOVIL = 0.65  # ancho/alto del recorte para móviles (< 576 px); el hero ahí es casi vertical (~0,52-0,62)
HERO_ALTO_MOVIL_MAX = 1500


def _a_webp(archivo):
    """Imagen subida -> WebP (<= HERO_ANCHO_MAX px de ancho). Si no se puede leer, se conserva el original."""
    try:
        with Image.open(archivo) as img:
            if img.format == "WEBP" and img.width <= HERO_ANCHO_MAX:
                archivo.seek(0)
                return archivo  # ya es WebP razonable: no se recomprime
            img = ImageOps.exif_transpose(img)
            img.thumbnail((HERO_ANCHO_MAX, HERO_ANCHO_MAX * 2), Image.LANCZOS)  # solo reduce, nunca amplía
            buf = BytesIO()
            img.convert("RGBA" if img.has_transparency_data else "RGB").save(buf, "WEBP", quality=HERO_CALIDAD_WEBP, method=6)
    except (OSError, ValueError):
        archivo.seek(0)  # Image.open ya leyó el archivo: sin rebobinar se guardaría vacío
        return archivo
    return ContentFile(buf.getvalue(), name=os.path.splitext(os.path.basename(archivo.name))[0] + ".webp")

def _recorte_movil(archivo):
    """Recorte central vertical del hero para móviles: son exactamente los píxeles que `object-fit: cover` ya muestra
    ahí, con la misma calidad y ~la mitad de peso. None si la imagen ya es casi vertical o no se puede leer."""
    try:
        with Image.open(archivo) as img:
            img = ImageOps.exif_transpose(img)
            if img.width / img.height <= HERO_ASPECTO_MOVIL:
                return None
            ancho = round(img.height * HERO_ASPECTO_MOVIL)
            izq = (img.width - ancho) // 2
            img = img.crop((izq, 0, izq + ancho, img.height))
            img.thumbnail((img.width, HERO_ALTO_MOVIL_MAX), Image.LANCZOS)
            buf = BytesIO()
            img.convert("RGB").save(buf, "WEBP", quality=HERO_CALIDAD_WEBP, method=6)
    except (OSError, ValueError):
        return None
    finally:
        archivo.seek(0)
    return ContentFile(buf.getvalue(), name=os.path.splitext(os.path.basename(archivo.name))[0] + "_movil.webp")


class HomeHeroSlide(models.Model):
    TIPO_ARCHIVO_CHOICES = [
        ('image', 'Imagen'),
        ('video', 'Video'),
        ('gif', 'GIF'),
    ]

    etiqueta = models.CharField(max_length=100, help_text="Ejemplo: Historia · Cultura · Naturaleza")
    titulo_principal = models.CharField(max_length=150, help_text="Ejemplo: Descubre lugares")
    titulo_resaltado = models.CharField(max_length=150, help_text="Ejemplo: con identidad")
    descripcion = models.TextField()
    
    tipo_archivo = models.CharField(max_length=10, choices=TIPO_ARCHIVO_CHOICES, default='image')
    archivo = models.FileField(upload_to="home/hero/", help_text="Acepta imagen, video o gif")
    archivo_movil = models.ImageField(upload_to="home/hero/movil/", blank=True, editable=False)  # recorte móvil, se genera solo
    poster_video = models.ImageField(upload_to="home/hero/posters/", blank=True, null=True, help_text="Imagen previa para videos (recomendado)")
    texto_alt = models.CharField(max_length=255, blank=True, help_text="Para accesibilidad de imágenes/gifs")
    
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    intervalo_ms = models.PositiveIntegerField(default=5500, help_text="Tiempo en milisegundos que dura el slide")
    
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['orden', 'id']
        verbose_name = "Slide del Hero"
        verbose_name_plural = "Slides del Hero"

    def __str__(self):
        return f"{self.titulo_principal} {self.titulo_resaltado}"

    def save(self, *args, **kwargs):
        # El hero es el LCP del Home: un PNG de ~3 MB se sirve como WebP de ~150 KB. Solo imágenes recién subidas.
        if self.tipo_archivo == 'image' and self.archivo and not self.archivo._committed:
            self.archivo_movil = _recorte_movil(self.archivo) or ""
            self.archivo = _a_webp(self.archivo)
        super().save(*args, **kwargs)


class ConfiguracionPublica(models.Model):
    """Interruptores del sitio público. Una sola fila (singleton): se edita desde Admin > Configuración pública."""

    mostrar_metricas_home = models.BooleanField(
        "Mostrar estadísticas en Home", default=False,
        help_text='Muestra la sección "Viaje Informado en cifras" en el Home. Si está apagada no se renderiza nada.',
    )
    mostrar_sponsors_footer = models.BooleanField(
        "Mostrar sponsors en Footer", default=False,
        help_text="Muestra la franja de sponsors activos antes de la zona legal del footer.",
    )

    class Meta:
        verbose_name = "Configuración pública"
        verbose_name_plural = "Configuración pública"

    def __str__(self):
        return "Configuración pública"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton: siempre la misma fila
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return (0, {})  # no se borra: sin fila, los interruptores volverían a su valor por defecto

    @classmethod
    def cargar(cls):
        """Fila única, creándola si falta (uso del Admin)."""
        return cls.objects.get_or_create(pk=1)[0]

    @classmethod
    def leer(cls):
        """Fila única para el sitio público: una sola consulta y sin escribir; si no existe, valores por defecto (OFF)."""
        return cls.objects.filter(pk=1).first() or cls()


class Sponsor(models.Model):
    """Logo de sponsor para la franja del footer (visible solo si el interruptor global y `activo` están en ON)."""

    nombre = models.CharField(max_length=120)
    logo = models.ImageField(upload_to="sponsors/", help_text="Preferible PNG/SVG/WebP con fondo transparente.")
    url = models.URLField("URL (opcional)", blank=True, help_text="Si se indica, el logo enlaza a esta dirección.")
    orden = models.PositiveIntegerField(default=0, help_text="Menor número = aparece antes.")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre", "id"]
        verbose_name = "Sponsor"
        verbose_name_plural = "Sponsors"

    def __str__(self):
        return self.nombre
