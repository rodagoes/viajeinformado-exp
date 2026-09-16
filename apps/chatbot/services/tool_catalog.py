"""
Catálogo cerrado de herramientas de Pillco Bot. Solo lo registrado aquí
puede ejecutarse; los nombres son estables porque en C4 se expondrán al
modelo de IA (el schema específico del proveedor se define allí, no aquí).
"""
import inspect

from .providers import ArgumentoInvalido
from .providers import (
    establecimientos,
    eventos,
    favoritos,
    gastronomia,
    itinerario,
    movilidad,
    servicios,
    turismo,
    ubicaciones,
)

TOOL_REGISTRY = {
    "buscar_lugares": (
        turismo.buscar_lugares,
        "Busca lugares turísticos activos por texto, categoría, ubicación, costo o dificultad.",
    ),
    "obtener_lugar": (
        turismo.obtener_lugar,
        "Ficha completa de un lugar turístico por slug.",
    ),
    "buscar_ubicaciones": (
        ubicaciones.buscar_ubicaciones,
        "Resuelve departamentos, provincias, distritos o localidades por nombre.",
    ),
    "buscar_restaurantes": (
        establecimientos.buscar_restaurantes,
        "Busca restaurantes activos por texto, categoría, ubicación, rango de precio o servicio.",
    ),
    "buscar_alojamientos": (
        establecimientos.buscar_alojamientos,
        "Busca alojamientos activos por texto, categoría, ubicación, rango de precio o servicio.",
    ),
    "obtener_establecimiento": (
        establecimientos.obtener_establecimiento,
        "Ficha completa de un restaurante o alojamiento por slug, con sus sucursales.",
    ),
    "buscar_restaurantes_por_plato": (
        establecimientos.buscar_restaurantes_por_plato,
        "Restaurantes activos donde se sirve un plato típico (por slug o nombre).",
    ),
    "buscar_platos": (
        gastronomia.buscar_platos,
        "Busca platos típicos activos por texto, categoría o si son plato bandera.",
    ),
    "obtener_plato": (
        gastronomia.obtener_plato,
        "Ficha de un plato típico por slug, con restaurantes donde se sirve.",
    ),
    "buscar_eventos": (
        eventos.buscar_eventos,
        "Busca eventos publicados por texto, categoría, ubicación, costo, tags o rango de fechas ISO.",
    ),
    "obtener_evento": (
        eventos.obtener_evento,
        "Ficha completa de un evento publicado por slug.",
    ),
    "consultar_tarifas_movilidad": (
        movilidad.consultar_tarifas_movilidad,
        "Tarifas mínimas referenciales del transporte urbano (PEN y USD) y consejos.",
    ),
    "consultar_como_llegar": (
        movilidad.consultar_como_llegar,
        "Rutas para llegar a Huánuco por vía terrestre o aérea, con consejos.",
    ),
    "consultar_servicios_utiles": (
        servicios.consultar_servicios_utiles,
        "Servicios útiles para el turista (bancos, farmacias, etc.) por texto, categoría, atención o zona.",
    ),
    "consultar_emergencias": (
        servicios.consultar_emergencias,
        "Contactos de emergencia nacionales y locales por categoría, ámbito o distrito.",
    ),
    "consultar_clima": (
        servicios.consultar_clima,
        "Clima actual de una ciudad soportada (huanuco, tingo-maria). Origen: Open-Meteo.",
    ),
    "consultar_tipo_cambio": (
        servicios.consultar_tipo_cambio,
        "Tipo de cambio USD/PEN vigente (compra y venta).",
    ),
    "consultar_favoritos": (
        favoritos.consultar_favoritos,
        "Favoritos (lugares, restaurantes, alojamientos) del turista autenticado, con sugerencias afines opcionales.",
    ),
    "planificar_itinerario": (
        itinerario.planificar_itinerario,
        "Itinerario propuesto por días entre dos fechas con datos internos y presupuesto opcional.",
    ),
}

# Tools que reciben la identidad del turista desde el backend (kwarg
# keyword-only `usuario`): nunca como argumento del modelo ni del cliente.
TOOLS_CON_USUARIO = frozenset({"consultar_favoritos", "planificar_itinerario"})
_ARGUMENTOS_RESERVADOS = frozenset({"usuario", "user", "user_id", "username", "email", "session_key"})


def listar_herramientas():
    return [
        {"name": nombre, "description": descripcion}
        for nombre, (_, descripcion) in TOOL_REGISTRY.items()
    ]


def obtener_herramienta(nombre):
    if not isinstance(nombre, str) or nombre not in TOOL_REGISTRY:
        raise KeyError(nombre)
    return TOOL_REGISTRY[nombre][0]


def _error(nombre, codigo, detalle=None):
    return {
        "ok": False,
        "tool": nombre if isinstance(nombre, str) else None,
        "error": codigo,
        "detail": detalle,
    }


def ejecutar_herramienta(nombre, argumentos, usuario=None):
    """
    Despacha solo a funciones registradas. Argumentos que no encajan con la
    firma o que el provider rechaza → resultado {"ok": False}. Cualquier otra
    excepción se propaga: un bug interno no se disfraza de "sin resultados".
    `usuario` (contexto seguro del backend) solo llega a TOOLS_CON_USUARIO;
    cualquier intento de pasar identidad en `argumentos` se rechaza.
    """
    try:
        funcion = obtener_herramienta(nombre)
    except KeyError:
        return _error(nombre, "herramienta_desconocida")
    if not isinstance(argumentos, dict):
        return _error(nombre, "argumentos_invalidos", "los argumentos deben ser un objeto")
    if _ARGUMENTOS_RESERVADOS & set(argumentos):
        return _error(nombre, "argumentos_invalidos", "la identidad del usuario no es un argumento")
    contexto = {"usuario": usuario} if nombre in TOOLS_CON_USUARIO else {}

    try:
        inspect.signature(funcion).bind(**argumentos, **contexto)
    except TypeError as exc:
        return _error(nombre, "argumentos_invalidos", str(exc))

    try:
        return funcion(**argumentos, **contexto)
    except ArgumentoInvalido as exc:
        return _error(nombre, "argumento_invalido", str(exc))
