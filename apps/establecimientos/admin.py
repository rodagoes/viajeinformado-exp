from django.contrib import admin
from modeltranslation.admin import TranslationAdmin, TranslationStackedInline, TranslationTabularInline
from .models import (
    CategoriaEstablecimiento,
    ServicioEstablecimiento,
    Establecimiento,
    SucursalEstablecimiento,
    ImagenEstablecimiento,
    RecomendacionEstablecimiento,
    ContactoSucursalEstablecimiento
)
from apps.gastronomia.models import PlatoEstablecimiento
from apps.ubicaciones.admin_filtros import DistritoDependienteFilter, ProvinciaDependienteFilter

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — CategoriaEstablecimientoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
CATEGORIA_ESTABLECIMIENTO_COLUMNAS_ADMIN = ("nombre", "tipo_icono", "icono_bootstrap", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
CATEGORIA_ESTABLECIMIENTO_FILTROS_ADMIN = ("activo", "tipo_icono")
# ==========================================================================


@admin.register(CategoriaEstablecimiento)
class CategoriaEstablecimientoAdmin(TranslationAdmin):
    list_display = CATEGORIA_ESTABLECIMIENTO_COLUMNAS_ADMIN
    ordering = ("nombre",)
    search_fields = ("nombre", "descripcion", "icono_bootstrap")
    list_filter = CATEGORIA_ESTABLECIMIENTO_FILTROS_ADMIN
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

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — ServicioEstablecimientoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
SERVICIO_ESTABLECIMIENTO_COLUMNAS_ADMIN = ("nombre", "aplica_a", "tipo_icono", "icono_bootstrap", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
SERVICIO_ESTABLECIMIENTO_FILTROS_ADMIN = ("activo", "aplica_a", "tipo_icono")
# ==========================================================================


@admin.register(ServicioEstablecimiento)
class ServicioEstablecimientoAdmin(TranslationAdmin):
    list_display = SERVICIO_ESTABLECIMIENTO_COLUMNAS_ADMIN
    ordering = ("nombre",)
    search_fields = ("nombre", "descripcion", "icono_bootstrap")
    list_filter = SERVICIO_ESTABLECIMIENTO_FILTROS_ADMIN
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

class SucursalEstablecimientoInline(TranslationStackedInline):
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
        ("Google Maps (precisión exacta)", {
            "description": (
                "Rellena estos campos solo si el establecimiento aparece en Google Maps. "
                "Permiten mostrar el pin con el nombre real del negocio y que los botones "
                "'Abrir mapa' y 'Cómo llegar' apunten a la ficha exacta. "
                "Si el local no aparece en Google Maps, déjalos vacíos y se usarán las coordenadas o la dirección."
            ),
            "fields": (
                "embed_maps",
                "maps_url",
            ),
            "classes": ("collapse",),
        }),
        ("Contacto rápido", {
            "fields": (
                ("telefono", "whatsapp"),
                "correo",
                "horario_atencion",
            )
        }),
    )

class ImagenEstablecimientoInline(TranslationTabularInline):
    model = ImagenEstablecimiento
    extra = 1
    fields = ("imagen", "titulo", "texto_alt", "orden", "activo")

class RecomendacionEstablecimientoInline(TranslationTabularInline):
    model = RecomendacionEstablecimiento
    extra = 1
    max_num = 3
    fields = ("orden", "nombre", "imagen", "icono_archivo", "plato_tipico", "activo")
    autocomplete_fields = ("plato_tipico",)
    ordering = ("orden", "id")
    verbose_name = "Recomendación Top 3"
    verbose_name_plural = "Recomendaciones Top 3"


class PlatoEstablecimientoInline(admin.TabularInline):
    model = PlatoEstablecimiento
    extra = 1
    fields = ("plato", "activo")
    autocomplete_fields = ("plato",)
    verbose_name = "Plato típico disponible"
    verbose_name_plural = "PLATOS TÍPICOS DISPONIBLES"

class ContactoSucursalEstablecimientoInline(TranslationTabularInline):
    model = ContactoSucursalEstablecimiento
    extra = 1
    fields = ("tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo")

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — EstablecimientoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
ESTABLECIMIENTO_COLUMNAS_ADMIN = (
    "nombre", "tipo", "categoria_principal",
    "total_sucursales", "sucursal_principal",
    "rango_precio", "rango_precios_soles", "total_recomendaciones", "destacado", "activo"
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
ESTABLECIMIENTO_FILTROS_ADMIN = (
    "tipo", "categoria_principal", "categorias_secundarias",
    "servicios", "rango_precio", "destacado", "activo",
    "sucursales__distrito__provincia__departamento",
    ("sucursales__distrito__provincia", ProvinciaDependienteFilter), ("sucursales__distrito", DistritoDependienteFilter)
)
# ==========================================================================


@admin.register(Establecimiento)
class EstablecimientoAdmin(TranslationAdmin):
    list_display = ESTABLECIMIENTO_COLUMNAS_ADMIN
    # list_editable = ("destacado", "activo")
    ordering = ("tipo", "nombre")
    search_fields = (
        "nombre", "descripcion_corta", "descripcion",
        "categoria_principal__nombre", "categorias_secundarias__nombre",
        "servicios__nombre", "recomendaciones__nombre", "sucursales__nombre",
        "sucursales__direccion", "sucursales__distrito__nombre_oficial",
        "sucursales__localidad__nombre"
    )
    list_filter = ESTABLECIMIENTO_FILTROS_ADMIN
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ("categoria_principal",)
    filter_horizontal = ("categorias_secundarias", "servicios")
    readonly_fields = ("creado", "actualizado")
    inlines = [
        SucursalEstablecimientoInline,
        ImagenEstablecimientoInline,
        RecomendacionEstablecimientoInline,
        PlatoEstablecimientoInline,
    ]

    def get_inline_instances(self, request, obj=None):
        inlines = super().get_inline_instances(request, obj)
        if obj is not None and obj.tipo != "restaurante":
            inlines = [i for i in inlines if not isinstance(i, PlatoEstablecimientoInline)]
        return inlines

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


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — SucursalEstablecimientoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
SUCURSAL_ESTABLECIMIENTO_COLUMNAS_ADMIN = (
    "establecimiento", "nombre", "distrito",
    "localidad", "es_principal", "activo"
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
SUCURSAL_ESTABLECIMIENTO_FILTROS_ADMIN = (
    "activo", "es_principal",
    "distrito__provincia__departamento",
    ("distrito__provincia", ProvinciaDependienteFilter), ("distrito", DistritoDependienteFilter)
)
# ==========================================================================


@admin.register(SucursalEstablecimiento)
class SucursalEstablecimientoAdmin(TranslationAdmin):
    list_display = SUCURSAL_ESTABLECIMIENTO_COLUMNAS_ADMIN
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
    list_filter = SUCURSAL_ESTABLECIMIENTO_FILTROS_ADMIN
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
        ("Google Maps (precisión exacta)", {
            "description": (
                "Rellena estos campos solo si el establecimiento aparece en Google Maps. "
                "Permiten mostrar el pin con el nombre real del negocio y que los botones "
                "'Abrir mapa' y 'Cómo llegar' apunten a la ficha exacta. "
                "Si el local no aparece en Google Maps, déjalos vacíos y se usarán las coordenadas o la dirección."
            ),
            "fields": ("embed_maps", "maps_url"),
            "classes": ("collapse",),
        }),
        ("Contacto", {
            "fields": ("telefono", "whatsapp", "correo", "horario_atencion")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — ImagenEstablecimientoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
IMAGEN_ESTABLECIMIENTO_COLUMNAS_ADMIN = ("establecimiento", "titulo", "orden", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
IMAGEN_ESTABLECIMIENTO_FILTROS_ADMIN = (
    "activo",
    "establecimiento",
)
# ==========================================================================


@admin.register(ImagenEstablecimiento)
class ImagenEstablecimientoAdmin(TranslationAdmin):
    list_display = IMAGEN_ESTABLECIMIENTO_COLUMNAS_ADMIN
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
    list_filter = IMAGEN_ESTABLECIMIENTO_FILTROS_ADMIN
    autocomplete_fields = (
        "establecimiento",
    )
    list_per_page = 25


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — RecomendacionEstablecimientoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
RECOMENDACION_ESTABLECIMIENTO_COLUMNAS_ADMIN = ("establecimiento", "orden", "nombre", "tiene_imagen", "tiene_icono", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
RECOMENDACION_ESTABLECIMIENTO_FILTROS_ADMIN = ("activo", "orden", "establecimiento__tipo")
# ==========================================================================


@admin.register(RecomendacionEstablecimiento)
class RecomendacionEstablecimientoAdmin(TranslationAdmin):
    list_display = RECOMENDACION_ESTABLECIMIENTO_COLUMNAS_ADMIN
    ordering = ("establecimiento__nombre", "orden", "id")
    search_fields = ("establecimiento__nombre", "nombre")
    list_filter = RECOMENDACION_ESTABLECIMIENTO_FILTROS_ADMIN
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

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — ContactoSucursalEstablecimientoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
CONTACTO_SUCURSAL_ESTABLECIMIENTO_COLUMNAS_ADMIN = ("sucursal", "tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
CONTACTO_SUCURSAL_ESTABLECIMIENTO_FILTROS_ADMIN = ("activo", "es_principal", "tipo_contacto", "sucursal__establecimiento__tipo")
# ==========================================================================


@admin.register(ContactoSucursalEstablecimiento)
class ContactoSucursalEstablecimientoAdmin(TranslationAdmin):
    list_display = CONTACTO_SUCURSAL_ESTABLECIMIENTO_COLUMNAS_ADMIN
    # list_editable = ("es_principal", "orden", "activo")
    ordering = (
        "sucursal__establecimiento__nombre",
        "sucursal__nombre",
        "orden",
        "id",
    )
    search_fields = ("sucursal__establecimiento__nombre", "sucursal__nombre", "etiqueta", "valor")
    list_filter = CONTACTO_SUCURSAL_ESTABLECIMIENTO_FILTROS_ADMIN
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
