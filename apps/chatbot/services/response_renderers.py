"""
Renderers deterministas: resultado estructurado de C3 → texto plano para el
turista. Sin IA, sin HTML, sin ORM, sin request. Nunca completan datos
ausentes ni deducen apertura a partir de horarios en texto libre.
"""
from apps.emergencias.models import ContactoEmergencia
from apps.servicios_turista.models import ServicioTurista
from apps.turismo.models import DIFICULTAD_CHOICES

SIN_RESULTADOS = "No encontré información registrada que confirme eso."

TIPO_COSTO = {
    "gratis": "entrada gratuita",
    "no_requiere": "no requiere entrada",
    "pagado": "entrada pagada",
    "consultar": "costo por consultar",
    "no_aplica": "sin costo aplicable",
}
RANGO_PRECIO = {
    "economico": "precio económico",
    "moderado": "precio moderado",
    "alto": "precio alto",
    "consultar": "precio por consultar",
}
ESTADO_EVENTO = {"reprogramado": "REPROGRAMADO", "cancelado": "CANCELADO"}
MESES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIFICULTAD = dict(DIFICULTAD_CHOICES)
CATEGORIA_EMERGENCIA = dict(ContactoEmergencia.CATEGORIAS)
DISPONIBILIDAD = dict(ServicioTurista.DISPONIBILIDAD_CHOICES)
TIPO_ATENCION = dict(ServicioTurista.TIPO_ATENCION_CHOICES)


def _unir(*partes, sep=" — "):
    return sep.join(str(p) for p in partes if p)


def _lista(titulo, lineas, pie=None):
    cuerpo = "\n".join(f"- {linea}" for linea in lineas)
    return _unir(titulo, cuerpo, pie, sep="\n")


def _precio(desde, hasta):
    if desde and hasta:
        return f"S/ {desde} a S/ {hasta}"
    if desde:
        return f"desde S/ {desde}"
    if hasta:
        return f"hasta S/ {hasta}"
    return None


def _costo(item):
    return _unir(TIPO_COSTO.get(item.get("tipo_costo")), _precio(item.get("precio_desde"), item.get("precio_hasta")), sep=", ")


def _horario(valor):
    return f"Horario registrado: {valor}" if valor else None


def _enlace(item, clave="url", etiqueta="Ver más"):
    """
    "Etiqueta: <url>" — el frontend (pillcobot.js) reconoce cualquier línea
    con este patrón y la convierte en un botón con esa etiqueta; la ruta
    interna nunca se muestra como texto suelto al turista.
    """
    return f"{etiqueta}: {item[clave]}" if item.get(clave) else None


def _ubicacion(item):
    return _unir(item.get("localidad"), item.get("distrito"), item.get("provincia"), sep=", ")


# --- Turismo ----------------------------------------------------------------

def _lugar(item):
    return _unir(
        f"{item['nombre']} ({_unir(item.get('categoria'), item.get('distrito'), sep=', ')})",
        _costo(item),
        _horario(item.get("horario_visita")),
        _enlace(item, etiqueta="Ver lugar"),
    )


def renderizar_lugares(resultado):
    return _lista("Lugares turísticos registrados:", [_lugar(i) for i in resultado["items"]])


def renderizar_lugar(resultado):
    item = resultado["item"]
    lineas = [
        f"{item['nombre']} ({item.get('categoria')})",
        item.get("descripcion_corta"),
        _unir("Ubicación:", _unir(item.get("direccion"), _ubicacion(item), sep=", "), sep=" "),
        _unir("Costo:", _costo(item), sep=" "),
        _horario(item.get("horario_visita")),
        f"Tiempo de visita estimado: {item['tiempo_visita_estimado']}" if item.get("tiempo_visita_estimado") else None,
        f"Dificultad: {DIFICULTAD.get(item.get('dificultad'))}" if item.get("dificultad") not in (None, "no_aplica") else None,
        f"Servicios: {', '.join(item['servicios'])}" if item.get("servicios") else None,
        f"Cómo llegar: {item['como_llegar']}" if item.get("como_llegar") else None,
        f"Recomendaciones: {item['recomendaciones']}" if item.get("recomendaciones") else None,
        _enlace(item, etiqueta="Ver lugar"),
    ]
    return _unir(*lineas, sep="\n")


# --- Establecimientos -------------------------------------------------------

def _sucursal_texto(sucursal):
    if not sucursal:
        return None
    return _unir(sucursal.get("direccion"), _ubicacion(sucursal), sep=", ")


def _establecimiento(item, etiqueta_cta="Ver más"):
    sucursal = item.get("sucursal") or {}
    return _unir(
        f"{item['nombre']} ({item.get('categoria')})",
        _unir(RANGO_PRECIO.get(item.get("rango_precio")), _precio(item.get("precio_desde"), item.get("precio_hasta")), sep=", "),
        _sucursal_texto(sucursal),
        _horario(sucursal.get("horario_atencion")),
        _enlace(item, etiqueta=etiqueta_cta),
    )


def renderizar_restaurantes(resultado):
    lineas = [_establecimiento(i, "Ver restaurante") for i in resultado["items"]]
    return _lista("Restaurantes registrados:", lineas)


def renderizar_alojamientos(resultado):
    lineas = [_establecimiento(i, "Ver alojamiento") for i in resultado["items"]]
    return _lista("Alojamientos registrados:", lineas)


def renderizar_restaurantes_por_plato(resultado):
    plato = resultado.get("plato") or {}
    titulo = f"Restaurantes registrados donde sirven {plato.get('nombre', 'ese plato')}:"
    lineas = [_establecimiento(i, "Ver dónde comer") for i in resultado["items"]]
    return _lista(titulo, lineas)


def renderizar_establecimiento(resultado):
    item = resultado["item"]
    etiqueta_cta = "Ver alojamiento" if item.get("tipo") == "alojamiento" else "Ver restaurante"
    lineas = [
        f"{item['nombre']} ({item.get('categoria')})",
        item.get("descripcion_corta"),
        _unir(RANGO_PRECIO.get(item.get("rango_precio")), _precio(item.get("precio_desde"), item.get("precio_hasta")), sep=", "),
        f"Servicios: {', '.join(item['servicios'])}" if item.get("servicios") else None,
        f"Recomendaciones de la casa: {', '.join(r['nombre'] for r in item['recomendaciones'])}" if item.get("recomendaciones") else None,
        _unir("Contacto:", _unir(item.get("telefono"), item.get("whatsapp"), item.get("correo"), sep=" / "), sep=" ") if any(item.get(k) for k in ("telefono", "whatsapp", "correo")) else None,
    ]
    for sucursal in item.get("sucursales") or []:
        lineas.append(_unir(f"Sucursal {sucursal['nombre']}:", _sucursal_texto(sucursal), _horario(sucursal.get("horario_atencion")), sep=" "))
    lineas.append(_enlace(item, etiqueta=etiqueta_cta))
    return _unir(*lineas, sep="\n")


# --- Gastronomía ------------------------------------------------------------

def _plato(item):
    return _unir(
        f"{item['nombre']}{' (plato bandera)' if item.get('es_plato_bandera') else ''}",
        item.get("descripcion_corta"),
        _enlace(item, clave="url_donde_comer", etiqueta="Ver dónde comer"),
    )


def renderizar_platos(resultado):
    return _lista("Platos típicos registrados:", [_plato(i) for i in resultado["items"]])


def renderizar_plato(resultado):
    item = resultado["item"]
    lineas = [
        _plato(item),
        f"Categoría: {item.get('categoria')}" if item.get("categoria") else None,
        f"Ingredientes clave: {', '.join(item['ingredientes'])}" if item.get("ingredientes") else None,
    ]
    restaurantes = item.get("restaurantes") or []
    if restaurantes:
        lineas.append(_lista(
            "Restaurantes registrados donde se sirve:",
            [_unir(r["nombre"], _enlace(r, etiqueta="Ver restaurante")) for r in restaurantes],
        ))
    return _unir(*lineas, sep="\n")


# --- Eventos ----------------------------------------------------------------

def _fechas_evento(item):
    tipo = item.get("tipo_fecha")
    if tipo == "por_confirmar":
        fechas = "fecha por confirmar"
    elif tipo == "mes_aproximado" and item.get("mes_aproximado"):
        fechas = f"aproximadamente en {MESES[item['mes_aproximado']]} de {item.get('anio_aproximado')}"
    elif item.get("fecha_inicio") and item.get("fecha_fin") and item["fecha_inicio"] != item["fecha_fin"]:
        fechas = f"del {item['fecha_inicio']} al {item['fecha_fin']}"
    elif item.get("fecha_inicio"):
        fechas = item["fecha_inicio"]
    else:
        fechas = None
    hora = f"desde las {item['hora_inicio'][:5]}" if item.get("hora_inicio") else None
    return _unir(fechas, hora, sep=", ")


def _evento(item):
    return _unir(
        item["nombre"],
        _fechas_evento(item),
        ESTADO_EVENTO.get(item.get("estado")),
        _unir(item.get("lugar"), item.get("distrito") or item.get("provincia"), sep=", "),
        _costo(item),
    )


def renderizar_eventos(resultado):
    pie = _enlace(resultado["items"][0], "url_listado") if resultado["items"] else None
    return _lista("Eventos registrados:", [_evento(i) for i in resultado["items"]], pie)


def renderizar_evento(resultado):
    item = resultado["item"]
    lineas = [
        _evento(item),
        item.get("descripcion_corta"),
        f"Contexto: {item['contexto_cultural']}" if item.get("contexto_cultural") else None,
        f"Recomendaciones: {item['recomendaciones']}" if item.get("recomendaciones") else None,
        f"Organiza: {item['organizador']}" if item.get("organizador") else None,
        _enlace(item, "url_listado", etiqueta="Ver evento"),
    ]
    return _unir(*lineas, sep="\n")


# --- Movilidad --------------------------------------------------------------

def renderizar_tarifas(resultado):
    lineas = [
        _unir(
            f"{i['nombre']}{f' ({i['nombre_alternativo']})' if i.get('nombre_alternativo') else ''}: desde S/ {i['tarifa_minima_pen']}",
            f"aprox. USD {i['tarifa_minima_usd']}" if i.get("tarifa_minima_usd") else None,
            sep=" — ",
        )
        for i in resultado["items"]
    ]
    consejos = resultado.get("consejos") or []
    pie = _unir(
        _lista("Consejos:", consejos) if consejos else None,
        f"Ver más: {resultado['url']}" if resultado.get("url") else None,
        sep="\n",
    )
    return _lista("Tarifas mínimas referenciales de transporte urbano:", lineas, pie)


def _ruta(item):
    return _unir(
        f"[Vía {item['via']}] {item['nombre']}",
        _unir(item.get("origen"), item.get("destino"), sep=" → ") if item.get("origen") or item.get("destino") else None,
        _unir(
            f"en bus: {item['duracion_bus']}" if item.get("duracion_bus") else None,
            f"en auto: {item['duracion_automovil']}" if item.get("duracion_automovil") else None,
            f"duración: {item['duracion_estimada']}" if item.get("duracion_estimada") else None,
            sep=", ",
        ),
        _costo(item),
        f"Advertencias: {item['advertencias']}" if item.get("advertencias") else None,
    )


def renderizar_como_llegar(resultado):
    consejos = resultado.get("consejos") or {}
    pies = [_lista(f"Consejos vía {via}:", textos) for via, textos in consejos.items() if textos]
    if resultado.get("url"):
        pies.append(f"Ver más: {resultado['url']}")
    return _lista("Rutas registradas para llegar a Huánuco:", [_ruta(i) for i in resultado["items"]], _unir(*pies, sep="\n"))


# --- Servicios útiles y emergencias -----------------------------------------

def _servicio(item):
    contactos = ", ".join(f"{c['tipo']}: {c['valor']}" for c in item.get("contactos") or [])
    return _unir(
        f"{item['nombre']} ({item.get('categoria')})",
        _unir(item.get("direccion"), item.get("zona") or item.get("distrito"), sep=", "),
        DISPONIBILIDAD.get(item.get("disponibilidad")),
        _horario(item.get("horario_atencion")),
        _unir(item.get("telefono"), item.get("whatsapp"), contactos, sep=" / ") or None,
    )


def renderizar_servicios(resultado):
    pie = _enlace(resultado["items"][0]) if resultado["items"] else None
    return _lista("Servicios útiles registrados:", [_servicio(i) for i in resultado["items"]], pie)


def _emergencia(item):
    adicionales = ", ".join(
        _unir(n.get("etiqueta"), n["numero"], sep=" ") for n in item.get("numeros_adicionales") or []
    )
    return _unir(
        f"{item['nombre']} ({CATEGORIA_EMERGENCIA.get(item.get('categoria'), item.get('categoria'))}): {item['numero']}",
        adicionales or None,
        item.get("horario"),
        f"zonas: {', '.join(item['zonas'])}" if item.get("zonas") else None,
    )


def renderizar_emergencias(resultado):
    pie = _enlace(resultado["items"][0]) if resultado["items"] else None
    return _lista("Contactos de emergencia registrados:", [_emergencia(i) for i in resultado["items"]], pie)


# --- Clima y tipo de cambio -------------------------------------------------

def renderizar_clima(resultado):
    """
    Solo información turística útil: nunca se menciona el proveedor técnico
    (Open-Meteo) ni la ruta interna de la pantalla de clima — el frontend
    añade su propia sugerencia contextual ("También te puede interesar")
    detectando la primera línea de este texto.
    """
    item = resultado["item"]
    lugar = item.get("ubicacion") or item.get("ciudad_slug") or "la ciudad"
    if not item.get("disponible"):
        return f"No pude obtener el clima actual de {lugar} en este momento."
    resumen = _unir(item.get("estado_texto"), f"{item['temperatura_c']} °C" if item.get("temperatura_c") is not None else None, sep=" · ")
    detalles = [
        f"Sensación térmica: {item['sensacion_c']} °C" if item.get("sensacion_c") is not None else None,
        f"Humedad: {item['humedad_pct']}%" if item.get("humedad_pct") is not None else None,
        f"Viento: {item['viento_kph']} km/h" if item.get("viento_kph") is not None else None,
        f"Probabilidad de lluvia: {item['probabilidad_lluvia_pct']}%" if item.get("probabilidad_lluvia_pct") is not None else None,
    ]
    return _unir(
        f"Clima actual en {lugar}",
        _unir(resumen, *[d for d in detalles if d], sep="\n"),
        "(dato de respaldo, puede no estar actualizado)" if item.get("es_respaldo") else None,
        sep="\n\n",
    )


def renderizar_tipo_cambio(resultado):
    item = resultado["item"]
    return _unir(
        f"Tipo de cambio {item.get('moneda_origen')}/{item.get('moneda_destino')} registrado al {item.get('fecha')}: compra S/ {item.get('compra')}, venta S/ {item.get('venta')}.",
        f"Fuente: {item['fuente']}" if item.get("fuente") else None,
        _enlace(item),
        sep="\n",
    )


# --- C8: favoritos e itinerario -----------------------------------------------

def renderizar_favoritos(resultado):
    lineas = [
        _lugar(item) if item["tipo"] == "lugar" else _establecimiento(item)
        for item in resultado["items"]
    ]
    return _lista("Tus favoritos:", lineas)


def renderizar_itinerario(resultado):
    """Texto plano compacto; presenters.presentar_itinerario añade presupuesto
    y detalle. Nunca completa costos no registrados."""
    it = resultado["item"]
    partes = [
        f"Itinerario propuesto para {it['destino']} del {it['fecha_inicio']} al {it['fecha_fin']} "
        f"({it['dias']} días, {it['noches']} noches)."
    ]
    for dia in it["dias_plan"]:
        lineas = [
            _unir(act["momento"].capitalize(), act["item"]["nombre"], sep=": ")
            for act in dia["actividades"]
        ] or ["sin actividades registradas"]
        partes.append(_lista(f"{dia['titulo']} ({dia['fecha']})", lineas))
    return "\n\n".join(partes)


RENDERERS = {
    "buscar_lugares": renderizar_lugares,
    "obtener_lugar": renderizar_lugar,
    "buscar_restaurantes": renderizar_restaurantes,
    "buscar_alojamientos": renderizar_alojamientos,
    "obtener_establecimiento": renderizar_establecimiento,
    "buscar_restaurantes_por_plato": renderizar_restaurantes_por_plato,
    "buscar_platos": renderizar_platos,
    "obtener_plato": renderizar_plato,
    "buscar_eventos": renderizar_eventos,
    "obtener_evento": renderizar_evento,
    "consultar_tarifas_movilidad": renderizar_tarifas,
    "consultar_como_llegar": renderizar_como_llegar,
    "consultar_servicios_utiles": renderizar_servicios,
    "consultar_emergencias": renderizar_emergencias,
    "consultar_clima": renderizar_clima,
    "consultar_tipo_cambio": renderizar_tipo_cambio,
    "consultar_favoritos": renderizar_favoritos,
    "planificar_itinerario": renderizar_itinerario,
}
# buscar_ubicaciones queda fuera: es un auxiliar de resolución, no una respuesta al turista.
DIRECT_RENDER_TOOLS = frozenset(RENDERERS)


def renderizar(tool, resultado):
    """Texto para un resultado ok de una tool direct-render; None si no aplica."""
    renderer = RENDERERS.get(tool)
    if renderer is None or not resultado.get("ok"):
        return None
    if "items" in resultado and resultado.get("count", 0) == 0:
        plato = resultado.get("plato")
        if tool == "buscar_restaurantes_por_plato" and plato:
            return f"No encontré restaurantes registrados que sirvan {plato['nombre']}."
        return SIN_RESULTADOS
    if "item" in resultado and resultado["item"] is None:
        return SIN_RESULTADOS
    return renderer(resultado)
