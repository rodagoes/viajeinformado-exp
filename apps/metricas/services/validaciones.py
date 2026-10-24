"""Validaciones cruzadas de la edición de métricas (compartidas por Admin y futuros servicios)."""
from django.db.models import Sum

from apps.metricas.models import MetricaDiaria

MAX_MENSAJES_POSTERIORES = 3


def mensaje_recurrentes_excedidos(fecha, recurrentes, previos):
    if previos == 0:
        return f"Los usuarios recurrentes del {fecha:%d/%m/%Y} deben ser 0: no hay usuarios nuevos en días anteriores."
    return (
        f"Los usuarios recurrentes del {fecha:%d/%m/%Y} ({recurrentes}) no pueden superar "
        f"los nuevos acumulados de días anteriores ({previos})."
    )


def errores_recurrentes_serie(diarias):
    """Mismo criterio que errores_recurrentes_diarios, para todo un periodo en memoria (sin consultas).

    `diarias`: {fecha: {"usuarios_nuevos": n, "usuarios_recurrentes": r}} de un solo periodo y origen.
    """
    errores, acumulado = [], 0
    for fecha in sorted(diarias):
        fila = diarias[fecha]
        if fila["usuarios_recurrentes"] > acumulado:
            errores.append(mensaje_recurrentes_excedidos(fecha, fila["usuarios_recurrentes"], acumulado))
        acumulado += fila["usuarios_nuevos"]
    return errores


def errores_recurrentes_diarios(*, periodo, origen, fecha, nuevos, recurrentes, excluir_pk=None):
    """Mensajes de error (lista vacía si todo es coherente) para una fila diaria.

    Regla: recurrentes del día <= Σ nuevos de fechas anteriores (mismo periodo y origen).
    El primer día no tiene nuevos previos, así que sus recurrentes deben ser 0.
    También se comprueba que el cambio no deje imposible a los días posteriores.
    Nunca corrige datos: solo informa.
    """
    del_origen = MetricaDiaria.objects.filter(periodo=periodo, origen=origen).exclude(pk=excluir_pk)
    previos = del_origen.filter(fecha__lt=fecha).aggregate(t=Sum("usuarios_nuevos"))["t"] or 0

    errores = []
    if recurrentes > previos:
        errores.append(mensaje_recurrentes_excedidos(fecha, recurrentes, previos))

    acumulado = previos + nuevos
    afectados = 0
    posteriores = del_origen.filter(fecha__gt=fecha).order_by("fecha").values_list(
        "fecha", "usuarios_nuevos", "usuarios_recurrentes",
    )
    for dia, nuevos_dia, recurrentes_dia in posteriores:
        if recurrentes_dia > acumulado:
            afectados += 1
            if afectados <= MAX_MENSAJES_POSTERIORES:
                errores.append(
                    f"Este cambio dejaría imposible el día {dia:%d/%m/%Y}: tiene {recurrentes_dia} recurrentes "
                    f"y solo habría {acumulado} nuevos acumulados anteriores."
                )
        acumulado += nuevos_dia
    if afectados > MAX_MENSAJES_POSTERIORES:
        errores.append(f"… y {afectados - MAX_MENSAJES_POSTERIORES} día(s) posterior(es) más.")
    return errores
