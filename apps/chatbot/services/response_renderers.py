"""
Renderers deterministas: resultado estructurado de C3 → texto plano para el
turista. Sin IA, sin HTML, sin ORM, sin request. Nunca completan datos
ausentes ni deducen apertura a partir de horarios en texto libre.
"""
from django.utils.dates import MONTHS
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from apps.emergencias.models import ContactoEmergencia
from apps.servicios_turista.models import ServicioTurista
from apps.turismo.models import DIFICULTAD_CHOICES

# Todo texto visible se traduce al momento de la petición (gettext / lazy): el
# idioma activo lo fija CookieLocaleMiddleware. Los nombres propios que llegan de
# la BD (lugares, eventos, platos…) se muestran tal cual.
SIN_RESULTADOS = gettext_lazy("No encontré información registrada que confirme eso.")

TIPO_COSTO = {
    "gratis": gettext_lazy("entrada gratuita"),
    "no_requiere": gettext_lazy("no requiere entrada"),
    "pagado": gettext_lazy("entrada pagada"),
    "consultar": gettext_lazy("costo por consultar"),
    "no_aplica": gettext_lazy("sin costo aplicable"),
}
RANGO_PRECIO = {
    "economico": gettext_lazy("precio económico"),
    "moderado": gettext_lazy("precio moderado"),
    "alto": gettext_lazy("precio alto"),
    "consultar": gettext_lazy("precio por consultar"),
}
ESTADO_EVENTO = {"reprogramado": gettext_lazy("REPROGRAMADO"), "cancelado": gettext_lazy("CANCELADO")}
DIFICULTAD = dict(DIFICULTAD_CHOICES)
CATEGORIA_EMERGENCIA = dict(ContactoEmergencia.CATEGORIAS)
DISPONIBILIDAD = dict(ServicioTurista.DISPONIBILIDAD_CHOICES)
TIPO_ATENCION = dict(ServicioTurista.TIPO_ATENCION_CHOICES)


def nombre_mes(numero):
    """Nombre del mes en el idioma activo (minúsculas en es, capitalizado en en)."""
    return str(MONTHS[int(numero)])


def _traducir(clave, tabla, defecto=None):
    """Etiqueta de un choice de modelo (se guardan en español) en el idioma activo."""
    etiqueta = tabla.get(clave, defecto)
    return _(etiqueta) if etiqueta else etiqueta


def _unir(*partes, sep=" — "):
    return sep.join(str(p) for p in partes if p)


def _lista(titulo, lineas, pie=None):
    cuerpo = "\n".join(f"- {linea}" for linea in lineas)
    return _unir(titulo, cuerpo, pie, sep="\n")


def _precio(desde, hasta):
    if desde and hasta:
        return _("S/ %(desde)s a S/ %(hasta)s") % {"desde": desde, "hasta": hasta}
    if desde:
        return _("desde S/ %(monto)s") % {"monto": desde}
    if hasta:
        return _("hasta S/ %(monto)s") % {"monto": hasta}
    return None


def _costo(item):
    return _unir(TIPO_COSTO.get(item.get("tipo_costo")), _precio(item.get("precio_desde"), item.get("precio_hasta")), sep=", ")


def _horario(valor):
    return _("Horario registrado: %(valor)s") % {"valor": valor} if valor else None


def _enlace(item, clave="url", etiqueta=gettext_lazy("Ver más")):
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
        _enlace(item, etiqueta=_("Ver lugar")),
    )


def renderizar_lugares(resultado):
    return _lista(_("Lugares turísticos registrados:"), [_lugar(i) for i in resultado["items"]])


def renderizar_lugar(resultado):
    item = resultado["item"]
    lineas = [
        f"{item['nombre']} ({item.get('categoria')})",
        item.get("descripcion_corta"),
        _unir(_("Ubicación:"), _unir(item.get("direccion"), _ubicacion(item), sep=", "), sep=" "),
        _unir(_("Costo:"), _costo(item), sep=" "),
        _horario(item.get("horario_visita")),
        _("Tiempo de visita estimado: %(valor)s") % {"valor": item["tiempo_visita_estimado"]} if item.get("tiempo_visita_estimado") else None,
        _("Dificultad: %(valor)s") % {"valor": _traducir(item.get("dificultad"), DIFICULTAD)} if item.get("dificultad") not in (None, "no_aplica") else None,
        _("Servicios: %(valor)s") % {"valor": ", ".join(item["servicios"])} if item.get("servicios") else None,
        _("Cómo llegar: %(valor)s") % {"valor": item["como_llegar"]} if item.get("como_llegar") else None,
        _("Recomendaciones: %(valor)s") % {"valor": item["recomendaciones"]} if item.get("recomendaciones") else None,
        _enlace(item, etiqueta=_("Ver lugar")),
    ]
    return _unir(*lineas, sep="\n")


# --- Establecimientos -------------------------------------------------------

def _sucursal_texto(sucursal):
    if not sucursal:
        return None
    return _unir(sucursal.get("direccion"), _ubicacion(sucursal), sep=", ")


def _establecimiento(item, etiqueta_cta=None):
    sucursal = item.get("sucursal") or {}
    return _unir(
        f"{item['nombre']} ({item.get('categoria')})",
        _unir(RANGO_PRECIO.get(item.get("rango_precio")), _precio(item.get("precio_desde"), item.get("precio_hasta")), sep=", "),
        _sucursal_texto(sucursal),
        _horario(sucursal.get("horario_atencion")),
        _enlace(item, etiqueta=etiqueta_cta or _("Ver más")),
    )


def renderizar_restaurantes(resultado):
    lineas = [_establecimiento(i, _("Ver restaurante")) for i in resultado["items"]]
    return _lista(_("Restaurantes registrados:"), lineas)


def renderizar_alojamientos(resultado):
    lineas = [_establecimiento(i, _("Ver alojamiento")) for i in resultado["items"]]
    return _lista(_("Alojamientos registrados:"), lineas)


def renderizar_restaurantes_por_plato(resultado):
    plato = resultado.get("plato") or {}
    titulo = _("Restaurantes registrados donde sirven %(plato)s:") % {"plato": plato.get("nombre") or _("ese plato")}
    lineas = [_establecimiento(i, _("Ver dónde comer")) for i in resultado["items"]]
    return _lista(titulo, lineas)


def renderizar_establecimiento(resultado):
    item = resultado["item"]
    etiqueta_cta = _("Ver alojamiento") if item.get("tipo") == "alojamiento" else _("Ver restaurante")
    lineas = [
        f"{item['nombre']} ({item.get('categoria')})",
        item.get("descripcion_corta"),
        _unir(RANGO_PRECIO.get(item.get("rango_precio")), _precio(item.get("precio_desde"), item.get("precio_hasta")), sep=", "),
        _("Servicios: %(valor)s") % {"valor": ", ".join(item["servicios"])} if item.get("servicios") else None,
        _("Recomendaciones de la casa: %(valor)s") % {"valor": ", ".join(r["nombre"] for r in item["recomendaciones"])} if item.get("recomendaciones") else None,
        _unir(_("Contacto:"), _unir(item.get("telefono"), item.get("whatsapp"), item.get("correo"), sep=" / "), sep=" ") if any(item.get(k) for k in ("telefono", "whatsapp", "correo")) else None,
    ]
    for sucursal in item.get("sucursales") or []:
        lineas.append(_unir(_("Sucursal %(nombre)s:") % {"nombre": sucursal["nombre"]}, _sucursal_texto(sucursal), _horario(sucursal.get("horario_atencion")), sep=" "))
    lineas.append(_enlace(item, etiqueta=etiqueta_cta))
    return _unir(*lineas, sep="\n")


# --- Gastronomía ------------------------------------------------------------

def _plato(item):
    return _unir(
        f"{item['nombre']}{_(' (plato bandera)') if item.get('es_plato_bandera') else ''}",
        item.get("descripcion_corta"),
        _enlace(item, clave="url_donde_comer", etiqueta=_("Ver dónde comer")),
    )


def renderizar_platos(resultado):
    return _lista(_("Platos típicos registrados:"), [_plato(i) for i in resultado["items"]])


def renderizar_plato(resultado):
    item = resultado["item"]
    lineas = [
        _plato(item),
        _("Categoría: %(valor)s") % {"valor": item.get("categoria")} if item.get("categoria") else None,
        _("Ingredientes clave: %(valor)s") % {"valor": ", ".join(item["ingredientes"])} if item.get("ingredientes") else None,
    ]
    restaurantes = item.get("restaurantes") or []
    if restaurantes:
        lineas.append(_lista(
            _("Restaurantes registrados donde se sirve:"),
            [_unir(r["nombre"], _enlace(r, etiqueta=_("Ver restaurante"))) for r in restaurantes],
        ))
    return _unir(*lineas, sep="\n")


# --- Eventos ----------------------------------------------------------------

def _fechas_evento(item):
    tipo = item.get("tipo_fecha")
    if tipo == "por_confirmar":
        fechas = _("fecha por confirmar")
    elif tipo == "mes_aproximado" and item.get("mes_aproximado"):
        fechas = _("aproximadamente en %(mes)s de %(anio)s") % {
            "mes": nombre_mes(item["mes_aproximado"]), "anio": item.get("anio_aproximado"),
        }
    elif item.get("fecha_inicio") and item.get("fecha_fin") and item["fecha_inicio"] != item["fecha_fin"]:
        fechas = _("del %(inicio)s al %(fin)s") % {"inicio": item["fecha_inicio"], "fin": item["fecha_fin"]}
    elif item.get("fecha_inicio"):
        fechas = item["fecha_inicio"]
    else:
        fechas = None
    hora = _("desde las %(hora)s") % {"hora": item["hora_inicio"][:5]} if item.get("hora_inicio") else None
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
    return _lista(_("Eventos registrados:"), [_evento(i) for i in resultado["items"]], pie)


def renderizar_evento(resultado):
    item = resultado["item"]
    lineas = [
        _evento(item),
        item.get("descripcion_corta"),
        _("Contexto: %(valor)s") % {"valor": item["contexto_cultural"]} if item.get("contexto_cultural") else None,
        _("Recomendaciones: %(valor)s") % {"valor": item["recomendaciones"]} if item.get("recomendaciones") else None,
        _("Organiza: %(valor)s") % {"valor": item["organizador"]} if item.get("organizador") else None,
        _enlace(item, "url_listado", etiqueta=_("Ver evento")),
    ]
    return _unir(*lineas, sep="\n")


# --- Movilidad --------------------------------------------------------------

def renderizar_tarifas(resultado):
    lineas = [
        _unir(
            _("%(nombre)s: desde S/ %(monto)s") % {
                "nombre": f"{i['nombre']}{' (' + i['nombre_alternativo'] + ')' if i.get('nombre_alternativo') else ''}",
                "monto": i["tarifa_minima_pen"],
            },
            _("aprox. USD %(monto)s") % {"monto": i["tarifa_minima_usd"]} if i.get("tarifa_minima_usd") else None,
            sep=" — ",
        )
        for i in resultado["items"]
    ]
    consejos = resultado.get("consejos") or []
    pie = _unir(
        _lista(_("Consejos:"), consejos) if consejos else None,
        _("Ver más: %(url)s") % {"url": resultado["url"]} if resultado.get("url") else None,
        sep="\n",
    )
    return _lista(_("Tarifas mínimas referenciales de transporte urbano:"), lineas, pie)


_VIAS = {"terrestre": gettext_lazy("terrestre"), "aerea": gettext_lazy("aerea")}


def _via(clave):
    return str(_VIAS.get(clave, clave))


def _ruta(item):
    return _unir(
        _("[Vía %(via)s] %(nombre)s") % {"via": _via(item["via"]), "nombre": item["nombre"]},
        _unir(item.get("origen"), item.get("destino"), sep=" → ") if item.get("origen") or item.get("destino") else None,
        _unir(
            _("en bus: %(valor)s") % {"valor": item["duracion_bus"]} if item.get("duracion_bus") else None,
            _("en auto: %(valor)s") % {"valor": item["duracion_automovil"]} if item.get("duracion_automovil") else None,
            _("duración: %(valor)s") % {"valor": item["duracion_estimada"]} if item.get("duracion_estimada") else None,
            sep=", ",
        ),
        _costo(item),
        _("Advertencias: %(valor)s") % {"valor": item["advertencias"]} if item.get("advertencias") else None,
    )


def renderizar_como_llegar(resultado):
    consejos = resultado.get("consejos") or {}
    pies = [_lista(_("Consejos vía %(via)s:") % {"via": _via(via)}, textos) for via, textos in consejos.items() if textos]
    if resultado.get("url"):
        pies.append(_("Ver más: %(url)s") % {"url": resultado["url"]})
    return _lista(_("Rutas registradas para llegar a Huánuco:"), [_ruta(i) for i in resultado["items"]], _unir(*pies, sep="\n"))


# --- Servicios útiles y emergencias -----------------------------------------

def _servicio(item):
    contactos = ", ".join(f"{c['tipo']}: {c['valor']}" for c in item.get("contactos") or [])
    return _unir(
        f"{item['nombre']} ({item.get('categoria')})",
        _unir(item.get("direccion"), item.get("zona") or item.get("distrito"), sep=", "),
        _traducir(item.get("disponibilidad"), DISPONIBILIDAD),
        _horario(item.get("horario_atencion")),
        _unir(item.get("telefono"), item.get("whatsapp"), contactos, sep=" / ") or None,
    )


def renderizar_servicios(resultado):
    pie = _enlace(resultado["items"][0]) if resultado["items"] else None
    return _lista(_("Servicios útiles registrados:"), [_servicio(i) for i in resultado["items"]], pie)


def _emergencia(item):
    adicionales = ", ".join(
        _unir(n.get("etiqueta"), n["numero"], sep=" ") for n in item.get("numeros_adicionales") or []
    )
    return _unir(
        f"{item['nombre']} ({_traducir(item.get('categoria'), CATEGORIA_EMERGENCIA, item.get('categoria'))}): {item['numero']}",
        adicionales or None,
        item.get("horario"),
        _("zonas: %(valor)s") % {"valor": ", ".join(item["zonas"])} if item.get("zonas") else None,
    )


def renderizar_emergencias(resultado):
    pie = _enlace(resultado["items"][0]) if resultado["items"] else None
    return _lista(_("Contactos de emergencia registrados:"), [_emergencia(i) for i in resultado["items"]], pie)


# --- Clima y tipo de cambio -------------------------------------------------

def renderizar_clima(resultado):
    """
    Solo información turística útil: nunca se menciona el proveedor técnico
    (Open-Meteo) ni la ruta interna de la pantalla de clima — el frontend
    añade su propia sugerencia contextual ("También te puede interesar")
    detectando la primera línea de este texto.
    """
    item = resultado["item"]
    lugar = item.get("ubicacion") or item.get("ciudad_slug") or _("la ciudad")
    if not item.get("disponible"):
        return _("No pude obtener el clima actual de %(lugar)s en este momento.") % {"lugar": lugar}
    resumen = _unir(item.get("estado_texto"), f"{item['temperatura_c']} °C" if item.get("temperatura_c") is not None else None, sep=" · ")
    detalles = [
        _("Sensación térmica: %(valor)s °C") % {"valor": item["sensacion_c"]} if item.get("sensacion_c") is not None else None,
        _("Humedad: %(valor)s%%") % {"valor": item["humedad_pct"]} if item.get("humedad_pct") is not None else None,
        _("Viento: %(valor)s km/h") % {"valor": item["viento_kph"]} if item.get("viento_kph") is not None else None,
        _("Probabilidad de lluvia: %(valor)s%%") % {"valor": item["probabilidad_lluvia_pct"]} if item.get("probabilidad_lluvia_pct") is not None else None,
    ]
    return _unir(
        _("Clima actual en %(lugar)s") % {"lugar": lugar},
        _unir(resumen, *[d for d in detalles if d], sep="\n"),
        _("(dato de respaldo, puede no estar actualizado)") if item.get("es_respaldo") else None,
        sep="\n\n",
    )


def renderizar_tipo_cambio(resultado):
    item = resultado["item"]
    return _unir(
        _("Tipo de cambio %(origen)s/%(destino)s registrado al %(fecha)s: compra S/ %(compra)s, venta S/ %(venta)s.") % {
            "origen": item.get("moneda_origen"), "destino": item.get("moneda_destino"),
            "fecha": item.get("fecha"), "compra": item.get("compra"), "venta": item.get("venta"),
        },
        _("Fuente: %(valor)s") % {"valor": item["fuente"]} if item.get("fuente") else None,
        _enlace(item),
        sep="\n",
    )


# --- C8: favoritos e itinerario -----------------------------------------------

def renderizar_favoritos(resultado):
    lineas = [
        _lugar(item) if item["tipo"] == "lugar" else _establecimiento(item)
        for item in resultado["items"]
    ]
    return _lista(_("Tus favoritos:"), lineas)


def nombre_momento(clave):
    """Momento del día de una actividad del itinerario en el idioma activo."""
    return str(_MOMENTOS.get(clave, clave)).capitalize()


_MOMENTOS = {
    "mañana": gettext_lazy("mañana"), "tarde": gettext_lazy("tarde"), "noche": gettext_lazy("noche"),
}


def texto_duracion(dias, noches):
    return _("%(dias)s, %(noches)s") % {
        "dias": ngettext("%(n)s día", "%(n)s días", dias) % {"n": dias},
        "noches": ngettext("%(n)s noche", "%(n)s noches", noches) % {"n": noches},
    }


def renderizar_itinerario(resultado):
    """Texto plano compacto; presenters.presentar_itinerario añade presupuesto
    y detalle. Nunca completa costos no registrados."""
    it = resultado["item"]
    partes = [
        _("Itinerario propuesto para %(destino)s del %(inicio)s al %(fin)s (%(duracion)s).") % {
            "destino": it["destino"], "inicio": it["fecha_inicio"], "fin": it["fecha_fin"],
            "duracion": texto_duracion(it["dias"], it["noches"]),
        }
    ]
    for dia in it["dias_plan"]:
        lineas = [
            _unir(nombre_momento(act["momento"]), act["item"]["nombre"], sep=": ")
            for act in dia["actividades"]
        ] or [_("sin actividades registradas")]
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
            return _("No encontré restaurantes registrados que sirvan %(plato)s.") % {"plato": plato["nombre"]}
        return str(SIN_RESULTADOS)
    if "item" in resultado and resultado["item"] is None:
        return str(SIN_RESULTADOS)
    return renderer(resultado)
