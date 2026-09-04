from django.contrib import admin
from django.utils import timezone

from .models import (
    MES_CHOICES, CategoriaEvento, Evento, ImagenEvento, RecomendacionEvento, TagExperiencia,
    ocurrencia_pascua_relevante, ocurrencia_relativa_relevante,
)

_MESES_NOMBRE = dict(MES_CHOICES)
_ORDEN_SEMANA_NOMBRE = dict(Evento.ORDEN_SEMANA_CHOICES)
_DIA_SEMANA_NOMBRE = dict(Evento.DIA_SEMANA_CHOICES)
_PASCUA_NOMBRE = dict(Evento.PASCUA_OFFSET_CHOICES)
_MESES_ABREV = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


def _regla_relativa_texto(obj):
    orden = _ORDEN_SEMANA_NOMBRE.get(obj.orden_semana_relativa, "").lower()
    dia_semana = _DIA_SEMANA_NOMBRE.get(obj.dia_semana_relativa, "").lower()
    mes = _MESES_NOMBRE.get(obj.mes_relativa, "").lower()
    texto = f"{orden} {dia_semana}".strip().capitalize()
    if obj.dia_ancla_relativa:
        return f"{texto} después del {obj.dia_ancla_relativa} de {mes}"
    return f"{texto} de {mes}"


def _fecha_abreviada(fecha):
    return f"{fecha.day} {_MESES_ABREV.get(fecha.month, '')} {fecha.year}"


def _dia_mes_abreviado(dia, mes):
    return f"{dia} {_MESES_ABREV.get(mes, '')}".strip()


@admin.register(CategoriaEvento)
class CategoriaEventoAdmin(admin.ModelAdmin):
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


@admin.register(TagExperiencia)
class TagExperienciaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "icono_bootstrap", "activo"]
    search_fields = ["nombre"]
    list_filter = ["activo"]
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ["creado", "actualizado"]
    ordering = ["nombre"]


class ImagenEventoInline(admin.TabularInline):
    model = ImagenEvento
    extra = 0
    fields = ["imagen", "titulo", "texto_alt", "orden", "activo"]


class RecomendacionEventoInline(admin.TabularInline):
    model = RecomendacionEvento
    extra = 0
    fields = ["orden", "titulo", "descripcion", "icono_archivo", "icono_bootstrap", "activo"]
    ordering = ["orden", "id"]


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = [
        "nombre", "categoria_principal", "fecha_resumen",
        "modalidad", "distrito", "tipo_costo", "rango_precios_soles",
        "estado", "destacado", "activo"
    ]
    search_fields = [
        "nombre", "descripcion_corta", "descripcion", "organizador",
        "lugar", "direccion", "referencia", "distrito__nombre_oficial",
        "localidad__nombre", "categoria_principal__nombre", "categorias_secundarias__nombre"
    ]
    list_filter = [
        "activo", "destacado", "estado", "tipo_fecha", "tipo_ubicacion",
        "categoria_principal", "categorias_secundarias",
        "tipo_costo", "modalidad",
        "distrito__provincia__departamento", "distrito__provincia", "distrito"
    ]
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ["categoria_principal", "provincia", "distrito", "localidad"]
    filter_horizontal = ["categorias_secundarias", "tags_experiencia"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["nombre"]
    inlines = [ImagenEventoInline, RecomendacionEventoInline]

    class Media:
        js = ("assets/js/eventos-admin.js",)

    fieldsets = (
        ("Información principal", {
            "fields": (
                "categoria_principal", "categorias_secundarias", "tags_experiencia",
                "nombre", "slug", "descripcion_corta", "descripcion", "contexto_cultural",
            )
        }),
        ("Fecha", {
            "fields": (
                "tipo_fecha",
                "fecha_inicio", "fecha_fin",
                "dia_inicio_anual", "mes_inicio_anual", "dia_fin_anual", "mes_fin_anual",
                "orden_semana_relativa", "dia_semana_relativa", "mes_relativa", "dia_ancla_relativa",
                "offset_dias_pascua",
                "mes_aproximado", "anio_aproximado",
            ),
            "description": (
                "Los campos visibles dependen del tipo de fecha elegido. "
                "\"Exacta\" es un único día (sin fecha de fin); para varios días usa \"Rango\"."
            ),
        }),
        ("Horario", {
            "fields": ("tipo_horario", "hora_inicio", "hora_fin")
        }),
        ("Estado", {
            "fields": ("estado",)
        }),
        ("Ubicación", {
            "fields": (
                "tipo_ubicacion", "provincia", "distrito", "localidad", "descripcion_ubicacion",
                "lugar", "direccion", "referencia", "latitud", "longitud",
            ),
            "description": (
                "Para \"Ámbito general\": deja provincia y distrito vacíos para toda la Región Huánuco, "
                "indica solo provincia para ámbito provincial, o solo distrito para ámbito distrital."
            ),
        }),
        ("Costos", {
            "fields": ("tipo_costo", "precio_desde", "precio_hasta")
        }),
        ("Organización y contacto", {
            "fields": (
                "organizador", "telefono", "whatsapp", "correo",
                "sitio_web", "facebook", "instagram"
            )
        }),
        ("Información útil", {
            "fields": ("recomendaciones",)
        }),
        ("Legado", {
            "fields": ("publico_objetivo",),
            "classes": ("collapse",),
            "description": "Campo antiguo, ya no alimenta \"Ideal para\" ni los filtros públicos. Usa Tags de experiencia.",
        }),
        ("Multimedia", {
            "fields": ("imagen_principal", "texto_alt_imagen")
        }),
        ("Control interno (no público)", {
            "fields": ("notas", "url_fuente", "fecha_verificacion"),
            "classes": ("collapse",),
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

    def fecha_resumen(self, obj):
        if obj.tipo_fecha == "exacta":
            return _fecha_abreviada(obj.fecha_inicio) if obj.fecha_inicio else "-"

        if obj.tipo_fecha == "rango":
            if obj.fecha_inicio and obj.fecha_fin:
                return f"{_fecha_abreviada(obj.fecha_inicio)} – {_fecha_abreviada(obj.fecha_fin)}"
            return "-"

        if obj.tipo_fecha == "anual_fija":
            if not (obj.dia_inicio_anual and obj.mes_inicio_anual):
                return "-"
            inicio = _dia_mes_abreviado(obj.dia_inicio_anual, obj.mes_inicio_anual)
            if obj.dia_fin_anual and obj.mes_fin_anual:
                fin = _dia_mes_abreviado(obj.dia_fin_anual, obj.mes_fin_anual)
                return f"{inicio} – {fin} · Cada año"
            return f"{inicio} · Cada año"

        if obj.tipo_fecha == "anual_relativa":
            if not (obj.orden_semana_relativa and obj.dia_semana_relativa is not None and obj.mes_relativa):
                return "-"
            ocurrencia, _fin, _en_curso = ocurrencia_relativa_relevante(
                obj.orden_semana_relativa, obj.dia_semana_relativa,
                obj.mes_relativa, obj.dia_ancla_relativa, timezone.localdate(),
            )
            return f"{_regla_relativa_texto(obj)} · ocurrencia: {_fecha_abreviada(ocurrencia)}"

        if obj.tipo_fecha == "pascua_relativa":
            if obj.offset_dias_pascua is None:
                return "-"
            ocurrencia, _fin, _en_curso = ocurrencia_pascua_relevante(obj.offset_dias_pascua, timezone.localdate())
            nombre_dia = _PASCUA_NOMBRE.get(obj.offset_dias_pascua, "")
            return f"{nombre_dia} · ocurrencia: {_fecha_abreviada(ocurrencia)}"

        if obj.tipo_fecha == "mes_aproximado":
            nombre_mes = _MESES_NOMBRE.get(obj.mes_aproximado, "")
            anio = obj.anio_aproximado or ""
            return f"{nombre_mes} {anio} · Fecha por confirmar".strip()

        return "Fecha por confirmar"

    fecha_resumen.short_description = "Fecha"


@admin.register(ImagenEvento)
class ImagenEventoAdmin(admin.ModelAdmin):
    list_display = ["evento", "titulo", "orden", "activo", "creado"]
    search_fields = ["evento__nombre", "titulo", "texto_alt"]
    list_filter = ["activo", "evento"]
    autocomplete_fields = ["evento"]
    ordering = ["evento__nombre", "orden", "id"]
    list_per_page = 25


@admin.register(RecomendacionEvento)
class RecomendacionEventoAdmin(admin.ModelAdmin):
    list_display = ["evento", "titulo", "orden", "activo", "actualizado"]
    search_fields = ["evento__nombre", "titulo", "descripcion"]
    list_filter = ["activo", "evento"]
    autocomplete_fields = ["evento"]
    ordering = ["evento__nombre", "orden", "id"]
    list_per_page = 25
