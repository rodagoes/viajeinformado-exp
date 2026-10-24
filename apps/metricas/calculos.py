"""Fórmulas puras de los indicadores. Sin acceso a BD.

Con denominador 0 devuelven None ("sin dato"), nunca 0. No redondean: el
redondeo es solo de presentación (`redondear`) y jamás se guarda en BD.
Las usarán también los agregados semanal/mensual, siempre sobre bases sumadas
(nunca promediando razones diarias).
"""


def dividir(numerador, denominador):
    if not denominador:
        return None
    return numerador / denominador


def porcentaje(numerador, denominador):
    razon = dividir(numerador, denominador)
    return None if razon is None else razon * 100


def redondear(valor, decimales=2):
    return None if valor is None else round(valor, decimales)
