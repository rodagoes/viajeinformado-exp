"""Generador reproducible del dataset SIMULADO de un periodo.

Flujo (cada paso es independiente y puede inspeccionarse antes del siguiente):

    dataset = simular_periodo(periodo, semilla)      # 1. en memoria, sin tocar la BD
    errores = validar_dataset(dataset)               # 2. validación completa
    resumen = dataset.a_datos()                      # 3. previsualización con los mismos cálculos del Admin
    persistir_dataset(dataset, reemplazar=...)       # 4. recién aquí se escribe, en una transacción

Los participantes son una población lógica EN MEMORIA (jamás se persisten, ni como User ni como
VisitanteMetrica): de ellos se derivan los nuevos y recurrentes diarios y los recurrentes
semanales/mensuales. Todos los parámetros son SUPUESTOS DE SIMULACIÓN: no son datos medidos ni de GA4.
"""
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from django.db import transaction

from apps.metricas.choices import (
    AlcancePeriodo,
    DispositivoAcceso,
    EstadoGeneracion,
    FuenteTrafico,
    OrigenDato,
    TipoInteraccion,
)
from apps.metricas.models import (
    GeneracionSimulada,
    InteraccionDiaria,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    UnicosPeriodo,
)

from .datos import DatosPeriodo, cargar_datos
from .intervalos import intervalos_mensuales
from .unicos import intervalos_esperados
from .validacion import COMPLETO, validar_periodo_metricas

SIM = OrigenDato.SIMULADO
FUENTES = [codigo for codigo, _ in FuenteTrafico.choices]
DISPOSITIVOS = [codigo for codigo, _ in DispositivoAcceso.choices]
TIPOS = [codigo for codigo, _ in TipoInteraccion.choices]


class SimulacionError(Exception):
    """Configuración imposible de simular (metas ausentes, alcance incorrecto…)."""


class DatasetInvalido(Exception):
    def __init__(self, errores):
        self.errores = errores
        super().__init__("; ".join(errores[:5]))


class DatosSimuladosExistentes(Exception):
    def __init__(self, conteos):
        self.conteos = conteos
        super().__init__(f"El periodo ya tiene datos SIMULADOS: {conteos}")


# ---------------------------------------------------------------- parámetros (supuestos de simulación)

@dataclass(frozen=True)
class ParametrosSimulacion:
    """Supuestos del simulador. Cambiarlos cambia el dataset (y su huella)."""

    # -- incorporación (nuevos): la cuota mensual la fija el periodo; aquí solo cómo se reparte en días
    factor_fin_de_semana_nuevos: float = 1.25
    crecimiento_intramensual: float = 0.30  # el último día del mes pesa +30 % frente al primero
    ruido_nuevos: float = 0.35  # sigma lognormal del peso diario

    # -- recurrencia: probabilidad diaria de que un participante ya incorporado vuelva
    prob_retorno_base: float = 0.050
    heterogeneidad_retorno: float = 0.90  # sigma lognormal de la afinidad individual (hay usuarios muy y poco activos)
    decaimiento_dias: float = 25.0  # el interés inicial decae con la antigüedad…
    piso_retorno: float = 0.45  # …hasta este porcentaje de la probabilidad base
    crecimiento_uso: float = 0.50  # la intensidad de uso crece hasta +50 % al final del periodo
    factor_fin_de_semana_retorno: float = 1.15
    prob_retorno_max: float = 0.60
    ruido_actividad_diaria: float = 0.12  # sigma lognormal común a todo un día (correlaciona métricas)

    # -- sesiones por usuario único
    prob_sesion_extra: float = 0.22  # probabilidad de una 2.ª sesión en el día
    prob_sesion_extra_adicional: float = 0.12  # y de cada sesión siguiente
    max_sesiones_por_usuario: int = 4
    factor_fin_de_semana_sesiones: float = 1.10

    # -- rebote clásico (sesión de una sola página) y páginas
    # La tasa latente del día se acota; en días con suficientes sesiones el CONTEO se genera con ruido
    # reducido y se acota a [limite_inferior, limite_superior] (sanity check de simulación, no regla de BD).
    rebote_media: float = 0.38
    rebote_desvio: float = 0.05
    rebote_min: float = 0.22
    rebote_max: float = 0.55
    sesiones_dia_estable: int = 10  # desde este número de sesiones se controla el ruido de conteo
    ruido_conteo_rebote: float = 0.50  # fracción de la desviación binomial que se conserva
    rebote_limite_inferior: float = 0.20
    rebote_limite_superior: float = 0.60
    paginas_prob_corte_media: float = 0.38  # tras la 2.ª página, probabilidad de terminar en cada una siguiente
    paginas_prob_corte_desvio: float = 0.04
    paginas_max_por_sesion: int = 15
    paginas_media_min: float = 1.8  # sanity check en días con sesiones_dia_estable o más sesiones
    paginas_media_max: float = 4.5

    # -- duración (segundos), por página vista con distribución lognormal
    # Colas truncadas: una sola página o sesión extrema no puede arrastrar la media del día.
    seg_por_pagina_media: float = 50.0
    seg_por_pagina_sigma: float = 0.45
    seg_max_pagina: int = 300
    seg_rebote_media: float = 18.0
    seg_rebote_sigma: float = 0.50
    seg_max_sesion: int = 900
    ruido_duracion_diaria: float = 0.08
    duracion_media_min_seg: int = 45  # sanity check en días con sesiones_dia_estable o más sesiones
    duracion_media_max_seg: int = 270

    # -- fuente de tráfico y dispositivo (pesos base y variación diaria)
    pesos_fuente: dict = field(default_factory=lambda: {
        "DIRECTO": 0.38, "ORGANICO": 0.27, "SOCIAL": 0.18, "REFERIDO": 0.12, "OTROS": 0.05,
    })
    variacion_fuente: float = 0.15
    pesos_dispositivo: dict = field(default_factory=lambda: {"MOVIL": 0.66, "ESCRITORIO": 0.29, "TABLET": 0.05})
    variacion_dispositivo: float = 0.08

    # -- interacciones: tasas esperadas (Poisson) ligadas a la actividad del día
    tasa_chatbot_por_sesion: float = 0.40
    tasa_lugar_por_pagina: float = 0.14
    tasa_restaurante_por_pagina: float = 0.10
    tasa_alojamiento_por_pagina: float = 0.07
    tasa_evento_por_pagina: float = 0.06
    tasa_gastronomia_por_pagina: float = 0.04
    tasa_favorito_por_apertura: float = 0.12  # favoritos / (lugares + restaurantes + alojamientos abiertos)
    tasa_ubicacion_por_apertura: float = 0.30  # clics de mapa / (aperturas de lugar, restaurante, alojamiento, evento)
    tasa_idioma_por_usuario: float = 0.03


# ---------------------------------------------------------------- estructuras

@dataclass
class FilaDiaria:
    fecha: object
    sesiones: int
    paginas_vistas: int
    duracion_total_seg: int
    sesiones_rebote: int
    usuarios_nuevos: int
    usuarios_recurrentes: int
    fuentes: dict
    dispositivos: dict
    interacciones: dict


@dataclass
class FilaUnicos:
    granularidad: str
    inicio: object
    fin: object
    usuarios_recurrentes: int


@dataclass
class DatasetSimulado:
    periodo: object
    semilla: int
    parametros: ParametrosSimulacion
    metas: dict  # (anio, mes) -> objetivo
    diarias: list
    unicos: list
    participantes: int  # solo el conteo: la población nunca se persiste
    checksum: str = ""

    def a_datos(self):
        """Mismo formato que cargar_datos(), para reutilizar resúmenes y validaciones sin tocar la BD."""
        return DatosPeriodo(
            periodo=self.periodo, origen=SIM,
            diarias={f.fecha: {
                "fecha": f.fecha, "sesiones": f.sesiones, "paginas_vistas": f.paginas_vistas,
                "duracion_total_seg": f.duracion_total_seg, "sesiones_rebote": f.sesiones_rebote,
                "usuarios_nuevos": f.usuarios_nuevos, "usuarios_recurrentes": f.usuarios_recurrentes,
            } for f in self.diarias},
            fuentes={f.fecha: dict(f.fuentes) for f in self.diarias},
            dispositivos={f.fecha: dict(f.dispositivos) for f in self.diarias},
            interacciones={f.fecha: dict(f.interacciones) for f in self.diarias},
            unicos={(u.granularidad, u.inicio): {
                "pk": None, "granularidad": u.granularidad, "inicio": u.inicio, "fin": u.fin,
                "usuarios_recurrentes": u.usuarios_recurrentes,
            } for u in self.unicos},
            metas=dict(self.metas),
        )


def calcular_huella(dataset):
    """SHA-256 determinista de lo relevante del dataset (no depende de pks, hora ni orden de consultas)."""
    contenido = {
        "periodo": [dataset.periodo.fecha_inicio.isoformat(), dataset.periodo.fecha_fin.isoformat()],
        "semilla": dataset.semilla,
        "parametros": asdict(dataset.parametros),
        "metas": sorted([anio, mes, objetivo] for (anio, mes), objetivo in dataset.metas.items()),
        "diarias": [
            [f.fecha.isoformat(), f.sesiones, f.paginas_vistas, f.duracion_total_seg, f.sesiones_rebote,
             f.usuarios_nuevos, f.usuarios_recurrentes,
             [f.fuentes[c] for c in FUENTES], [f.dispositivos[c] for c in DISPOSITIVOS],
             [f.interacciones[c] for c in TIPOS]]
            for f in dataset.diarias
        ],
        "unicos": [[u.granularidad, u.inicio.isoformat(), u.fin.isoformat(), u.usuarios_recurrentes] for u in dataset.unicos],
    }
    texto = json.dumps(contenido, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(texto.encode("ascii")).hexdigest()


# ---------------------------------------------------------------- utilidades deterministas

def reparto_entero(total, pesos):
    """Reparte `total` en enteros proporcionales a `pesos` (método del resto mayor). La suma es exacta."""
    suma = sum(pesos)
    if suma <= 0:
        raise ValueError("Los pesos deben sumar más que cero.")
    cuotas = [total * peso / suma for peso in pesos]
    partes = [int(c) for c in cuotas]
    faltan = total - sum(partes)
    for i in sorted(range(len(pesos)), key=lambda i: (-(cuotas[i] - partes[i]), i))[:faltan]:
        partes[i] += 1
    return partes


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limite, k, producto = math.exp(-lam), 0, 1.0
    while True:
        producto *= rng.random()
        if producto <= limite:
            return k
        k += 1


def _acotar(valor, minimo, maximo):
    return max(minimo, min(maximo, valor))


def _lognormal_con_media(rng, media, sigma):
    return rng.lognormvariate(math.log(media) - sigma ** 2 / 2, sigma)


def _es_fin_de_semana(fecha):
    return fecha.weekday() >= 5


# ---------------------------------------------------------------- 1. nuevos por día

def _repartir_nuevos(rng, periodo, metas, dias, p):
    """Cuota mensual -> nuevos por día. Cada incorporación elige su día con pesos: suma exacta por mes."""
    indice = {fecha: i for i, fecha in enumerate(dias)}
    nuevos = [0] * len(dias)
    for intervalo in intervalos_mensuales(periodo.fecha_inicio, periodo.fecha_fin):
        cuota = metas.get((intervalo.inicio.year, intervalo.inicio.month))
        if cuota is None:
            raise SimulacionError(f"Falta la meta mensual de {intervalo.inicio:%m/%Y}.")
        fechas = [intervalo.inicio + timedelta(days=n) for n in range(intervalo.dias)]
        pesos = []
        for n, fecha in enumerate(fechas):
            avance = n / (len(fechas) - 1) if len(fechas) > 1 else 0
            peso = 1 + p.crecimiento_intramensual * avance
            if _es_fin_de_semana(fecha):
                peso *= p.factor_fin_de_semana_nuevos
            pesos.append(peso * _lognormal_con_media(rng, 1.0, p.ruido_nuevos))
        for posicion in rng.choices(range(len(fechas)), weights=pesos, k=cuota):
            nuevos[indice[fechas[posicion]]] += 1
    return nuevos


# ---------------------------------------------------------------- 2. participantes (solo en memoria)

def _simular_visitas(rng, dias, nuevos, factores_dia, p):
    """Devuelve (primera_visita[], visitas[]) por participante, como índices de día. Efímero."""
    primeras = [d for d, n in enumerate(nuevos) for _ in range(n)]
    afinidad = [_lognormal_con_media(rng, 1.0, p.heterogeneidad_retorno) for _ in primeras]
    visitas = [[] for _ in primeras]
    ultimo = max(len(dias) - 1, 1)
    for d, fecha in enumerate(dias):
        intensidad = (1 + p.crecimiento_uso * d / ultimo) * factores_dia[d]
        if _es_fin_de_semana(fecha):
            intensidad *= p.factor_fin_de_semana_retorno
        for i, primera in enumerate(primeras):
            if primera >= d:
                continue
            antiguedad = d - primera
            memoria = p.piso_retorno + (1 - p.piso_retorno) * math.exp(-antiguedad / p.decaimiento_dias)
            prob = min(p.prob_retorno_max, p.prob_retorno_base * afinidad[i] * intensidad * memoria)
            if rng.random() < prob:
                visitas[i].append(d)
    return primeras, visitas


# ---------------------------------------------------------------- 3. métricas de un día

def _sesiones_del_dia(rng, unicos, fecha, factor_dia, p):
    prob = _acotar(p.prob_sesion_extra * (p.factor_fin_de_semana_sesiones if _es_fin_de_semana(fecha) else 1)
                   * factor_dia, 0.0, 0.9)
    total = 0
    for _ in range(unicos):
        sesiones = 1
        if rng.random() < prob:
            sesiones += 1
            while sesiones < p.max_sesiones_por_usuario and rng.random() < p.prob_sesion_extra_adicional:
                sesiones += 1
        total += sesiones
    return total


def _contar_rebotes(rng, sesiones, tasa, p):
    """Sesiones de una sola página. Con pocas sesiones: binomial puro (el ruido de muestra pequeña es real).
    Con suficientes: conteo con ruido reducido y acotado, para no producir rebotes diarios extremos por azar.
    """
    if sesiones < p.sesiones_dia_estable:
        return sum(1 for _ in range(sesiones) if rng.random() < tasa)
    desvio = math.sqrt(sesiones * tasa * (1 - tasa)) * p.ruido_conteo_rebote
    minimo = math.ceil(round(sesiones * p.rebote_limite_inferior, 9))
    maximo = math.floor(round(sesiones * p.rebote_limite_superior, 9))
    return int(_acotar(round(rng.gauss(sesiones * tasa, desvio)), minimo, maximo))


def _navegacion(rng, sesiones, p):
    """(rebotes, páginas, segundos) generados juntos: por construcción páginas >= rebotes + 2·(sesiones − rebotes)."""
    tasa = _acotar(rng.gauss(p.rebote_media, p.rebote_desvio), p.rebote_min, p.rebote_max)
    prob_corte = _acotar(rng.gauss(p.paginas_prob_corte_media, p.paginas_prob_corte_desvio), 0.15, 0.70)
    factor_duracion = _lognormal_con_media(rng, 1.0, p.ruido_duracion_diaria)
    rebotes = _contar_rebotes(rng, sesiones, tasa, p)
    paginas = 0
    segundos = 0.0
    for n in range(sesiones):
        if n < rebotes:
            paginas += 1
            duracion = min(p.seg_max_pagina, _lognormal_con_media(rng, p.seg_rebote_media, p.seg_rebote_sigma))
        else:
            vistas = 2
            while vistas < p.paginas_max_por_sesion and rng.random() > prob_corte:
                vistas += 1
            paginas += vistas
            duracion = sum(
                min(p.seg_max_pagina, _lognormal_con_media(rng, p.seg_por_pagina_media, p.seg_por_pagina_sigma))
                for _ in range(vistas)
            )
        segundos += min(p.seg_max_sesion, duracion * factor_duracion)
    if sesiones >= p.sesiones_dia_estable:
        # Solo puede SUBIR el mínimo: nunca baja de rebotes + 2·(sesiones − rebotes), así que la invariante se conserva.
        paginas = int(_acotar(paginas, math.ceil(round(p.paginas_media_min * sesiones, 9)),
                              math.floor(round(p.paginas_media_max * sesiones, 9))))
        segundos = _acotar(segundos, p.duracion_media_min_seg * sesiones, p.duracion_media_max_seg * sesiones)
    return rebotes, paginas, round(segundos)


def _desglose(rng, sesiones, pesos_base, codigos, variacion):
    pesos = [pesos_base[c] * _lognormal_con_media(rng, 1.0, variacion) for c in codigos]
    return dict(zip(codigos, reparto_entero(sesiones, pesos)))


def _interacciones(rng, usuarios, sesiones, paginas, factor_dia, p):
    def cuenta(esperado):
        return _poisson(rng, esperado * factor_dia)

    lugares = cuenta(paginas * p.tasa_lugar_por_pagina)
    restaurantes = cuenta(paginas * p.tasa_restaurante_por_pagina)
    alojamientos = cuenta(paginas * p.tasa_alojamiento_por_pagina)
    eventos = cuenta(paginas * p.tasa_evento_por_pagina)
    aperturas_fichas = lugares + restaurantes + alojamientos
    return {
        "chatbot_consulta": cuenta(sesiones * p.tasa_chatbot_por_sesion),
        "lugar_detalle_click": lugares,
        "restaurante_detalle_click": restaurantes,
        "alojamiento_detalle_click": alojamientos,
        "evento_detalle_click": eventos,
        "gastronomia_donde_comer_click": cuenta(paginas * p.tasa_gastronomia_por_pagina),
        # nunca más favoritos que aperturas de ficha: son una fracción de ellas
        "favorito_agregado": min(aperturas_fichas, cuenta(aperturas_fichas * p.tasa_favorito_por_apertura)),
        "ubicacion_click": cuenta((aperturas_fichas + eventos) * p.tasa_ubicacion_por_apertura),
        "idioma_cambiado": cuenta(usuarios * p.tasa_idioma_por_usuario),
    }


# ---------------------------------------------------------------- API pública

def simular_periodo(periodo, semilla, parametros=None):
    """Genera el dataset completo en memoria. Determinista para (periodo, metas, semilla, parámetros)."""
    p = parametros or ParametrosSimulacion()
    if periodo.alcance != AlcancePeriodo.MUESTRA_REGISTRADA or not periodo.tamano_muestra:
        raise SimulacionError("Solo se simulan periodos de muestra registrada con tamaño de muestra definido.")
    metas = {(m["anio"], m["mes"]): m["nuevos_objetivo"]
             for m in periodo.metas_mensuales.values("anio", "mes", "nuevos_objetivo")}
    if sum(metas.values()) != periodo.tamano_muestra:
        raise SimulacionError(
            f"Las metas mensuales suman {sum(metas.values())}, no el tamaño de la muestra ({periodo.tamano_muestra})."
        )

    rng = random.Random(semilla)
    dias = [periodo.fecha_inicio + timedelta(days=n) for n in range((periodo.fecha_fin - periodo.fecha_inicio).days + 1)]
    nuevos = _repartir_nuevos(rng, periodo, metas, dias, p)
    factores_dia = [_lognormal_con_media(rng, 1.0, p.ruido_actividad_diaria) for _ in dias]
    primeras, visitas = _simular_visitas(rng, dias, nuevos, factores_dia, p)

    recurrentes = [0] * len(dias)
    for lista in visitas:
        for d in lista:
            recurrentes[d] += 1

    diarias = []
    for d, fecha in enumerate(dias):
        unicos = nuevos[d] + recurrentes[d]
        sesiones = _sesiones_del_dia(rng, unicos, fecha, factores_dia[d], p)
        rebotes, paginas, segundos = _navegacion(rng, sesiones, p) if sesiones else (0, 0, 0)
        diarias.append(FilaDiaria(
            fecha=fecha, sesiones=sesiones, paginas_vistas=paginas, duracion_total_seg=segundos,
            sesiones_rebote=rebotes, usuarios_nuevos=nuevos[d], usuarios_recurrentes=recurrentes[d],
            fuentes=_desglose(rng, sesiones, p.pesos_fuente, FUENTES, p.variacion_fuente),
            dispositivos=_desglose(rng, sesiones, p.pesos_dispositivo, DISPOSITIVOS, p.variacion_dispositivo),
            interacciones=_interacciones(rng, unicos, sesiones, paginas, factores_dia[d], p),
        ))

    # Recurrentes de semana/mes: participantes que visitan el intervalo con primera visita ANTERIOR a su inicio.
    unicos_filas = []
    for granularidad, intervalo in intervalos_esperados(periodo):
        a, b = (intervalo.inicio - periodo.fecha_inicio).days, (intervalo.fin - periodo.fecha_inicio).days
        cuenta = sum(
            1 for primera, lista in zip(primeras, visitas)
            if primera < a and any(a <= d <= b for d in lista)
        )
        unicos_filas.append(FilaUnicos(granularidad, intervalo.inicio, intervalo.fin, cuenta))

    dataset = DatasetSimulado(
        periodo=periodo, semilla=semilla, parametros=p, metas=metas, diarias=diarias, unicos=unicos_filas,
        participantes=len(primeras),
    )
    dataset.checksum = calcular_huella(dataset)
    return dataset


def validar_dataset(dataset):
    """Lista de errores (vacía si el dataset es íntegro y coherente). No toca la BD."""
    errores = []
    periodo = dataset.periodo
    esperados = [periodo.fecha_inicio + timedelta(days=n) for n in range((periodo.fecha_fin - periodo.fecha_inicio).days + 1)]
    if [f.fecha for f in dataset.diarias] != esperados:
        errores.append("La cobertura diaria no es exactamente la del periodo (sin huecos ni fechas fuera de rango).")
    for f in dataset.diarias:
        d = f"{f.fecha:%d/%m/%Y}"
        if min(f.sesiones, f.paginas_vistas, f.duracion_total_seg, f.sesiones_rebote, f.usuarios_nuevos, f.usuarios_recurrentes) < 0:
            errores.append(f"{d}: hay valores negativos.")
        if f.sesiones < f.usuarios_nuevos + f.usuarios_recurrentes:
            errores.append(f"{d}: las sesiones ({f.sesiones}) son menos que los usuarios únicos.")
        if f.sesiones_rebote > f.sesiones:
            errores.append(f"{d}: más rebotes que sesiones.")
        if f.paginas_vistas < f.sesiones_rebote + 2 * (f.sesiones - f.sesiones_rebote):
            errores.append(f"{d}: páginas vistas insuficientes para las sesiones y rebotes.")
        if set(f.fuentes) != set(FUENTES) or sum(f.fuentes.values()) != f.sesiones or min(f.fuentes.values()) < 0:
            errores.append(f"{d}: las fuentes no suman las sesiones.")
        if set(f.dispositivos) != set(DISPOSITIVOS) or sum(f.dispositivos.values()) != f.sesiones or min(f.dispositivos.values()) < 0:
            errores.append(f"{d}: los dispositivos no suman las sesiones.")
        if set(f.interacciones) != set(TIPOS) or min(f.interacciones.values()) < 0:
            errores.append(f"{d}: las interacciones no son los 9 tipos con valores >= 0.")
    if len(dataset.unicos) != len(intervalos_esperados(periodo)):
        errores.append("No coincide el número de intervalos semanales y mensuales de únicos.")
    if any(u.usuarios_recurrentes < 0 for u in dataset.unicos):
        errores.append("Hay recurrentes semanales o mensuales negativos.")
    if sum(f.usuarios_nuevos for f in dataset.diarias) != dataset.participantes:
        errores.append("Los nuevos diarios no suman los participantes simulados.")

    # Mismas reglas que la validación global del Admin: cuotas, recurrentes, cotas de únicos, cobertura…
    resultado = validar_periodo_metricas(periodo, SIM, datos=dataset.a_datos())
    errores += resultado.errores
    if resultado.estado != COMPLETO:
        errores += [f"No concluyente: {a}" for a in resultado.advertencias]
    return errores


def contar_datos_simulados(periodo):
    return {
        "metricas_diarias": MetricaDiaria.objects.filter(periodo=periodo, origen=SIM).count(),
        "interacciones": InteraccionDiaria.objects.filter(periodo=periodo, origen=SIM).count(),
        "unicos": UnicosPeriodo.objects.filter(periodo=periodo, origen=SIM).count(),
    }


def _insertar_metricas(dataset):
    MetricaDiaria.objects.bulk_create([
        MetricaDiaria(
            periodo=dataset.periodo, origen=SIM, fecha=f.fecha, sesiones=f.sesiones, paginas_vistas=f.paginas_vistas,
            duracion_total_seg=f.duracion_total_seg, sesiones_rebote=f.sesiones_rebote,
            usuarios_nuevos=f.usuarios_nuevos, usuarios_recurrentes=f.usuarios_recurrentes, editado_manual=False,
        ) for f in dataset.diarias
    ])
    ids = dict(MetricaDiaria.objects.filter(periodo=dataset.periodo, origen=SIM).values_list("fecha", "pk"))
    MetricaDiariaFuente.objects.bulk_create([
        MetricaDiariaFuente(metrica_diaria_id=ids[f.fecha], fuente=c, sesiones=f.fuentes[c])
        for f in dataset.diarias for c in FUENTES
    ])
    MetricaDiariaDispositivo.objects.bulk_create([
        MetricaDiariaDispositivo(metrica_diaria_id=ids[f.fecha], dispositivo=c, sesiones=f.dispositivos[c])
        for f in dataset.diarias for c in DISPOSITIVOS
    ])


def _insertar_interacciones(dataset):
    InteraccionDiaria.objects.bulk_create([
        InteraccionDiaria(periodo=dataset.periodo, origen=SIM, fecha=f.fecha, tipo=t, cantidad=f.interacciones[t])
        for f in dataset.diarias for t in TIPOS
    ])


def _insertar_unicos(dataset):
    UnicosPeriodo.objects.bulk_create([
        UnicosPeriodo(
            periodo=dataset.periodo, origen=SIM, granularidad=u.granularidad, inicio=u.inicio, fin=u.fin,
            usuarios_recurrentes=u.usuarios_recurrentes,
        ) for u in dataset.unicos
    ])


def persistir_dataset(dataset, reemplazar=False, usuario=None):
    """Escribe el dataset en una transacción y devuelve su GeneracionSimulada.

    - Si falla la validación: no se escribe nada (DatasetInvalido).
    - Si el periodo ya tiene datos SIMULADOS y no se pide `reemplazar`: no se escribe nada.
    - `reemplazar` borra SOLO filas SIMULADO de ESTE periodo (nunca REAL/GA4, ni el periodo, ni sus metas).
    - Si algo falla al escribir, la transacción se revierte entera y se deja una generación FALLIDA.
    """
    errores = validar_dataset(dataset)
    if errores:
        raise DatasetInvalido(errores)
    periodo = dataset.periodo
    try:
        with transaction.atomic():
            existentes = contar_datos_simulados(periodo)
            if any(existentes.values()):
                if not reemplazar:
                    raise DatosSimuladosExistentes(existentes)
                MetricaDiaria.objects.filter(periodo=periodo, origen=SIM).delete()  # arrastra fuentes y dispositivos
                InteraccionDiaria.objects.filter(periodo=periodo, origen=SIM).delete()
                UnicosPeriodo.objects.filter(periodo=periodo, origen=SIM).delete()
                GeneracionSimulada.objects.filter(periodo=periodo, estado=EstadoGeneracion.GENERADA).update(
                    estado=EstadoGeneracion.REEMPLAZADA,
                )
            _insertar_metricas(dataset)
            _insertar_interacciones(dataset)
            _insertar_unicos(dataset)
            verificacion = validar_periodo_metricas(periodo, SIM, datos=cargar_datos(periodo, SIM))
            if verificacion.estado != COMPLETO:
                raise DatasetInvalido(["Lo escrito en la BD no pasa la validación: " + "; ".join(
                    verificacion.errores + verificacion.advertencias)])
            return GeneracionSimulada.objects.create(
                periodo=periodo, semilla=dataset.semilla, usuario=usuario, estado=EstadoGeneracion.GENERADA,
                parametros=asdict(dataset.parametros), filas_diarias=len(dataset.diarias),
                usuarios_objetivo=periodo.tamano_muestra, huella_inicial=dataset.checksum,
            )
    except (DatosSimuladosExistentes, DatasetInvalido):
        raise
    except Exception as exc:
        GeneracionSimulada.objects.create(
            periodo=periodo, semilla=dataset.semilla, usuario=usuario, estado=EstadoGeneracion.FALLIDA,
            parametros=asdict(dataset.parametros), filas_diarias=0, usuarios_objetivo=periodo.tamano_muestra,
            huella_inicial=dataset.checksum, observaciones=f"{type(exc).__name__}: {exc}"[:200],
        )
        raise
