from django.contrib import admin
from django.utils.html import format_html
from django.utils.text import Truncator

from .models import Favorito, Resena


class TipoRecursoFilter(admin.SimpleListFilter):
    title = "tipo de recurso"
    parameter_name = "tipo_recurso"

    def lookups(self, request, model_admin):
        return (
            ("establecimiento", "Establecimiento"),
            ("lugar", "Lugar turístico"),
        )

    def queryset(self, request, queryset):
        if self.value() == "establecimiento":
            return queryset.filter(establecimiento__isnull=False)
        if self.value() == "lugar":
            return queryset.filter(lugar_turistico__isnull=False)
        return queryset


def tipo_recurso(obj):
    return "Establecimiento" if obj.establecimiento_id else "Lugar turístico"
tipo_recurso.short_description = "Tipo"


@admin.register(Favorito)
class FavoritoAdmin(admin.ModelAdmin):
    list_display = ("usuario", "recurso", tipo_recurso, "creado")
    list_filter = (TipoRecursoFilter, "creado")
    search_fields = ("usuario__username", "establecimiento__nombre", "lugar_turistico__nombre")
    autocomplete_fields = ("usuario", "establecimiento", "lugar_turistico")
    readonly_fields = ("creado",)
    ordering = ("-creado",)


class TipoRecursoResenaFilter(admin.SimpleListFilter):
    title = "tipo de recurso"
    parameter_name = "tipo_recurso"

    def lookups(self, request, model_admin):
        return (
            ("restaurante", "Restaurante"),
            ("alojamiento", "Alojamiento"),
            ("lugar", "Lugar turístico"),
        )

    def queryset(self, request, queryset):
        valor = self.value()
        if valor == "restaurante":
            return queryset.filter(establecimiento__tipo="restaurante")
        if valor == "alojamiento":
            return queryset.filter(establecimiento__tipo="alojamiento")
        if valor == "lugar":
            return queryset.filter(lugar_turistico__isnull=False)
        return queryset


@admin.register(Resena)
class ResenaAdmin(admin.ModelAdmin):
    list_display = (
        "usuario", "recurso", "tipo_recurso_detallado",
        "valoracion_estrellas", "comentario_resumido", "estado_visual", "creado",
    )
    list_filter = ("estado", "valoracion", TipoRecursoResenaFilter, "creado")
    search_fields = ("usuario__username", "establecimiento__nombre", "lugar_turistico__nombre", "comentario")
    list_select_related = ("usuario", "establecimiento", "lugar_turistico")
    ordering = ("-creado",)
    actions = ["ocultar_resenas", "publicar_resenas"]
    readonly_fields = (
        "usuario", "establecimiento", "lugar_turistico",
        "valoracion", "comentario", "enlace_recurso_publico",
        "creado", "actualizado",
    )
    fieldsets = (
        ("Reseña", {"fields": (
            "usuario", "establecimiento", "lugar_turistico",
            "valoracion", "comentario", "enlace_recurso_publico",
            "creado", "actualizado",
        )}),
        ("Moderación", {"fields": ("estado",)}),
    )

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        # Paridad con las acciones bulk: el changeform individual solo
        # escribe "estado", sin disparar auto_now sobre "actualizado"
        # (que representa la última edición del propio usuario, no la
        # fecha de moderación).
        if change:
            obj.save(update_fields=["estado"])
            return
        super().save_model(request, obj, form, change)

    def tipo_recurso_detallado(self, obj):
        if obj.establecimiento_id:
            return obj.establecimiento.get_tipo_display()
        return "Lugar turístico"
    tipo_recurso_detallado.short_description = "Tipo"

    @admin.display(description="Valoración", ordering="valoracion")
    def valoracion_estrellas(self, obj):
        return f"{obj.valoracion} ★"

    def comentario_resumido(self, obj):
        return Truncator(obj.comentario).chars(60) if obj.comentario else "Sin comentario"
    comentario_resumido.short_description = "Comentario"

    @admin.display(description="Estado", ordering="estado")
    def estado_visual(self, obj):
        if obj.estado == Resena.ESTADO_PUBLICADO:
            return format_html('<span style="color:#15803d;">●</span> Publicado')
        return format_html('<span style="color:#b45309;">●</span> Oculto')

    def enlace_recurso_publico(self, obj):
        recurso = obj.recurso
        if recurso is None:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Ver recurso público ↗</a>',
            recurso.get_absolute_url(),
        )
    enlace_recurso_publico.short_description = "Recurso público"

    @admin.action(description="Ocultar reseñas seleccionadas", permissions=["change"])
    def ocultar_resenas(self, request, queryset):
        actualizadas = queryset.exclude(estado=Resena.ESTADO_OCULTO).update(estado=Resena.ESTADO_OCULTO)
        palabra = "reseña" if actualizadas == 1 else "reseñas"
        self.message_user(request, f"{actualizadas} {palabra} {'ocultada' if actualizadas == 1 else 'ocultadas'}.")

    @admin.action(description="Publicar reseñas seleccionadas", permissions=["change"])
    def publicar_resenas(self, request, queryset):
        actualizadas = queryset.exclude(estado=Resena.ESTADO_PUBLICADO).update(estado=Resena.ESTADO_PUBLICADO)
        palabra = "reseña" if actualizadas == 1 else "reseñas"
        self.message_user(request, f"{actualizadas} {palabra} {'publicada' if actualizadas == 1 else 'publicadas'}.")
