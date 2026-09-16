"""
Natural Fast Path: reconoce, con alta confianza, mensajes de texto libre que
significan exactamente lo mismo que una Quick Action ya registrada, para
resolverlos con 0 llamadas de IA. Es una lista blanca de frases (no un
router NLP): ante cualquier duda devuelve None y el mensaje sigue por el
flujo normal del LLM. No decide argumentos ni ejecuta nada — solo mapea
texto → id de QUICK_ACTIONS.
"""
import re
import unicodedata

from . import presenters
from .quick_actions import QUICK_ACTIONS


def _normalizar(texto):
    texto = re.sub(r"[¿¡?!.]", "", texto.strip().lower())
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()


_FRASES = {
    "clima_huanuco": {
        "clima en huanuco", "clima de huanuco", "clima huanuco",
        "como esta el clima en huanuco", "que clima hace en huanuco",
        "temperatura en huanuco", "temperatura de huanuco",
        "cual es la temperatura en huanuco", "que temperatura hace en huanuco",
        "tiempo en huanuco", "como esta el tiempo en huanuco",
    },
    "clima_tingo_maria": {
        "clima en tingo maria", "clima de tingo maria", "clima tingo maria",
        "como esta el clima en tingo maria", "que clima hace en tingo maria",
        "temperatura en tingo maria", "temperatura de tingo maria",
        "cual es la temperatura en tingo maria", "que temperatura hace en tingo maria",
        "tiempo en tingo maria", "como esta el tiempo en tingo maria",
    },
    "tipo_cambio": {
        "tipo de cambio", "cual es el tipo de cambio", "cual es el tipo de cambio hoy",
        "a como esta el dolar", "cuanto esta el dolar", "cuanto esta el dolar hoy",
        "precio del dolar", "cotizacion del dolar",
    },
    "emergencias": {
        "emergencias", "emergencia",
        "numeros de emergencia", "numero de emergencia",
        "contactos de emergencia", "telefonos de emergencia",
    },
    "eventos_proximos": {
        "eventos proximos", "que eventos hay", "que eventos hay proximamente",
        "hay algun evento proximo", "eventos de esta semana",
    },
    "platos_tipicos": {
        "platos tipicos", "cuales son los platos tipicos", "que platos tipicos hay",
        "platos tipicos de huanuco", "cuales son los platos tipicos de huanuco",
    },
    "lugares_destacados": {
        "lugares destacados", "que lugares turisticos hay",
        "lugares turisticos destacados", "que lugares me recomiendas",
    },
    "tarifas_movilidad": {
        "tarifas de movilidad", "tarifa de taxi", "tarifas de taxi",
        "cuanto cuesta el taxi", "precio del taxi",
        # Consultas GENERALES de movilidad (sin origen/destino): §41/§48.
        "como me movilizo en huanuco", "como puedo movilizarme en huanuco",
        "que transportes hay en huanuco", "que transporte hay en huanuco",
        "tarifas de transporte en huanuco", "cuanto cuesta movilizarme en huanuco",
        "cuanto cuesta el mototaxi",
    },
    "mis_favoritos": {
        "mis favoritos", "cuales son mis favoritos", "muestrame mis favoritos",
        "ver mis favoritos", "que tengo en favoritos", "que favoritos tengo",
        "muestrame mis lugares favoritos", "cuales son mis lugares favoritos",
    },
}

assert set(_FRASES) <= set(QUICK_ACTIONS)

# "emergencias en <zona>" / "policía en <zona>" / ... — la zona se valida
# contra datos reales (presenters.resolver_zona_emergencia); si no coincide
# con alguna que tenga contactos locales registrados, no hay match.
_PATRON_EMERGENCIA_ZONA = re.compile(
    r"^(?:emergencias?|policia|contactos? de emergencia|numeros? de emergencia)\s+en\s+(.+)$"
)


def detectar(mensaje):
    """id de QUICK_ACTIONS si el mensaje coincide sin ambigüedad, si no None."""
    normalizado = _normalizar(mensaje)
    for accion_id, frases in _FRASES.items():
        if normalizado in frases:
            return accion_id
    return None


def detectar_emergencia_zona(mensaje):
    """{"slug", "nombre", "mensaje"} si el mensaje pide emergencias de una
    zona real con contactos locales registrados; si no, None."""
    coincidencia = _PATRON_EMERGENCIA_ZONA.match(_normalizar(mensaje))
    if not coincidencia:
        return None
    return presenters.resolver_zona_emergencia(coincidencia.group(1).strip())
