"""Intervalos semanales (lunes a domingo) y mensuales de un periodo. Funciones puras."""
import calendar
from datetime import date, timedelta
from typing import NamedTuple

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


class Intervalo(NamedTuple):
    inicio: date
    fin: date

    @property
    def dias(self):
        return (self.fin - self.inicio).days + 1


def intervalos_semanales(inicio, fin):
    """Semanas lunes-domingo recortadas al rango [inicio, fin]."""
    resultado, actual = [], inicio
    while actual <= fin:
        domingo = actual + timedelta(days=6 - actual.weekday())
        resultado.append(Intervalo(actual, min(domingo, fin)))
        actual = domingo + timedelta(days=1)
    return resultado


def intervalos_mensuales(inicio, fin):
    """Un intervalo por cada mes calendario que intersecta [inicio, fin], recortado al rango."""
    if fin < inicio:
        return []
    resultado, anio, mes = [], inicio.year, inicio.month
    while (anio, mes) <= (fin.year, fin.month):
        primero, ultimo = date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])
        resultado.append(Intervalo(max(primero, inicio), min(ultimo, fin)))
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return resultado


def etiqueta_mes(anio, mes):
    return f"{MESES[mes - 1].capitalize()} {anio}"


def etiqueta_semana(intervalo):
    return f"{intervalo.inicio:%d/%m} – {intervalo.fin:%d/%m/%Y}"
