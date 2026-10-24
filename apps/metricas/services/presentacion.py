"""Tablas de texto listas para mostrar en el Admin, construidas desde los resúmenes.

Solo presentación: no se guarda nada y los valores no se redondean antes de formatearse.
"""
from apps.metricas import formatos
from apps.metricas.choices import DispositivoAcceso, FuenteTrafico, TipoInteraccion

from .intervalos import Intervalo, etiqueta_mes, etiqueta_semana


def etiqueta_semanal(resumen):
    return etiqueta_semana(Intervalo(resumen.inicio, resumen.fin))


def etiqueta_mensual(resumen):
    return etiqueta_mes(resumen.inicio.year, resumen.inicio.month)


def _tabla(titulo, encabezados, filas, nota=""):
    return {"titulo": titulo, "encabezados": encabezados, "filas": filas, "nota": nota}


def _por_categoria(titulo, resumenes, etiqueta, opciones, atributo, total_label):
    encabezados = ["Intervalo"] + [nombre for _, nombre in opciones.choices] + [total_label]
    filas = []
    for r in resumenes:
        valores = getattr(r, atributo)
        filas.append(
            [etiqueta(r)] + [str(valores.get(codigo, 0)) for codigo, _ in opciones.choices] + [str(sum(valores.values()))]
        )
    return _tabla(titulo, encabezados, filas)


def tablas_intervalos(resumenes, etiqueta, mensual=False):
    encabezados = [
        "Intervalo", "Días con datos", "Sesiones", "Usuarios nuevos", "Recurrentes", "Únicos", "Páginas vistas",
        "Páginas por sesión", "Duración media", "Tasa de rebote", "% nuevos", "% recurrentes",
    ] + (["Meta de nuevos", "Avance de la meta"] if mensual else [])
    filas = []
    for r in resumenes:
        fila = [
            etiqueta(r), f"{r.dias_con_datos} / {r.dias_totales}", str(r.sesiones), str(r.usuarios_nuevos),
            formatos.entero(r.usuarios_recurrentes), formatos.entero(r.usuarios_unicos), str(r.paginas_vistas),
            formatos.num(r.paginas_por_sesion), formatos.duracion(r.duracion_media), formatos.pct(r.tasa_rebote),
            formatos.pct(r.porcentaje_nuevos), formatos.pct(r.porcentaje_recurrentes),
        ]
        if mensual:
            fila += [formatos.entero(r.meta_objetivo), formatos.pct(r.avance_meta)]
        filas.append(fila)
    nota = (
        "Los usuarios únicos no se suman: = nuevos del intervalo + recurrentes guardados en «Únicos por semana o mes». "
        "«—» indica que falta ese dato (fila de únicos inexistente o sin sesiones)."
    )
    return [
        _tabla("Indicadores", encabezados, filas, nota),
        _por_categoria("Sesiones por fuente de tráfico", resumenes, etiqueta, FuenteTrafico, "fuentes", "Total"),
        _por_categoria("Sesiones por dispositivo", resumenes, etiqueta, DispositivoAcceso, "dispositivos", "Total"),
        _por_categoria("Interacciones", resumenes, etiqueta, TipoInteraccion, "interacciones", "Total"),
    ]


def _distribucion(titulo, valores, opciones, total_sesiones):
    filas = [
        [nombre, str(valores.get(codigo, 0)), formatos.pct(
            None if not total_sesiones else valores.get(codigo, 0) / total_sesiones * 100
        )]
        for codigo, nombre in opciones.choices
    ]
    return _tabla(titulo, ["Categoría", "Sesiones", "% de las sesiones"], filas)


def tablas_total(t):
    es_muestra = t.usuarios_unicos is not None
    unicos = formatos.entero(t.usuarios_unicos)
    if es_muestra and t.tamano_muestra and t.usuarios_unicos < t.tamano_muestra:
        unicos += " (parcial)"
    indicadores = [
        ["Días con datos", f"{t.dias_con_datos} / {t.dias_totales}"],
        ["Sesiones totales", str(t.sesiones)],
        ["Usuarios nuevos totales", str(t.usuarios_nuevos)],
        ["Usuarios únicos de la muestra", unicos],
        ["Avance de la muestra", f"{t.usuarios_nuevos} / {t.tamano_muestra} ({formatos.pct(t.avance_muestra)})"
         if t.tamano_muestra else formatos.SIN_DATO],
        ["Páginas vistas", str(t.paginas_vistas)],
        ["Páginas por sesión", formatos.num(t.paginas_por_sesion)],
        ["Duración media de la sesión", formatos.duracion(t.duracion_media)],
        ["Tasa de rebote", formatos.pct(t.tasa_rebote)],
        ["Interacciones totales", str(t.total_interacciones)],
    ]
    interacciones = [[nombre, str(t.interacciones.get(codigo, 0))] for codigo, nombre in TipoInteraccion.choices]
    return [
        _tabla(
            "Indicadores del periodo", ["Indicador", "Valor"], indicadores,
            "No se muestra % nuevo/recurrente del total: la muestra arranca en cero, así que todos los participantes "
            "son nuevos en algún momento del periodo.",
        ),
        _distribucion("Fuente de tráfico", t.fuentes, FuenteTrafico, t.sesiones),
        _distribucion("Dispositivo", t.dispositivos, DispositivoAcceso, t.sesiones),
        _tabla("Interacciones", ["Interacción", "Cantidad"], interacciones),
    ]
