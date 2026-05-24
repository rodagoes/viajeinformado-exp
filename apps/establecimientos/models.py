from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from apps.ubicaciones.models import Distrito, Localidad

class CategoriaEstablecimiento(models.Model):
    TIPO_ICONO_CHOICES = [
        ("bootstrap", "Bootstrap Icon"),
        ("imagen", "Imagen / SVG / GIF"),
        ("lottie", "Lottie JSON"),
    ]

    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)
    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(
        max_length=80, 
        blank=True, 
        help_text="Ejemplo: bi-cup-hot-fill"
    )
    icono_archivo = models.FileField(
        upload_to="establecimientos/iconos/", 
        blank=True, 
        help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons."
    )
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Categoría de establecimiento"
        verbose_name_plural = "Categorías de establecimientos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class ServicioEstablecimiento(models.Model):
    APLICA_A_CHOICES = [
        ("todos", "Todos"),
        ("restaurante", "Restaurantes"),
        ("alojamiento", "Alojamientos"),
    ]

    TIPO_ICONO_CHOICES = [
        ("bootstrap", "Bootstrap Icon"),
        ("imagen", "Imagen / SVG / GIF"),
        ("lottie", "Lottie JSON"),
    ]

    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)
    aplica_a = models.CharField(max_length=20, choices=APLICA_A_CHOICES, default="todos")
    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(
        max_length=80, 
        blank=True, 
        help_text="Ejemplo: bi-wifi"
    )
    icono_archivo = models.FileField(
        upload_to="establecimientos/servicios/iconos/", 
        blank=True, 
        help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons."
    )
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Servicio de establecimiento"
        verbose_name_plural = "Servicios de establecimientos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Establecimiento(models.Model):
    TIPO_CHOICES = [
        ("restaurante", "Restaurante"),
        ("alojamiento", "Alojamiento"),
    ]

    RANGO_PRECIO_CHOICES = [
        ("economico", "Económico"),
        ("moderado", "Moderado"),
        ("alto", "Alto"),
        ("consultar", "Consultar"),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    categoria_principal = models.ForeignKey(CategoriaEstablecimiento, related_name="establecimientos_principales", on_delete=models.PROTECT, verbose_name="Categoría principal")
    categorias_secundarias = models.ManyToManyField(CategoriaEstablecimiento, related_name="establecimientos_secundarios", blank=True, verbose_name="Categorías secundarias", help_text="Especialidades adicionales del establecimiento.")
    servicios = models.ManyToManyField(ServicioEstablecimiento, related_name="establecimientos", blank=True, verbose_name="Servicios", help_text="Servicios o amenidades que ofrece el establecimiento.")
    
    nombre = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    descripcion_corta = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)
    
    telefono = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(blank=True)
    sitio_web = models.URLField(blank=True)
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)
    carta_pdf = models.FileField(
        upload_to="establecimientos/cartas/",
        blank=True,
        verbose_name="Carta en PDF",
        help_text="Opcional. Para restaurantes: sube la carta en formato PDF. Se abrirá en una nueva pestaña."
    )
    carta_url = models.URLField(
        blank=True,
        verbose_name="URL de carta externa",
        help_text="Opcional. Úsalo si la carta está publicada en una URL externa."
    )
    
    rango_precio = models.CharField(max_length=20, choices=RANGO_PRECIO_CHOICES, default="consultar")
    precio_desde = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Precio desde",
        help_text="Monto mínimo referencial en soles. Ejemplo: plato más económico o habitación más económica."
    )
    precio_hasta = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precio hasta",
        help_text="Monto máximo referencial en soles. Ejemplo: plato de mayor precio o habitación de mayor precio."
    )
    
    imagen_principal = models.ImageField(upload_to="establecimientos/principales/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)
    
    destacado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Establecimiento"
        verbose_name_plural = "Establecimientos"
        ordering = ["tipo", "nombre"]

    def clean(self):
        super().clean()
        if self.precio_desde and self.precio_hasta and self.precio_hasta < self.precio_desde:
            raise ValidationError({
                "precio_hasta": "El precio hasta no puede ser menor que el precio desde."
            })

        if self.carta_pdf and not self.carta_pdf.name.lower().endswith(".pdf"):
            raise ValidationError({
                "carta_pdf": "La carta debe ser un archivo PDF."
            })

    def __str__(self):
        return self.nombre


class SucursalEstablecimiento(models.Model):
    establecimiento = models.ForeignKey(Establecimiento, related_name="sucursales", on_delete=models.CASCADE)
    nombre = models.CharField(max_length=160, help_text="Ejemplo: Sucursal principal, Sucursal Huallayco, Sucursal Cayhuayna")
    slug = models.SlugField(max_length=200)
    distrito = models.ForeignKey(Distrito, related_name="sucursales_establecimientos", on_delete=models.PROTECT)
    localidad = models.ForeignKey(Localidad, related_name="sucursales_establecimientos", on_delete=models.SET_NULL, null=True, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(blank=True)
    horario_atencion = models.CharField(max_length=180, blank=True)
    latitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    es_principal = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sucursal de establecimiento"
        verbose_name_plural = "Sucursales de establecimientos"
        ordering = ["establecimiento__nombre", "-es_principal", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["establecimiento", "nombre"], name="unique_sucursal_nombre_por_establecimiento"),
            models.UniqueConstraint(fields=["establecimiento", "slug"], name="unique_sucursal_slug_por_establecimiento"),
            models.UniqueConstraint(
                fields=["establecimiento"],
                condition=Q(es_principal=True),
                name="unique_sucursal_principal_por_establecimiento"
            )
        ]

    def __str__(self):
        return f"{self.establecimiento.nombre} - {self.nombre}"


class ImagenEstablecimiento(models.Model):
    establecimiento = models.ForeignKey(Establecimiento, related_name="imagenes", on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to="establecimientos/galeria/")
    titulo = models.CharField(max_length=160, blank=True)
    texto_alt = models.CharField(max_length=180, blank=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Imagen de establecimiento"
        verbose_name_plural = "Imágenes de establecimientos"
        ordering = ["orden", "id"]

    def __str__(self):
        return self.titulo if self.titulo else f"Imagen de {self.establecimiento.nombre}"


class RecomendacionEstablecimiento(models.Model):
    establecimiento = models.ForeignKey(
        Establecimiento,
        related_name="recomendaciones",
        on_delete=models.CASCADE
    )
    nombre = models.CharField(
        max_length=140,
        help_text="Ejemplo restaurante: Pachamanca. Ejemplo alojamiento: Habitación individual."
    )
    imagen = models.ImageField(
        upload_to="establecimientos/recomendaciones/",
        blank=True,
        help_text="Opcional. En restaurantes puede usarse para la imagen del plato. En alojamientos no se mostrará en el detalle público."
    )
    icono_archivo = models.FileField(
        upload_to="establecimientos/recomendaciones/iconos/",
        blank=True,
        verbose_name="Ícono para alojamiento",
        help_text="Opcional. Para alojamientos: sube un ícono SVG, PNG, JPG o WebP para esta recomendación."
    )
    orden = models.PositiveSmallIntegerField(
        default=1,
        help_text="Orden de visualización. Usar 1, 2 o 3."
    )
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Recomendación de establecimiento"
        verbose_name_plural = "Recomendaciones de establecimientos"
        ordering = ["establecimiento__nombre", "orden", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["establecimiento", "orden"],
                name="unique_recomendacion_orden_por_establecimiento"
            )
        ]

    def clean(self):
        super().clean()
        if self.orden < 1 or self.orden > 3:
            raise ValidationError({
                "orden": "El orden debe estar entre 1 y 3."
            })

    def __str__(self):
        return f"{self.establecimiento.nombre} - #{self.orden} {self.nombre}"


class ContactoSucursalEstablecimiento(models.Model):
    TIPO_CONTACTO_CHOICES = [
        ("telefono", "Teléfono"),
        ("celular", "Celular"),
        ("whatsapp", "WhatsApp"),
        ("correo", "Correo"),
        ("reservas", "Reservas"),
        ("atencion_cliente", "Atención al cliente"),
        ("administracion", "Administración"),
    ]

    sucursal = models.ForeignKey(SucursalEstablecimiento, related_name="contactos", on_delete=models.CASCADE)
    tipo_contacto = models.CharField(max_length=30, choices=TIPO_CONTACTO_CHOICES)
    etiqueta = models.CharField(max_length=80, blank=True, help_text="Ejemplo: Reservas, Atención al cliente, Administración, Celular principal.")
    valor = models.CharField(max_length=120, help_text="Número, correo o dato de contacto.")
    es_principal = models.BooleanField(default=False)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contacto de sucursal"
        verbose_name_plural = "Contactos de sucursales"
        ordering = ["sucursal__establecimiento__nombre", "sucursal__nombre", "orden", "id"]
        constraints = [
            models.UniqueConstraint(fields=["sucursal", "valor"], name="unique_contacto_valor_por_sucursal"),
            models.UniqueConstraint(
                fields=["sucursal", "tipo_contacto"],
                condition=Q(es_principal=True),
                name="unique_contacto_principal_por_tipo_sucursal"
            )
        ]

    def __str__(self):
        if self.etiqueta:
            return f"{self.etiqueta} - {self.valor}"
        return f"{self.get_tipo_contacto_display()} - {self.valor}"
