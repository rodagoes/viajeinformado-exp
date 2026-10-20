"""
Horario estructurado de una sede (JSON compacto) y su texto ES/EN.

Forma: {"lv": [["08:00","18:00"], ...], "sa": [...], "do": [...]}
  - clave ausente  -> día(s) sin indicar
  - lista vacía    -> cerrado
  - hasta 2 tramos por bloque (horario partido); hasta < desde = cruza la medianoche.

El texto generado se guarda en SedeServicioTurista.horario_atencion_es/en, que son
los campos que ya leen la tarjeta, Pillco Bot y el importador ES/EN. 24 horas,
emergencia y «por confirmar» siguen en `disponibilidad`; las excepciones, en texto
personalizado (sin estructura).
"""
import re

BLOQUES = ("lv", "sa", "do")
MAX_TRAMOS = 2
MAX_LONGITUD = 255  # horario_atencion (y sus columnas _es/_en)

_HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

_NOMBRES = {
    "es": {
        "lv": "Lunes a viernes", "sa": "Sábados", "do": "Domingos",
        ("lv", "sa"): "Lunes a sábado", ("sa", "do"): "Sábados y domingos",
        ("lv", "sa", "do"): "Todos los días",
        "cerrado": "Cerrado", "y": " y ", "siguiente": " (día siguiente)", "am": "a. m.", "pm": "p. m.",
    },
    "en": {
        "lv": "Monday to Friday", "sa": "Saturdays", "do": "Sundays",
        ("lv", "sa"): "Monday to Saturday", ("sa", "do"): "Saturdays and Sundays",
        ("lv", "sa", "do"): "Every day",
        "cerrado": "Closed", "y": " and ", "siguiente": " (next day)", "am": "a.m.", "pm": "p.m.",
    },
}


def _minutos(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _intervalo(tramo):
    inicio, fin = _minutos(tramo[0]), _minutos(tramo[1])
    return inicio, fin if fin > inicio else fin + 1440


def _se_solapan(a, b):
    (a1, a2), (b1, b2) = _intervalo(a), _intervalo(b)
    return any(a1 < b2 + d and b1 + d < a2 for d in (-1440, 0, 1440))


def validar_estructura(horario):
    """Lista de errores (vacía si es válido). {} / None = sin estructura."""
    if not horario:
        return []
    if not isinstance(horario, dict) or set(horario) - set(BLOQUES):
        return ["El horario estructurado tiene un formato no válido."]
    errores = []
    for clave in BLOQUES:
        if clave not in horario:
            continue
        tramos = horario[clave]
        if not isinstance(tramos, list) or len(tramos) > MAX_TRAMOS:
            errores.append(f"{_NOMBRES['es'][clave]}: máximo {MAX_TRAMOS} tramos.")
            continue
        validos = []
        for tramo in tramos:
            if not (isinstance(tramo, list) and len(tramo) == 2 and all(isinstance(x, str) and _HORA_RE.match(x) for x in tramo)):
                errores.append(f"{_NOMBRES['es'][clave]}: hora no válida.")
            elif tramo[0] == tramo[1]:
                errores.append(f"{_NOMBRES['es'][clave]}: la hora de inicio y fin no pueden ser iguales (para todo el día use «24 horas»).")
            else:
                validos.append(tramo)
        if len(validos) == 2 and _se_solapan(*validos):
            errores.append(f"{_NOMBRES['es'][clave]}: los tramos se solapan.")
    if not errores:
        for idioma in ("es", "en"):
            if len(generar(horario, idioma)) > MAX_LONGITUD:
                errores.append("El horario generado es demasiado largo; simplifíquelo o use un texto personalizado.")
                break
    return errores


def _hora(hhmm, idioma):
    h, m = (int(x) for x in hhmm.split(":"))
    sufijo = _NOMBRES[idioma]["am" if h < 12 else "pm"]
    return f"{h % 12 or 12}:{m:02d} {sufijo}"


def _tramos_texto(tramos, idioma):
    if not tramos:
        return _NOMBRES[idioma]["cerrado"]
    partes = []
    for desde, hasta in tramos:
        texto = f"{_hora(desde, idioma)} – {_hora(hasta, idioma)}"
        if _minutos(hasta) < _minutos(desde):
            texto += _NOMBRES[idioma]["siguiente"]
        partes.append(texto)
    return _NOMBRES[idioma]["y"].join(partes)


def generar(horario, idioma):
    """Texto determinista del horario en 'es' o 'en'; '' si no hay estructura.
    Une días contiguos con exactamente el mismo horario (lv+sa, sa+do, todos)."""
    if not horario:
        return ""
    grupos = []  # [(claves, tramos)]
    for clave in BLOQUES:
        if clave not in horario:
            continue
        tramos = horario[clave]
        previo = grupos[-1] if grupos else None
        contiguo = previo and BLOQUES.index(previo[0][-1]) == BLOQUES.index(clave) - 1
        if contiguo and previo[1] == tramos:
            previo[0].append(clave)
        else:
            grupos.append(([clave], tramos))
    nombres = _NOMBRES[idioma]
    return "; ".join(
        f"{nombres[claves[0]] if len(claves) == 1 else nombres[tuple(claves)]}: {_tramos_texto(tramos, idioma)}"
        for claves, tramos in grupos
    )
