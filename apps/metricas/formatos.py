"""Formato de presentación de indicadores. Solo para mostrar: nada de esto se guarda."""
from django.utils.formats import number_format

SIN_DATO = "—"


def num(valor):
    # round() antes: number_format trunca los float en lugar de redondearlos.
    return SIN_DATO if valor is None else number_format(round(valor, 2), decimal_pos=2)


def pct(valor):
    return SIN_DATO if valor is None else f"{num(valor)} %"


def duracion(segundos):
    if segundos is None:
        return SIN_DATO
    horas, resto = divmod(round(segundos), 3600)
    minutos, seg = divmod(resto, 60)
    return f"{horas}:{minutos:02d}:{seg:02d}" if horas else f"{minutos:02d}:{seg:02d}"


def entero(valor):
    return SIN_DATO if valor is None else str(valor)
