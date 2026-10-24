from django.contrib import admin
from modeltranslation.admin import TranslationAdmin, TranslationStackedInline, TranslationTabularInline
from .models import (
    CategoriaLugarTuristico,
    ServicioLugarTuristico,
    LugarTuristico,
    ImagenLugarTuristico,
    RecomendacionLugarTuristico,
)
from apps.ubicaciones.admin_filtros import DistritoDependienteFilter, ProvinciaDependienteFilter


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — CategoriaLugarTuristicoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
CATEGORIA_LUGAR_TURISTICO_COLUMNAS_ADMIN = ("nombre", "tipo_icono", "icono_bootstrap", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
CATEGORIA_LUGAR_TURISTICO_FILTROS_ADMIN = ("activo", "tipo_icono")
# ==========================================================================


@admin.register(CategoriaLugarTuristico)
class CategoriaLugarTuristicoAdmin(TranslationAdmin):
    list_display = CATEGORIA_LUGAR_TURISTICO_COLUMNAS_ADMIN
    search_fields = ("nombre", "descripcion", "icono_bootstrap")
    list_filter = CATEGORIA_LUGAR_TURISTICO_FILTROS_ADMIN
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ("creado", "actualizado")
    ordering = ("nombre",)

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
# CONFIGURACIÓN DEL LISTADO — ServicioLugarTuristicoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
SERVICIO_LUGAR_TURISTICO_COLUMNAS_ADMIN = ("nombre", "tipo_icono", "icono_bootstrap", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
SERVICIO_LUGAR_TURISTICO_FILTROS_ADMIN = ("activo", "tipo_icono")
# ==========================================================================


@admin.register(ServicioLugarTuristico)
class ServicioLugarTuristicoAdmin(TranslationAdmin):
    list_display = SERVICIO_LUGAR_TURISTICO_COLUMNAS_ADMIN
    search_fields = ("nombre", "descripcion", "icono_bootstrap")
    list_filter = SERVICIO_LUGAR_TURISTICO_FILTROS_ADMIN
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ("creado", "actualizado")
    ordering = ("nombre",)

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


class ImagenLugarTuristicoInline(TranslationStackedInline):
    model = ImagenLugarTuristico
    extra = 0
    ordering = ("orden", "id")
    classes = ("collapse",)
    fieldsets = (
        ("Configuración", {
            "fields": ("tipo_media", "orden", "activo"),
        }),
        ("Archivo o enlace", {
            "fields": ("imagen", "video_url", "video_archivo"),
            "description": "Usa solo el campo que corresponda al tipo: Imagen/GIF, Video externo o Video MP4.",
        }),
        ("Contenido visible", {
            "fields": ("titulo", "descripcion", "texto_alt"),
        }),
    )


class RecomendacionLugarTuristicoInline(TranslationTabularInline):
    model = RecomendacionLugarTuristico
    extra = 0
    fields = ("titulo", "descripcion", "icono_bootstrap", "orden", "activo")
    ordering = ("orden", "id")


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — LugarTuristicoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
LUGAR_TURISTICO_COLUMNAS_ADMIN = (
    "nombre", "categoria_principal", "distrito", "localidad",
    "tipo_costo", "rango_precios_soles", "dificultad", "destacado", "activo"
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
LUGAR_TURISTICO_FILTROS_ADMIN = (
    "activo", "destacado", "categoria_principal", "categorias_secundarias",
    "servicios", "tipo_costo", "dificultad",
    "distrito__provincia__departamento", ("distrito__provincia", ProvinciaDependienteFilter), ("distrito", DistritoDependienteFilter)
)
# ==========================================================================


@admin.register(LugarTuristico)
class LugarTuristicoAdmin(TranslationAdmin):
    list_display = LUGAR_TURISTICO_COLUMNAS_ADMIN
    search_fields = (
        "nombre", "descripcion_corta", "descripcion", "historia", "referencia",
        "distrito__nombre_oficial", "localidad__nombre",
        "categoria_principal__nombre", "categorias_secundarias__nombre",
        "servicios__nombre", "recomendaciones_items__titulo", "recomendaciones_items__descripcion"
    )
    list_filter = LUGAR_TURISTICO_FILTROS_ADMIN
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ("categoria_principal", "distrito", "localidad")
    filter_horizontal = ("categorias_secundarias", "servicios")
    readonly_fields = ("creado", "actualizado")
    ordering = ("nombre",)
    inlines = [ImagenLugarTuristicoInline, RecomendacionLugarTuristicoInline]

    fieldsets = (
        ("Información principal", {
            "fields": (
                "categoria_principal", "categorias_secundarias", "servicios",
                "nombre", "slug", "descripcion_corta", "descripcion", "historia"
            )
        }),
        ("Imagen histórica", {
            "fields": ("imagen_historia", "texto_alt_imagen_historia"),
            "description": "Úsalo para mostrar una imagen antigua o histórica junto al bloque Historia."
        }),
        ("Ubicación", {
            "fields": (
                "distrito", "localidad", "direccion", "referencia",
                "latitud", "longitud",
                "embed_maps", "maps_url",
            )
        }),
        ("Información para el turista", {
            "fields": (
                "horario_visita", "tipo_costo", "precio_desde", "precio_hasta",
                "tiempo_visita_estimado", "dificultad", "recomendaciones", "como_llegar"
            )
        }),
        ("Multimedia principal", {
            "fields": (
                "imagen_principal", "texto_alt_imagen"
            )
        }),
        ("Configuración", {
            "fields": (
                "destacado", "activo", "creado", "actualizado"
            )
        }),
    )

    def rango_precios_soles(self, obj):
        if obj.precio_desde and obj.precio_hasta:
            if obj.precio_desde == obj.precio_hasta:
                return f"S/ {obj.precio_desde}"
            return f"S/ {obj.precio_desde} - S/ {obj.precio_hasta}"
        if obj.precio_desde:
            return f"Desde S/ {obj.precio_desde}"
        if obj.precio_hasta:
            return f"Hasta S/ {obj.precio_hasta}"
        return "-"
    rango_precios_soles.short_description = "Rango en soles"


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — RecomendacionLugarTuristicoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
RECOMENDACION_LUGAR_TURISTICO_COLUMNAS_ADMIN = ("lugar", "titulo", "orden", "activo", "actualizado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
RECOMENDACION_LUGAR_TURISTICO_FILTROS_ADMIN = ("activo", "lugar")
# ==========================================================================


@admin.register(RecomendacionLugarTuristico)
class RecomendacionLugarTuristicoAdmin(TranslationAdmin):
    list_display = RECOMENDACION_LUGAR_TURISTICO_COLUMNAS_ADMIN
    search_fields = ("lugar__nombre", "titulo", "descripcion", "icono_bootstrap")
    list_filter = RECOMENDACION_LUGAR_TURISTICO_FILTROS_ADMIN
    autocomplete_fields = ("lugar",)
    ordering = ("lugar__nombre", "orden", "id")
    list_per_page = 25

    fieldsets = (
        ("Relación", {"fields": ("lugar", "orden", "activo")}),
        ("Contenido", {"fields": ("titulo", "descripcion", "icono_bootstrap")}),
    )


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — ImagenLugarTuristicoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
IMAGEN_LUGAR_TURISTICO_COLUMNAS_ADMIN = ("lugar", "tipo_media", "titulo", "orden", "activo", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
IMAGEN_LUGAR_TURISTICO_FILTROS_ADMIN = ("activo", "tipo_media", "lugar")
# ==========================================================================


@admin.register(ImagenLugarTuristico)
class ImagenLugarTuristicoAdmin(TranslationAdmin):
    list_display = IMAGEN_LUGAR_TURISTICO_COLUMNAS_ADMIN
    search_fields = ("lugar__nombre", "titulo", "descripcion", "texto_alt", "video_url", "video_archivo")
    list_filter = IMAGEN_LUGAR_TURISTICO_FILTROS_ADMIN
    autocomplete_fields = ("lugar",)
    ordering = ("lugar__nombre", "orden", "id")
    list_per_page = 25

    fieldsets = (
        ("Relación", {"fields": ("lugar", "tipo_media", "orden", "activo")}),
        ("Archivo o enlace", {
            "fields": ("imagen", "video_url", "video_archivo"),
            "description": "Usa solo el campo que corresponda al tipo elegido.",
        }),
        ("Contenido", {"fields": ("titulo", "descripcion", "texto_alt")}),
    )
