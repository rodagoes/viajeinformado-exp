"""Resúmenes semanal, mensual y total calculados desde las métricas diarias.

- Magnitudes aditivas: se suman las filas diarias del intervalo.
- Ratios: siempre desde las bases agregadas (nunca promediando ratios diarios).
- Usuarios únicos: NO se suman. Semana/mes: nuevos del intervalo + recurrentes guardados
  en UnicosPeriodo (None si esa fila aún no existe). Total: ver ResumenTotal.
"""
from dataclasses import dataclass, field

from apps.metricas import calculos
from apps.metricas.choices import AlcancePeriodo, DispositivoAcceso, FuenteTrafico, GranularidadUnicos, TipoInteraccion

from .datos import cargar_datos
from .intervalos import intervalos_mensuales, intervalos_semanales


def _ceros(opciones):
    return {valor: 0 for valor, _ in opciones.choices}


@dataclass
class Resumen:
    inicio: object
    fin: object
    dias_totales: int
    dias_con_datos: int
    sesiones: int = 0
    paginas_vistas: int = 0
    duracion_total_seg: int = 0
    sesiones_rebote: int = 0
    usuarios_nuevos: int = 0
    usuarios_recurrentes: int | None = None  # None: no hay fila de UnicosPeriodo (sin dato)
    fuentes: dict = field(default_factory=lambda: _ceros(FuenteTrafico))
    dispositivos: dict = field(default_factory=lambda: _ceros(DispositivoAcceso))
    interacciones: dict = field(default_factory=lambda: _ceros(TipoInteraccion))
    meta_objetivo: int | None = None

    @property
    def usuarios_unicos(self):
        if self.usuarios_recurrentes is None:
            return None
        return self.usuarios_nuevos + self.usuarios_recurrentes

    @property
    def paginas_por_sesion(self):
        return calculos.dividir(self.paginas_vistas, self.sesiones)

    @property
    def duracion_media(self):
        return calculos.dividir(self.duracion_total_seg, self.sesiones)

    @property
    def tasa_rebote(self):
        return calculos.porcentaje(self.sesiones_rebote, self.sesiones)

    @property
    def porcentaje_nuevos(self):
        if self.usuarios_unicos is None:
            return None
        return calculos.porcentaje(self.usuarios_nuevos, self.usuarios_unicos)

    @property
    def porcentaje_recurrentes(self):
        if self.usuarios_unicos is None:
            return None
        return calculos.porcentaje(self.usuarios_recurrentes, self.usuarios_unicos)

    @property
    def avance_meta(self):
        return calculos.porcentaje(self.usuarios_nuevos, self.meta_objetivo) if self.meta_objetivo else None

    @property
    def total_interacciones(self):
        return sum(self.interacciones.values())


@dataclass
class ResumenTotal(Resumen):
    """Todo el periodo. No hay % nuevo/recurrente: la muestra arranca en cero, así que
    todos los participantes son nuevos en algún momento y el indicador no informa.
    """

    tamano_muestra: int | None = None
    alcance: str = ""

    @property
    def usuarios_unicos(self):
        # Solo para muestra registrada: cada participante es nuevo una vez, luego únicos = Σ nuevos.
        return self.usuarios_nuevos if self.alcance == AlcancePeriodo.MUESTRA_REGISTRADA else None

    @property
    def porcentaje_nuevos(self):
        return None

    @property
    def porcentaje_recurrentes(self):
        return None

    @property
    def avance_muestra(self):
        return calculos.porcentaje(self.usuarios_nuevos, self.tamano_muestra) if self.tamano_muestra else None


def agregar(datos, inicio, fin, cls=Resumen, **extra):
    """Suma las filas diarias de [inicio, fin] y sus desgloses."""
    resumen = cls(
        inicio=inicio, fin=fin, dias_totales=(fin - inicio).days + 1,
        dias_con_datos=sum(1 for f in datos.diarias if inicio <= f <= fin), **extra,
    )
    for fecha, fila in datos.diarias.items():
        if not inicio <= fecha <= fin:
            continue
        resumen.sesiones += fila["sesiones"]
        resumen.paginas_vistas += fila["paginas_vistas"]
        resumen.duracion_total_seg += fila["duracion_total_seg"]
        resumen.sesiones_rebote += fila["sesiones_rebote"]
        resumen.usuarios_nuevos += fila["usuarios_nuevos"]
        for destino, por_fecha in ((resumen.fuentes, datos.fuentes), (resumen.dispositivos, datos.dispositivos)):
            for categoria, valor in por_fecha.get(fecha, {}).items():
                destino[categoria] = destino.get(categoria, 0) + valor
    # Las interacciones se suman por su propia fecha: pueden existir sin fila de MetricaDiaria.
    for fecha, tipos in datos.interacciones.items():
        if inicio <= fecha <= fin:
            for tipo, valor in tipos.items():
                resumen.interacciones[tipo] = resumen.interacciones.get(tipo, 0) + valor
    return resumen


def _recurrentes(datos, granularidad, intervalo):
    fila = datos.unicos.get((granularidad, intervalo.inicio))
    return None if fila is None else fila["usuarios_recurrentes"]


def resumen_semanal(periodo, origen, datos=None):
    datos = datos or cargar_datos(periodo, origen)
    return [
        agregar(datos, i.inicio, i.fin, usuarios_recurrentes=_recurrentes(datos, GranularidadUnicos.SEMANA, i))
        for i in intervalos_semanales(periodo.fecha_inicio, periodo.fecha_fin)
    ]


def resumen_mensual(periodo, origen, datos=None):
    datos = datos or cargar_datos(periodo, origen)
    return [
        agregar(
            datos, i.inicio, i.fin, usuarios_recurrentes=_recurrentes(datos, GranularidadUnicos.MES, i),
            meta_objetivo=datos.metas.get((i.inicio.year, i.inicio.month)),
        )
        for i in intervalos_mensuales(periodo.fecha_inicio, periodo.fecha_fin)
    ]


def resumen_total(periodo, origen, datos=None):
    datos = datos or cargar_datos(periodo, origen)
    return agregar(
        datos, periodo.fecha_inicio, periodo.fecha_fin, cls=ResumenTotal,
        tamano_muestra=periodo.tamano_muestra, alcance=periodo.alcance,
    )
