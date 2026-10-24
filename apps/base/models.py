from django.db import models

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
