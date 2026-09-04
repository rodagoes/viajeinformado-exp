import calendar
import datetime

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


MES_CHOICES = [
    (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
    (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
    (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
]

DIA_VALIDATORS = [MinValueValidator(1), MaxValueValidator(31)]

# Año no bisiesto de referencia usado para validar combinaciones día/mes de
# `anual_fija`. Con esta referencia el 29 de febrero queda rechazado sin
# necesidad de una regla especial (no se admite ninguna fecha que no exista
# todos los años, ver documento maestro V4, sección 7).
ANIO_REFERENCIA_NO_BISIESTO = 2025


def dia_mes_valido(dia, mes):
    dias_en_mes = calendar.monthrange(ANIO_REFERENCIA_NO_BISIESTO, mes)[1]
    return 1 <= dia <= dias_en_mes


def _ocurrencia_anual_desde(dia_inicio, mes_inicio, dia_fin, mes_fin, anio_inicio):
    inicio = datetime.date(anio_inicio, mes_inicio, dia_inicio)
    if dia_fin and mes_fin:
        cruza_anio = (mes_fin, dia_fin) < (mes_inicio, dia_inicio)
        anio_fin = anio_inicio + 1 if cruza_anio else anio_inicio
        fin = datetime.date(anio_fin, mes_fin, dia_fin)
    else:
        fin = inicio
    return inicio, fin


def _elegir_ocurrencia_relevante(construir_para_anio, hoy):
    """
    Dado un callable(anio) -> (inicio, fin), elige la ocurrencia vigente o
    próxima respecto a `hoy`, probando año anterior/actual/siguiente.
    Compartido por anual_fija, anual_relativa y pascua_relativa.

    Devuelve (inicio, fin, en_curso).
    """
    candidato_anterior = construir_para_anio(hoy.year - 1)
    candidato_actual = construir_para_anio(hoy.year)

    if candidato_anterior[0] <= hoy <= candidato_anterior[1]:
        return candidato_anterior[0], candidato_anterior[1], True
    if candidato_actual[0] <= hoy <= candidato_actual[1]:
        return candidato_actual[0], candidato_actual[1], True
    if hoy < candidato_actual[0]:
        return candidato_actual[0], candidato_actual[1], False
    candidato_siguiente = construir_para_anio(hoy.year + 1)
    return candidato_siguiente[0], candidato_siguiente[1], False


def ocurrencia_anual_relevante(dia_inicio, mes_inicio, dia_fin, mes_fin, hoy):
    """
    Calcula la ocurrencia vigente o próxima de un evento con
    tipo_fecha='anual_fija', respecto a la fecha `hoy`.

    Devuelve (inicio, fin, en_curso).
    """
    def construir(anio):
        return _ocurrencia_anual_desde(dia_inicio, mes_inicio, dia_fin, mes_fin, anio)

    return _elegir_ocurrencia_relevante(construir, hoy)


def ocurrencia_anual_en_rango(dia_inicio, mes_inicio, dia_fin, mes_fin, fecha_desde, fecha_hasta):
    """
    (inicio, fin) de la ocurrencia anual (año de fecha_desde -1, mismo año, +1)
    que solapa con [fecha_desde, fecha_hasta], o None si ninguna lo hace.
    Usado para B4: mostrar la ocurrencia que realmente hizo match con un
    filtro temporal, no la "vigente/próxima respecto a hoy".
    """
    for anio_inicio in (fecha_desde.year - 1, fecha_desde.year, fecha_desde.year + 1):
        inicio, fin = _ocurrencia_anual_desde(dia_inicio, mes_inicio, dia_fin, mes_fin, anio_inicio)
        if inicio <= fecha_hasta and fin >= fecha_desde:
            return inicio, fin
    return None


def ocurrencia_anual_solapa(dia_inicio, mes_inicio, dia_fin, mes_fin, fecha_desde, fecha_hasta):
    """True si alguna ocurrencia anual solapa con [fecha_desde, fecha_hasta]."""
    return ocurrencia_anual_en_rango(dia_inicio, mes_inicio, dia_fin, mes_fin, fecha_desde, fecha_hasta) is not None


def _ocurrencia_relativa_desde(anio, mes, orden, dia_semana, dia_ancla=None):
    """
    N-ésimo `dia_semana` (0=lunes..6=domingo) posterior a un ancla, para un
    evento con tipo_fecha='anual_relativa'.

    Sin `dia_ancla`: el ancla es el último día del mes anterior, así el día 1
    de `mes` queda disponible como primer candidato (representa "N-ésimo día
    de semana del mes", ej. "segundo domingo de enero").

    Con `dia_ancla` (día de `mes`, mismo mes siempre): el ancla es esa fecha
    exacta y solo se admite orden=1 — "primer día de semana estrictamente
    posterior al ancla" (ej. "primer viernes después del 15 de agosto").
    Esa restricción la aplica Evento.clean(), no esta función.
    """
    if dia_ancla is None:
        ancla = datetime.date(anio, mes, 1) - datetime.timedelta(days=1)
    else:
        ancla = datetime.date(anio, mes, dia_ancla)
    dias_hasta = (dia_semana - ancla.weekday()) % 7 or 7
    return ancla + datetime.timedelta(days=dias_hasta + 7 * (orden - 1))


def ocurrencia_relativa_relevante(orden, dia_semana, mes, dia_ancla, hoy):
    """Ocurrencia vigente o próxima de un evento 'anual_relativa'. Ver _elegir_ocurrencia_relevante."""
    def construir(anio):
        fecha = _ocurrencia_relativa_desde(anio, mes, orden, dia_semana, dia_ancla)
        return fecha, fecha

    return _elegir_ocurrencia_relevante(construir, hoy)


def ocurrencia_relativa_en_rango(orden, dia_semana, mes, dia_ancla, fecha_desde, fecha_hasta):
    """(inicio, fin) de la ocurrencia (año -1/actual/+1) que cae dentro de
    [fecha_desde, fecha_hasta], o None si ninguna lo hace (ver B4)."""
    for anio in (fecha_desde.year - 1, fecha_desde.year, fecha_desde.year + 1):
        fecha = _ocurrencia_relativa_desde(anio, mes, orden, dia_semana, dia_ancla)
        if fecha_desde <= fecha <= fecha_hasta:
            return fecha, fecha
    return None


def ocurrencia_relativa_solapa(orden, dia_semana, mes, dia_ancla, fecha_desde, fecha_hasta):
    """True si alguna ocurrencia (año -1/actual/+1) cae dentro de [fecha_desde, fecha_hasta]."""
    return ocurrencia_relativa_en_rango(orden, dia_semana, mes, dia_ancla, fecha_desde, fecha_hasta) is not None


def pascua(anio):
    """Domingo de Pascua para `anio` (algoritmo gregoriano de Gauss/Meeus, sin dependencias)."""
    a = anio % 19
    b = anio // 100
    c = anio % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(anio, mes, dia + 1)


def ocurrencia_pascua_relevante(offset_dias, hoy):
    """Ocurrencia vigente o próxima de un evento 'pascua_relativa'. Ver _elegir_ocurrencia_relevante."""
    def construir(anio):
        fecha = pascua(anio) + datetime.timedelta(days=offset_dias)
        return fecha, fecha

    return _elegir_ocurrencia_relevante(construir, hoy)


def ocurrencia_pascua_en_rango(offset_dias, fecha_desde, fecha_hasta):
    """(inicio, fin) de la ocurrencia (año -1/actual/+1) que cae dentro de
    [fecha_desde, fecha_hasta], o None si ninguna lo hace (ver B4)."""
    for anio in (fecha_desde.year - 1, fecha_desde.year, fecha_desde.year + 1):
        fecha = pascua(anio) + datetime.timedelta(days=offset_dias)
        if fecha_desde <= fecha <= fecha_hasta:
            return fecha, fecha
    return None


def ocurrencia_pascua_solapa(offset_dias, fecha_desde, fecha_hasta):
    """True si alguna ocurrencia (año -1/actual/+1) cae dentro de [fecha_desde, fecha_hasta]."""
    return ocurrencia_pascua_en_rango(offset_dias, fecha_desde, fecha_hasta) is not None


class CategoriaEvento(models.Model):
    TIPO_ICONO_CHOICES = [
        ("bootstrap", "Bootstrap Icon"),
        ("imagen", "Imagen / SVG / GIF"),
        ("lottie", "Lottie JSON"),
    ]

    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    descripcion = models.TextField(blank=True)

    tipo_icono = models.CharField(max_length=20, choices=TIPO_ICONO_CHOICES, default="bootstrap")
    icono_bootstrap = models.CharField(
        max_length=80,
        blank=True,
        help_text="Ejemplo: bi-calendar-star-fill, bi-music-note-beamed"
    )
    icono_archivo = models.FileField(
        upload_to="eventos/categorias/iconos/",
        blank=True,
        help_text="Sube SVG, PNG, WebP, GIF o JSON Lottie si no usarás Bootstrap Icons."
    )

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Categoría de evento"
        verbose_name_plural = "Categorías de eventos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class TagExperiencia(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    icono_bootstrap = models.CharField(
        max_length=80,
        blank=True,
        help_text="Ejemplo: bi-people-fill, bi-camera-fill, bi-tree-fill"
    )
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tag de experiencia"
        verbose_name_plural = "Tags de experiencia"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class EventoQuerySet(models.QuerySet):

    def publicados(self):
        return self.filter(activo=True)

    def que_solapan(self, fecha_desde, fecha_hasta):
        """
        Devuelve los eventos (exacta/rango/anual_fija/anual_relativa/
        pascua_relativa) cuya fecha real u ocurrencia calculada solapa con
        [fecha_desde, fecha_hasta].

        Opera siempre sobre `self` para conservar cualquier filtro
        encadenado previamente (ej. .publicados().filter(categoria=...)).
        No participan mes_aproximado ni por_confirmar.
        """
        base = self

        ids_confirmados = list(
            base.filter(tipo_fecha__in=["exacta", "rango"])
            .filter(
                models.Q(fecha_inicio__lte=fecha_hasta)
                & (
                    models.Q(fecha_fin__gte=fecha_desde)
                    | models.Q(fecha_fin__isnull=True, fecha_inicio__gte=fecha_desde)
                )
            )
            .values_list("id", flat=True)
        )

        ids_anuales = [
            evento.id
            for evento in base.filter(tipo_fecha="anual_fija")
            if ocurrencia_anual_solapa(
                evento.dia_inicio_anual, evento.mes_inicio_anual,
                evento.dia_fin_anual, evento.mes_fin_anual,
                fecha_desde, fecha_hasta,
            )
        ]

        ids_relativos = [
            evento.id
            for evento in base.filter(tipo_fecha="anual_relativa")
            if ocurrencia_relativa_solapa(
                evento.orden_semana_relativa, evento.dia_semana_relativa,
                evento.mes_relativa, evento.dia_ancla_relativa,
                fecha_desde, fecha_hasta,
            )
        ]

        ids_pascua = [
            evento.id
            for evento in base.filter(tipo_fecha="pascua_relativa")
            if ocurrencia_pascua_solapa(evento.offset_dias_pascua, fecha_desde, fecha_hasta)
        ]

        return base.filter(id__in=ids_confirmados + ids_anuales + ids_relativos + ids_pascua)


class Evento(models.Model):
    TIPO_COSTO_CHOICES = [
        ("gratis", "Gratis"),
        ("pagado", "Pagado"),
        ("consultar", "Consultar"),
        ("no_aplica", "No aplica"),
    ]

    MODALIDAD_CHOICES = [
        ("presencial", "Presencial"),
        ("virtual", "Virtual"),
        ("mixta", "Mixta"),
    ]

    TIPO_FECHA_CHOICES = [
        ("exacta", "Fecha exacta (un solo día)"),
        ("rango", "Rango de fechas"),
        ("anual_fija", "Fecha anual fija (se repite cada año)"),
        ("anual_relativa", "Día de semana relativo (ej. 2do domingo de un mes)"),
        ("pascua_relativa", "Fecha móvil relativa a Pascua"),
        ("mes_aproximado", "Mes aproximado"),
        ("por_confirmar", "Fecha por confirmar"),
    ]

    ORDEN_SEMANA_CHOICES = [
        (1, "Primer"), (2, "Segundo"), (3, "Tercer"), (4, "Cuarto"),
    ]
    DIA_SEMANA_CHOICES = [
        (0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"),
        (4, "Viernes"), (5, "Sábado"), (6, "Domingo"),
    ]
    PASCUA_OFFSET_CHOICES = [
        (-7, "Domingo de Ramos"),
        (-3, "Jueves Santo"),
        (-2, "Viernes Santo"),
        (0, "Domingo de Resurrección"),
    ]

    TIPO_HORARIO_CHOICES = [
        ("exacta", "Hora exacta"),
        ("rango", "Rango de horas"),
        ("todo_el_dia", "Todo el día"),
        ("variable", "Horarios variables"),
        ("por_confirmar", "Horario por confirmar"),
        ("no_aplica", "No aplica"),
    ]

    TIPO_UBICACION_CHOICES = [
        ("lugar_exacto", "Lugar exacto"),
        ("varios_lugares", "Varios lugares"),
        ("itinerante", "Itinerante"),
        ("ambito_general", "Ámbito general"),
    ]

    ESTADO_CHOICES = [
        ("programado", "Programado"),
        ("reprogramado", "Reprogramado"),
        ("cancelado", "Cancelado"),
    ]

    objects = EventoQuerySet.as_manager()

    # Clasificación
    categoria_principal = models.ForeignKey(
        CategoriaEvento,
        related_name="eventos_principales",
        on_delete=models.PROTECT,
        verbose_name="Categoría principal"
    )
    categorias_secundarias = models.ManyToManyField(
        CategoriaEvento,
        related_name="eventos_secundarios",
        blank=True,
        verbose_name="Categorías secundarias"
    )
    tags_experiencia = models.ManyToManyField(
        TagExperiencia,
        related_name="eventos",
        blank=True,
        verbose_name="Ideal para",
    )

    # Principal
    nombre = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    descripcion_corta = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)
    contexto_cultural = models.TextField(
        blank=True,
        verbose_name="¿Qué debes saber?",
        help_text="Significado, tradición o contexto cultural. Se omite en el sitio si queda vacío."
    )

    # Fecha
    tipo_fecha = models.CharField(max_length=20, choices=TIPO_FECHA_CHOICES, default="exacta")
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    mes_aproximado = models.PositiveSmallIntegerField(choices=MES_CHOICES, null=True, blank=True)
    anio_aproximado = models.PositiveSmallIntegerField(null=True, blank=True)
    dia_inicio_anual = models.PositiveSmallIntegerField(null=True, blank=True, validators=DIA_VALIDATORS)
    mes_inicio_anual = models.PositiveSmallIntegerField(choices=MES_CHOICES, null=True, blank=True)
    dia_fin_anual = models.PositiveSmallIntegerField(null=True, blank=True, validators=DIA_VALIDATORS)
    mes_fin_anual = models.PositiveSmallIntegerField(choices=MES_CHOICES, null=True, blank=True)
    orden_semana_relativa = models.PositiveSmallIntegerField(choices=ORDEN_SEMANA_CHOICES, null=True, blank=True)
    dia_semana_relativa = models.PositiveSmallIntegerField(choices=DIA_SEMANA_CHOICES, null=True, blank=True)
    mes_relativa = models.PositiveSmallIntegerField(choices=MES_CHOICES, null=True, blank=True)
    dia_ancla_relativa = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=DIA_VALIDATORS,
        help_text="Vacío = N-ésimo día de semana del mes. Con valor = PRIMER día de semana posterior a "
                   "esa fecha (mismo mes que 'mes_relativa'). Con ancla, el orden debe ser 'Primer'."
    )
    offset_dias_pascua = models.SmallIntegerField(choices=PASCUA_OFFSET_CHOICES, null=True, blank=True)

    # Horario
    tipo_horario = models.CharField(max_length=20, choices=TIPO_HORARIO_CHOICES, default="exacta")
    hora_inicio = models.TimeField(null=True, blank=True)
    hora_fin = models.TimeField(null=True, blank=True)

    # Estado
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="programado")

    # Ubicación
    tipo_ubicacion = models.CharField(max_length=20, choices=TIPO_UBICACION_CHOICES, default="lugar_exacto")
    modalidad = models.CharField(max_length=20, choices=MODALIDAD_CHOICES, default="presencial")
    provincia = models.ForeignKey(
        'ubicaciones.Provincia',
        related_name="eventos",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Usar solo si el evento NO tiene un distrito único identificable (se deriva del distrito si este está indicado)."
    )
    distrito = models.ForeignKey(
        'ubicaciones.Distrito',
        related_name="eventos",
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )
    localidad = models.ForeignKey(
        'ubicaciones.Localidad',
        related_name="eventos",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    descripcion_ubicacion = models.CharField(
        max_length=255,
        blank=True,
        help_text="Ejemplo: Diversos puntos de la ciudad de Huánuco. Solo para itinerante/varios lugares."
    )
    lugar = models.CharField(
        max_length=180,
        blank=True,
        help_text="Ejemplo: Plaza de Armas, Coliseo, Centro Cultural, explanada, auditorio."
    )
    direccion = models.CharField(max_length=255, blank=True)
    referencia = models.CharField(max_length=255, blank=True)
    latitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    # Costos
    tipo_costo = models.CharField(max_length=20, choices=TIPO_COSTO_CHOICES, default="consultar")
    precio_desde = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precio desde",
        help_text="Monto mínimo referencial en soles, si aplica."
    )
    precio_hasta = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precio hasta",
        help_text="Monto máximo referencial en soles, si aplica."
    )

    # Organización y contacto
    organizador = models.CharField(max_length=180, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(blank=True)
    sitio_web = models.URLField(blank=True)
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)

    # Información útil
    recomendaciones = models.TextField(
        blank=True,
        help_text="Consejos para asistentes: llegar temprano, llevar abrigo, restricciones, etc."
    )
    publico_objetivo = models.CharField(
        max_length=160,
        blank=True,
        help_text="Campo legado: ya no alimenta filtros ni \"Ideal para\" (usar Tags de experiencia). "
                   "Ejemplo: público general, familias, niños, turistas, jóvenes."
    )
    notas = models.TextField(blank=True, help_text="Uso exclusivo del equipo editor. No se muestra al turista.")
    url_fuente = models.URLField(blank=True, help_text="Enlace usado para verificar esta información. Uso interno.")
    fecha_verificacion = models.DateField(null=True, blank=True, help_text="Última revisión del dato. Uso interno.")

    # Multimedia
    imagen_principal = models.ImageField(upload_to="eventos/principales/", blank=True)
    texto_alt_imagen = models.CharField(max_length=180, blank=True)

    # Control
    destacado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Evento"
        verbose_name_plural = "Eventos"
        ordering = ["-fecha_inicio", "nombre"]

    def _campos_mes_aproximado_poblados(self):
        return bool(self.mes_aproximado or self.anio_aproximado)

    def _campos_anual_poblados(self):
        return bool(self.dia_inicio_anual or self.mes_inicio_anual or self.dia_fin_anual or self.mes_fin_anual)

    def _campos_relativa_poblados(self):
        return bool(
            self.orden_semana_relativa or self.dia_semana_relativa is not None
            or self.mes_relativa or self.dia_ancla_relativa
        )

    def clean(self):
        super().clean()
        errors = {}

        # --- tipo_fecha ---
        if self.tipo_fecha == "exacta":
            if not self.fecha_inicio:
                errors["fecha_inicio"] = "La fecha es obligatoria para una fecha exacta."
            if self.fecha_fin:
                errors["fecha_fin"] = (
                    "Un evento con fecha exacta corresponde a un solo día. "
                    "Para varios días utiliza el tipo de fecha \"Rango\"."
                )
            if (
                self._campos_mes_aproximado_poblados() or self._campos_anual_poblados()
                or self._campos_relativa_poblados() or self.offset_dias_pascua is not None
            ):
                errors["tipo_fecha"] = "Sobran campos de otro tipo de fecha para el tipo 'Exacta'."

        elif self.tipo_fecha == "rango":
            if not self.fecha_inicio:
                errors["fecha_inicio"] = "La fecha de inicio es obligatoria para un rango."
            if not self.fecha_fin:
                errors["fecha_fin"] = "La fecha de fin es obligatoria para un rango."
            if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
                errors["fecha_fin"] = "La fecha de fin no puede ser anterior a la fecha de inicio."
            if (
                self._campos_mes_aproximado_poblados() or self._campos_anual_poblados()
                or self._campos_relativa_poblados() or self.offset_dias_pascua is not None
            ):
                errors["tipo_fecha"] = "Sobran campos de otro tipo de fecha para el tipo 'Rango'."

        elif self.tipo_fecha == "anual_fija":
            if self.fecha_inicio or self.fecha_fin:
                errors["tipo_fecha"] = "Un evento de fecha anual fija no debe tener fecha_inicio/fecha_fin concretas."
            if (
                self._campos_mes_aproximado_poblados() or self._campos_relativa_poblados()
                or self.offset_dias_pascua is not None
            ):
                errors["tipo_fecha"] = "Un evento de fecha anual fija no debe tener campos de otro tipo de fecha."
            if not self.dia_inicio_anual or not self.mes_inicio_anual:
                errors["dia_inicio_anual"] = "El día y mes de inicio son obligatorios para una fecha anual fija."
            elif not dia_mes_valido(self.dia_inicio_anual, self.mes_inicio_anual):
                errors["dia_inicio_anual"] = (
                    "Ese día no existe todos los años en ese mes "
                    "(el 29 de febrero no está permitido)."
                )
            fin_parcial = bool(self.dia_fin_anual) != bool(self.mes_fin_anual)
            if fin_parcial:
                errors["dia_fin_anual"] = "El día y mes de fin deben completarse juntos, o dejarse ambos vacíos."
            elif self.dia_fin_anual and self.mes_fin_anual and not dia_mes_valido(self.dia_fin_anual, self.mes_fin_anual):
                errors["dia_fin_anual"] = (
                    "Ese día no existe todos los años en ese mes "
                    "(el 29 de febrero no está permitido)."
                )

        elif self.tipo_fecha == "anual_relativa":
            if self.fecha_inicio or self.fecha_fin:
                errors["tipo_fecha"] = "Un evento de fecha relativa no debe tener fecha_inicio/fecha_fin concretas."
            if (
                self._campos_mes_aproximado_poblados() or self._campos_anual_poblados()
                or self.offset_dias_pascua is not None
            ):
                errors["tipo_fecha"] = "Un evento de fecha relativa no debe tener campos de otro tipo de fecha."
            if not self.orden_semana_relativa or self.dia_semana_relativa is None or not self.mes_relativa:
                errors["orden_semana_relativa"] = "Orden, día de semana y mes son obligatorios para una fecha relativa."
            if self.dia_ancla_relativa:
                if self.orden_semana_relativa and self.orden_semana_relativa != 1:
                    errors["orden_semana_relativa"] = (
                        "Con día ancla definido, la regla solo admite 'Primer' "
                        "(primer día de semana posterior al ancla)."
                    )
                if self.mes_relativa and not dia_mes_valido(self.dia_ancla_relativa, self.mes_relativa):
                    errors["dia_ancla_relativa"] = (
                        "Ese día no existe todos los años en ese mes "
                        "(el 29 de febrero no está permitido)."
                    )

        elif self.tipo_fecha == "pascua_relativa":
            if self.fecha_inicio or self.fecha_fin:
                errors["tipo_fecha"] = "Un evento de fecha móvil no debe tener fecha_inicio/fecha_fin concretas."
            if (
                self._campos_mes_aproximado_poblados() or self._campos_anual_poblados()
                or self._campos_relativa_poblados()
            ):
                errors["tipo_fecha"] = "Un evento de fecha móvil no debe tener campos de otro tipo de fecha."
            if self.offset_dias_pascua is None:
                errors["offset_dias_pascua"] = "Debes elegir a qué día de Semana Santa corresponde."

        elif self.tipo_fecha == "mes_aproximado":
            if self.fecha_inicio or self.fecha_fin:
                errors["tipo_fecha"] = "Un evento de mes aproximado no debe tener fecha_inicio/fecha_fin concretas."
            if (
                self._campos_anual_poblados() or self._campos_relativa_poblados()
                or self.offset_dias_pascua is not None
            ):
                errors["tipo_fecha"] = "Un evento de mes aproximado no debe tener campos de otro tipo de fecha."
            if not self.mes_aproximado:
                errors["mes_aproximado"] = "El mes aproximado es obligatorio."
            if not self.anio_aproximado:
                errors["anio_aproximado"] = "El año aproximado es obligatorio."

        elif self.tipo_fecha == "por_confirmar":
            if (
                self.fecha_inicio or self.fecha_fin
                or self._campos_mes_aproximado_poblados()
                or self._campos_anual_poblados()
                or self._campos_relativa_poblados()
                or self.offset_dias_pascua is not None
            ):
                errors["tipo_fecha"] = "Un evento 'Por confirmar' no debe tener ningún campo de fecha poblado."

        # --- tipo_horario ---
        if self.tipo_horario == "exacta":
            if not self.hora_inicio:
                errors["hora_inicio"] = "La hora de inicio es obligatoria para un horario exacto."
        elif self.tipo_horario == "rango":
            if not self.hora_inicio:
                errors["hora_inicio"] = "La hora de inicio es obligatoria para un rango de horario."
            if not self.hora_fin:
                errors["hora_fin"] = "La hora de fin es obligatoria para un rango de horario."
            if self.hora_inicio and self.hora_fin and self.hora_fin < self.hora_inicio:
                errors["hora_fin"] = "La hora de fin no puede ser anterior a la hora de inicio."
        else:  # todo_el_dia, variable, por_confirmar, no_aplica
            if self.hora_inicio or self.hora_fin:
                errors["hora_inicio"] = (
                    "Este tipo de horario no admite hora de inicio/fin. "
                    "Cambia el tipo de horario o borra las horas."
                )

        # --- tipo_costo ---
        if self.tipo_costo in ("gratis", "consultar", "no_aplica"):
            if self.precio_desde or self.precio_hasta:
                errors["precio_desde"] = (
                    "Este tipo de costo no admite precios. Cambia el tipo de costo o borra los precios."
                )
        elif self.tipo_costo == "pagado":
            if not self.precio_desde:
                errors["precio_desde"] = "El precio 'desde' es obligatorio cuando el evento es pagado."
            if self.precio_desde and self.precio_hasta and self.precio_hasta < self.precio_desde:
                errors["precio_hasta"] = "El precio hasta no puede ser menor que el precio desde."

        # --- territorio (Alternativa A: sin redundancia) ---
        if self.distrito_id and self.provincia_id:
            errors["provincia"] = (
                "No indiques provincia si ya seleccionaste un distrito: la provincia se obtiene del distrito."
            )
        if self.localidad_id:
            if not self.distrito_id:
                errors["localidad"] = "La localidad requiere que se indique también su distrito."
            elif self.localidad.distrito_id != self.distrito_id:
                errors["localidad"] = "La localidad seleccionada no pertenece al distrito indicado."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.nombre


class ImagenEvento(models.Model):
    evento = models.ForeignKey(Evento, related_name="imagenes", on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to="eventos/galeria/")
    titulo = models.CharField(max_length=160, blank=True)
    texto_alt = models.CharField(max_length=180, blank=True)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Imagen de evento"
        verbose_name_plural = "Imágenes de eventos"
        ordering = ["evento__nombre", "orden", "id"]

    def __str__(self):
        if self.titulo:
            return self.titulo
        return f"Imagen de {self.evento.nombre}"


# Solo el nombre del archivo (nunca ruta/URL): la carpeta base
# `static/assets/img/eventos/` ya es conocida (ver `_icono_archivo_url` en
# apps/eventos/views.py). `[\w-]+\.svg` rechaza `../`, `/`, y esquemas
# `http(s)://` sin necesidad de inspeccionar el filesystem en cada request.
icono_archivo_svg_validator = RegexValidator(
    regex=r"^[\w-]+\.svg$",
    message="Usa solo el nombre del archivo SVG (sin rutas ni URLs), ej. reco-programacion.svg.",
)


class RecomendacionEvento(models.Model):
    """Mismo patrón que apps.turismo.RecomendacionLugarTuristico: recomendación
    estructurada (título + descripción + icono) en vez de texto libre. El
    acento de color es puramente CSS (ver .ev-reco-item), nunca se guarda
    un hex en BD."""
    evento = models.ForeignKey(
        Evento,
        related_name="recomendaciones_detalle",
        on_delete=models.CASCADE,
    )
    titulo = models.CharField(
        max_length=140,
        help_text="Título corto del consejo. Ejemplo: Llega con anticipación."
    )
    descripcion = models.TextField(
        help_text="Detalle breve de la recomendación. Evita textos largos; idealmente 1 o 2 líneas."
    )
    icono_archivo = models.CharField(
        max_length=120,
        blank=True,
        validators=[icono_archivo_svg_validator],
        verbose_name="Icono SVG",
        help_text=(
            "Nombre del archivo SVG en static/assets/img/eventos/ (no la ruta completa). "
            "Ejemplo: reco-programacion.svg. Si se deja vacío, se usa el icono de Bootstrap."
        ),
    )
    icono_bootstrap = models.CharField(
        max_length=80,
        blank=True,
        default="bi bi-lightbulb",
        verbose_name="Icono Bootstrap (fallback)",
        help_text="Ejemplo: bi bi-shield-check, bi bi-camera, bi bi-cup-hot"
    )
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Recomendación de evento"
        verbose_name_plural = "Recomendaciones de eventos"
        ordering = ["evento__nombre", "orden", "id"]

    def __str__(self):
        return self.titulo
