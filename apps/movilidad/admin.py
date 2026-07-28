from django.contrib import admin
from django.utils.html import format_html
from .models import (
    CategoriaMovilidad,
    ServicioMovilidad,
    OperadorMovilidad,
    RutaMovilidad,
    ImagenRutaMovilidad,
    TransportePublico,
    ConsejoMovilidad,
)

@admin.register(CategoriaMovilidad)
class CategoriaMovilidadAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo_icono", "icono_bootstrap", "activo", "creado"]
    search_fields = ["nombre", "descripcion", "icono_bootstrap"]
    list_filter = ["activo", "tipo_icono"]
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ["creado", "actualizado"]
    ordering = ["nombre"]

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


@admin.register(ServicioMovilidad)
class ServicioMovilidadAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo_icono", "icono_bootstrap", "activo", "creado"]
    search_fields = ["nombre", "descripcion", "icono_bootstrap"]
    list_filter = ["activo", "tipo_icono"]
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ["creado", "actualizado"]
    ordering = ["nombre"]

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


@admin.register(OperadorMovilidad)
class OperadorMovilidadAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo_operador", "distrito", "whatsapp", "destacado", "activo"]
    search_fields = [
        "nombre", "descripcion_corta", "descripcion", "telefono", 
        "whatsapp", "correo", "distrito__nombre_oficial", "localidad__nombre"
    ]
    list_filter = [
        "activo", "destacado", "tipo_operador", "servicios", 
        "distrito__provincia__departamento", "distrito__provincia", "distrito"
    ]
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ["distrito", "localidad"]
    filter_horizontal = ["servicios"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["tipo_operador", "nombre"]

    fieldsets = (
        ("Información principal", {
            "fields": (
                "tipo_operador", "servicios", "nombre", "slug", 
                "descripcion_corta", "descripcion"
            )
        }),
        ("Ubicación", {
            "fields": (
                "distrito", "localidad", "direccion", 
                "referencia", "latitud", "longitud"
            )
        }),
        ("Contacto y redes", {
            "fields": (
                "telefono", "whatsapp", "correo", 
                "sitio_web", "facebook", "instagram"
            )
        }),
        ("Multimedia", {
            "fields": ("imagen_principal", "texto_alt_imagen")
        }),
        ("Configuración", {
            "fields": ("destacado", "activo", "creado", "actualizado")
        }),
    )


class ImagenRutaMovilidadInline(admin.TabularInline):
    model = ImagenRutaMovilidad
    extra = 0
    fields = ["imagen", "titulo", "texto_alt", "orden", "activo"]


@admin.register(RutaMovilidad)
class RutaMovilidadAdmin(admin.ModelAdmin):
    list_display = [
        "nombre", "categoria_principal", "origen_texto", "destino_texto", 
        "duracion_estimada", "tipo_costo", "rango_precios_soles", "destacado", "activo"
    ]
    search_fields = [
        "nombre", "descripcion_corta", "descripcion", "origen_texto", 
        "destino_texto", "punto_partida", "punto_llegada", "indicaciones", 
        "origen_distrito__nombre_oficial", "origen_localidad__nombre", 
        "destino_distrito__nombre_oficial", "destino_localidad__nombre", 
        "categoria_principal__nombre", "categorias_secundarias__nombre", 
        "servicios__nombre", "operador__nombre"
    ]
    list_filter = [
        "activo", "destacado", "categoria_principal", "categorias_secundarias", 
        "servicios", "tipo_costo", "dificultad", "operador", 
        "origen_distrito__provincia__departamento", "origen_distrito__provincia", 
        "origen_distrito", "destino_distrito__provincia__departamento", 
        "destino_distrito__provincia", "destino_distrito"
    ]
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = [
        "categoria_principal", "operador", "origen_distrito", 
        "origen_localidad", "destino_distrito", "destino_localidad"
    ]
    filter_horizontal = ["categorias_secundarias", "servicios"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["nombre"]
    inlines = [ImagenRutaMovilidadInline]

    fieldsets = (
        ("Información principal", {
            "fields": (
                "categoria_principal", "categorias_secundarias", "servicios", 
                "operador", "nombre", "slug", "descripcion_corta", "descripcion"
            )
        }),
        ("Origen", {
            "fields": ("origen_distrito", "origen_localidad", "origen_texto")
        }),
        ("Destino", {
            "fields": ("destino_distrito", "destino_localidad", "destino_texto")
        }),
        ("Información de ruta", {
            "fields": (
                "punto_partida", "punto_llegada", "indicaciones", 
                "duracion_estimada", "distancia_km", "frecuencia", "horario_referencial"
            )
        }),
        ("Costos", {
            "fields": ("tipo_costo", "precio_desde", "precio_hasta")
        }),
        ("Información útil", {
            "fields": ("dificultad", "recomendaciones", "advertencias")
        }),
        ("Multimedia", {
            "fields": ("imagen_principal", "texto_alt_imagen")
        }),
        ("Configuración", {
            "fields": ("destacado", "activo", "creado", "actualizado")
        }),
    )

    def rango_precios_soles(self, obj):
        if obj.precio_desde and obj.precio_hasta:
            return f"S/ {obj.precio_desde} - S/ {obj.precio_hasta}"
        if obj.precio_desde:
            return f"Desde S/ {obj.precio_desde}"
        if obj.precio_hasta:
            return f"Hasta S/ {obj.precio_hasta}"
        return "-"
    
    rango_precios_soles.short_description = "Rango en soles"


@admin.register(ImagenRutaMovilidad)
class ImagenRutaMovilidadAdmin(admin.ModelAdmin):
    list_display = ["ruta", "titulo", "orden", "activo", "creado"]
    search_fields = ["ruta__nombre", "titulo", "texto_alt"]
    list_filter = ["activo", "ruta"]
    autocomplete_fields = ["ruta"]
    ordering = ["ruta__nombre", "orden", "id"]
    list_per_page = 25


@admin.register(TransportePublico)
class TransportePublicoAdmin(admin.ModelAdmin):
    list_display = [
        "miniatura",
        "nombre",
        "nombre_alternativo",
        "tarifa_minima",
        "orden",
        "activo",
    ]
    list_editable = ["tarifa_minima", "orden", "activo"]
    search_fields = ["nombre", "nombre_alternativo", "descripcion"]
    list_filter = ["activo"]
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ["creado", "actualizado", "vista_previa_imagen"]
    ordering = ["orden", "nombre"]

    fieldsets = (
        ("Información principal", {
            "fields": ("nombre", "slug", "nombre_alternativo", "descripcion")
        }),
        ("Fotografía", {
            "fields": ("imagen", "vista_previa_imagen", "texto_alt_imagen")
        }),
        ("Tarifa referencial", {
            "fields": ("tarifa_minima",)
        }),
        ("Configuración", {
            "fields": ("orden", "activo", "creado", "actualizado")
        }),
    )

    def miniatura(self, obj):
        if not obj.imagen:
            return "—"
        return format_html(
            '<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:6px;">',
            obj.imagen.url,
        )
    miniatura.short_description = ""

    def vista_previa_imagen(self, obj):
        if not obj.imagen:
            return "Sin fotografía cargada."
        return format_html(
            '<img src="{}" style="max-width:220px;border-radius:10px;">',
            obj.imagen.url,
        )
    vista_previa_imagen.short_description = "Vista previa"


@admin.register(ConsejoMovilidad)
class ConsejoMovilidadAdmin(admin.ModelAdmin):
    list_display = ["texto", "orden", "activo"]
    list_editable = ["orden", "activo"]
    search_fields = ["texto"]
    list_filter = ["activo"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["orden", "id"]
