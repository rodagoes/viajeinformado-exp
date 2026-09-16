"""
Construye el input de Interactions API a partir del historial persistido en
Django (fuente de verdad) más el mensaje actual, que aún no está guardado.
"""
from ..models import Mensaje

MAX_HISTORY_MESSAGES = 8

_TIPO_PASO = {
    Mensaje.Rol.USUARIO: "user_input",
    Mensaje.Rol.ASISTENTE: "model_output",
}


def construir_historial(conversacion):
    """Últimos MAX_HISTORY_MESSAGES en orden cronológico; solo rol y contenido."""
    recientes = conversacion.mensajes.order_by("-creado", "-id")[:MAX_HISTORY_MESSAGES]
    return [{"rol": m.rol, "contenido": m.contenido} for m in reversed(list(recientes))]


def _paso(tipo, texto):
    return {"type": tipo, "content": [{"type": "text", "text": texto}]}


def construir_input(historial, mensaje_actual):
    pasos = [_paso(_TIPO_PASO[m["rol"]], m["contenido"]) for m in historial]
    pasos.append(_paso("user_input", mensaje_actual))
    return pasos
