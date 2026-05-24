from django.contrib import admin
from .models import (
    CategoriaEstablecimiento, 
    ServicioEstablecimiento,
    Establecimiento, 
    SucursalEstablecimiento,
    ImagenEstablecimiento,
    RecomendacionEstablecimiento,
    ContactoSucursalEstablecimiento
)

@admin.register(CategoriaEstablecimiento)
class CategoriaEstablecimientoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo_icono", "icono_bootstrap", "activo", "creado")
    ordering = ("nombre",)
    search_fields = ("nombre", "descripcion", "icono_bootstrap")
    list_filter = ("activo", "tipo_icono")
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ("creado", "actualizado")
    fieldsets = (
        ("Información principal", {
            "fields": ("nombre", "slug", "descripcion")
        }),
        ("Iconografía", {
            "fields": ("tipo_icono", "icono_bootstrap", "icono_archivo")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )

@admin.register(ServicioEstablecimiento)
class ServicioEstablecimientoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "aplica_a", "tipo_icono", "icono_bootstrap", "activo", "creado")
    ordering = ("nombre",)
    search_fields = ("nombre", "descripcion", "icono_bootstrap")
    list_filter = ("activo", "aplica_a", "tipo_icono")
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ("creado", "actualizado")
    fieldsets = (
        ("Información principal", {
            "fields": ("nombre", "slug", "descripcion", "aplica_a")
        }),
        ("Iconografía", {
            "fields": ("tipo_icono", "icono_bootstrap", "icono_archivo")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )

class SucursalEstablecimientoInline(admin.StackedInline):
    model = SucursalEstablecimiento
    extra = 0
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ("distrito", "localidad")

    fieldsets = (
        ("Datos de la sucursal", {
            "fields": (
                ("nombre", "slug"),
                ("es_principal", "activo"),
            )
        }),
        ("Ubicación", {
            "fields": (
                ("distrito", "localidad"),
                "direccion",
                "referencia",
                ("latitud", "longitud"),
            )
        }),
        ("Contacto rápido", {
            "fields": (
                ("telefono", "whatsapp"),
                "correo",
                "horario_atencion",
            )
        }),
    )

class ImagenEstablecimientoInline(admin.TabularInline):
    model = ImagenEstablecimiento
    extra = 1
    fields = ("imagen", "titulo", "texto_alt", "orden", "activo")

class RecomendacionEstablecimientoInline(admin.TabularInline):
    model = RecomendacionEstablecimiento
    extra = 1
    max_num = 3
    fields = ("orden", "nombre", "imagen", "icono_archivo", "activo")
    ordering = ("orden", "id")
    verbose_name = "Recomendación Top 3"
    verbose_name_plural = "Recomendaciones Top 3"

class ContactoSucursalEstablecimientoInline(admin.TabularInline):
    model = ContactoSucursalEstablecimiento
    extra = 1
    fields = ("tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo")

@admin.register(Establecimiento)
class EstablecimientoAdmin(admin.ModelAdmin):
    list_display = (
        "nombre", "tipo", "categoria_principal",
        "total_sucursales", "sucursal_principal",
        "rango_precio", "rango_precios_soles", "total_recomendaciones", "destacado", "activo"
    )
    # list_editable = ("destacado", "activo")
    ordering = ("tipo", "nombre")
    search_fields = (
        "nombre", "descripcion_corta", "descripcion",
        "categoria_principal__nombre", "categorias_secundarias__nombre",
        "servicios__nombre", "recomendaciones__nombre", "sucursales__nombre",
        "sucursales__direccion", "sucursales__distrito__nombre_oficial",
        "sucursales__localidad__nombre"
    )
    list_filter = (
        "tipo", "categoria_principal", "categorias_secundarias",
        "servicios", "rango_precio", "destacado", "activo",
        "sucursales__distrito__provincia__departamento",
        "sucursales__distrito__provincia", "sucursales__distrito"
    )
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ("categoria_principal",)
    filter_horizontal = ("categorias_secundarias", "servicios")
    readonly_fields = ("creado", "actualizado")
    inlines = [SucursalEstablecimientoInline, ImagenEstablecimientoInline, RecomendacionEstablecimientoInline]
    
    fieldsets = (
        ("Información principal", {
            "fields": (
                "tipo", "categoria_principal", "categorias_secundarias",
                "servicios", "nombre", "slug", "descripcion_corta", "descripcion"
            )
        }),
        ("Contacto general y redes", {
            "fields": ("telefono", "whatsapp", "correo", "sitio_web", "facebook", "instagram")
        }),
        ("Carta digital (solo restaurantes)", {
            "fields": ("carta_pdf", "carta_url"),
            "description": "Opcional. Si se carga un PDF o URL, el botón Ver carta se abrirá en una nueva pestaña."
        }),
        ("Precios", {
            "fields": ("rango_precio", "precio_desde", "precio_hasta")
        }),
        ("Multimedia", {
            "fields": ("imagen_principal", "texto_alt_imagen")
        }),
        ("Configuración", {
            "fields": ("destacado", "activo", "creado", "actualizado")
        }),
    )

    def total_sucursales(self, obj):
        return obj.sucursales.count()
    total_sucursales.short_description = "Sucursales"

    def total_recomendaciones(self, obj):
        return obj.recomendaciones.count()
    total_recomendaciones.short_description = "Recomendaciones"

    def sucursal_principal(self, obj):
        sucursal = obj.sucursales.filter(es_principal=True).first()
        return sucursal.nombre if sucursal else "-"
    sucursal_principal.short_description = "Sucursal principal"

    def rango_precios_soles(self, obj):
        if obj.precio_desde and obj.precio_hasta:
            return f"S/ {obj.precio_desde} - S/ {obj.precio_hasta}"
        if obj.precio_desde:
            return f"Desde S/ {obj.precio_desde}"
        if obj.precio_hasta:
            return f"Hasta S/ {obj.precio_hasta}"
        return "-"
    rango_precios_soles.short_description = "Rango en soles"


@admin.register(SucursalEstablecimiento)
class SucursalEstablecimientoAdmin(admin.ModelAdmin):
    list_display = (
        "establecimiento", "nombre", "distrito",
        "localidad", "es_principal", "activo"
    )
    # list_editable = ("es_principal", "activo")
    ordering = (
        "establecimiento__nombre",
        "-es_principal",
        "nombre",
    )
    search_fields = (
        "establecimiento__nombre", "nombre", "direccion",
        "referencia", "distrito__nombre_oficial", "localidad__nombre"
    )
    list_filter = (
        "activo", "es_principal",
        "distrito__provincia__departamento",
        "distrito__provincia", "distrito"
    )
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ("establecimiento", "distrito", "localidad")
    readonly_fields = ("creado", "actualizado")
    inlines = [ContactoSucursalEstablecimientoInline]
    
    fieldsets = (
        ("Establecimiento", {
            "fields": ("establecimiento", "nombre", "slug", "es_principal")
        }),
        ("Ubicación", {
            "fields": ("distrito", "localidad", "direccion", "referencia", "latitud", "longitud")
        }),
        ("Contacto", {
            "fields": ("telefono", "whatsapp", "correo", "horario_atencion")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )

@admin.register(ImagenEstablecimiento)
class ImagenEstablecimientoAdmin(admin.ModelAdmin):
    list_display = ("establecimiento", "titulo", "orden", "activo", "creado")
    # list_editable = ("orden", "activo")
    ordering = (
        "establecimiento__nombre",
        "orden",
        "id",
    )
    search_fields = (
        "establecimiento__nombre",
        "titulo",
        "texto_alt",
    )
    list_filter = (
        "activo",
        "establecimiento",
    )
    autocomplete_fields = (
        "establecimiento",
    )
    list_per_page = 25


@admin.register(RecomendacionEstablecimiento)
class RecomendacionEstablecimientoAdmin(admin.ModelAdmin):
    list_display = ("establecimiento", "orden", "nombre", "tiene_imagen", "tiene_icono", "activo", "creado")
    ordering = ("establecimiento__nombre", "orden", "id")
    search_fields = ("establecimiento__nombre", "nombre")
    list_filter = ("activo", "orden", "establecimiento__tipo")
    autocomplete_fields = ("establecimiento",)
    readonly_fields = ("creado", "actualizado")
    list_per_page = 25

    fieldsets = (
        ("Establecimiento", {
            "fields": ("establecimiento",)
        }),
        ("Recomendación", {
            "fields": ("orden", "nombre", "imagen", "icono_archivo")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )

    def tiene_imagen(self, obj):
        return "Sí" if obj.imagen else "No"
    tiene_imagen.short_description = "Imagen"

    def tiene_icono(self, obj):
        return "Sí" if obj.icono_archivo else "No"
    tiene_icono.short_description = "Ícono alojamiento"

@admin.register(ContactoSucursalEstablecimiento)
class ContactoSucursalEstablecimientoAdmin(admin.ModelAdmin):
    list_display = ("sucursal", "tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo")
    # list_editable = ("es_principal", "orden", "activo")
    ordering = (
        "sucursal__establecimiento__nombre",
        "sucursal__nombre",
        "orden",
        "id",
    )
    search_fields = ("sucursal__establecimiento__nombre", "sucursal__nombre", "etiqueta", "valor")
    list_filter = ("activo", "es_principal", "tipo_contacto", "sucursal__establecimiento__tipo")
    autocomplete_fields = ("sucursal",)
    readonly_fields = ("creado", "actualizado")

    fieldsets = (
        ("Sucursal", {
            "fields": ("sucursal",)
        }),
        ("Contacto", {
            "fields": ("tipo_contacto", "etiqueta", "valor", "es_principal", "orden")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )
