import calendar
import json
import uuid
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q, Sum
from django.db.models.lookups import GreaterThanOrEqual

from . import calculos
from .choices import (
    AlcancePeriodo,
    DispositivoAcceso,
    EstadoGeneracion,
    FuenteTrafico,
    GranularidadUnicos,
    OrigenDato,
    TipoInteraccion,
)

# Convenciones de este módulo:
# - Conteos PositiveIntegerField (>= 0 en validación y en columna UNSIGNED).
# - Las reglas de una sola fila viven en CheckConstraint (también las ejecuta
#   full_clean). Las que cruzan filas o modelos (sumas de fuentes/dispositivos,
#   cotas de recurrentes, suma de metas) NO son constraints: son de servicio.
# - Los nombres de constraint llevan prefijo "metricas_" (en MySQL son únicos
#   por esquema).


class PeriodoEvaluacion(models.Model):
    nombre = models.CharField(max_length=150)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    # Obligatorio solo con alcance MUESTRA_REGISTRADA; con TODOS_VISITANTES es opcional.
    tamano_muestra = models.PositiveIntegerField(null=True, blank=True)
    alcance = models.CharField(
        max_length=20, choices=AlcancePeriodo.choices, default=AlcancePeriodo.MUESTRA_REGISTRADA,
    )
    activo = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Periodo de evaluación"
        verbose_name_plural = "Periodos de evaluación"
        ordering = ["-fecha_inicio"]
        constraints = [
            models.CheckConstraint(
                name="metricas_periodo_fin_gte_inicio",
                condition=Q(fecha_fin__gte=F("fecha_inicio")),
                violation_error_message="La fecha de fin no puede ser anterior a la de inicio.",
            ),
            models.CheckConstraint(
                name="metricas_periodo_muestra_requiere_tamano",
                condition=~Q(alcance=AlcancePeriodo.MUESTRA_REGISTRADA)
                | Q(tamano_muestra__isnull=False, tamano_muestra__gt=0),
                violation_error_message="Un periodo de muestra registrada requiere un tamaño de muestra mayor que 0.",
            ),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        # "Solo un periodo activo": MySQL/MariaDB no soportan UniqueConstraint
        # condicional, así que se valida aquí (y en el Admin/servicios que llamen
        # a full_clean). Limitación: no es atómico frente a dos guardados
        # concurrentes; aceptable para un panel de uso único de staff.
        if self.activo and PeriodoEvaluacion.objects.filter(activo=True).exclude(pk=self.pk).exists():
            raise ValidationError({"activo": "Ya existe otro periodo activo. Desactívalo primero."})
        if self.pk and self.fecha_inicio and self.fecha_fin and self._hay_datos_fuera_de_rango():
            raise ValidationError(
                "Hay datos del periodo fuera de las nuevas fechas. Elimínalos o amplía el rango."
            )

    def _hay_datos_fuera_de_rango(self):
        rango = (self.fecha_inicio, self.fecha_fin)
        return (
            self.metricas_diarias.exclude(fecha__range=rango).exists()
            or self.interacciones_diarias.exclude(fecha__range=rango).exists()
            or self.unicos.exclude(inicio__gte=self.fecha_inicio, fin__lte=self.fecha_fin).exists()
        )

    def nuevos_por_origen(self):
        """{origen: Σ usuarios_nuevos}. Nunca mezcla orígenes."""
        filas = self.metricas_diarias.values("origen").annotate(total=Sum("usuarios_nuevos"))
        return {fila["origen"]: fila["total"] or 0 for fila in filas}

    def contiene(self, fecha):
        return self.fecha_inicio <= fecha <= self.fecha_fin

    def total_metas(self):
        return self.metas_mensuales.aggregate(total=Sum("nuevos_objetivo"))["total"] or 0

    def metas_completas(self):
        """True si las metas mensuales suman exactamente el tamaño de la muestra.

        Validación agregada (no es constraint): se invoca desde Admin/servicios,
        que admiten un estado intermedio mientras se cargan los meses.
        """
        return self.tamano_muestra is not None and self.total_metas() == self.tamano_muestra


def _solo_real(nombre):
    """Los hechos detallados (visitante, sesión, evento) existen solo para datos REAL.

    SIMULADO y GA4 se persisten como agregados. CheckConstraint simple y portable (MySQL/MariaDB).
    """
    return models.CheckConstraint(
        name=nombre,
        condition=Q(origen=OrigenDato.REAL),
        violation_error_message="Los hechos detallados solo admiten origen REAL.",
    )


def _validar_fecha_en_periodo(periodo_id, campo, valor, periodo=None):
    """Error {campo: msg} si `valor` cae fuera del periodo; None si es válido o no evaluable."""
    if periodo_id is None or valor is None:
        return None
    periodo = periodo or PeriodoEvaluacion.objects.get(pk=periodo_id)
    if not periodo.contiene(valor):
        return {campo: f"La fecha debe estar entre {periodo.fecha_inicio} y {periodo.fecha_fin}."}
    return None


class MetaMuestraMensual(models.Model):
    """Cuota de incorporación de usuarios registrados a la muestra en un mes.

    No es lo mismo que MetricaDiaria.usuarios_nuevos (primera visita): que
    coincidan es una regla del generador simulado de tesis, no del modelo.
    """

    periodo = models.ForeignKey(PeriodoEvaluacion, on_delete=models.CASCADE, related_name="metas_mensuales")
    anio = models.PositiveSmallIntegerField(validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    mes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    nuevos_objetivo = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Meta mensual de muestra"
        verbose_name_plural = "Metas mensuales de muestra"
        ordering = ["periodo", "anio", "mes"]
        constraints = [
            models.UniqueConstraint(fields=["periodo", "anio", "mes"], name="metricas_meta_unica_periodo_mes"),
        ]

    def __str__(self):
        return f"{self.anio}-{self.mes:02d}: {self.nuevos_objetivo}"

    def clean(self):
        if self.periodo_id is None or not self.anio or not self.mes or not 1 <= self.mes <= 12:
            return  # lo reportan los validadores de campo
        if not self.mes_intersecta(self.anio, self.mes, self.periodo.fecha_inicio, self.periodo.fecha_fin):
            raise ValidationError({"mes": "El mes no intersecta el periodo de evaluación."})

    @staticmethod
    def mes_intersecta(anio, mes, inicio, fin):
        primero = date(anio, mes, 1)
        ultimo = date(anio, mes, calendar.monthrange(anio, mes)[1])
        return not (ultimo < inicio or primero > fin)


class VisitanteMetrica(models.Model):
    """Identidad analítica lógica de un visitante REAL. Los datos SIMULADO y GA4 no crean filas aquí.

    No guarda IP, correo ni nombre: solo un UUID aleatorio y, si hay login, el vínculo al usuario.
    La pertenencia a una muestra depende de un PeriodoEvaluacion y NO vive en este modelo.
    """

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    origen = models.CharField(max_length=10, choices=OrigenDato.choices, default=OrigenDato.REAL)
    es_registrado = models.BooleanField(default=False)
    # SET_NULL: borrar la cuenta (eliminar_cuenta) no debe borrar métricas, solo desvincularlas.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="visitantes_metrica",
    )
    primera_visita = models.DateField()
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Visitante"
        verbose_name_plural = "Visitantes"
        constraints = [
            _solo_real("metricas_visitante_solo_real"),
            models.CheckConstraint(
                name="metricas_visitante_usuario_implica_registrado",
                condition=Q(usuario__isnull=True) | Q(es_registrado=True),
                violation_error_message="Un visitante vinculado a un usuario debe estar marcado como registrado.",
            ),
        ]

    def __str__(self):
        return f"{self.get_origen_display()} {self.uuid}"


class SesionMetrica(models.Model):
    # Identificador público opaco (cookie vi_sid): no se expone el pk autoincremental.
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    visitante = models.ForeignKey(VisitanteMetrica, on_delete=models.CASCADE, related_name="sesiones")
    origen = models.CharField(max_length=10, choices=OrigenDato.choices, default=OrigenDato.REAL)
    fecha = models.DateField(help_text="Fecha local (America/Lima) de inicio, ya materializada.")
    inicio = models.DateTimeField()
    fin = models.DateTimeField(null=True, blank=True)
    paginas_vistas = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    duracion_seg = models.PositiveIntegerField(default=0)
    fuente = models.CharField(max_length=10, choices=FuenteTrafico.choices)
    # Solo el host del referrer, nunca la URL completa ni el user-agent.
    referrer_host = models.CharField(max_length=255, blank=True)
    dispositivo = models.CharField(max_length=10, choices=DispositivoAcceso.choices)
    idioma = models.CharField(max_length=8, blank=True)
    es_nueva = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Sesión"
        verbose_name_plural = "Sesiones"
        indexes = [
            models.Index(fields=["fecha", "origen"], name="metricas_sesion_fecha_origen"),
            models.Index(fields=["visitante", "fecha"], name="metricas_sesion_visit_fecha"),
        ]
        constraints = [
            _solo_real("metricas_sesion_solo_real"),
            models.CheckConstraint(
                name="metricas_sesion_paginas_gte_1",
                condition=Q(paginas_vistas__gte=1),
                violation_error_message="Una sesión tiene al menos una página vista.",
            ),
            models.CheckConstraint(
                name="metricas_sesion_fin_gte_inicio",
                condition=Q(fin__isnull=True) | Q(fin__gte=F("inicio")),
                violation_error_message="El fin de la sesión no puede ser anterior a su inicio.",
            ),
        ]

    def __str__(self):
        return f"Sesión {self.pk} ({self.fecha})"

    @property
    def es_rebote(self):
        return self.paginas_vistas == 1

    def clean(self):
        if self.visitante_id and self.origen and self.visitante.origen != self.origen:
            raise ValidationError({"origen": "El origen de la sesión debe coincidir con el de su visitante."})


class EventoMetrica(models.Model):
    META_MAX_CARACTERES = 500

    sesion = models.ForeignKey(
        SesionMetrica, null=True, blank=True, on_delete=models.SET_NULL, related_name="eventos",
    )
    visitante = models.ForeignKey(
        VisitanteMetrica, null=True, blank=True, on_delete=models.SET_NULL, related_name="eventos",
    )
    origen = models.CharField(max_length=10, choices=OrigenDato.choices, default=OrigenDato.REAL)
    tipo = models.CharField(max_length=40, choices=TipoInteraccion.choices)
    fecha = models.DateField(help_text="Fecha local (America/Lima), ya materializada.")
    creado = models.DateTimeField(auto_now_add=True)
    entidad_tipo = models.CharField(max_length=30, blank=True)
    entidad_id = models.PositiveIntegerField(null=True, blank=True)
    # Metadatos pequeños y no sensibles (p. ej. via, resultado). Nunca texto del chatbot.
    meta = models.JSONField(default=dict, blank=True)
    # Idempotencia de reintentos/doble envío. En MySQL varios NULL no chocan en un índice único.
    click_id = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        verbose_name = "Evento de interacción"
        verbose_name_plural = "Eventos de interacción"
        indexes = [
            models.Index(fields=["tipo", "fecha"], name="metricas_evento_tipo_fecha"),
            models.Index(fields=["origen", "fecha"], name="metricas_evento_origen_fecha"),
        ]
        constraints = [_solo_real("metricas_evento_solo_real")]

    def __str__(self):
        return f"{self.tipo} ({self.fecha})"

    def clean(self):
        if not isinstance(self.meta, dict):
            raise ValidationError({"meta": "Los metadatos deben ser un objeto JSON."})
        if len(json.dumps(self.meta, ensure_ascii=False)) > self.META_MAX_CARACTERES:
            raise ValidationError({"meta": f"Los metadatos exceden {self.META_MAX_CARACTERES} caracteres."})
        if self.sesion_id and self.origen and self.sesion.origen != self.origen:
            raise ValidationError({"origen": "El origen del evento debe coincidir con el de su sesión."})
        if self.sesion_id and self.visitante_id and self.sesion.visitante_id != self.visitante_id:
            raise ValidationError({"visitante": "El visitante no coincide con el de la sesión."})


class MetricaDiaria(models.Model):
    """Base diaria de los indicadores. Fuente editable del dataset SIMULADO.

    Solo guarda variables base. Únicos, ratios y porcentajes se calculan.
    """

    periodo = models.ForeignKey(PeriodoEvaluacion, on_delete=models.PROTECT, related_name="metricas_diarias")
    origen = models.CharField(max_length=10, choices=OrigenDato.choices)
    fecha = models.DateField()
    sesiones = models.PositiveIntegerField(default=0)
    paginas_vistas = models.PositiveIntegerField(default=0)
    duracion_total_seg = models.PositiveIntegerField(default=0)
    sesiones_rebote = models.PositiveIntegerField(default=0)
    usuarios_nuevos = models.PositiveIntegerField(default=0)
    usuarios_recurrentes = models.PositiveIntegerField(default=0)
    editado_manual = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Métrica diaria"
        verbose_name_plural = "Métricas diarias"
        ordering = ["fecha"]
        constraints = [
            models.UniqueConstraint(fields=["periodo", "origen", "fecha"], name="metricas_diaria_unica"),
            models.CheckConstraint(
                name="metricas_diaria_rebote_lte_sesiones",
                condition=Q(sesiones_rebote__lte=F("sesiones")),
                violation_error_message="Las sesiones de rebote no pueden superar las sesiones.",
            ),
            models.CheckConstraint(
                name="metricas_diaria_sesiones_gte_unicos",
                condition=Q(sesiones__gte=F("usuarios_nuevos") + F("usuarios_recurrentes")),
                violation_error_message="Las sesiones no pueden ser menos que los usuarios únicos del día.",
            ),
            models.CheckConstraint(
                name="metricas_diaria_paginas_coherentes",
                # Sesiones que no rebotan tienen >= 2 páginas: paginas >= rebote + 2*(sesiones - rebote).
                # Escrito solo con sumas para no restar columnas UNSIGNED en MySQL.
                condition=GreaterThanOrEqual(
                    F("paginas_vistas") + F("sesiones_rebote"), 2 * F("sesiones"),
                ),
                violation_error_message="Las páginas vistas son insuficientes para el número de sesiones y rebotes.",
            ),
        ]

    def __str__(self):
        return f"{self.get_origen_display()} {self.fecha}"

    def clean(self):
        errores = _validar_fecha_en_periodo(self.periodo_id, "fecha", self.fecha)
        if errores:
            raise ValidationError(errores)

    @property
    def usuarios_unicos(self):
        return self.usuarios_nuevos + self.usuarios_recurrentes

    @property
    def paginas_por_sesion(self):
        return calculos.dividir(self.paginas_vistas, self.sesiones)

    @property
    def duracion_media(self):
        return calculos.dividir(self.duracion_total_seg, self.sesiones)

    @property
    def tasa_rebote(self):
        return calculos.porcentaje(self.sesiones_rebote, self.sesiones)

    @property
    def porcentaje_nuevos(self):
        return calculos.porcentaje(self.usuarios_nuevos, self.usuarios_unicos)

    @property
    def porcentaje_recurrentes(self):
        return calculos.porcentaje(self.usuarios_recurrentes, self.usuarios_unicos)


class MetricaDiariaFuente(models.Model):
    # La suma de fuentes = sesiones del día se valida en formset/servicio, no aquí.
    metrica_diaria = models.ForeignKey(MetricaDiaria, on_delete=models.CASCADE, related_name="fuentes")
    fuente = models.CharField(max_length=10, choices=FuenteTrafico.choices)
    sesiones = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Sesiones por fuente"
        verbose_name_plural = "Sesiones por fuente"
        constraints = [
            models.UniqueConstraint(fields=["metrica_diaria", "fuente"], name="metricas_fuente_unica"),
        ]

    def __str__(self):
        return f"{self.get_fuente_display()}: {self.sesiones}"


class MetricaDiariaDispositivo(models.Model):
    # La suma de dispositivos = sesiones del día se valida en formset/servicio, no aquí.
    metrica_diaria = models.ForeignKey(MetricaDiaria, on_delete=models.CASCADE, related_name="dispositivos")
    dispositivo = models.CharField(max_length=10, choices=DispositivoAcceso.choices)
    sesiones = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Sesiones por dispositivo"
        verbose_name_plural = "Sesiones por dispositivo"
        constraints = [
            models.UniqueConstraint(fields=["metrica_diaria", "dispositivo"], name="metricas_dispositivo_unico"),
        ]

    def __str__(self):
        return f"{self.get_dispositivo_display()}: {self.sesiones}"


class InteraccionDiaria(models.Model):
    periodo = models.ForeignKey(PeriodoEvaluacion, on_delete=models.PROTECT, related_name="interacciones_diarias")
    origen = models.CharField(max_length=10, choices=OrigenDato.choices)
    fecha = models.DateField()
    tipo = models.CharField(max_length=40, choices=TipoInteraccion.choices)
    cantidad = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Interacción diaria"
        verbose_name_plural = "Interacciones diarias"
        ordering = ["fecha", "tipo"]
        constraints = [
            models.UniqueConstraint(fields=["periodo", "origen", "fecha", "tipo"], name="metricas_interaccion_unica"),
        ]

    def __str__(self):
        return f"{self.tipo} {self.fecha}: {self.cantidad}"

    def clean(self):
        errores = _validar_fecha_en_periodo(self.periodo_id, "fecha", self.fecha)
        if errores:
            raise ValidationError(errores)


class UnicosPeriodo(models.Model):
    """Recurrentes de una semana o mes: el único dato no aditivo que se guarda.

    nuevos  = SUM(MetricaDiaria.usuarios_nuevos) del intervalo (cada usuario es nuevo un solo día).
    únicos  = nuevos + recurrentes.
    Las cotas respecto de las filas diarias se validan en servicio, no con constraints.
    """

    periodo = models.ForeignKey(PeriodoEvaluacion, on_delete=models.PROTECT, related_name="unicos")
    origen = models.CharField(max_length=10, choices=OrigenDato.choices)
    granularidad = models.CharField(max_length=10, choices=GranularidadUnicos.choices)
    inicio = models.DateField()
    fin = models.DateField()
    usuarios_recurrentes = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Únicos por semana o mes"
        verbose_name_plural = "Únicos por semana o mes"
        ordering = ["granularidad", "inicio"]
        constraints = [
            models.UniqueConstraint(
                fields=["periodo", "origen", "granularidad", "inicio"], name="metricas_unicos_unico",
            ),
            models.CheckConstraint(
                name="metricas_unicos_inicio_lte_fin",
                condition=Q(inicio__lte=F("fin")),
                violation_error_message="El inicio no puede ser posterior al fin.",
            ),
        ]

    def __str__(self):
        return f"{self.get_granularidad_display()} {self.inicio} → {self.fin}"

    def clean(self):
        if self.periodo_id is None:
            return
        periodo = self.periodo
        errores = {}
        for campo in ("inicio", "fin"):
            error = _validar_fecha_en_periodo(self.periodo_id, campo, getattr(self, campo), periodo)
            if error:
                errores.update(error)
        if errores:
            raise ValidationError(errores)

    @property
    def usuarios_nuevos(self):
        """Suma de nuevos diarios del intervalo (1 consulta; los servicios de reporte deben agregar en lote)."""
        return MetricaDiaria.objects.filter(
            periodo_id=self.periodo_id, origen=self.origen, fecha__range=(self.inicio, self.fin),
        ).aggregate(total=Sum("usuarios_nuevos"))["total"] or 0

    @property
    def usuarios_unicos(self):
        return self.usuarios_nuevos + self.usuarios_recurrentes


class GeneracionSimulada(models.Model):
    """Auditoría de una ejecución del generador del dataset SIMULADO.

    Registra con qué semilla y parámetros se generó y la huella (SHA-256) del dataset INICIAL.
    No guarda participantes ni datos personales. Las ediciones manuales posteriores de las
    métricas no la reescriben: la huella describe lo generado, no el estado actual.
    """

    # Solo estos campos pueden cambiar tras crear la fila (p. ej. GENERADA -> REEMPLAZADA).
    CAMPOS_MUTABLES = frozenset({"estado", "observaciones"})

    periodo = models.ForeignKey(PeriodoEvaluacion, on_delete=models.CASCADE, related_name="generaciones")
    semilla = models.BigIntegerField()
    creado = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="generaciones_metricas",
    )
    estado = models.CharField(max_length=15, choices=EstadoGeneracion.choices)
    parametros = models.JSONField(default=dict, blank=True)
    filas_diarias = models.PositiveIntegerField(default=0)
    usuarios_objetivo = models.PositiveIntegerField(default=0)
    huella_inicial = models.CharField(max_length=64, blank=True)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Generación simulada"
        verbose_name_plural = "Generaciones simuladas"
        ordering = ["-creado", "-id"]

    def __str__(self):
        return f"Generación {self.pk} · semilla {self.semilla} · {self.get_estado_display()}"

    def save(self, *args, **kwargs):
        if self.pk and not (kwargs.get("update_fields") and set(kwargs["update_fields"]) <= self.CAMPOS_MUTABLES):
            raise ValueError("Una generación ya registrada solo puede cambiar 'estado' u 'observaciones'.")
        super().save(*args, **kwargs)
