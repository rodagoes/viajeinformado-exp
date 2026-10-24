"""Validación en servidor de los eventos que llegan desde el navegador.

Nunca se confía en lo que envía el cliente: el tipo debe estar en la lista blanca de eventos de frontend,
la entidad debe existir (y coincidir con el tipo de evento) y `via` debe ser uno de los valores previstos.
La entidad se devuelve en forma canónica (tipo + pk); lo que mande el cliente como tipo de entidad solo se usa
para `ubicacion_click`, y aun así contra una lista cerrada.
"""
import re

from apps.eventos.models import Evento
from apps.establecimientos.models import Establecimiento
from apps.gastronomia.models import PlatoTipico
from apps.metricas.choices import TipoInteraccion
from apps.servicios_turista.models import ServicioTurista
from apps.turismo.models import LugarTuristico

T = TipoInteraccion

# Los eventos server-side (chatbot, favoritos, idioma) NO pueden enviarse desde el navegador.
TIPOS_FRONTEND = {
    T.LUGAR_DETALLE_CLICK, T.RESTAURANTE_DETALLE_CLICK, T.ALOJAMIENTO_DETALLE_CLICK,
    T.EVENTO_DETALLE_CLICK, T.GASTRONOMIA_DONDE_COMER_CLICK, T.UBICACION_CLICK,
}

_VIAS_CONTENIDO = {"listado", "favoritos", "chatbot"}
VIAS = {
    T.LUGAR_DETALLE_CLICK: _VIAS_CONTENIDO,
    T.RESTAURANTE_DETALLE_CLICK: _VIAS_CONTENIDO,
    T.ALOJAMIENTO_DETALLE_CLICK: _VIAS_CONTENIDO,
    T.EVENTO_DETALLE_CLICK: {"agenda"},
    T.GASTRONOMIA_DONDE_COMER_CLICK: {"platos_tipicos"},
    T.UBICACION_CLICK: {"como_llegar", "iniciar_ruta", "abrir_mapa", "servicios_utiles"},
}
ENTIDADES_UBICACION = {"lugar", "establecimiento", "servicio"}
# Modo de desplazamiento de ubicacion_click con via=iniciar_ruta. Para añadir otro (p. ej. transporte público) basta
# agregarlo aquí y en el componente de mapa: el tipo de evento no cambia.
MODOS_RUTA = {"a_pie", "auto"}
_SLUG = re.compile(r"^[-\w]{1,200}$")


def _entero(valor):
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return numero if 0 < numero < 2**31 else None


def _buscar(queryset, entidad_id, entidad_slug):
    """pk de la entidad por id o, si no hay id, por slug; None si no existe o el dato es inválido."""
    if entidad_id is not None:
        return queryset.filter(pk=entidad_id).values_list("pk", flat=True).first()
    if entidad_slug and _SLUG.match(entidad_slug):
        return queryset.filter(slug=entidad_slug).values_list("pk", flat=True).first()
    return None


def validar_evento_frontend(tipo, via, entidad_tipo, entidad_id, entidad_slug, modo=""):
    """(entidad_tipo canónico, entidad pk, meta) o None si el evento no es válido. Hace consultas de existencia."""
    if tipo not in TIPOS_FRONTEND or via not in VIAS[tipo]:
        return None
    meta = {"via": via}
    if tipo == T.UBICACION_CLICK and via == "iniciar_ruta" and modo:
        # `modo` solo aplica a iniciar_ruta y es opcional (clientes antiguos); si llega, debe ser de la lista cerrada.
        # Para cualquier otro tipo/via se ignora sin guardarlo ni rechazar el clic.
        if modo not in MODOS_RUTA:
            return None
        meta["modo"] = modo
    if entidad_id not in (None, ""):
        entidad_id = _entero(entidad_id)
        if entidad_id is None:  # un id enviado pero inválido no se sustituye por el slug
            return None
    else:
        entidad_id = None
    if entidad_id is None and not (entidad_slug and _SLUG.match(entidad_slug)):
        return None

    lugares = LugarTuristico.objects.filter(activo=True)
    establecimientos = Establecimiento.objects.filter(activo=True)
    if tipo == T.LUGAR_DETALLE_CLICK:
        canonico, pk = "lugar", _buscar(lugares, entidad_id, entidad_slug)
    elif tipo == T.RESTAURANTE_DETALLE_CLICK:
        canonico, pk = "establecimiento", _buscar(establecimientos.filter(tipo="restaurante"), entidad_id, entidad_slug)
    elif tipo == T.ALOJAMIENTO_DETALLE_CLICK:
        canonico, pk = "establecimiento", _buscar(establecimientos.filter(tipo="alojamiento"), entidad_id, entidad_slug)
    elif tipo == T.EVENTO_DETALLE_CLICK:
        canonico, pk = "evento", _buscar(Evento.objects.publicados(), entidad_id, None)
    elif tipo == T.GASTRONOMIA_DONDE_COMER_CLICK:
        canonico, pk = "plato", _buscar(PlatoTipico.objects.filter(activo=True), entidad_id, entidad_slug)
    else:  # ubicacion_click: la entidad puede ser un lugar, un establecimiento o un servicio útil
        if entidad_tipo not in ENTIDADES_UBICACION:
            return None
        canonico = entidad_tipo
        origen = {
            "lugar": lugares, "establecimiento": establecimientos, "servicio": ServicioTurista.objects.filter(activo=True),
        }[entidad_tipo]
        pk = _buscar(origen, entidad_id, entidad_slug if entidad_tipo != "servicio" else None)
    if pk is None:
        return None
    return canonico, pk, meta
