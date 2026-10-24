"""Carga en lote de los datos base de un periodo y origen (número fijo de consultas).

Todos los resúmenes y validaciones parten de aquí, así que nunca hay una consulta por fila.
Siempre filtra por periodo Y origen: los orígenes no se mezclan.
"""
from dataclasses import dataclass, field

from apps.metricas.models import (
    InteraccionDiaria,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    UnicosPeriodo,
)

CAMPOS_BASE = (
    "sesiones", "paginas_vistas", "duracion_total_seg", "sesiones_rebote", "usuarios_nuevos", "usuarios_recurrentes",
)


@dataclass
class DatosPeriodo:
    periodo: object
    origen: str
    diarias: dict = field(default_factory=dict)  # fecha -> {campo base}
    fuentes: dict = field(default_factory=dict)  # fecha -> {fuente: sesiones}
    dispositivos: dict = field(default_factory=dict)  # fecha -> {dispositivo: sesiones}
    interacciones: dict = field(default_factory=dict)  # fecha -> {tipo: cantidad}
    unicos: dict = field(default_factory=dict)  # (granularidad, inicio) -> {pk, fin, usuarios_recurrentes}
    metas: dict = field(default_factory=dict)  # (anio, mes) -> nuevos_objetivo


def _por_fecha(filas, clave_fecha, clave_categoria, clave_valor):
    resultado = {}
    for fila in filas:
        resultado.setdefault(fila[clave_fecha], {})[fila[clave_categoria]] = fila[clave_valor]
    return resultado


def cargar_datos(periodo, origen):
    diarias = MetricaDiaria.objects.filter(periodo=periodo, origen=origen)
    desglose = {"metrica_diaria__periodo": periodo, "metrica_diaria__origen": origen}
    return DatosPeriodo(
        periodo=periodo,
        origen=origen,
        diarias={f["fecha"]: f for f in diarias.values("fecha", *CAMPOS_BASE)},
        fuentes=_por_fecha(
            MetricaDiariaFuente.objects.filter(**desglose).values("metrica_diaria__fecha", "fuente", "sesiones"),
            "metrica_diaria__fecha", "fuente", "sesiones",
        ),
        dispositivos=_por_fecha(
            MetricaDiariaDispositivo.objects.filter(**desglose).values("metrica_diaria__fecha", "dispositivo", "sesiones"),
            "metrica_diaria__fecha", "dispositivo", "sesiones",
        ),
        interacciones=_por_fecha(
            InteraccionDiaria.objects.filter(periodo=periodo, origen=origen).values("fecha", "tipo", "cantidad"),
            "fecha", "tipo", "cantidad",
        ),
        unicos={
            (u["granularidad"], u["inicio"]): u
            for u in UnicosPeriodo.objects.filter(periodo=periodo, origen=origen).values(
                "pk", "granularidad", "inicio", "fin", "usuarios_recurrentes",
            )
        },
        metas={(m["anio"], m["mes"]): m["nuevos_objetivo"] for m in periodo.metas_mensuales.values("anio", "mes", "nuevos_objetivo")},
    )
