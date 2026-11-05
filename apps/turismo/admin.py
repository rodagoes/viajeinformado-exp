from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
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


# Unidades del formulario de duración (no se guardan: solo convierten a minutos).
DURACION_UNIDADES = (("minutos", "Minutos", 1), ("horas", "Horas", 60), ("dias", "Días", 1440))
DURACION_FACTOR = {clave: factor for clave, _, factor in DURACION_UNIDADES}
DURACION_CAMPOS_MODELO = {
    "duracion_min_minutos": "duracion_minima",
    "duracion_max_minutos": "duracion_maxima",
}


class LugarTuristicoAdminForm(forms.ModelForm):
    """Duración de la visita con unidad (minutos/horas/días); persiste solo minutos."""

    duracion_minima = forms.IntegerField(label="Duración mínima", required=False)
    duracion_maxima = forms.IntegerField(label="Duración máxima (opcional)", required=False)
    duracion_unidad = forms.ChoiceField(
        label="Unidad",
        choices=[(clave, nombre) for clave, nombre, _ in DURACION_UNIDADES],
        initial="minutos",
        help_text="La unidad se aplica a ambos valores: si la cambias sin tocar los números, "
                  "cambia la duración guardada. Máximo 7 días.",
    )

    class Meta:
        model = LugarTuristico
        exclude = tuple(DURACION_CAMPOS_MODELO)  # las columnas en minutos no se editan directamente

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        minimo = self.instance.duracion_min_minutos
        if minimo:
            valores = [minimo] + ([self.instance.duracion_max_minutos] if self.instance.duracion_max_minutos else [])
            # Unidad más grande que divide exactamente todos los valores (ida y vuelta sin redondeos).
            unidad = next(c for c, _, f in reversed(DURACION_UNIDADES) if all(v % f == 0 for v in valores))
            factor = DURACION_FACTOR[unidad]
            self.initial["duracion_unidad"] = unidad
            self.initial["duracion_minima"] = minimo // factor
            if len(valores) > 1:
                self.initial["duracion_maxima"] = valores[1] // factor

    def clean(self):
        datos = super().clean()
        # Convierte a minutos y deja la validación de rangos a LugarTuristico.clean().
        factor = DURACION_FACTOR.get(datos.get("duracion_unidad"), 1)
        minimo, maximo = datos.get("duracion_minima"), datos.get("duracion_maxima")
        self.instance.duracion_min_minutos = None if minimo is None else minimo * factor
        self.instance.duracion_max_minutos = None if maximo is None else maximo * factor
        return datos

    def _update_errors(self, errors):
        # Los errores del modelo apuntan a las columnas en minutos; se muestran en los campos del formulario.
        if hasattr(errors, "error_dict"):
            errors = ValidationError({
                DURACION_CAMPOS_MODELO.get(campo, campo): lista
                for campo, lista in errors.error_dict.items()
            })
        super()._update_errors(errors)


@admin.register(LugarTuristico)
class LugarTuristicoAdmin(TranslationAdmin):
    form = LugarTuristicoAdminForm
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
                "dificultad", "recomendaciones", "como_llegar"
            )
        }),
        ("Duración de la visita", {
            "fields": (("duracion_minima", "duracion_maxima", "duracion_unidad"),),
            "description": "Duración estructurada (opcional). Se guarda en minutos. "
                           "Mientras no se use en el sitio, se sigue mostrando el texto anterior.",
        }),
        ("Texto anterior de duración (respaldo)", {
            "classes": ("collapse",),
            "fields": ("tiempo_visita_estimado",),
            "description": "Es el texto que se muestra actualmente en el sitio. Se conserva como respaldo "
                           "hasta que la duración estructurada se utilice en las cards, el detalle y el chatbot.",
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
