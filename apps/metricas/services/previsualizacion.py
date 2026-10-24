"""Texto de previsualización de un dataset simulado (usa los mismos cálculos que el Admin)."""
from apps.metricas import formatos
from apps.metricas.choices import DispositivoAcceso, FuenteTrafico, OrigenDato, TipoInteraccion

from .diagnostico import diagnosticar_dataset
from .intervalos import etiqueta_mes
from .resumenes import resumen_mensual, resumen_total

SIM = OrigenDato.SIMULADO


def _estado_meta(nuevos, meta):
    if meta is None:
        return "sin meta"
    return "exacta" if nuevos == meta else ("por debajo" if nuevos < meta else "POR ENCIMA")


def _cociente(numerador, denominador):
    return formatos.SIN_DATO if not denominador else formatos.num(numerador / denominador)


def _distribucion(titulo, valores, opciones, sesiones):
    lineas = [f"-- {titulo} --"]
    for codigo, nombre in opciones.choices:
        cantidad = valores.get(codigo, 0)
        porcentaje = formatos.pct(cantidad / sesiones * 100) if sesiones else formatos.SIN_DATO
        lineas.append(f"  {nombre:<22}{cantidad:>8}  {porcentaje:>9}")
    return lineas


def _extremo(texto, minimo, maximo, formato):
    if minimo is None:
        return f"  {texto:<26}{formatos.SIN_DATO}"
    return (f"  {texto:<26}mín {formato(minimo.valor)} ({minimo.fecha:%d/%m})  ·  "
            f"máx {formato(maximo.valor)} ({maximo.fecha:%d/%m})")


def _lineas_diagnostico(dataset):
    d = diagnosticar_dataset(dataset)
    pct = lambda v: formatos.pct(v * 100)  # noqa: E731
    dias = lambda pares: ", ".join(f"{f:%d/%m} ({n})" for f, n in pares)  # noqa: E731
    lineas = [
        "-- DIAGNÓSTICO DE SIMULACIÓN (sanity checks; no son datos empíricos ni objetivos de la tesis) --",
        f"  Días con >= {d.rangos.sesiones_dia_estable} sesiones: {d.dias_estables}",
        _extremo("Rebote diario", d.rebote_min, d.rebote_max, pct),
        _extremo("Duración media diaria", d.duracion_min, d.duracion_max, formatos.duracion),
        _extremo("Páginas por sesión", d.paginas_min, d.paginas_max, formatos.num),
        "  Días sin sesiones:        " + (
            f"{len(d.dias_sin_sesiones)} ({', '.join(f'{f:%d/%m}' for f in d.dias_sin_sesiones[:8])})"
            if d.dias_sin_sesiones else "ninguno"),
        f"  Base consolidada desde:   {d.inicio_base_consolidada:%d/%m/%Y}" if d.inicio_base_consolidada else "",
        (f"  Máx. sesiones/único (día):{d.max_sesiones_por_unico.valor:>6.2f} ({d.max_sesiones_por_unico.fecha:%d/%m})"
         if d.max_sesiones_por_unico else ""),
        (f"  Máx. recurrentes (día):   {int(d.max_recurrentes.valor)} ({d.max_recurrentes.fecha:%d/%m})"
         if d.max_recurrentes else ""),
        f"  Mayor actividad (sesiones): {dias(d.mayor_actividad)}",
        f"  Menor actividad (sesiones): {dias(d.menor_actividad)}",
    ]
    lineas = [x for x in lineas if x]
    if d.advertencias:
        lineas += ["  ADVERTENCIAS:"] + [f"   ! {a}" for a in d.advertencias]
    else:
        lineas.append("  Sin advertencias.")
    return lineas


def lineas_previsualizacion(dataset, con_dias=False):
    periodo = dataset.periodo
    datos = dataset.a_datos()
    total = resumen_total(periodo, SIM, datos=datos)
    lineas = [
        "=== Previsualización del dataset SIMULADO (supuestos de simulación; no son datos reales ni de GA4) ===",
        f"Periodo:              {periodo.nombre} ({periodo.fecha_inicio:%d/%m/%Y} – {periodo.fecha_fin:%d/%m/%Y})",
        f"Semilla:              {dataset.semilla}",
        f"Días:                 {len(dataset.diarias)}",
        f"Usuarios nuevos:      {total.usuarios_nuevos} (muestra: {periodo.tamano_muestra})",
        f"Sesiones:             {total.sesiones}",
        f"Páginas vistas:       {total.paginas_vistas}",
        f"Páginas por sesión:   {formatos.num(total.paginas_por_sesion)}",
        f"Duración media:       {formatos.duracion(total.duracion_media)}",
        f"Tasa de rebote:       {formatos.pct(total.tasa_rebote)}",
        f"Sesiones/usuario de la muestra: {_cociente(total.sesiones, total.usuarios_unicos)}",
        f"Checksum (SHA-256):   {dataset.checksum}",
        "",
        "-- Resumen mensual (nuevos vs. recurrentes) --",
        f"  {'Mes':<16}{'Nuevos':>7}{'Recurr.':>8}{'Únicos':>8}{'% nuevos':>10}{'% recur.':>10}{'Sesiones':>10}"
        f"{'Ses/únic':>9}{'Pág/ses':>9}{'Duración':>10}{'Rebote':>10}{'Meta':>6}  Estado",
    ]
    for mes in resumen_mensual(periodo, SIM, datos=datos):
        lineas.append(
            f"  {etiqueta_mes(mes.inicio.year, mes.inicio.month):<16}{mes.usuarios_nuevos:>7}"
            f"{formatos.entero(mes.usuarios_recurrentes):>8}{formatos.entero(mes.usuarios_unicos):>8}"
            f"{formatos.pct(mes.porcentaje_nuevos):>10}{formatos.pct(mes.porcentaje_recurrentes):>10}{mes.sesiones:>10}"
            f"{_cociente(mes.sesiones, mes.usuarios_unicos):>9}{formatos.num(mes.paginas_por_sesion):>9}"
            f"{formatos.duracion(mes.duracion_media):>10}{formatos.pct(mes.tasa_rebote):>10}"
            f"{formatos.entero(mes.meta_objetivo):>6}  {_estado_meta(mes.usuarios_nuevos, mes.meta_objetivo)}"
        )
    lineas += ["", *_distribucion("Fuente de tráfico", total.fuentes, FuenteTrafico, total.sesiones)]
    lineas += ["", *_distribucion("Dispositivo", total.dispositivos, DispositivoAcceso, total.sesiones)]
    todas = total.total_interacciones
    lineas += ["", "-- Interacciones (totales del periodo) --"]
    for codigo, nombre in TipoInteraccion.choices:
        cantidad = total.interacciones.get(codigo, 0)
        lineas.append(f"  {nombre:<36}{cantidad:>8}  {formatos.pct(cantidad / todas * 100 if todas else None):>9}")
    chatbot = total.interacciones.get("chatbot_consulta", 0)
    lineas += [
        f"  {'Total':<36}{todas:>8}",
        f"  Interacciones/sesión:            {_cociente(todas, total.sesiones)}",
        f"  Consultas al chatbot/sesión:     {_cociente(chatbot, total.sesiones)}",
        f"  Consultas al chatbot/usuario de la muestra: {_cociente(chatbot, periodo.tamano_muestra)}",
        "",
        *_lineas_diagnostico(dataset),
        "",
        f"Filas que se escribirían: {len(dataset.diarias)} métricas diarias, "
        f"{len(dataset.diarias) * len(FuenteTrafico.choices)} de fuente, "
        f"{len(dataset.diarias) * len(DispositivoAcceso.choices)} de dispositivo, "
        f"{len(dataset.diarias) * len(TipoInteraccion.choices)} de interacciones, {len(dataset.unicos)} de únicos.",
    ]
    if con_dias:
        lineas += ["", "-- Detalle diario --", "  Fecha       Nuevos Recurr. Sesiones Páginas Duración"]
        for f in dataset.diarias:
            lineas.append(
                f"  {f.fecha:%d/%m/%Y} {f.usuarios_nuevos:>6} {f.usuarios_recurrentes:>7} {f.sesiones:>8} "
                f"{f.paginas_vistas:>7} {formatos.duracion(f.duracion_total_seg / f.sesiones if f.sesiones else None):>8}"
            )
    return lineas
