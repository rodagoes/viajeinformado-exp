"""UnicosPeriodo: estructura (semanas y meses esperados) y cotas de los recurrentes."""
from dataclasses import dataclass, field

from django.db import transaction

from apps.metricas.choices import GranularidadUnicos, OrigenDato
from apps.metricas.models import UnicosPeriodo

from .datos import cargar_datos
from .intervalos import (
    Intervalo,
    etiqueta_mes,
    etiqueta_semana,
    intervalos_mensuales,
    intervalos_semanales,
)


def intervalos_esperados(periodo):
    """[(granularidad, Intervalo)] que debe tener un periodo: todas sus semanas y todos sus meses."""
    return (
        [(GranularidadUnicos.SEMANA, i) for i in intervalos_semanales(periodo.fecha_inicio, periodo.fecha_fin)]
        + [(GranularidadUnicos.MES, i) for i in intervalos_mensuales(periodo.fecha_inicio, periodo.fecha_fin)]
    )


def etiqueta_intervalo(granularidad, intervalo):
    if granularidad == GranularidadUnicos.MES:
        return etiqueta_mes(intervalo.inicio.year, intervalo.inicio.month)
    return f"Semana {etiqueta_semana(intervalo)}"


@dataclass
class ResultadoEstructura:
    creados: int = 0
    existentes: int = 0
    inconsistentes: list = field(default_factory=list)  # filas con el mismo inicio pero otro fin: no se tocan


def asegurar_intervalos_unicos(periodo, origen=OrigenDato.SIMULADO):
    """Crea las filas de UnicosPeriodo que falten (recurrentes = 0). Idempotente.

    Nunca modifica ni borra filas existentes: una fila con el mismo inicio pero otro fin se
    informa como inconsistente y se deja intacta. Solo SIMULADO: REAL/GA4 los calcula otro proceso.
    """
    if origen != OrigenDato.SIMULADO:
        raise ValueError("Solo se crean intervalos estructurales para datos SIMULADO.")
    resultado = ResultadoEstructura()
    with transaction.atomic():
        existentes = {
            (u.granularidad, u.inicio): u for u in UnicosPeriodo.objects.filter(periodo=periodo, origen=origen)
        }
        nuevos = []
        for granularidad, intervalo in intervalos_esperados(periodo):
            fila = existentes.get((granularidad, intervalo.inicio))
            if fila is None:
                nuevos.append(UnicosPeriodo(
                    periodo=periodo, origen=origen, granularidad=granularidad,
                    inicio=intervalo.inicio, fin=intervalo.fin, usuarios_recurrentes=0,
                ))
            else:
                resultado.existentes += 1
                if fila.fin != intervalo.fin:
                    resultado.inconsistentes.append(fila)
        UnicosPeriodo.objects.bulk_create(nuevos)
        resultado.creados = len(nuevos)
    return resultado


def evaluar_cotas_unicos(datos, etiqueta, inicio, fin, recurrentes):
    """(errores, advertencias) de los recurrentes de un intervalo semanal o mensual. No corrige nada.

    nuevos = Σ nuevos diarios del intervalo;  únicos = nuevos + recurrentes.
    Cotas: recurrentes <= Σ recurrentes diarios del intervalo
           recurrentes <= Σ nuevos anteriores al intervalo
           máx(únicos diarios) <= únicos <= Σ únicos diarios
    La cota inferior (>= máximo diario) es siempre concluyente. Las que dependen de sumas solo
    lo son si hay datos de todos los días necesarios; si no, se informan como advertencia.
    """
    if recurrentes < 0:
        return [f"{etiqueta}: los recurrentes no pueden ser negativos."], []
    dias = {fecha: fila for fecha, fila in datos.diarias.items() if inicio <= fecha <= fin}
    if not dias:
        return [], [f"{etiqueta}: sin métricas diarias en el intervalo; no se pueden validar las cotas de recurrentes."]

    errores, advertencias = [], []
    nuevos = sum(f["usuarios_nuevos"] for f in dias.values())
    suma_recurrentes = sum(f["usuarios_recurrentes"] for f in dias.values())
    unicos_diarios = [f["usuarios_nuevos"] + f["usuarios_recurrentes"] for f in dias.values()]
    previos = [f["usuarios_nuevos"] for fecha, f in datos.diarias.items() if fecha < inicio]
    unicos = nuevos + recurrentes

    cobertura_intervalo = len(dias) == (fin - inicio).days + 1
    cobertura_previa = len(previos) == (inicio - datos.periodo.fecha_inicio).days

    def informar(concluyente, mensaje):
        if concluyente:
            errores.append(mensaje)
        else:
            advertencias.append(f"{mensaje} (no concluyente: faltan métricas diarias)")

    if unicos < max(unicos_diarios):
        errores.append(
            f"{etiqueta}: los únicos del intervalo ({unicos} = {nuevos} nuevos + {recurrentes} recurrentes) no pueden "
            f"ser menos que el máximo de únicos de un día ({max(unicos_diarios)})."
        )
    if recurrentes > suma_recurrentes:
        informar(cobertura_intervalo, (
            f"{etiqueta}: los recurrentes ({recurrentes}) superan la suma de recurrentes diarios del intervalo "
            f"({suma_recurrentes})."
        ))
    if recurrentes > sum(previos):
        informar(cobertura_previa, (
            f"{etiqueta}: los recurrentes ({recurrentes}) superan los usuarios nuevos anteriores al intervalo ({sum(previos)})."
        ))
    if unicos > sum(unicos_diarios):
        informar(cobertura_intervalo, (
            f"{etiqueta}: los únicos del intervalo ({unicos}) superan la suma de únicos diarios ({sum(unicos_diarios)})."
        ))
    return errores, advertencias


def evaluar_fila_unicos(unicos, recurrentes=None, datos=None):
    """Valida una fila UnicosPeriodo (p. ej. desde el Admin), opcionalmente con un valor aún no guardado.

    Devuelve (errores, advertencias).
    """
    datos = datos or cargar_datos(unicos.periodo, unicos.origen)
    if recurrentes is None:
        recurrentes = unicos.usuarios_recurrentes
    etiqueta = etiqueta_intervalo(unicos.granularidad, Intervalo(unicos.inicio, unicos.fin))
    return evaluar_cotas_unicos(datos, etiqueta, unicos.inicio, unicos.fin, recurrentes)
