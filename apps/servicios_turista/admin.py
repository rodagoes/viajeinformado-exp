from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html
from modeltranslation.admin import TranslationAdmin, TranslationTabularInline

from .models import (
    CategoriaServicioTurista,
    ContactoServicioTurista,
    SedeServicioTurista,
    ServicioTurista,
)
from .forms import SedeAdminForm
from .services import horarios
from .services.contactos import clave_dedup


@admin.register(CategoriaServicioTurista)
class CategoriaServicioTuristaAdmin(TranslationAdmin):
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


class ContactoFormSet(BaseInlineFormSet):
    """Contactos de entidad (fk servicio) o de sede (fk sede): evita asociaciones
    incorrectas y repetidos dentro del mismo envío del formulario."""

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        if self.fk.name == "sede":
            form.instance.servicio_id = self.instance.servicio_id
        return form

    def clean(self):
        super().clean()
        vistos, principales = set(), set()
        for form in self.forms:
            datos = getattr(form, "cleaned_data", None)
            if not datos or datos.get("DELETE") or not datos.get("valor"):
                continue
            clave = clave_dedup(datos["valor"])
            if clave in vistos:
                raise ValidationError(f"Contacto repetido: {datos['valor']}.")
            vistos.add(clave)
            if datos.get("es_principal"):
                if datos.get("tipo_contacto") in principales:
                    raise ValidationError("Solo puede haber un contacto principal por tipo.")
                principales.add(datos.get("tipo_contacto"))


class ContactoGeneralInline(TranslationTabularInline):
    """Contactos generales de la entidad (los de sede se editan en la sede)."""
    model = ContactoServicioTurista
    formset = ContactoFormSet
    extra = 0
    fields = ["tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo"]
    verbose_name = "Contacto general"
    verbose_name_plural = "Contactos generales de la entidad"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(sede__isnull=True)


class ContactoSedeInline(TranslationTabularInline):
    model = ContactoServicioTurista
    formset = ContactoFormSet
    fk_name = "sede"
    extra = 0
    fields = ["tipo_contacto", "etiqueta", "valor", "es_principal", "orden", "activo"]
    verbose_name = "Contacto de la sede"
    verbose_name_plural = "Contactos de esta sede"


class SedeInline(admin.TabularInline):
    """Alta rápida de sedes desde la entidad. Mapas, referencia y horario
    se editan en la ficha de la sede (enlace «Cambiar»)."""
    model = SedeServicioTurista
    extra = 0
    fields = ["nombre", "distrito", "direccion", "telefono", "activo"]
    autocomplete_fields = ["distrito"]
    show_change_link = True

    def get_min_num(self, request, obj=None, **kwargs):
        return 1 if obj is None else 0

    def get_formset(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["validate_min"] = True  # una entidad nueva nace con al menos una sede
        return super().get_formset(request, obj, **kwargs)


@admin.register(ServicioTurista)
class ServicioTuristaAdmin(TranslationAdmin):
    list_display = ["nombre", "categoria_principal", "sedes", "destacado", "activo"]
    search_fields = [
        "nombre", "descripcion_corta", "telefono", "categoria_principal__nombre",
        "sedes__nombre", "sedes__direccion", "sedes__distrito__nombre_oficial",
        "contactos__valor",
    ]
    list_filter = ["activo", "destacado", "categoria_principal", "sedes__distrito"]
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ["categoria_principal"]
    filter_horizontal = ["categorias_secundarias"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["categoria_principal__nombre", "nombre"]
    inlines = [SedeInline, ContactoGeneralInline]

    # Los campos físicos (distrito, dirección, mapas, horario...) viven en la
    # sede; `notas` y la galería siguen en BD pero ya no se editan aquí.
    fieldsets = (
        ("Información principal", {
            "fields": (
                "categoria_principal", "nombre", "slug", "descripcion_corta",
                "imagen_principal", "texto_alt_imagen",
            )
        }),
        ("Contacto general y redes", {
            "classes": ("collapse",),
            "fields": ("telefono", "whatsapp", "correo", "sitio_web", "facebook", "instagram"),
        }),
        ("Opciones avanzadas", {
            "classes": ("collapse",),
            "fields": ("categorias_secundarias", "tipo_atencion", "descripcion", "recomendaciones"),
        }),
        ("Configuración", {
            "fields": ("destacado", "activo", "creado", "actualizado")
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _sedes_total=Count("sedes", distinct=True),
            _sedes_activas=Count("sedes", filter=Q(sedes__activo=True), distinct=True),
        )

    @admin.display(description="Sedes (activas / total)", ordering="_sedes_total")
    def sedes(self, obj):
        return f"{obj._sedes_activas} / {obj._sedes_total}"


@admin.register(SedeServicioTurista)
class SedeServicioTuristaAdmin(TranslationAdmin):
    form = SedeAdminForm
    list_display = ["nombre_publico", "distrito", "direccion", "telefono", "activo"]
    list_select_related = ["servicio", "distrito"]
    search_fields = ["nombre", "servicio__nombre", "direccion", "telefono", "distrito__nombre_oficial"]
    list_filter = ["activo", "servicio__categoria_principal", "distrito__provincia", "distrito"]
    autocomplete_fields = ["servicio", "distrito", "localidad"]
    readonly_fields = ["vista_previa_horario", "creado", "actualizado"]
    ordering = ["servicio__nombre", "nombre", "id"]

    fieldsets = (
        ("Sede", {
            "fields": ("servicio", "nombre", "distrito", "direccion", "telefono")
        }),
        ("Ubicación en Google Maps", {
            "description": (
                "Pegue la ficha exacta de ESTA sede. Con ella, el mapa, «Abrir mapa» y «Cómo llegar» apuntan al lugar "
                "correcto; si solo hay dirección, el mapa es aproximado y puede ubicar otro lugar."
            ),
            "fields": ("maps_url", "embed_maps"),
        }),
        ("Horario", {
            "description": (
                "Elija bloques (se generan los textos en español e inglés) o escriba un texto personalizado abajo. "
                "24 horas, emergencia o por confirmar se eligen en «Disponibilidad»."
            ),
            "fields": (
                "disponibilidad", "copiar_horario_de",
                ("lv_estado", "lv_d1", "lv_h1", "lv_d2", "lv_h2"),
                ("sa_estado", "sa_d1", "sa_h1", "sa_d2", "sa_h2"),
                ("do_estado", "do_d1", "do_h1", "do_d2", "do_h2"),
                "horario_atencion", "vista_previa_horario",
            ),
        }),
        ("Más datos de ubicación (opcional)", {
            "classes": ("collapse",),
            "fields": ("localidad", "referencia", "latitud", "longitud"),
        }),
        ("Configuración", {
            "fields": ("slug", "activo", "creado", "actualizado")
        }),
    )

    @admin.display(description="Nombre público", ordering="servicio__nombre")
    def nombre_publico(self, obj):
        return obj.nombre_publico

    @admin.display(description="Vista previa del horario")
    def vista_previa_horario(self, obj):
        if not obj or not obj.pk:
            return "Se mostrará después de guardar."
        modo = "Por bloques" if obj.horario else "Texto personalizado"
        aviso = ""
        if obj.horario:
            aviso = format_html(
                '<p class="sede-vista-previa__nota">Para escribir un texto personalizado, ponga los tres bloques en '
                "«Sin indicar» y guarde.</p>"
            )
        if obj.horario and (horarios.generar(obj.horario, "es") != obj.horario_atencion_es
                            or horarios.generar(obj.horario, "en") != obj.horario_atencion_en):
            aviso += format_html(
                '<p class="sede-vista-previa__aviso">El texto no coincide con los bloques (se editó fuera del Admin). '
                "Guarde de nuevo los bloques para regenerarlo.</p>"
            )
        return format_html(
            '<div class="sede-vista-previa"><p class="sede-vista-previa__modo">{}</p>'
            '<dl class="sede-vista-previa__textos">'
            '<dt>Español (ES)</dt><dd>{}</dd><dt>Inglés (EN)</dt><dd>{}</dd></dl>{}</div>',
            modo, obj.horario_atencion_es or "—", obj.horario_atencion_en or "—", aviso,
        )

    def save_model(self, request, obj, form, change):
        previo_es, previo_en = form.initial.get("horario_atencion_es"), form.initial.get("horario_atencion_en")
        estaba_estructurado = any(form.initial.get(f"{k}_estado") for k in ("lv", "sa", "do"))
        super().save_model(request, obj, form, change)
        if obj.horario and not estaba_estructurado and (previo_es or previo_en) and previo_es != obj.horario_atencion_es:
            messages.warning(
                request,
                f"El texto de horario personalizado fue reemplazado por el generado desde los bloques. "
                f"Texto anterior — ES: «{previo_es or ''}» / EN: «{previo_en or ''}».",
            )

    def get_inline_instances(self, request, obj=None):
        # Los contactos de sede se agregan al editar (la sede ya existe).
        return super().get_inline_instances(request, obj) if obj else []

    inlines = [ContactoSedeInline]


# ContactoServicioTurista e ImagenServicioTurista no se registran como entradas
# independientes: los contactos se editan en la entidad (generales) o en la
# sede (locales). La galería sigue en BD pero la UI no la usa.
