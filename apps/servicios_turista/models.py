import copy

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from apps.base.services.mapas import coord_a_texto

from .services import horarios, mapas_sede

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


class SedeServicioTurista(models.Model):
    """Punto físico de un ServicioTurista (entidad). Cada sede activa es una
    tarjeta en /planifica/servicios-utiles/; su pk es el id que usa el JS.

    ponytail: sin 'es_principal' ni UniqueConstraint(condition=...): MariaDB no
    aplica restricciones condicionales. Las reglas de aplicación viven en clean()."""

    servicio = models.ForeignKey(ServicioTurista, related_name="sedes", on_delete=models.CASCADE, verbose_name="Entidad")
    nombre = models.CharField(
        max_length=160, blank=True,
        help_text="Opcional. Distingue esta sede de otras de la misma entidad (ej. Agencia Ambo). "
                  "Déjalo vacío si la entidad solo tiene una sede.",
    )
    slug = models.SlugField(
        max_length=200, blank=True,
        help_text="Se genera automáticamente al guardar; no hace falta escribirlo.",
    )

    distrito = models.ForeignKey('ubicaciones.Distrito', related_name="sedes_servicios_turista", on_delete=models.PROTECT)
    localidad = models.ForeignKey('ubicaciones.Localidad', related_name="sedes_servicios_turista", on_delete=models.SET_NULL, null=True, blank=True)
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

    disponibilidad = models.CharField(max_length=30, choices=ServicioTurista.DISPONIBILIDAD_CHOICES, default="consultar")
    horario = models.JSONField(
        default=dict, blank=True,
        help_text="Horario por bloques (lunes a viernes, sábados, domingos). Si tiene datos, genera el texto ES/EN de "
                  "«horario_atencion»; si está vacío, ese texto es personalizado. Se edita desde el Admin.",
    )
    horario_atencion = models.CharField(max_length=255, blank=True, help_text="Ejemplo: Lunes a domingo: 8:00 a. m. - 10:00 p. m. o Atención 24 horas.")
    telefono = models.CharField(max_length=30, blank=True, help_text="Teléfono de esta sede. Si se deja vacío se usa el de la entidad.")

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sede de servicio útil"
        verbose_name_plural = "Sedes de servicios útiles"
        ordering = ["servicio__nombre", "nombre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["servicio", "slug"], name="unique_sede_servicio_turista_slug"),
        ]

    def __str__(self):
        return self.nombre_publico

    @property
    def nombre_publico(self):
        """'Entidad - Sede', o solo 'Entidad' cuando la sede no tiene nombre."""
        nombre = (self.nombre or "").strip()
        return f"{self.servicio.nombre} - {nombre}" if nombre else self.servicio.nombre

    def _generar_slug(self):
        # slugify quita tildes (Huánuco -> huanuco). Sin nombre: 'principal'.
        base = (slugify(self.nombre) or "principal")[:180]
        otros = SedeServicioTurista.objects.filter(servicio_id=self.servicio_id).exclude(pk=self.pk)
        usados = set(otros.values_list("slug", flat=True))
        slug, n = base, 2
        while slug in usados:
            slug = f"{base}-{n}"
            n += 1
        return slug

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Para regenerar el texto del horario solo cuando el horario cambió.
        self._horario_orig = copy.deepcopy(self.__dict__.get("horario"))

    def clean(self):
        errores = {}
        if (self.latitud is None) != (self.longitud is None):
            errores["longitud" if self.latitud is not None else "latitud"] = "Indica latitud y longitud juntas, o ninguna."
        direccion = (self.direccion or "").strip()
        if direccion and self.servicio_id and self.distrito_id:
            repetida = SedeServicioTurista.objects.filter(
                servicio_id=self.servicio_id, distrito_id=self.distrito_id, direccion__iexact=direccion,
            ).exclude(pk=self.pk).exists()
            if repetida:
                errores["direccion"] = "Esta entidad ya tiene una sede con la misma dirección en este distrito."

        src, error = mapas_sede.validar_embed(self.embed_maps)
        if error:
            errores["embed_maps"] = error
        elif src:
            self.embed_maps = mapas_sede.iframe_canonico(src)  # normalizado: solo atributos permitidos
        url, tipo, error = mapas_sede.validar_maps_url(self.maps_url)
        if error:
            errores["maps_url"] = error
        else:
            self.maps_url = url
        if not errores.keys() & {"embed_maps", "maps_url", "longitud"}:
            admin = (coord_a_texto(self.latitud), coord_a_texto(self.longitud)) if self.latitud is not None and self.longitud is not None else None
            hay_conflicto, mensajes, _misma = mapas_sede.evaluar_conflictos(src, url, tipo, admin)
            if hay_conflicto:  # contradicción real entre fuentes: no se guarda como «verificada»
                errores["maps_url"] = mensajes

        problemas = horarios.validar_estructura(self.horario)
        if not problemas and self.horario and self.disponibilidad not in ("horario", "emergencia"):
            problemas = ["El horario por bloques solo se usa con «Horario específico» o «Emergencia»."]
            errores["disponibilidad"] = problemas[0]
        elif problemas:
            errores[NON_FIELD_ERRORS] = problemas
        if errores:
            raise ValidationError(errores)

    def _regenerar_horario(self, update_fields):
        """Texto ES/EN desde el JSON, solo si el horario cambió (o aún no hay texto).
        No corre con QuerySet.update()/bulk_*: esas rutas no pasan por save()."""
        if not self.horario or (update_fields is not None and "horario" not in update_fields):
            return False
        cambio = (
            self._state.adding or self.horario != self._horario_orig
            or not self.horario_atencion_es or not self.horario_atencion_en
        )
        if cambio:
            self.horario_atencion_es = horarios.generar(self.horario, "es")
            self.horario_atencion_en = horarios.generar(self.horario, "en")
        return cambio

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generar_slug()
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "slug"}
        if self._regenerar_horario(kwargs.get("update_fields")) and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "horario_atencion_es", "horario_atencion_en"}
        super().save(*args, **kwargs)
        self._horario_orig = copy.deepcopy(self.horario)


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
    sede = models.ForeignKey(
        SedeServicioTurista, related_name="contactos", on_delete=models.CASCADE, null=True, blank=True,
        help_text="Vacío = contacto general de la entidad; con sede = contacto solo de ese local.",
    )
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
            # ponytail: MariaDB no crea restricciones condicionales; la regla real
            # (un principal por tipo y por sede/entidad) se valida en clean().
            models.UniqueConstraint(
                fields=["servicio", "sede", "tipo_contacto"],
                condition=Q(es_principal=True),
                name="unique_contacto_principal_tipo_sede_servicio_turista"
            )
        ]

    def __str__(self):
        if self.etiqueta:
            return f"{self.etiqueta} - {self.valor}"
        return f"{self.get_tipo_contacto_display()} - {self.valor}"

    def clean(self):
        if self.sede_id:
            if self.servicio_id and self.sede.servicio_id != self.servicio_id:
                raise ValidationError({"sede": "La sede no pertenece a la entidad de este contacto."})
        servicio_id = self.servicio_id or (self.sede.servicio_id if self.sede_id else None)
        if not servicio_id:
            return
        errores = {}
        valor = (self.valor or "").strip()
        if valor and ContactoServicioTurista.objects.filter(servicio_id=servicio_id, valor=valor).exclude(pk=self.pk).exists():
            errores["valor"] = ("Este contacto ya está registrado en la entidad. "
                                "Si es común a varias sedes, regístralo una sola vez como contacto general.")
        if self.es_principal and ContactoServicioTurista.objects.filter(
            servicio_id=servicio_id, sede_id=self.sede_id, tipo_contacto=self.tipo_contacto, es_principal=True,
        ).exclude(pk=self.pk).exists():
            errores["es_principal"] = "Ya existe un contacto principal de este tipo en este mismo nivel (entidad o sede)."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        if self.sede_id and not self.servicio_id:
            self.servicio_id = self.sede.servicio_id
        super().save(*args, **kwargs)


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
