"""Consolidación de métricas REAL: de los hechos (visitantes, sesiones, eventos) a los agregados de la Fase C.

Estrategia
- Se reconstruye un RANGO de un PeriodoEvaluacion (por defecto, desde su inicio hasta hoy o su fin). Dentro del rango
  se BORRAN los agregados origen=REAL del periodo (métricas diarias con sus desgloses, interacciones y los intervalos
  de únicos incluidos) y se vuelven a crear desde los hechos, todo dentro de una transacción: re-ejecutar con los
  mismos hechos produce exactamente el mismo resultado, y una falla a mitad deja intacto lo anterior.
- Nunca toca SIMULADO ni GA4, ni otros periodos, ni fechas fuera del rango.
- Los agregados REAL son de solo lectura en el Admin: se regeneran, no se editan.

Definiciones (las del instrumento)
- sesiones = SesionMetrica REAL del día; páginas y duración = sumas; rebote = sesiones con una sola página.
- Usuarios del día = visitantes DISTINTOS con al menos una sesión ese día (la actividad que cuenta es una sesión: así
  sesiones >= únicos, que exige el modelo). nuevo: primera_visita == fecha; recurrente: primera_visita < fecha.
- Únicos de semana/mes: visitantes distintos del intervalo (NO se suman únicos diarios). Se persiste solo
  `usuarios_recurrentes` = visitantes activos en el intervalo con primera_visita anterior a su inicio.
  Caso borde: un visitante creado sin sesión (solo un evento) y que luego tiene su primera sesión se cuenta como
  recurrente ese día; puede dejar el total de un intervalo en ±1 respecto de los distintos reales.
- Desgloses e interacciones: solo se guardan categorías/tipos con valor > 0; la ausencia equivale a 0 (los resúmenes y
  la validación de la Fase C ya lo interpretan así).
- Alcance del periodo: TODOS_VISITANTES incluye anónimos y registrados; MUESTRA_REGISTRADA solo visitantes
  registrados con cuenta verificada (nunca se mezclan anónimos en una muestra).
- Cobertura: se crean filas diarias hasta hoy (hora de Lima), también las de 0 sesiones; los días futuros no existen aún.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.metricas.choices import AlcancePeriodo, OrigenDato
from apps.metricas.models import (
    EventoMetrica,
    InteraccionDiaria,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    SesionMetrica,
    UnicosPeriodo,
)

from .datos import cargar_datos
from .unicos import intervalos_esperados
from .validacion import validar_periodo_metricas

REAL = OrigenDato.REAL


def hoy():
    return timezone.localdate()


@dataclass
class FilaDiariaReal:
    fecha: object
    sesiones: int = 0
    paginas_vistas: int = 0
    duracion_total_seg: int = 0
    sesiones_rebote: int = 0
    usuarios_nuevos: int = 0
    usuarios_recurrentes: int = 0
    fuentes: dict = field(default_factory=dict)
    dispositivos: dict = field(default_factory=dict)


@dataclass
class FilaUnicosReal:
    granularidad: str
    inicio: object
    fin: object
    usuarios_recurrentes: int
    usuarios_unicos: int  # solo informativo (el modelo no lo guarda)


@dataclass
class AgregadosReales:
    periodo: object
    desde: object
    hasta: object
    diarias: list
    interacciones: list  # [(fecha, tipo, cantidad)]
    unicos: list

    @property
    def totales(self):
        return {
            "sesiones": sum(f.sesiones for f in self.diarias),
            "paginas_vistas": sum(f.paginas_vistas for f in self.diarias),
            "duracion_total_seg": sum(f.duracion_total_seg for f in self.diarias),
            "sesiones_rebote": sum(f.sesiones_rebote for f in self.diarias),
            "usuarios_nuevos": sum(f.usuarios_nuevos for f in self.diarias),
            "interacciones": sum(c for _, _, c in self.interacciones),
        }


@dataclass
class ResultadoReconstruccion:
    agregados: AgregadosReales
    existentes: dict  # filas REAL del rango que se reemplazarían/reemplazaron
    escribio: bool
    validacion: object = None

    @property
    def filas(self):
        a = self.agregados
        return {
            "metricas_diarias": len(a.diarias),
            "fuentes": sum(len(f.fuentes) for f in a.diarias),
            "dispositivos": sum(len(f.dispositivos) for f in a.diarias),
            "interacciones": len(a.interacciones),
            "unicos": len(a.unicos),
        }


# ---------------------------------------------------------------- rango y alcance

def rango_efectivo(periodo, fecha_inicio=None, fecha_fin=None):
    """(desde, hasta) validados dentro del periodo. Por defecto: del inicio del periodo a hoy (o su fin)."""
    techo = min(periodo.fecha_fin, hoy())
    desde = fecha_inicio or periodo.fecha_inicio
    hasta = fecha_fin or techo
    if desde < periodo.fecha_inicio or hasta > periodo.fecha_fin:
        raise ValueError(
            f"El rango {desde} – {hasta} queda fuera del periodo ({periodo.fecha_inicio} – {periodo.fecha_fin})."
        )
    if desde > hasta:
        raise ValueError("La fecha de inicio es posterior a la de fin (o el periodo aún no empieza).")
    return desde, hasta


def _filtro_alcance(periodo, prefijo=""):
    if periodo.alcance == AlcancePeriodo.MUESTRA_REGISTRADA:
        return {
            f"{prefijo}es_registrado": True,
            f"{prefijo}usuario__perfil__verificado": True,
            f"{prefijo}usuario__is_staff": False,
        }
    return {}


# ---------------------------------------------------------------- cálculo (solo lecturas)

def calcular_agregados_reales(periodo, fecha_inicio=None, fecha_fin=None):
    """Agregados REAL del rango, sin escribir nada. Número de consultas fijo (no crece con los datos)."""
    desde, hasta = rango_efectivo(periodo, fecha_inicio, fecha_fin)
    sesiones = SesionMetrica.objects.filter(origen=REAL, fecha__range=(desde, hasta), **_filtro_alcance(periodo, "visitante__"))

    filas = {desde + timedelta(days=n): FilaDiariaReal(desde + timedelta(days=n)) for n in range((hasta - desde).days + 1)}
    for r in sesiones.values("fecha").annotate(
        n=Count("id"), paginas=Sum("paginas_vistas"), duracion=Sum("duracion_seg"), rebotes=Count("id", filter=Q(paginas_vistas=1)),
    ):
        f = filas[r["fecha"]]
        f.sesiones, f.paginas_vistas, f.duracion_total_seg, f.sesiones_rebote = r["n"], r["paginas"], r["duracion"] or 0, r["rebotes"]
    for r in sesiones.values("fecha", "fuente").annotate(n=Count("id")):
        filas[r["fecha"]].fuentes[r["fuente"]] = r["n"]
    for r in sesiones.values("fecha", "dispositivo").annotate(n=Count("id")):
        filas[r["fecha"]].dispositivos[r["dispositivo"]] = r["n"]

    # Visitantes distintos por día (una sola consulta; sirve para el diario y para los intervalos de únicos).
    dias_visitante = list(sesiones.values_list("fecha", "visitante_id", "visitante__primera_visita").distinct())
    for fecha, _, primera in dias_visitante:
        if primera == fecha:
            filas[fecha].usuarios_nuevos += 1
        else:
            filas[fecha].usuarios_recurrentes += 1

    eventos = EventoMetrica.objects.filter(origen=REAL, fecha__range=(desde, hasta), **_filtro_alcance(periodo, "visitante__"))
    interacciones = sorted(
        (r["fecha"], r["tipo"], r["n"]) for r in eventos.values("fecha", "tipo").annotate(n=Count("id"))
    )

    unicos = []
    techo = min(periodo.fecha_fin, hoy())
    for granularidad, intervalo in intervalos_esperados(periodo):
        completo_en_rango = intervalo.fin <= hasta or hasta >= techo
        if not (desde <= intervalo.inicio <= hasta and completo_en_rango):
            continue  # con datos parciales del intervalo el valor no sería válido
        activos = {v: p for f, v, p in dias_visitante if intervalo.inicio <= f <= intervalo.fin}
        recurrentes = sum(1 for primera in activos.values() if primera < intervalo.inicio)
        unicos.append(FilaUnicosReal(granularidad, intervalo.inicio, intervalo.fin, recurrentes, len(activos)))

    return AgregadosReales(periodo, desde, hasta, list(filas.values()), interacciones, unicos)


# ---------------------------------------------------------------- escritura

def _pks_unicos(agregados):
    """pks de los UnicosPeriodo REAL que esta reconstrucción reemplaza (mismo periodo, granularidad e inicio)."""
    if not agregados.unicos:
        return []
    claves = Q()
    for u in agregados.unicos:
        claves |= Q(granularidad=u.granularidad, inicio=u.inicio)
    return list(UnicosPeriodo.objects.filter(claves, periodo=agregados.periodo, origen=REAL).values_list("pk", flat=True))


def _filtros_existentes(agregados):
    p, d, h = agregados.periodo, agregados.desde, agregados.hasta
    return (
        MetricaDiaria.objects.filter(periodo=p, origen=REAL, fecha__range=(d, h)),
        InteraccionDiaria.objects.filter(periodo=p, origen=REAL, fecha__range=(d, h)),
        UnicosPeriodo.objects.filter(
            periodo=p, origen=REAL, pk__in=_pks_unicos(agregados),
        ),
    )


def contar_existentes(agregados):
    diarias, interacciones, unicos = _filtros_existentes(agregados)
    return {
        "metricas_diarias": diarias.count(), "interacciones": interacciones.count(), "unicos": unicos.count(),
    }


def _insertar(agregados):
    p = agregados.periodo
    MetricaDiaria.objects.bulk_create([
        MetricaDiaria(
            periodo=p, origen=REAL, fecha=f.fecha, sesiones=f.sesiones, paginas_vistas=f.paginas_vistas,
            duracion_total_seg=f.duracion_total_seg, sesiones_rebote=f.sesiones_rebote,
            usuarios_nuevos=f.usuarios_nuevos, usuarios_recurrentes=f.usuarios_recurrentes, editado_manual=False,
        ) for f in agregados.diarias
    ])
    ids = dict(MetricaDiaria.objects.filter(periodo=p, origen=REAL, fecha__range=(agregados.desde, agregados.hasta)).values_list("fecha", "pk"))
    MetricaDiariaFuente.objects.bulk_create([
        MetricaDiariaFuente(metrica_diaria_id=ids[f.fecha], fuente=c, sesiones=n)
        for f in agregados.diarias for c, n in sorted(f.fuentes.items()) if n
    ])
    MetricaDiariaDispositivo.objects.bulk_create([
        MetricaDiariaDispositivo(metrica_diaria_id=ids[f.fecha], dispositivo=c, sesiones=n)
        for f in agregados.diarias for c, n in sorted(f.dispositivos.items()) if n
    ])
    InteraccionDiaria.objects.bulk_create([
        InteraccionDiaria(periodo=p, origen=REAL, fecha=fecha, tipo=tipo, cantidad=n) for fecha, tipo, n in agregados.interacciones
    ])
    UnicosPeriodo.objects.bulk_create([
        UnicosPeriodo(
            periodo=p, origen=REAL, granularidad=u.granularidad, inicio=u.inicio, fin=u.fin,
            usuarios_recurrentes=u.usuarios_recurrentes,
        ) for u in agregados.unicos
    ])


def reconstruir_metricas_reales(periodo, fecha_inicio=None, fecha_fin=None, dry_run=True):
    """Reconstruye (o solo calcula, con dry_run) los agregados REAL del rango. Idempotente y atómico.

    Por seguridad, `dry_run` es True por defecto: hay que pedir expresamente la escritura.
    """
    agregados = calcular_agregados_reales(periodo, fecha_inicio, fecha_fin)
    if dry_run:
        return ResultadoReconstruccion(agregados, contar_existentes(agregados), escribio=False)
    with transaction.atomic():
        existentes = contar_existentes(agregados)
        diarias, interacciones, unicos = _filtros_existentes(agregados)
        diarias.delete()  # arrastra fuentes y dispositivos
        interacciones.delete()
        unicos.delete()
        _insertar(agregados)
        validacion = validar_periodo_metricas(periodo, REAL, datos=cargar_datos(periodo, REAL))
    return ResultadoReconstruccion(agregados, existentes, escribio=True, validacion=validacion)
