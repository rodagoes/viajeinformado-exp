from django.contrib import admin
from .models import (
    CategoriaServicioTurista,
    ServicioTurista,
    ContactoServicioTurista,
    ImagenServicioTurista
)

@admin.register(CategoriaServicioTurista)
class CategoriaServicioTuristaAdmin(admin.ModelAdmin):
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


class ContactoServicioTuristaInline(admin.TabularInline):
    model = ContactoServicioTurista
    extra = 0
    fields = ["tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo"]


class ImagenServicioTuristaInline(admin.TabularInline):
    model = ImagenServicioTurista
    extra = 0
    fields = ["imagen", "titulo", "texto_alt", "orden", "activo"]


@admin.register(ServicioTurista)
class ServicioTuristaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "categoria_principal", "distrito", "disponibilidad", "tipo_atencion", "telefono", "destacado", "activo"]
    search_fields = [
        "nombre", "descripcion_corta", "descripcion", "direccion", 
        "referencia", "telefono", "whatsapp", "correo", 
        "distrito__nombre_oficial", "localidad__nombre", 
        "categoria_principal__nombre", "categorias_secundarias__nombre", 
        "contactos__valor", "contactos__etiqueta"
    ]
    list_filter = [
        "activo", "destacado", "categoria_principal", "categorias_secundarias", 
        "disponibilidad", "tipo_atencion", 
        "distrito__provincia__departamento", "distrito__provincia", "distrito"
    ]
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ["categoria_principal", "distrito", "localidad"]
    filter_horizontal = ["categorias_secundarias"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["categoria_principal__nombre", "nombre"]
    inlines = [ContactoServicioTuristaInline, ImagenServicioTuristaInline]

    fieldsets = (
        ("Información principal", {
            "fields": (
                "categoria_principal", "categorias_secundarias", 
                "nombre", "slug", "descripcion_corta", "descripcion"
            )
        }),
        ("Ubicación", {
            "fields": (
                "distrito", "localidad", "direccion",
                "referencia", "latitud", "longitud"
            )
        }),
        ("Google Maps (precisión exacta)", {
            "description": (
                "Rellena estos campos solo si el servicio aparece en Google Maps. "
                "Permiten mostrar el pin con el nombre real del negocio y que los botones "
                "'Abrir mapa' y 'Cómo llegar' apunten a la ficha exacta. "
                "Si el local no aparece en Google Maps, déjalos vacíos y se usarán las coordenadas o la dirección."
            ),
            "fields": ("embed_maps", "maps_url"),
            "classes": ("collapse",),
        }),
        ("Atención", {
            "fields": (
                "tipo_atencion", "disponibilidad", "horario_atencion"
            )
        }),
        ("Contacto general y redes", {
            "fields": (
                "telefono", "whatsapp", "correo", 
                "sitio_web", "facebook", "instagram"
            )
        }),
        ("Información útil", {
            "fields": ("recomendaciones", "notas")
        }),
        ("Multimedia", {
            "fields": ("imagen_principal", "texto_alt_imagen")
        }),
        ("Configuración", {
            "fields": ("destacado", "activo", "creado", "actualizado")
        }),
    )


@admin.register(ContactoServicioTurista)
class ContactoServicioTuristaAdmin(admin.ModelAdmin):
    list_display = ["servicio", "tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo"]
    search_fields = ["servicio__nombre", "etiqueta", "valor"]
    list_filter = ["activo", "es_principal", "tipo_contacto", "servicio__categoria_principal"]
    autocomplete_fields = ["servicio"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["servicio__nombre", "orden", "id"]

    fieldsets = (
        ("Servicio", {
            "fields": ("servicio",)
        }),
        ("Contacto", {
            "fields": ("tipo_contacto", "etiqueta", "valor", "es_principal", "orden")
        }),
        ("Configuración", {
            "fields": ("activo", "creado", "actualizado")
        }),
    )



# ImagenServicioTurista no se registra como entrada independiente: la UI de
# Servicios útiles no usa galería, solo ServicioTurista.imagen_principal.
# El modelo, la tabla y los datos existentes se conservan; se sigue editando
# desde el inline de ServicioTuristaAdmin (ImagenServicioTuristaInline).
