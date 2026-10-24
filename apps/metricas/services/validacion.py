"""Validación global (solo lectura) de un periodo y origen.

No modifica nada ni corrige valores: devuelve errores (bloquean), advertencias (el periodo está
incompleto o no es concluyente) y comprobaciones correctas. El estado se deriva, no se guarda.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from apps.metricas.choices import AlcancePeriodo

from .datos import cargar_datos
from .intervalos import MESES, intervalos_mensuales
from .unicos import evaluar_cotas_unicos, etiqueta_intervalo, intervalos_esperados
from .validaciones import errores_recurrentes_serie

SIN_DATOS = "Sin datos"
EN_PROGRESO = "En progreso"
COMPLETO = "Completo"
CON_ERRORES = "Con errores"

MENSAJES_ESTADO = {
    SIN_DATOS: "El periodo aún no tiene datos.",
    EN_PROGRESO: "El periodo está en progreso.",
    COMPLETO: "El periodo está completo y es coherente.",
    CON_ERRORES: "El periodo tiene errores: corríjalos antes de usar los resultados.",
}

MAX_DETALLES = 5  # por tipo de hallazgo repetitivo


@dataclass
class ResultadoValidacion:
    periodo: object
    origen: str
    estado: str = SIN_DATOS
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)
    correctos: list = field(default_factory=list)
    resumen: dict = field(default_factory=dict)

    @property
    def valido(self):
        return not self.errores

    @property
    def mensaje_estado(self):
        return MENSAJES_ESTADO[self.estado]


def _limitar(mensajes, maximo=MAX_DETALLES):
    if len(mensajes) <= maximo:
        return mensajes
    return mensajes[:maximo] + [f"… y {len(mensajes) - maximo} más."]


def _rangos(fechas, maximo=4):
    """'01/06–05/06, 09/06' desde fechas ordenadas, comprimiendo días consecutivos."""
    tramos = []
    for fecha in fechas:
        if tramos and fecha - tramos[-1][1] == timedelta(days=1):
            tramos[-1][1] = fecha
        else:
            tramos.append([fecha, fecha])
    texto = [f"{a:%d/%m}" if a == b else f"{a:%d/%m}–{b:%d/%m}" for a, b in tramos[:maximo]]
    if len(tramos) > maximo:
        texto.append("…")
    return ", ".join(texto)


def validar_periodo_metricas(periodo, origen, datos=None):
    datos = datos or cargar_datos(periodo, origen)
    r = ResultadoValidacion(periodo=periodo, origen=origen)
    errores, advertencias, correctos = r.errores, r.advertencias, r.correctos

    dias_periodo = [periodo.fecha_inicio + timedelta(days=n) for n in range((periodo.fecha_fin - periodo.fecha_inicio).days + 1)]
    con_datos = [f for f in dias_periodo if f in datos.diarias]
    fuera = [f for f in datos.diarias if not periodo.contiene(f)]
    faltantes = [f for f in dias_periodo if f not in datos.diarias]
    nuevos_total = sum(datos.diarias[f]["usuarios_nuevos"] for f in con_datos)

    es_muestra = periodo.alcance == AlcancePeriodo.MUESTRA_REGISTRADA and bool(periodo.tamano_muestra)
    tamano = periodo.tamano_muestra

    # -- metas
    if es_muestra:
        total_metas = sum(datos.metas.values())
        if not datos.metas:
            advertencias.append("No hay metas mensuales definidas.")
        elif total_metas > tamano:
            errores.append(f"Las metas mensuales suman {total_metas}, más que el tamaño de la muestra ({tamano}).")
        elif total_metas < tamano:
            advertencias.append(f"Metas incompletas: {total_metas} / {tamano}.")
        else:
            correctos.append(f"Metas completas: {total_metas} / {tamano}.")

    # -- cobertura diaria
    if fuera:
        errores.append(f"Hay {len(fuera)} fila(s) diaria(s) fuera del rango del periodo.")
    if faltantes:
        advertencias.append(f"Faltan métricas diarias para {len(faltantes)} días ({_rangos(faltantes)}).")
    else:
        correctos.append(f"Cobertura diaria completa ({len(dias_periodo)} días).")

    # -- nuevos por mes y total frente a la muestra
    if es_muestra:
        varios_anios = periodo.fecha_inicio.year != periodo.fecha_fin.year
        for intervalo in intervalos_mensuales(periodo.fecha_inicio, periodo.fecha_fin):
            mes = intervalo.inicio.month
            nombre = MESES[mes - 1].capitalize() + (f" {intervalo.inicio.year}" if varios_anios else "")
            nuevos = sum(datos.diarias[f]["usuarios_nuevos"] for f in con_datos if intervalo.inicio <= f <= intervalo.fin)
            meta = datos.metas.get((intervalo.inicio.year, mes))
            if meta is None:
                advertencias.append(f"{nombre}: sin meta mensual definida ({nuevos} usuarios nuevos).")
            elif nuevos > meta:
                errores.append(f"{nombre}: {nuevos} / {meta} usuarios nuevos exceden la meta mensual.")
            elif nuevos < meta:
                advertencias.append(f"{nombre}: {nuevos} / {meta} usuarios nuevos.")
            else:
                correctos.append(f"{nombre}: {nuevos} / {meta} usuarios nuevos (meta alcanzada).")
        if nuevos_total > tamano:
            errores.append(f"Los usuarios nuevos ({nuevos_total}) exceden el tamaño de la muestra ({tamano}).")
        elif nuevos_total < tamano:
            advertencias.append(f"Muestra: {nuevos_total} / {tamano} usuarios nuevos.")
        else:
            correctos.append(f"Muestra completa: {nuevos_total} / {tamano} usuarios nuevos.")

    # -- recurrentes diarios (mismo criterio que el formulario del Admin)
    errores_rec = errores_recurrentes_serie({f: datos.diarias[f] for f in con_datos})
    errores.extend(_limitar(errores_rec))
    if con_datos and not errores_rec:
        correctos.append("Recurrentes diarios coherentes con los nuevos acumulados.")

    # -- fuentes y dispositivos
    for nombre, por_fecha in (("fuente de tráfico", datos.fuentes), ("dispositivo", datos.dispositivos)):
        malos = []
        for f in con_datos:
            suma = sum(por_fecha.get(f, {}).values())
            if suma != datos.diarias[f]["sesiones"]:
                malos.append(f"{f:%d/%m/%Y}: la suma por {nombre} ({suma}) no coincide con las sesiones ({datos.diarias[f]['sesiones']}).")
        errores.extend(_limitar(malos))
        if con_datos and not malos:
            correctos.append(f"La suma por {nombre} coincide con las sesiones en todos los días.")

    # -- únicos semanales y mensuales
    esperados = intervalos_esperados(periodo)
    claves_esperadas = {(g, i.inicio) for g, i in esperados}
    faltan_unicos, avisos_unicos = [], []
    for granularidad, intervalo in esperados:
        fila = datos.unicos.get((granularidad, intervalo.inicio))
        if fila is None:
            faltan_unicos.append((granularidad, intervalo))
            continue
        etiqueta = etiqueta_intervalo(granularidad, intervalo)
        if fila["fin"] != intervalo.fin:
            errores.append(f"{etiqueta}: el intervalo guardado termina el {fila['fin']:%d/%m/%Y}, se esperaba {intervalo.fin:%d/%m/%Y}.")
            continue
        e, a = evaluar_cotas_unicos(datos, etiqueta, intervalo.inicio, intervalo.fin, fila["usuarios_recurrentes"])
        errores.extend(e)
        avisos_unicos.extend(a)
    for clave in datos.unicos.keys() - claves_esperadas:
        errores.append(f"Intervalo de únicos inesperado ({clave[0]} desde {clave[1]:%d/%m/%Y}).")
    if faltan_unicos:
        advertencias.append(
            f"Los intervalos de únicos todavía están incompletos: faltan {len(faltan_unicos)} de {len(esperados)}."
        )
    elif not avisos_unicos and not any("únicos" in m or "recurrentes" in m for m in errores):
        correctos.append("Intervalos semanales y mensuales de únicos completos y dentro de las cotas.")
    advertencias.extend(_limitar(avisos_unicos))

    # -- estado derivado
    sin_datos = not datos.diarias and not datos.interacciones and not datos.unicos
    if errores:
        r.estado = CON_ERRORES
    elif sin_datos:
        r.estado = SIN_DATOS
    elif advertencias:
        r.estado = EN_PROGRESO
    else:
        r.estado = COMPLETO

    r.resumen = {
        "dias_esperados": len(dias_periodo),
        "dias_con_datos": len(con_datos),
        "dias_faltantes": len(faltantes),
        "usuarios_nuevos": nuevos_total,
        "tamano_muestra": tamano if es_muestra else None,
        "intervalos_unicos_esperados": len(esperados),
        "intervalos_unicos_existentes": len(esperados) - len(faltan_unicos),
    }
    return r
