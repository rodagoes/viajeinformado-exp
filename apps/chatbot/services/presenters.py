"""
Presentadores: resultado estructurado de un provider C3 → (texto_fallback,
presentacion | None). `presentacion` es un dict JSON-serializable pensado
para que el frontend construya un componente visual claro sin parsear texto;
`texto_fallback` sigue existiendo para clientes que no la usen. Nunca se
persiste en BD ni sustituye la política de tipo_fuente del backend.
"""
import datetime
from decimal import Decimal

from django.urls import reverse
from django.utils.dateformat import format as date_format
from django.utils.dates import MONTHS_3
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from apps.clima.ubicaciones import obtener_ciudad
from apps.emergencias.models import ContactoEmergencia, ZonaAtencionEmergencia
from apps.servicios_turista.services.zonas import nombre_publico_zona

from . import response_renderers
from .providers import INTERNAL
from .providers.favoritos import TIPO_LABEL

# Todo texto visible se resuelve al momento de la petición (idioma activo).
# Los nombres propios que vienen de la BD (eventos, platos, lugares…) no se tocan.


def _mes_abrev(numero):
    return str(MONTHS_3[int(numero)]).upper()


_mes_nombre = response_renderers.nombre_mes
_CONECTORES = {"de", "del", "la", "las", "los", "y", "en", "el"}


def _nombre_legible(nombre):
    """Title-case solo si el nombre está TODO en mayúsculas (dato legado);
    si ya trae mayúsculas/minúsculas propias se conserva tal cual para no
    arriesgar romper siglas o nombres propios (ver auditoría C6.2)."""
    if not nombre or nombre != nombre.upper() or nombre == nombre.lower():
        return nombre
    palabras = nombre.title().split(" ")
    # El primer término conserva mayúscula aunque sea conector ("EL VIAJERO" → "El Viajero").
    return " ".join(p.lower() if i and p.lower() in _CONECTORES else p for i, p in enumerate(palabras))


def _normalizar_simple(texto):
    import re
    import unicodedata
    texto = re.sub(r"[¿¡?!.]", "", (texto or "").strip().lower())
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c)).strip()


# --- Clima -------------------------------------------------------------

def presentar_clima(resultado):
    item = resultado["item"]
    texto = response_renderers.renderizar_clima(resultado)
    if not item.get("disponible"):
        return texto, None

    ciudad_slug = item.get("ciudad_slug")
    ciudad = obtener_ciudad(ciudad_slug)["nombre"] if ciudad_slug else (item.get("ubicacion") or "")
    presentacion = {
        "tipo": "clima",
        "ciudad": ciudad,
        "temperatura": item.get("temperatura_c"),
        "estado": item.get("estado_texto"),
        "sensacion": item.get("sensacion_c"),
        "humedad": item.get("humedad_pct"),
        "viento": item.get("viento_kph"),
        "lluvia": item.get("probabilidad_lluvia_pct"),
        "respaldo": bool(item.get("es_respaldo")),
        "cta": (
            {
                "titulo": _("También te puede interesar"),
                "texto": _("Conoce las temporadas de %(ciudad)s") % {"ciudad": ciudad},
                "label": _("Ver más"),
                "url": f"{reverse('clima:clima_temporadas')}?ciudad={ciudad_slug}",
            }
            if ciudad_slug
            else None
        ),
    }
    return texto, presentacion


# --- Emergencias ---------------------------------------------------------

def _zonas_con_contactos_locales(limit=5):
    zonas = (
        ZonaAtencionEmergencia.objects.filter(
            activo=True, contactos__ambito=ContactoEmergencia.AMBITO_LOCAL, contactos__activo=True
        )
        .select_related("distrito")
        .distinct()
        .order_by("orden")[:limit]
    )
    resultado = []
    for zona in zonas:
        nombre = nombre_publico_zona(zona.distrito)
        resultado.append({"slug": zona.distrito.slug, "nombre": nombre, "mensaje": _("Emergencias en %(zona)s") % {"zona": nombre}})
    return resultado


def resolver_zona_emergencia(texto_zona):
    """slug+nombre si `texto_zona` coincide con una zona real que tiene
    contactos locales registrados (nunca inventa una zona)."""
    objetivo = _normalizar_simple(texto_zona)
    if not objetivo:
        return None
    for zona in _zonas_con_contactos_locales(limit=20):
        if _normalizar_simple(zona["nombre"]) == objetivo:
            return zona
    return None


def _contacto_card(contacto):
    return {
        "nombre": contacto["nombre"],
        "numero": contacto["numero"],
        "numero_tel": contacto["numero_tel"],
        "horario": _("Atención 24/7") if contacto.get("es_24_horas") else (contacto.get("horario") or None),
        "zonas": contacto.get("zonas") or [],
    }


def presentar_emergencias(resultado, zona_nombre=None):
    """
    Nivel 1 (sin distrito, o distrito filtrado que casualmente solo trae
    nacionales): 3 contactos nacionales + invitación a indicar zona.
    Nivel 2 (con distrito, contactos locales encontrados): directorio local.
    Sin contactos locales para la zona pedida: mensaje + nacionales de
    respaldo (nunca se le pide al LLM inventar un directorio).
    """
    texto = response_renderers.renderizar_emergencias(resultado)
    items = resultado.get("items") or []
    todas_nacionales = bool(items) and all(c.get("ambito") == "nacional" for c in items)

    if todas_nacionales or (not items and zona_nombre is None):
        presentacion = {
            "tipo": "emergencias_nacionales",
            "titulo": _("Contactos de emergencia"),
            "items": [_contacto_card(c) for c in items],
            "zona_prompt": _(
                "Si me indicas dónde te encuentras, puedo mostrarte los contactos "
                "de emergencia de esa zona."
            ),
            "zonas": _zonas_con_contactos_locales(),
        }
        return texto, presentacion

    if not items and zona_nombre is not None:
        nacionales = ContactoEmergencia.objects.filter(activo=True, ambito="nacional").order_by("orden")[:3]
        presentacion = {
            "tipo": "emergencias_nacionales",
            "titulo": _("No encontré contactos locales registrados para %(zona)s") % {"zona": zona_nombre},
            "items": [
                {"nombre": c.nombre, "numero": c.numero_visible, "numero_tel": c.numero_tel, "horario": _("Atención 24/7"), "zonas": []}
                for c in nacionales
            ],
            "zona_prompt": None,
            "zonas": [],
        }
        return _("No encontré contactos locales registrados para %(zona)s.") % {"zona": zona_nombre}, presentacion

    titulo = _("Contactos en %(zona)s") % {"zona": zona_nombre} if zona_nombre else _("Contactos de emergencia locales")
    presentacion = {
        "tipo": "emergencias_locales",
        "titulo": titulo,
        "items": [_contacto_card(c) for c in items],
    }
    return texto, presentacion


# --- Eventos ---------------------------------------------------------------

def _fecha_corta(iso):
    anio, mes, dia = iso.split("-")
    return f"{int(dia)} {_mes_abrev(mes)}"


def _fecha_evento_card(item):
    tipo = item.get("tipo_fecha")
    if tipo == "por_confirmar":
        return _("Por confirmar")
    if tipo == "mes_aproximado" and item.get("mes_aproximado"):
        anio = item.get("anio_aproximado")
        return f"{_mes_nombre(item['mes_aproximado']).capitalize()}{f' {anio}' if anio else ''}"
    inicio, fin = item.get("fecha_inicio"), item.get("fecha_fin")
    if inicio and fin and inicio != fin:
        return f"{_fecha_corta(inicio)} – {_fecha_corta(fin)}"
    if inicio:
        return _fecha_corta(inicio)
    return None


def _costo_evento_humano(item):
    tipo = item.get("tipo_costo")
    if tipo in (None, "no_aplica"):
        return None
    if tipo == "gratis":
        return _("Gratis")
    if tipo == "consultar":
        return _("Consultar precio")
    if tipo == "pagado":
        desde, hasta = item.get("precio_desde"), item.get("precio_hasta")
        if desde and hasta and desde != hasta:
            return f"S/ {desde} – S/ {hasta}"
        if desde:
            return _("Desde S/ %(monto)s") % {"monto": desde}
        return _("Consultar precio")
    return None


_ESTADO_EVENTO_HUMANO = {"cancelado": gettext_lazy("Cancelado"), "reprogramado": gettext_lazy("Reprogramado")}


def presentar_eventos(resultado):
    items = resultado.get("items") or []
    if not items:
        url = reverse("eventos:listado_eventos")
        return (
            _("No hay eventos con fecha confirmada para los próximos días.")
            + "\n\n" + _("Ver agenda de eventos: %(url)s") % {"url": url},
            None,
        )
    tarjetas = [
        {
            "fecha": _fecha_evento_card(item),
            "nombre": item["nombre"],
            "ubicacion": item.get("lugar") or item.get("distrito") or item.get("provincia"),
            "costo": _costo_evento_humano(item),
            "estado_especial": str(_ESTADO_EVENTO_HUMANO[item["estado"]]) if item.get("estado") in _ESTADO_EVENTO_HUMANO else None,
            "cta_label": _("Ver evento"),
            "url": item.get("url_listado"),
        }
        for item in items
    ]
    texto = response_renderers.renderizar_eventos(resultado)
    return texto, {"tipo": "eventos", "titulo": _("Eventos próximos"), "items": tarjetas}


# --- Platos típicos ---------------------------------------------------------

def _texto_aspecto(resultado):
    """Respuesta directa al aspecto preguntado con el dato interno registrado."""
    aspecto, items = resultado["aspecto"], resultado["items"]
    partes = []
    for item in items:
        if aspecto == "ingredientes" and item.get("ingredientes"):
            partes.append(
                _("Según la información registrada en Viaje Informado, %(nombre)s lleva como ingredientes clave: %(ingredientes)s.")
                % {"nombre": item["nombre"], "ingredientes": ", ".join(item["ingredientes"])}
            )
        elif aspecto == "descripcion" and item.get("descripcion_corta"):
            partes.append(f"{item['nombre']}: {item['descripcion_corta']}")
        else:
            continue
        if item.get("url_donde_comer"):
            partes.append(_("Ver dónde comer: %(url)s") % {"url": item["url_donde_comer"]})
    return "\n".join(partes)


def presentar_platos_tipicos(resultado):
    items = resultado.get("items") or []
    if not items:
        return str(response_renderers.SIN_RESULTADOS), None
    if resultado.get("aspecto") and resultado.get("evidencia_suficiente"):
        return _texto_aspecto(resultado), None
    tarjetas = [
        {"nombre": p["nombre"], "cta_label": _("Ver dónde comer"), "url": p["url_donde_comer"]}
        for p in items
    ]
    texto = "\n".join(f"- {p['nombre']}" for p in tarjetas)
    return texto, {"tipo": "platos_tipicos", "titulo": _("Platos típicos de Huánuco"), "items": tarjetas}


# --- Lugares turísticos ------------------------------------------------------

_ENTRADA_LIBRE = {"no_requiere", "gratis"}


def _entrada_lugar(item):
    tipo = item.get("tipo_costo")
    if tipo in _ENTRADA_LIBRE:
        return _("Entrada libre")
    if tipo == "consultar":
        return _("Consultar entrada")
    if tipo == "pagado":
        desde, hasta = item.get("precio_desde"), item.get("precio_hasta")
        if desde and hasta and desde != hasta:
            return f"S/ {desde} – S/ {hasta}"
        if desde:
            return _("Desde S/ %(monto)s") % {"monto": desde}
        return _("Consultar entrada")
    return None


def presentar_lugares(resultado):
    items = resultado.get("items") or []
    if not items:
        return str(response_renderers.SIN_RESULTADOS), None
    tarjetas = [
        {
            "nombre": _nombre_legible(lugar["nombre"]),
            "categoria": lugar.get("categoria"),
            "ubicacion": lugar.get("distrito"),
            "descripcion": lugar.get("descripcion_corta") or None,
            "entrada": _entrada_lugar(lugar),
            "horario": lugar.get("horario_visita") or None,
            "cta_label": _("Ver lugar"),
            "url": lugar.get("url"),
        }
        for lugar in items
    ]
    texto = response_renderers.renderizar_lugares(resultado)
    return texto, {"tipo": "lugares", "items": tarjetas}


# --- Movilidad ---------------------------------------------------------------

def presentar_movilidad(resultado):
    items = resultado.get("items") or []
    if not items:
        return str(response_renderers.SIN_RESULTADOS), None
    tarjetas = [
        {
            "tipo": t["nombre"],
            "descripcion": t.get("descripcion") or None,
            "pen": t.get("tarifa_minima_pen"),
            "usd": t.get("tarifa_minima_usd"),
        }
        for t in items
    ]
    # ponytail: cada consejo se muestra con un icono genérico — el texto es
    # libre (editable desde Django admin) y no controlamos su contenido para
    # mapear un icono específico por consejo sin arriesgar inventar sentido.
    recomendaciones = [{"icono": "💡", "texto": c} for c in (resultado.get("consejos") or [])]
    texto = response_renderers.renderizar_tarifas(resultado)
    return texto, {
        "tipo": "movilidad",
        "titulo": _("Transporte y tarifas"),
        "items": tarjetas,
        "recomendaciones": recomendaciones,
    }


# --- Alojamientos / restaurantes ---------------------------------------------

def _precio_rango(item):
    desde, hasta = item.get("precio_desde"), item.get("precio_hasta")
    if desde and hasta and desde != hasta:
        return f"S/ {desde} – S/ {hasta}"
    if desde:
        return _("Desde S/ %(monto)s") % {"monto": desde}
    if hasta:
        return _("Hasta S/ %(monto)s") % {"monto": hasta}
    return None


def _nota_presupuesto(presupuesto, items):
    """Texto honesto sobre el presupuesto: la búsqueda solo garantiza precio_desde
    <= presupuesto; si alguna opción tiene precio_hasta mayor, se avisa."""
    if not presupuesto:
        return None
    maximo = presupuesto["precio_max_pen"]
    conversion = presupuesto.get("conversion")
    origen = (
        _("US$ %(original)s ≈ S/ %(pen)s (tipo de cambio venta %(tc)s del %(fecha)s)") % {
            "original": conversion["monto_original"], "pen": maximo,
            "tc": conversion["tipo_cambio_venta"], "fecha": conversion["fecha_tipo_cambio"],
        }
        if conversion else f"S/ {maximo}"
    )
    excede = any(i.get("excede_presupuesto") for i in items)
    aviso = " " + _("Algunas opciones pueden superar tu presupuesto: revisa el rango de cada una.") if excede else ""
    return _(
        "Presupuesto máximo considerado: %(origen)s. Se muestran opciones cuyo precio mínimo registrado no lo supera."
    ) % {"origen": origen} + aviso


def _establecimiento_card(item, cta_label):
    sucursal = item.get("sucursal") or {}
    return {
        "nombre": _nombre_legible(item["nombre"]),
        "categoria": item.get("categoria"),
        "especialidades": item.get("especialidades") or [],
        "ubicacion": nombre_publico_zona_texto(sucursal),
        "precio": _precio_rango(item),
        "precio_desde": item.get("precio_desde"),
        "precio_hasta": item.get("precio_hasta"),
        "horario": sucursal.get("horario_atencion") or None,
        "cta_label": cta_label,
        "url": item.get("url"),
    }


def nombre_publico_zona_texto(sucursal):
    return sucursal.get("localidad") or sucursal.get("distrito") or None


def _presentar_establecimientos(resultado, tipo, titulo, cta_label):
    items = resultado.get("items") or []
    if not items:
        return response_renderers.renderizar(resultado["tool"], resultado), None
    presupuesto = resultado.get("presupuesto")
    tarjetas = [_establecimiento_card(i, cta_label) for i in items]
    if presupuesto:
        maximo = Decimal(presupuesto["precio_max_pen"])
        for tarjeta in tarjetas:
            hasta = tarjeta.get("precio_hasta")
            tarjeta["excede_presupuesto"] = bool(hasta) and Decimal(hasta) > maximo
    texto = response_renderers.renderizar(resultado["tool"], resultado)
    nota = _nota_presupuesto(presupuesto, tarjetas)
    if nota:
        texto = f"{texto}\n\n{nota}"
    return texto, {"tipo": tipo, "titulo": titulo, "items": tarjetas, "nota": nota}


def presentar_alojamientos(resultado):
    return _presentar_establecimientos(
        resultado, "alojamientos", _("Alojamientos registrados en Viaje Informado"), _("Ver alojamiento")
    )


def presentar_restaurantes(resultado):
    return _presentar_establecimientos(
        resultado, "restaurantes", _("Restaurantes registrados en Viaje Informado"), _("Ver restaurante")
    )


def presentar_restaurantes_por_plato(resultado):
    plato = resultado.get("plato") or {}
    return _presentar_establecimientos(
        resultado, "restaurantes",
        _("Restaurantes donde sirven %(plato)s") % {"plato": plato.get("nombre") or _("ese plato")}, _("Ver dónde comer"),
    )


# --- C8: favoritos -------------------------------------------------------------

TEXTO_FAVORITOS_LOGIN = gettext_lazy("Para consultar tus favoritos necesitas iniciar sesión.")
TEXTO_SIN_FAVORITOS = gettext_lazy(
    "Aún no tienes favoritos guardados. Si quieres, puedo ayudarte a descubrir "
    "lugares, restaurantes o alojamientos."
)
TITULO_SUGERENCIAS = gettext_lazy("Opciones que pueden interesarte")
_PLURAL_FAVORITO = {
    "lugar": gettext_lazy("lugares"), "restaurante": gettext_lazy("restaurantes"),
    "alojamiento": gettext_lazy("alojamientos"),
}
_CTA_FAVORITO = {
    "lugar": gettext_lazy("Ver lugar"), "restaurante": gettext_lazy("Ver restaurante"),
    "alojamiento": gettext_lazy("Ver alojamiento"),
}


def _favorito_card(item):
    tipo = item["tipo"]
    if tipo == "lugar":
        ubicacion, precio = item.get("distrito"), _entrada_lugar(item)
    else:
        ubicacion, precio = nombre_publico_zona_texto(item.get("sucursal") or {}), _precio_rango(item)
    return {
        "tipo": _(TIPO_LABEL[tipo]),
        "nombre": _nombre_legible(item["nombre"]),
        "categoria": item.get("categoria"),
        "ubicacion": ubicacion,
        "precio": precio,
        "motivo": item.get("motivo"),
        "cta_label": str(_CTA_FAVORITO[tipo]),
        "url": item.get("url"),
    }


def presentar_favoritos(resultado):
    if not resultado.get("autenticado"):
        return f"{TEXTO_FAVORITOS_LOGIN}\n\n{_('Iniciar sesión: %(url)s') % {'url': reverse('accounts:login')}}", None
    items = resultado.get("items") or []
    tipo = resultado.get("tipo")
    if not items:
        if tipo:
            return _("No tienes %(plural)s guardados en favoritos.") % {"plural": _PLURAL_FAVORITO[tipo]}, None
        return str(TEXTO_SIN_FAVORITOS), None
    tarjetas = [_favorito_card(i) for i in items]
    sugerencias = [_favorito_card(s) for s in resultado.get("sugerencias") or []]
    texto = response_renderers.renderizar_favoritos(resultado)
    if sugerencias:
        texto += f"\n\n{TITULO_SUGERENCIAS}:\n" + "\n".join(
            f"- {s['nombre']} — {s['motivo']}" for s in sugerencias
        )
    titulo = _("Tus favoritos") + (f" · {str(_PLURAL_FAVORITO[tipo]).capitalize()}" if tipo else "")
    return texto, {
        "tipo": "favoritos",
        "titulo": titulo,
        "items": tarjetas,
        "titulo_sugerencias": str(TITULO_SUGERENCIAS) if sugerencias else None,
        "sugerencias": sugerencias,
    }


# --- C8: itinerario ------------------------------------------------------------

def _fecha_larga(iso):
    anio, mes, dia = iso.split("-")
    return date_format(datetime.date(int(anio), int(mes), int(dia)), _("j \\d\\e F \\d\\e Y"))


def _detalle_actividad(act):
    item, tipo = act["item"], act["tipo"]
    if tipo == "lugar":
        partes = [item.get("categoria"), item.get("distrito"), _entrada_lugar(item)]
    elif tipo == "restaurante":
        sucursal = item.get("sucursal") or {}
        partes = [item.get("categoria"), nombre_publico_zona_texto(sucursal), _precio_rango(item)]
    else:
        partes = [
            _fecha_evento_card(item), item.get("lugar") or item.get("distrito"), _costo_evento_humano(item),
        ]
    return " · ".join(p for p in partes if p) or None


_CTA_ACTIVIDAD = {
    "lugar": gettext_lazy("Ver lugar"), "restaurante": gettext_lazy("Ver restaurante"),
    "evento": gettext_lazy("Ver evento"),
}


def _actividad_card(act):
    item = act["item"]
    return {
        "momento": response_renderers.nombre_momento(act["momento"]),
        "tipo": act["tipo"],
        "nombre": _nombre_legible(item["nombre"]),
        "detalle": _detalle_actividad(act),
        "motivo": act.get("motivo"),
        "cta_label": str(_CTA_ACTIVIDAD[act["tipo"]]),
        "url": item.get("url") or item.get("url_listado"),
    }


def _resumen_presupuesto(it):
    """Textos honestos: presupuesto declarado, costos registrados y margen.
    Nunca afirma precio garantizado ni completa costos desconocidos."""
    presupuesto, costos = it.get("presupuesto"), it["costos"]
    texto_presupuesto = None
    if presupuesto:
        conversion = presupuesto.get("conversion")
        if conversion:
            texto_presupuesto = (
                _("US$ %(original)s ≈ S/ %(pen)s (tipo de cambio venta %(tc)s del %(fecha)s)") % {
                    "original": conversion["monto_original"], "pen": presupuesto["monto_pen"],
                    "tc": conversion["tipo_cambio_venta"], "fecha": conversion["fecha_tipo_cambio"],
                }
            )
        elif presupuesto["moneda"] == "USD":
            texto_presupuesto = _("US$ %(monto)s (sin conversión verificable)") % {"monto": presupuesto["monto"]}
        else:
            texto_presupuesto = f"S/ {presupuesto['monto']}"
    minimo, maximo = costos["conocido_minimo"], costos["conocido_maximo"]
    estimado = (
        _("Costos registrados: desde S/ %(monto)s") % {"monto": minimo}
        + (" " + _("hasta S/ %(monto)s") % {"monto": maximo} if maximo != minimo else "")
        if costos["detalle"] else _("Sin costos registrados verificables para este plan")
    )
    margen = None
    if costos["suficiente"] is True:
        margen = _("Margen aproximado sobre los costos mínimos registrados: S/ %(monto)s") % {"monto": costos["margen"]}
    elif costos["suficiente"] is False:
        faltante = costos["margen"].lstrip("-")
        margen = (
            _("Con los precios registrados, el presupuesto no alcanza para esta combinación (faltan S/ %(monto)s).") % {"monto": faltante}
            + " " + _("Puedo ajustarlo reduciendo costos o mostrando alternativas más económicas.")
        )
    notas = []
    if it.get("aviso_presupuesto"):
        notas.append(it["aviso_presupuesto"])
    if it.get("ajustes_por_presupuesto"):
        notas.append(_("Para acercarme a tu presupuesto retiré: %(lista)s.") % {"lista": ", ".join(it["ajustes_por_presupuesto"])})
    notas.append(_("No incluye: %(lista)s.") % {"lista": ", ".join(costos["no_incluidos"])})
    return texto_presupuesto, estimado, margen, " ".join(notas)


def presentar_itinerario(resultado):
    it = resultado["item"]
    if not it.get("disponible"):
        return (
            _("No tengo suficiente información registrada sobre %(destino)s para proponerte un itinerario: no encontré %(lista)s.")
            % {"destino": it["destino"], "lista": ", ".join(it["sin_datos"])},
            None,
        )
    texto_presupuesto, estimado, margen, nota = _resumen_presupuesto(it)
    alojamiento = None
    if it.get("alojamiento"):
        a = it["alojamiento"]
        alojamiento = {
            **_establecimiento_card(a, _("Ver alojamiento")),
            "precio": (_("%(precio)s por noche") % {"precio": _precio_rango(a)} if _precio_rango(a) else _("Precio por consultar")),
            "cabe_en_presupuesto": a.get("cabe_en_presupuesto"),
            "motivo": a.get("motivo"),
        }
    dias = [
        {
            "fecha": d["fecha"],
            "fecha_texto": _fecha_larga(d["fecha"]),
            "titulo": d["titulo"],
            "actividades": [_actividad_card(a) for a in d["actividades"]],
        }
        for d in it["dias_plan"]
    ]
    presentacion = {
        "tipo": "itinerario",
        "resumen": {
            "destino": it["destino"],
            "fecha_inicio": it["fecha_inicio"],
            "fecha_fin": it["fecha_fin"],
            "fechas_texto": _("Del %(inicio)s al %(fin)s") % {
                "inicio": _fecha_larga(it["fecha_inicio"]), "fin": _fecha_larga(it["fecha_fin"]),
            } + " · " + response_renderers.texto_duracion(it["dias"], it["noches"]),
            "dias": it["dias"],
            "noches": it["noches"],
            "presupuesto": texto_presupuesto,
            "estimado": estimado,
            "margen": margen,
            "nota_presupuesto": nota,
            "favoritos": it.get("favoritos_usados") or [],
            "sin_datos": it.get("sin_datos") or [],
        },
        "alojamiento": alojamiento,
        "platos": it.get("platos_tipicos") or [],
        "dias_plan": dias,
    }
    texto = response_renderers.renderizar_itinerario(resultado)
    extras = [_("Presupuesto: %(valor)s.") % {"valor": texto_presupuesto} if texto_presupuesto else None, estimado + ".", margen, nota]
    if alojamiento:
        extras.insert(0, _("Alojamiento base: %(nombre)s (%(precio)s).") % {"nombre": alojamiento["nombre"], "precio": alojamiento["precio"]})
    if presentacion["resumen"]["favoritos"]:
        extras.append(_("Prioricé tus favoritos: %(lista)s.") % {"lista": ", ".join(presentacion["resumen"]["favoritos"])})
    if presentacion["platos"]:
        extras.append(_("Prueba también: %(lista)s.") % {"lista": ", ".join(p["nombre"] for p in presentacion["platos"])})
    if presentacion["resumen"]["sin_datos"]:
        extras.append(_("No encontré registrados: %(lista)s.") % {"lista": ", ".join(presentacion["resumen"]["sin_datos"])})
    texto = "\n\n".join([texto] + [e for e in extras if e])
    return texto, presentacion


# tipo_fuente cuando el resultado C8 llega "vacío" pero es respuesta completa
TIPO_FUENTE_VACIO = {
    "consultar_favoritos": INTERNAL,
    "planificar_itinerario": "no_evidence",
}


# --- Dispatch ----------------------------------------------------------------

_PRESENTADORES_SIMPLES = {
    "consultar_clima": presentar_clima,
    "buscar_eventos": presentar_eventos,
    "buscar_platos": presentar_platos_tipicos,
    "buscar_lugares": presentar_lugares,
    "consultar_tarifas_movilidad": presentar_movilidad,
    "buscar_alojamientos": presentar_alojamientos,
    "buscar_restaurantes": presentar_restaurantes,
    "buscar_restaurantes_por_plato": presentar_restaurantes_por_plato,
    "consultar_favoritos": presentar_favoritos,
    "planificar_itinerario": presentar_itinerario,
}


def texto_y_presentacion(tool, resultado, zona_nombre=None):
    """(texto_fallback, presentacion|None) para cualquier tool con presentador
    conocido; para el resto, delega en response_renderers (solo texto)."""
    if tool == "consultar_emergencias":
        return presentar_emergencias(resultado, zona_nombre=zona_nombre)
    presentador = _PRESENTADORES_SIMPLES.get(tool)
    if presentador:
        return presentador(resultado)
    return response_renderers.renderizar(tool, resultado), None
