"""
Única fuente neutral de los schemas de las 17 herramientas de C3 (nombre,
descripción, parámetros JSON Schema). Gemini y DeepSeek se adaptan desde
aquí; la ejecución siempre pasa por tool_catalog.ejecutar_herramienta().

Los providers no tienen type hints, así que los schemas se declaran a mano
(una generación automática los dejaría sin tipos ni choices).
"""
from apps.clima.ubicaciones import listar_ciudades
from apps.emergencias.models import ContactoEmergencia
from apps.establecimientos.models import Establecimiento
from apps.eventos.models import Evento
from apps.servicios_turista.models import ServicioTurista
from apps.turismo.models import DIFICULTAD_CHOICES, TIPO_COSTO_CHOICES

from .providers import MAX_LIMIT
from .providers.establecimientos import MONEDA_CHOICES
from .providers.favoritos import TIPO_CHOICES as TIPO_FAVORITO_CHOICES
from .providers.gastronomia import ASPECTO_CHOICES
from .providers.itinerario import MAX_DIAS
from .providers.movilidad import VIA_CHOICES
from .providers.ubicaciones import TIPO_CHOICES as TIPO_UBICACION_CHOICES
from .tool_catalog import TOOL_REGISTRY


def _texto(descripcion):
    return {"type": "string", "description": descripcion}


def _booleano(descripcion):
    return {"type": "boolean", "description": descripcion}


def _enum(descripcion, choices):
    return {"type": "string", "enum": [c[0] for c in choices], "description": descripcion}


def _fecha(descripcion):
    return {"type": "string", "description": f"{descripcion} Formato ISO YYYY-MM-DD."}


_LIMIT = {
    "type": "integer",
    "minimum": 1,
    "maximum": MAX_LIMIT,
    "description": f"Cantidad máxima de resultados (1 a {MAX_LIMIT}, por defecto 5).",
}
_DISTRITO = _texto(
    "Slug del distrito (ej. huanuco, amarilis, rupa-rupa). Si no lo conoces, resuélvelo antes con buscar_ubicaciones."
)
_PROVINCIA = _texto(
    "Slug de la provincia (ej. huanuco, leoncio-prado). Si no lo conoces, resuélvelo antes con buscar_ubicaciones."
)
_SLUG = _texto("Slug exacto tal como aparece en resultados previos de una herramienta buscar_*.")
_Q = _texto("Texto libre a buscar en el nombre y la descripción.")
_ASPECTO = _enum(
    "Dato concreto que pregunta el usuario sobre el plato (ingredientes, qué es, preparación, origen). "
    "Indícalo siempre que la pregunta sea sobre uno de esos aspectos y no un listado.",
    ASPECTO_CHOICES,
)


def _establecimiento_props():
    return {
        "q": _Q,
        "categoria": _texto(
            "Slug o nombre de la categoría/especialidad (ej. hotel, hostal, parrillas, criollo). "
            "Omítela para 'hotel' u 'hospedaje' en sentido genérico; úsala solo si el usuario pide una categoría concreta."
        ),
        "distrito": _DISTRITO,
        "provincia": _PROVINCIA,
        "rango_precio": _enum("Rango de precio.", Establecimiento.RANGO_PRECIO_CHOICES),
        "servicio": _texto("Slug de un servicio o amenidad (ej. wifi, estacionamiento)."),
        "destacado": _booleano("true para devolver solo establecimientos destacados."),
        "precio_max": {
            "type": "number",
            "minimum": 0,
            "description": (
                "Presupuesto máximo (por noche en alojamientos). Devuelve solo establecimientos cuyo "
                "precio mínimo registrado no lo supera; el rango real de precios viene en cada resultado."
            ),
        },
        "moneda": _enum(
            "Moneda de precio_max. USD se convierte con el tipo de cambio vigente registrado; por defecto PEN.",
            MONEDA_CHOICES,
        ),
        "limit": _LIMIT,
    }


ESQUEMAS = {
    "buscar_lugares": {
        "properties": {
            "q": _Q,
            "categoria": _texto("Slug de la categoría del lugar turístico."),
            "distrito": _DISTRITO,
            "provincia": _PROVINCIA,
            "tipo_costo": _enum("Tipo de costo de la entrada.", TIPO_COSTO_CHOICES),
            "dificultad": _enum("Dificultad de la visita.", DIFICULTAD_CHOICES),
            "destacado": _booleano("true para devolver solo lugares destacados."),
            "limit": _LIMIT,
        },
    },
    "obtener_lugar": {"properties": {"slug": _SLUG}, "required": ["slug"]},
    "buscar_ubicaciones": {
        "properties": {
            "q": _texto("Nombre del lugar a resolver (ej. Huánuco, Tingo María, Amarilis)."),
            "tipo": _enum("Limita el nivel territorial devuelto.", TIPO_UBICACION_CHOICES),
            "limit": _LIMIT,
        },
        "required": ["q"],
    },
    "buscar_restaurantes": {"properties": _establecimiento_props()},
    "buscar_alojamientos": {"properties": _establecimiento_props()},
    "obtener_establecimiento": {"properties": {"slug": _SLUG}, "required": ["slug"]},
    "buscar_restaurantes_por_plato": {
        "properties": {
            "plato": _texto("Slug o nombre del plato típico (ej. pachamanca, locro de gallina)."),
            "distrito": _DISTRITO,
            "provincia": _PROVINCIA,
            "limit": _LIMIT,
        },
        "required": ["plato"],
    },
    "buscar_platos": {
        "properties": {
            "q": _Q,
            "categoria": _texto("Slug de la categoría del plato típico."),
            "es_plato_bandera": _booleano("true para devolver solo platos bandera de Huánuco."),
            "aspecto": _ASPECTO,
            "limit": _LIMIT,
        },
    },
    "obtener_plato": {"properties": {"slug": _SLUG, "aspecto": _ASPECTO}, "required": ["slug"]},
    "buscar_eventos": {
        "properties": {
            "q": _Q,
            "categoria": _texto("Slug de la categoría del evento."),
            "provincia": _PROVINCIA,
            "distrito": _DISTRITO,
            "tipo_costo": _enum("Tipo de costo del evento.", Evento.TIPO_COSTO_CHOICES),
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Slugs de tags de experiencia (ej. familias, aventura).",
            },
            "fecha_desde": _fecha("Inicio del rango de fechas a consultar."),
            "fecha_hasta": _fecha("Fin del rango de fechas a consultar (por defecto igual a fecha_desde)."),
            "incluir_aproximados": _booleano(
                "Incluir eventos con mes aproximado o fecha por confirmar. Por defecto true sin rango de fechas y false con rango."
            ),
            "limit": _LIMIT,
        },
    },
    "obtener_evento": {"properties": {"slug": _SLUG}, "required": ["slug"]},
    "consultar_tarifas_movilidad": {"properties": {}},
    "consultar_como_llegar": {
        "properties": {
            "via": _enum("Vía de llegada a Huánuco; omite para ambas.", VIA_CHOICES),
            "limit": _LIMIT,
        },
    },
    "consultar_servicios_utiles": {
        "properties": {
            "q": _Q,
            "categoria": _texto("Slug de la categoría del servicio (ej. farmacias, bancos)."),
            "tipo_atencion": _enum("Modalidad de atención.", ServicioTurista.TIPO_ATENCION_CHOICES),
            "disponibilidad": _enum("Disponibilidad del servicio.", ServicioTurista.DISPONIBILIDAD_CHOICES),
            "distrito": _DISTRITO,
            "provincia": _PROVINCIA,
            "limit": _LIMIT,
        },
    },
    "consultar_emergencias": {
        "properties": {
            "categoria": _enum("Tipo de contacto de emergencia.", ContactoEmergencia.CATEGORIAS),
            "ambito": _enum("nacional o local; omite para ambos.", ContactoEmergencia.AMBITOS),
            "distrito": _DISTRITO,
            "solo_24_horas": _booleano("true para devolver solo contactos con atención 24 horas."),
            "limit": _LIMIT,
        },
    },
    "consultar_clima": {
        "properties": {
            "ciudad": _enum(
                "Ciudad soportada; por defecto huanuco.",
                [(c["slug"], c["nombre"]) for c in listar_ciudades()],
            ),
        },
    },
    "consultar_tipo_cambio": {"properties": {}},
    "consultar_favoritos": {
        "properties": {
            "tipo": _enum("Limita el tipo de favorito; omite para todos.", TIPO_FAVORITO_CHOICES),
            "sugerencias": _booleano(
                "true cuando el usuario pide recomendaciones a partir de sus favoritos: añade opciones afines explicadas."
            ),
            "limit": _LIMIT,
        },
    },
    "planificar_itinerario": {
        "properties": {
            "fecha_inicio": _fecha("Primer día del viaje."),
            "fecha_fin": _fecha(f"Último día del viaje (máximo {MAX_DIAS} días en total)."),
            "presupuesto": {
                "type": "number", "minimum": 0,
                "description": "Presupuesto para gastos durante la estadía, si el usuario lo indica.",
            },
            "moneda": _enum("Moneda del presupuesto; por defecto PEN.", MONEDA_CHOICES),
            "distrito": _DISTRITO,
            "provincia": _PROVINCIA,
        },
        "required": ["fecha_inicio", "fecha_fin"],
    },
}

# Matices que ayudan al modelo a elegir entre herramientas parecidas.
DESCRIPCIONES = {
    "buscar_lugares": "Lista lugares turísticos activos filtrando por texto, categoría, ubicación, costo o dificultad. Para la ficha completa de uno concreto usa obtener_lugar.",
    "obtener_lugar": "Ficha completa de UN lugar turístico por su slug (descripción, servicios, cómo llegar, recomendaciones, coordenadas).",
    "buscar_restaurantes": "Lista restaurantes activos por texto, categoría, ubicación, rango de precio o servicio. Si el usuario pregunta dónde comer un plato concreto, usa buscar_restaurantes_por_plato.",
    "buscar_restaurantes_por_plato": "Restaurantes activos donde se sirve un plato típico concreto (por slug o nombre). Devuelve también el plato resuelto.",
    "buscar_eventos": "Lista eventos publicados por texto, categoría, ubicación, costo, tags o rango de fechas ISO. Convierte expresiones como 'este fin de semana' a fechas antes de llamarla. Para la ficha completa usa obtener_evento.",
    "obtener_evento": "Ficha completa de UN evento publicado por su slug (descripción, contexto cultural, recomendaciones, organizador, contacto).",
    "consultar_favoritos": "Favoritos guardados por el usuario actual (el sistema ya sabe quién es; no pidas ni envíes su identidad). Con sugerencias=true añade opciones afines a sus favoritos, explicadas. Si devuelve autenticado=false, el usuario debe iniciar sesión.",
    "planificar_itinerario": "Itinerario propuesto por días (lugares, comida, alojamiento base, eventos confirmados) entre fecha_inicio y fecha_fin, con presupuesto opcional convertido con el tipo de cambio registrado. Úsala sola, en una única llamada, cuando el usuario pide un plan/itinerario de viaje con fechas.",
}

TOOL_SCHEMAS = {
    nombre: {
        "description": DESCRIPCIONES.get(nombre, descripcion),
        "parameters": {
            "type": "object",
            "properties": ESQUEMAS[nombre]["properties"],
            "required": ESQUEMAS[nombre].get("required", []),
        },
    }
    for nombre, (_, descripcion) in TOOL_REGISTRY.items()
}


def declaraciones_funcion():
    """{type: function, name, description, parameters}: el mismo formato es
    válido para Gemini Interactions API y para DeepSeek Responses API."""
    return [
        {"type": "function", "name": nombre, **schema}
        for nombre, schema in TOOL_SCHEMAS.items()
    ]
