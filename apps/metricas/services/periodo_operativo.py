"""Periodo operativo de producción: un PeriodoEvaluacion por año, creado solo cuando hace falta.

MetricaDiaria / InteraccionDiaria / UnicosPeriodo exigen un PeriodoEvaluacion. Los periodos de tesis ("Periodo de
evaluación junio-septiembre 2026", "Prueba REAL octubre 2026") no se reutilizan: en producción se usa
"Producción AAAA" (01/01–31/12, alcance TODOS_VISITANTES, sin muestra, `activo=False` para no chocar con el "solo un
periodo activo" de los periodos de tesis). No depende del Admin (en producción los periodos están ocultos).
"""
from datetime import date

from django.db import transaction

from apps.metricas.choices import AlcancePeriodo
from apps.metricas.models import PeriodoEvaluacion

from . import consolidacion_real

PREFIJO_PERIODO_OPERATIVO = "Producción"


def nombre_periodo_operativo(anio):
    return f"{PREFIJO_PERIODO_OPERATIVO} {anio}"


def buscar_periodo_operativo(fecha=None):
    """El periodo operativo del año de `fecha` (por defecto hoy, hora de Lima) o None si aún no existe."""
    anio = (fecha or consolidacion_real.hoy()).year
    return PeriodoEvaluacion.objects.filter(
        nombre=nombre_periodo_operativo(anio), alcance=AlcancePeriodo.TODOS_VISITANTES,
    ).first()


def asegurar_periodo_operativo(fecha=None):
    """(periodo, creado). Reutiliza el del año de `fecha`; si no existe lo crea. Idempotente; no crea años futuros."""
    anio = (fecha or consolidacion_real.hoy()).year
    with transaction.atomic():
        periodo = buscar_periodo_operativo(date(anio, 1, 1))
        if periodo is not None:
            return periodo, False
        periodo = PeriodoEvaluacion(
            nombre=nombre_periodo_operativo(anio), fecha_inicio=date(anio, 1, 1), fecha_fin=date(anio, 12, 31),
            alcance=AlcancePeriodo.TODOS_VISITANTES, tamano_muestra=None, activo=False,
        )
        periodo.full_clean()
        periodo.save()
        return periodo, True
