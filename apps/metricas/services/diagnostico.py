"""Diagnóstico estadístico de un dataset simulado: extremos, huecos y señales de plausibilidad.

NO invalida el dataset ni lo modifica. Los rangos son sanity checks de simulación, no datos empíricos
ni objetivos de la tesis.
"""
from dataclasses import dataclass, field
from datetime import date

from apps.metricas.choices import TipoInteraccion


@dataclass(frozen=True)
class RangosDiagnostico:
    sesiones_dia_estable: int = 10  # los extremos solo se juzgan en días con al menos estas sesiones
    rebote: tuple = (0.20, 0.60)
    duracion_media_seg: tuple = (45, 270)
    paginas_por_sesion: tuple = (1.8, 4.5)
    fraccion_base_sin_dias_vacios: float = 0.30  # con esta fracción de la muestra ya incorporada no debería haber días vacíos
    idioma_max_por_sesion: float = 0.10


@dataclass
class Extremo:
    valor: float
    fecha: date


@dataclass
class Diagnostico:
    rangos: RangosDiagnostico
    dias_estables: int = 0
    rebote_min: Extremo | None = None
    rebote_max: Extremo | None = None
    duracion_min: Extremo | None = None
    duracion_max: Extremo | None = None
    paginas_min: Extremo | None = None
    paginas_max: Extremo | None = None
    dias_sin_sesiones: list = field(default_factory=list)
    inicio_base_consolidada: date | None = None
    max_sesiones_por_unico: Extremo | None = None
    max_recurrentes: Extremo | None = None
    mayor_actividad: list = field(default_factory=list)  # [(fecha, sesiones)]
    menor_actividad: list = field(default_factory=list)
    interacciones_por_sesion: float | None = None
    chatbot_por_sesion: float | None = None
    chatbot_por_participante: float | None = None
    idioma_por_sesion: float | None = None
    advertencias: list = field(default_factory=list)


def _extremos(candidatos):
    """((min, fecha), (max, fecha)) de [(valor, fecha)]; desempata por fecha."""
    if not candidatos:
        return None, None
    ordenados = sorted(candidatos, key=lambda c: (c[0], c[1]))
    return Extremo(*ordenados[0]), Extremo(*ordenados[-1])


def diagnosticar_dataset(dataset, rangos=None):
    r = rangos or RangosDiagnostico()
    d = Diagnostico(rangos=r)
    diarias = dataset.diarias
    estables = [f for f in diarias if f.sesiones >= r.sesiones_dia_estable]
    d.dias_estables = len(estables)

    d.rebote_min, d.rebote_max = _extremos([(f.sesiones_rebote / f.sesiones, f.fecha) for f in estables])
    d.duracion_min, d.duracion_max = _extremos([(f.duracion_total_seg / f.sesiones, f.fecha) for f in estables])
    d.paginas_min, d.paginas_max = _extremos([(f.paginas_vistas / f.sesiones, f.fecha) for f in estables])
    d.dias_sin_sesiones = [f.fecha for f in diarias if f.sesiones == 0]
    d.max_sesiones_por_unico = _extremos(
        [(f.sesiones / (f.usuarios_nuevos + f.usuarios_recurrentes), f.fecha)
         for f in diarias if f.usuarios_nuevos + f.usuarios_recurrentes]
    )[1]
    d.max_recurrentes = _extremos([(f.usuarios_recurrentes, f.fecha) for f in diarias])[1]
    por_actividad = sorted(diarias, key=lambda f: (f.sesiones, f.fecha))
    d.menor_actividad = [(f.fecha, f.sesiones) for f in por_actividad[:3]]
    d.mayor_actividad = [(f.fecha, f.sesiones) for f in reversed(por_actividad[-3:])]

    sesiones = sum(f.sesiones for f in diarias)
    totales = {tipo: sum(f.interacciones[tipo] for f in diarias) for tipo, _ in TipoInteraccion.choices}
    if sesiones:
        d.interacciones_por_sesion = sum(totales.values()) / sesiones
        d.chatbot_por_sesion = totales["chatbot_consulta"] / sesiones
        d.idioma_por_sesion = totales["idioma_cambiado"] / sesiones
    if dataset.participantes:
        d.chatbot_por_participante = totales["chatbot_consulta"] / dataset.participantes

    # Primer día en que ya se incorporó la fracción indicada de la muestra.
    incorporados, umbral = 0, r.fraccion_base_sin_dias_vacios * dataset.participantes
    for f in diarias:
        incorporados += f.usuarios_nuevos
        if incorporados >= umbral:
            d.inicio_base_consolidada = f.fecha
            break

    # -- advertencias (nunca invalidan el dataset)
    a = d.advertencias

    def fuera(extremo, rango, texto, formato):
        if extremo is None:
            return
        if not rango[0] <= extremo.valor <= rango[1]:
            a.append(f"{texto} {formato(extremo.valor)} el {extremo.fecha:%d/%m/%Y} fuera de [{formato(rango[0])}, {formato(rango[1])}].")

    pct = lambda v: f"{v * 100:.1f} %"  # noqa: E731
    seg = lambda v: f"{int(v // 60):02d}:{int(v % 60):02d}"  # noqa: E731
    num = lambda v: f"{v:.2f}"  # noqa: E731
    for extremo in (d.rebote_min, d.rebote_max):
        fuera(extremo, r.rebote, "Rebote diario", pct)
    for extremo in (d.duracion_min, d.duracion_max):
        fuera(extremo, r.duracion_media_seg, "Duración media diaria", seg)
    for extremo in (d.paginas_min, d.paginas_max):
        fuera(extremo, r.paginas_por_sesion, "Páginas por sesión diarias", num)
    if d.inicio_base_consolidada:
        vacios = [f for f in d.dias_sin_sesiones if f >= d.inicio_base_consolidada]
        if vacios:
            a.append(
                f"{len(vacios)} día(s) sin sesiones con la base ya consolidada (desde {d.inicio_base_consolidada:%d/%m/%Y}): "
                + ", ".join(f"{f:%d/%m}" for f in vacios[:5]) + "."
            )
    if d.idioma_por_sesion is not None and d.idioma_por_sesion > r.idioma_max_por_sesion:
        a.append(f"El cambio de idioma es frecuente: {d.idioma_por_sesion * 100:.1f} % de las sesiones.")
    for f in diarias:
        if f.sesiones == 0 and any(f.interacciones.values()):
            a.append(f"{f.fecha:%d/%m/%Y}: hay interacciones sin sesiones.")
    return d
