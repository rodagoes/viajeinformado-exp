from django.db import models

class Departamento(models.Model):
    nombre_oficial = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    codigo_inei = models.CharField(max_length=2, unique=True, null=True, blank=True)
    activo = models.BooleanField(default=True, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Departamento"
        verbose_name_plural = "Departamentos"
        ordering = ["nombre_oficial"]

    def __str__(self):
        return self.nombre_oficial


class Provincia(models.Model):
    departamento = models.ForeignKey(Departamento, related_name="provincias", on_delete=models.PROTECT)
    nombre_oficial = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    codigo_inei = models.CharField(max_length=4, unique=True, null=True, blank=True)
    capital = models.CharField(max_length=120, blank=True)
    superficie_km2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    altitud_m = models.PositiveIntegerField(null=True, blank=True, help_text="Altitud de la capital provincial, en msnm.")
    activo = models.BooleanField(default=True, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Provincia"
        verbose_name_plural = "Provincias"
        ordering = ["departamento__nombre_oficial", "nombre_oficial"]
        constraints = [
            models.UniqueConstraint(fields=['departamento', 'nombre_oficial'], name='unique_provincia_nombre_departamento'),
            models.UniqueConstraint(fields=['departamento', 'slug'], name='unique_provincia_slug_departamento'),
        ]

    def __str__(self):
        return f"{self.nombre_oficial} - {self.departamento.nombre_oficial}"


class Distrito(models.Model):
    provincia = models.ForeignKey(Provincia, related_name="distritos", on_delete=models.PROTECT)
    nombre_oficial = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    codigo_inei = models.CharField(max_length=6, unique=True)
    codigo_api = models.CharField(max_length=20, blank=True)
    api_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    activo = models.BooleanField(default=True, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Distrito"
        verbose_name_plural = "Distritos"
        ordering = ["provincia__departamento__nombre_oficial", "provincia__nombre_oficial", "nombre_oficial"]
        constraints = [
            models.UniqueConstraint(fields=['provincia', 'nombre_oficial'], name='unique_distrito_nombre_provincia'),
            models.UniqueConstraint(fields=['provincia', 'slug'], name='unique_distrito_slug_provincia'),
        ]

    def __str__(self):
        return f"{self.nombre_oficial} - {self.provincia.nombre_oficial}"


class Localidad(models.Model):
    TIPO_CHOICES = [
        ("Capital distrital", "Capital distrital"),
        ("Ciudad", "Ciudad"),
        ("Centro poblado", "Centro poblado"),
        ("Zona", "Zona"),
        ("Sector", "Sector"),
        ("Referencia", "Referencia"),
    ]

    distrito = models.ForeignKey(Distrito, related_name="localidades", on_delete=models.PROTECT)
    nombre = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160)
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    descripcion = models.TextField(blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    activo = models.BooleanField(default=True, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Localidad"
        verbose_name_plural = "Localidades"
        ordering = [
            "distrito__provincia__departamento__nombre_oficial",
            "distrito__provincia__nombre_oficial",
            "distrito__nombre_oficial",
            "nombre"
        ]
        constraints = [
            models.UniqueConstraint(fields=['distrito', 'nombre'], name='unique_localidad_nombre_distrito'),
            models.UniqueConstraint(fields=['distrito', 'slug'], name='unique_localidad_slug_distrito'),
        ]

    def __str__(self):
        return f"{self.nombre} - {self.distrito.nombre_oficial}"
