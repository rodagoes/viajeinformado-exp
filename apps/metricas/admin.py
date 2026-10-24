import json

from django.conf import settings
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from . import formatos
from .admin_filtros import (
    AgruparPorFilter, AnioFilter, AnioPrimeraVisitaFilter, MesFilter, MesPrimeraVisitaFilter,
)
from .choices import DispositivoAcceso, FuenteTrafico, OrigenDato
from .forms import (
    DispositivoFormSet,
    FuenteFormSet,
    InteraccionDiariaForm,
    MetasFormSet,
    MetricaDiariaForm,
    UnicosPeriodoForm,
)
from .models import (
    EventoMetrica,
    GeneracionSimulada,
    InteraccionDiaria,
    MetaMuestraMensual,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    PeriodoEvaluacion,
    SesionMetrica,
    UnicosPeriodo,
    VisitanteMetrica,
)

from .vistas_admin import ResumenesAdminMixin

SIN_DATO = formatos.SIN_DATO

# Política de edición (todo el módulo):
# - SIMULADO: editable desde el Admin; REAL y GA4: solo lectura y sin borrado.
# - Visitante/Sesión/Evento (hechos REAL): solo consulta.
# - Sin acciones masivas (ni siquiera "eliminar seleccionados").


_num, _pct, _duracion = formatos.num, formatos.pct, formatos.duracion


# ---------------------------------------------------------------- mixins

class SinAccionesAdmin(admin.ModelAdmin):
    show_facets = admin.ShowFacets.NEVER  # sin el enlace "Mostrar recuentos" en ningún listado de métricas

    def get_actions(self, request):
        return {}


class EntornoMetricasAdminMixin:
    """Diferencia LOCAL / PRODUCCIÓN en los listados, solo desde el ModelAdmin (sin tocar modelos ni datos).

    Con settings.METRICAS_ADMIN_PRUEBAS_VISIBLE=True (local) se ve todo. Con False (producción):
    - se ocultan de columnas y filtros los nombres de `SOLO_LOCAL` (periodo, origen, editado manual...);
    - se excluyen del listado las filas SIMULADO (siguen en la BD; REAL y GA4 permanecen).
    Cada Admin define su tupla en la constante `<MODELO>_SOLO_LOCAL_ADMIN`.
    """

    SOLO_LOCAL = ()

    def _modo_pruebas(self):
        return getattr(settings, "METRICAS_ADMIN_PRUEBAS_VISIBLE", False)

    def get_list_display(self, request):
        columnas = super().get_list_display(request)
        return columnas if self._modo_pruebas() else [c for c in columnas if c not in self.SOLO_LOCAL]

    def get_list_filter(self, request):
        filtros = super().get_list_filter(request)
        return filtros if self._modo_pruebas() else [f for f in filtros if f not in self.SOLO_LOCAL]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if self._modo_pruebas() else qs.exclude(origen=OrigenDato.SIMULADO)


class SoloPruebasAdminMixin:
    """Herramientas de tesis/prueba (Generaciones simuladas, Periodos de evaluación).

    Visibles solo con settings.METRICAS_ADMIN_PRUEBAS_VISIBLE (True en local, False en producción). Apagadas: no aparecen
    en el sidebar ni en el índice y sus URLs responden 403. No se borra ni modifica ningún dato.
    """

    def _pruebas_visibles(self):
        return getattr(settings, "METRICAS_ADMIN_PRUEBAS_VISIBLE", False)

    def has_module_permission(self, request):
        return self._pruebas_visibles() and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._pruebas_visibles() and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self._pruebas_visibles() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return self._pruebas_visibles() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._pruebas_visibles() and super().has_delete_permission(request, obj)


class SoloLecturaProduccionAdminMixin:
    """En producción (METRICAS_ADMIN_PRUEBAS_VISIBLE=False) el listado es de solo consulta desde el Admin.

    Sin alta, sin edición y sin borrado: desaparecen "+ Añadir" (sidebar y listado) y los botones Guardar/Eliminar, y la
    ficha se abre en solo lectura (todos los campos readonly). Afecta únicamente a las vistas del Admin: el tracking REAL,
    los servicios, las consolidaciones y los comandos escriben por el ORM y no consultan estos permisos.
    En local (True) no cambia nada: rige la política de siempre (SIMULADO editable).
    """

    def _lectura_estricta(self):
        return not getattr(settings, "METRICAS_ADMIN_PRUEBAS_VISIBLE", False)

    def has_add_permission(self, request):
        return not self._lectura_estricta() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return not self._lectura_estricta() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._lectura_estricta() and super().has_delete_permission(request, obj)


class SoloSimuladoAdminMixin:
    """Solo las filas SIMULADO pueden modificarse o borrarse."""

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.origen != OrigenDato.SIMULADO:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.origen != OrigenDato.SIMULADO:
            return False
        return super().has_delete_permission(request, obj)


class SoloSimuladoInlineMixin:
    """Los inlines siguen el origen de la fila padre."""

    def _padre_editable(self, obj):
        return obj is None or obj.origen == OrigenDato.SIMULADO

    def has_add_permission(self, request, obj=None):
        return self._padre_editable(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._padre_editable(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._padre_editable(obj) and super().has_delete_permission(request, obj)


class SoloConsultaAdmin(SinAccionesAdmin):
    """Hechos REAL: sin alta, edición ni borrado."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------- periodo

class MetaMuestraMensualInline(admin.TabularInline):
    model = MetaMuestraMensual
    formset = MetasFormSet
    extra = 1
    fields = ("anio", "mes", "nuevos_objetivo")
    verbose_name = "Meta mensual"
    verbose_name_plural = "Metas mensuales de incorporación a la muestra"


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — PeriodoEvaluacionAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
PERIODO_EVALUACION_COLUMNAS_ADMIN = (
    "nombre", "fecha_inicio", "fecha_fin", "alcance", "tamano_muestra", "activo", "estado_metas", "avance_muestra",
    "resumenes",
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
PERIODO_EVALUACION_FILTROS_ADMIN = ("activo", "alcance", "fecha_inicio", "fecha_fin")
# ==========================================================================


@admin.register(PeriodoEvaluacion)
class PeriodoEvaluacionAdmin(SoloPruebasAdminMixin, ResumenesAdminMixin, SinAccionesAdmin):
    list_display = PERIODO_EVALUACION_COLUMNAS_ADMIN
    list_filter = PERIODO_EVALUACION_FILTROS_ADMIN
    search_fields = ("nombre",)
    inlines = [MetaMuestraMensualInline]
    readonly_fields = ("estado_metas", "avance_muestra", "resumenes", "creado", "actualizado")
    fieldsets = (
        (None, {"fields": ("nombre", "fecha_inicio", "fecha_fin", "alcance", "tamano_muestra", "activo")}),
        ("Estado de la muestra", {
            "fields": ("estado_metas", "avance_muestra", "resumenes"),
            "description": "Las metas pueden cargarse mes a mes; el estado indica cuánto falta.",
        }),
        ("Auditoría", {"fields": ("creado", "actualizado"), "classes": ("collapse",)}),
    )

    @admin.display(description="Resúmenes (solo consulta)")
    def resumenes(self, obj):
        if obj is None or obj.pk is None:
            return SIN_DATO
        return format_html_join(
            " · ", '<a href="{}">{}</a>', ((url, titulo) for titulo, url, _ in self.enlaces_resumen(obj)),
        )

    @admin.display(description="Metas mensuales")
    def estado_metas(self, obj):
        if obj is None or obj.pk is None or obj.tamano_muestra is None:
            return SIN_DATO
        estado = "completas" if obj.metas_completas() else "incompletas"
        return f"Metas {estado}: {obj.total_metas()} / {obj.tamano_muestra}"

    @admin.display(description="Avance de la muestra (nuevos)")
    def avance_muestra(self, obj):
        """Σ usuarios_nuevos por origen frente al tamaño de la muestra. Los orígenes no se suman entre sí."""
        if obj is None or obj.pk is None or obj.alcance != "MUESTRA_REGISTRADA" or not obj.tamano_muestra:
            return SIN_DATO
        por_origen = obj.nuevos_por_origen()
        if not por_origen:
            return "Sin datos"
        return " · ".join(
            f"{OrigenDato(origen).label}: {total} / {obj.tamano_muestra}" for origen, total in sorted(por_origen.items())
        )


# ---------------------------------------------------------------- métrica diaria

class DesgloseInline(SoloSimuladoInlineMixin, admin.TabularInline):
    fields = ("sesiones",)
    campo = None
    opciones = None

    def get_extra(self, request, obj=None, **kwargs):
        """Categorías aún no creadas, para completarlas todas en la misma pantalla."""
        existentes = 0
        if obj is not None and obj.pk:
            existentes = self.model.objects.filter(metrica_diaria=obj).count()
        return max(len(self.opciones.choices) - existentes, 0)


class FuenteInline(DesgloseInline):
    model = MetricaDiariaFuente
    formset = FuenteFormSet
    campo, opciones = "fuente", FuenteTrafico
    max_num = len(FuenteTrafico.choices)
    fields = ("fuente", "sesiones")
    verbose_name = "Fuente de tráfico"
    verbose_name_plural = "Fuente de tráfico (la suma debe igualar las sesiones del día)"


class DispositivoInline(DesgloseInline):
    model = MetricaDiariaDispositivo
    formset = DispositivoFormSet
    campo, opciones = "dispositivo", DispositivoAcceso
    max_num = len(DispositivoAcceso.choices)
    fields = ("dispositivo", "sesiones")
    verbose_name = "Dispositivo"
    verbose_name_plural = "Dispositivo (la suma debe igualar las sesiones del día)"


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — MetricaDiariaAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
METRICA_DIARIA_COLUMNAS_ADMIN = (
    "fecha", "periodo", "origen", "sesiones", "usuarios_nuevos", "usuarios_recurrentes", "usuarios_unicos",
    "paginas_por_sesion", "duracion_media", "tasa_rebote", "editado_manual",
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
METRICA_DIARIA_FILTROS_ADMIN = ("periodo", "origen", AnioFilter, MesFilter, "editado_manual")

# SOLO EN LOCAL: estos nombres se ocultan (columnas y filtros) cuando METRICAS_ADMIN_PRUEBAS_VISIBLE=False (producción).
METRICA_DIARIA_SOLO_LOCAL_ADMIN = ("periodo", "origen", "editado_manual")
# ==========================================================================


@admin.register(MetricaDiaria)
class MetricaDiariaAdmin(SoloLecturaProduccionAdminMixin, EntornoMetricasAdminMixin, SoloSimuladoAdminMixin, SinAccionesAdmin):
    SOLO_LOCAL = METRICA_DIARIA_SOLO_LOCAL_ADMIN
    form = MetricaDiariaForm
    inlines = [FuenteInline, DispositivoInline]
    ordering = ("-fecha",)
    list_select_related = ("periodo",)
    list_filter = METRICA_DIARIA_FILTROS_ADMIN
    list_display = METRICA_DIARIA_COLUMNAS_ADMIN
    CALCULADOS = (
        "usuarios_unicos", "paginas_por_sesion", "duracion_media", "tasa_rebote",
        "porcentaje_nuevos", "porcentaje_recurrentes",
    )
    fieldsets = (
        ("Identificación", {
            "fields": ("periodo", "origen", "fecha", "editado_manual"),
            "description": "Periodo, origen y fecha quedan fijos tras crear la fila. "
                           "Las filas creadas o modificadas aquí se marcan como editadas manualmente.",
        }),
        ("Usuarios", {"fields": ("usuarios_nuevos", "usuarios_recurrentes", "usuarios_unicos")}),
        ("Navegación", {"fields": ("sesiones", "paginas_vistas", "duracion_total_seg", "sesiones_rebote")}),
        ("Indicadores calculados", {
            "fields": ("paginas_por_sesion", "duracion_media", "tasa_rebote", "porcentaje_nuevos", "porcentaje_recurrentes"),
            "description": "Se calculan a partir de los datos base; no se guardan.",
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        fijos = ("editado_manual",) + self.CALCULADOS
        if obj is not None:
            fijos += ("periodo", "origen", "fecha")
        return fijos

    def save_model(self, request, obj, form, change):
        if not change or form.has_changed():
            obj.editado_manual = True
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.has_changed() and not form.instance.editado_manual:
            form.instance.editado_manual = True
            form.instance.save(update_fields=["editado_manual", "actualizado"])

    @admin.display(description="Usuarios únicos")
    def usuarios_unicos(self, obj):
        return obj.usuarios_unicos

    @admin.display(description="Páginas por sesión")
    def paginas_por_sesion(self, obj):
        return _num(obj.paginas_por_sesion)

    @admin.display(description="Duración media")
    def duracion_media(self, obj):
        return _duracion(obj.duracion_media)

    @admin.display(description="Tasa de rebote")
    def tasa_rebote(self, obj):
        return _pct(obj.tasa_rebote)

    @admin.display(description="% nuevos")
    def porcentaje_nuevos(self, obj):
        return _pct(obj.porcentaje_nuevos)

    @admin.display(description="% recurrentes")
    def porcentaje_recurrentes(self, obj):
        return _pct(obj.porcentaje_recurrentes)


# ---------------------------------------------------------------- interacciones y únicos

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — InteraccionDiariaAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
INTERACCION_DIARIA_COLUMNAS_ADMIN = ("fecha", "periodo", "origen", "tipo", "cantidad")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
INTERACCION_DIARIA_FILTROS_ADMIN = ("periodo", "origen", "tipo", AnioFilter, MesFilter)

# SOLO EN LOCAL: se ocultan en producción (columnas y filtros).
INTERACCION_DIARIA_SOLO_LOCAL_ADMIN = ("periodo", "origen")
# ==========================================================================


@admin.register(InteraccionDiaria)
class InteraccionDiariaAdmin(SoloLecturaProduccionAdminMixin, EntornoMetricasAdminMixin, SoloSimuladoAdminMixin, SinAccionesAdmin):
    SOLO_LOCAL = INTERACCION_DIARIA_SOLO_LOCAL_ADMIN
    form = InteraccionDiariaForm
    ordering = ("-fecha", "tipo")
    list_select_related = ("periodo",)
    list_display = INTERACCION_DIARIA_COLUMNAS_ADMIN
    list_filter = INTERACCION_DIARIA_FILTROS_ADMIN

    def get_readonly_fields(self, request, obj=None):
        return ("periodo", "origen", "fecha", "tipo") if obj is not None else ()


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — UnicosPeriodoAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
UNICOS_PERIODO_COLUMNAS_ADMIN = (
    "periodo", "origen", "agrupar_por", "inicio", "fin", "nuevos", "usuarios_recurrentes", "unicos",
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
UNICOS_PERIODO_FILTROS_ADMIN = ("periodo", "origen", AgruparPorFilter)

# SOLO EN LOCAL: se ocultan en producción (columnas y filtros).
UNICOS_PERIODO_SOLO_LOCAL_ADMIN = ("periodo", "origen")
# ==========================================================================


@admin.register(UnicosPeriodo)
class UnicosPeriodoAdmin(EntornoMetricasAdminMixin, SoloSimuladoAdminMixin, SinAccionesAdmin):
    """Solo `usuarios_recurrentes` es editable (y solo en SIMULADO).

    Los intervalos los crearán servicios (Fase C): sin alta ni borrado manual.
    Las cotas respecto de las filas diarias se validarán en la Fase C.
    """

    SOLO_LOCAL = UNICOS_PERIODO_SOLO_LOCAL_ADMIN
    form = UnicosPeriodoForm
    ordering = ("granularidad", "inicio")
    list_select_related = ("periodo",)
    list_display = UNICOS_PERIODO_COLUMNAS_ADMIN
    list_filter = UNICOS_PERIODO_FILTROS_ADMIN
    readonly_fields = ("periodo", "origen", "agrupar_por", "inicio", "fin", "nuevos", "unicos")
    fieldsets = (
        ("Intervalo", {"fields": ("periodo", "origen", "agrupar_por", "inicio", "fin")}),
        ("Usuarios", {
            "fields": ("nuevos", "usuarios_recurrentes", "unicos"),
            "description": "Nuevos = Σ nuevos diarios del intervalo; únicos = nuevos + recurrentes. "
                           "Los recurrentes no son aditivos, por eso se guardan aparte.",
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        for aviso in form.advertencias:
            self.message_user(request, aviso, level=messages.WARNING)

    @admin.display(description="Agrupar por", ordering="granularidad")
    def agrupar_por(self, obj):  # etiqueta visible de "granularidad" (el campo del modelo no cambia)
        return obj.get_granularidad_display()

    @admin.display(description="Usuarios nuevos")
    def nuevos(self, obj):
        return obj.usuarios_nuevos

    @admin.display(description="Usuarios únicos")
    def unicos(self, obj):
        return obj.usuarios_unicos


# ---------------------------------------------------------------- hechos REAL (solo consulta)

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — VisitanteMetricaAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
VISITANTE_METRICA_COLUMNAS_ADMIN = ("uuid", "es_registrado", "usuario", "primera_visita", "creado")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
VISITANTE_METRICA_FILTROS_ADMIN = ("es_registrado", AnioPrimeraVisitaFilter, MesPrimeraVisitaFilter)
# ==========================================================================


@admin.register(VisitanteMetrica)
class VisitanteMetricaAdmin(EntornoMetricasAdminMixin, SoloConsultaAdmin):
    list_select_related = ("usuario",)
    list_display = VISITANTE_METRICA_COLUMNAS_ADMIN
    list_filter = VISITANTE_METRICA_FILTROS_ADMIN
    search_fields = ("usuario__username",)
    readonly_fields = ("uuid", "origen", "es_registrado", "usuario", "primera_visita", "creado")
    fields = readonly_fields


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — SesionMetricaAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
SESION_METRICA_COLUMNAS_ADMIN = (
    "visitante", "fecha", "inicio", "fin", "paginas_vistas", "duracion_seg", "fuente", "dispositivo", "idioma",
    "es_nueva",
)

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
SESION_METRICA_FILTROS_ADMIN = (AnioFilter, MesFilter, "fuente", "dispositivo", "idioma", "es_nueva")
# ==========================================================================


@admin.register(SesionMetrica)
class SesionMetricaAdmin(EntornoMetricasAdminMixin, SoloConsultaAdmin):
    list_select_related = ("visitante",)
    list_display = SESION_METRICA_COLUMNAS_ADMIN
    list_filter = SESION_METRICA_FILTROS_ADMIN
    readonly_fields = (
        "visitante", "origen", "fecha", "inicio", "fin", "paginas_vistas", "duracion_seg", "fuente",
        "referrer_host", "dispositivo", "idioma", "es_nueva",
    )
    fields = readonly_fields


# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — EventoMetricaAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
EVENTO_METRICA_COLUMNAS_ADMIN = ("creado", "tipo", "entidad", "visitante", "sesion")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
EVENTO_METRICA_FILTROS_ADMIN = ("tipo", AnioFilter, MesFilter)
# ==========================================================================


@admin.register(EventoMetrica)
class EventoMetricaAdmin(EntornoMetricasAdminMixin, SoloConsultaAdmin):
    list_select_related = ("visitante", "sesion")
    list_display = EVENTO_METRICA_COLUMNAS_ADMIN
    list_filter = EVENTO_METRICA_FILTROS_ADMIN
    readonly_fields = (
        "creado", "origen", "tipo", "fecha", "entidad_tipo", "entidad_id", "visitante", "sesion", "click_id",
        "meta_formateado",
    )
    fields = readonly_fields

    @admin.display(description="Entidad")
    def entidad(self, obj):
        return f"{obj.entidad_tipo} #{obj.entidad_id}" if obj.entidad_tipo and obj.entidad_id else SIN_DATO

    @admin.display(description="Metadatos")
    def meta_formateado(self, obj):
        if not obj.meta:
            return SIN_DATO
        return format_html("<pre>{}</pre>", json.dumps(obj.meta, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- auditoría del generador

# ==========================================================================
# CONFIGURACIÓN DEL LISTADO — GeneracionSimuladaAdmin
# --------------------------------------------------------------------------
# COLUMNAS VISIBLES EN EL LISTADO.
# Para ocultar una columna, elimínala de esta tupla; para mostrarla, agrégala (debe existir en el modelo/Admin).
GENERACION_SIMULADA_COLUMNAS_ADMIN = ("creado", "periodo", "semilla", "estado", "usuario", "filas_diarias", "usuarios_objetivo", "huella_corta")

# FILTROS VISIBLES EN LA BARRA DE FILTROS (el orden de aquí es el orden en pantalla).
# Para ocultar un filtro, elimínalo de esta tupla; para volver a mostrarlo, agrégalo.
GENERACION_SIMULADA_FILTROS_ADMIN = ("estado", "periodo")
# ==========================================================================


@admin.register(GeneracionSimulada)
class GeneracionSimuladaAdmin(SoloPruebasAdminMixin, SoloConsultaAdmin):
    """Registro de cada ejecución del generador. Solo consulta: la semilla, los parámetros y la huella
    describen lo que se generó, no el estado actual de los datos (que pueden editarse después)."""

    list_select_related = ("periodo", "usuario")
    list_display = GENERACION_SIMULADA_COLUMNAS_ADMIN
    list_filter = GENERACION_SIMULADA_FILTROS_ADMIN
    readonly_fields = (
        "periodo", "semilla", "creado", "usuario", "estado", "filas_diarias", "usuarios_objetivo", "huella_inicial",
        "observaciones", "parametros_formateados",
    )
    fields = readonly_fields

    @admin.display(description="Huella inicial")
    def huella_corta(self, obj):
        return f"{obj.huella_inicial[:12]}…" if obj.huella_inicial else SIN_DATO

    @admin.display(description="Parámetros de simulación (supuestos)")
    def parametros_formateados(self, obj):
        return format_html("<pre>{}</pre>", json.dumps(obj.parametros, ensure_ascii=False, indent=2, sort_keys=True))
