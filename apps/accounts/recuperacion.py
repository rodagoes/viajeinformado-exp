"""Estado de la recuperación de contraseña en la sesión: correo solicitado y
cooldown de reenvío. La sesión (servidor) es la fuente de verdad; el contador
del navegador es solo presentación."""
import math
import time

SESSION_KEY = 'recuperacion_password'
COOLDOWN_SEGUNDOS = 120
VIGENCIA_SEGUNDOS = 30 * 60  # pasado este tiempo se olvida el correo y hay que empezar de nuevo


def recordar(request, email):
    request.session[SESSION_KEY] = {'email': email, 'enviado_en': time.time()}


def _estado(session):
    estado = session.get(SESSION_KEY)
    if not estado or time.time() - estado['enviado_en'] > VIGENCIA_SEGUNDOS:
        session.pop(SESSION_KEY, None)
        return None
    return estado


def email_pendiente(session):
    estado = _estado(session)
    return estado['email'] if estado else None


def segundos_restantes(session):
    """None si no hay solicitud reciente; si no, segundos que faltan para poder reenviar."""
    estado = _estado(session)
    if estado is None:
        return None
    return max(0, math.ceil(COOLDOWN_SEGUNDOS - (time.time() - estado['enviado_en'])))
