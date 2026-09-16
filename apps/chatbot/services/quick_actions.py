"""
Fast Path: acciones rápidas con intención ya conocida → 0 llamadas de IA.
Registro cerrado: el navegador solo envía un id; el backend resuelve la tool
permitida y sus argumentos controlados, y ejecuta vía TOOL_REGISTRY.
"""
import datetime

from django.utils import timezone

DIAS_EVENTOS_PROXIMOS = 7


class AccionInvalida(ValueError):
    pass


def _eventos_proximos():
    hoy = timezone.localdate()
    return {
        "fecha_desde": hoy.isoformat(),
        "fecha_hasta": (hoy + datetime.timedelta(days=DIAS_EVENTOS_PROXIMOS)).isoformat(),
        # "Próximos" implica fecha confirmada: mes_aproximado/por_confirmar quedan
        # fuera (que_solapan() ya excluye ambos; ver apps.eventos.models).
        "incluir_aproximados": False,
        "limit": 10,
    }


# id → (label humano persistido como mensaje del usuario, tool, argumentos)
QUICK_ACTIONS = {
    "clima_huanuco": ("Clima en Huánuco", "consultar_clima", {"ciudad": "huanuco"}),
    "clima_tingo_maria": ("Clima en Tingo María", "consultar_clima", {"ciudad": "tingo-maria"}),
    "eventos_proximos": ("Eventos próximos", "buscar_eventos", _eventos_proximos),
    "platos_tipicos": ("Platos típicos", "buscar_platos", {"limit": 10}),
    "lugares_destacados": ("Lugares destacados", "buscar_lugares", {"destacado": True, "limit": 10}),
    "restaurantes_destacados": (
        "Restaurantes destacados", "buscar_restaurantes", {"destacado": True, "limit": 10},
    ),
    "alojamientos_destacados": (
        "Alojamientos destacados", "buscar_alojamientos", {"destacado": True, "limit": 10},
    ),
    "tarifas_movilidad": ("Tarifas de movilidad", "consultar_tarifas_movilidad", {}),
    "como_llegar": ("Cómo llegar a Huánuco", "consultar_como_llegar", {}),
    "tipo_cambio": ("Tipo de cambio", "consultar_tipo_cambio", {}),
    # Nivel 1: solo los 3 contactos nacionales; el directorio local se pide
    # aparte indicando la zona (ver natural_quick_actions.detectar_emergencia_zona).
    "emergencias": ("Emergencias", "consultar_emergencias", {"ambito": "nacional", "limit": 3}),
    # C8: la identidad la inyecta el backend (TOOLS_CON_USUARIO); sin botón en la UI.
    "mis_favoritos": ("Mis favoritos", "consultar_favoritos", {"limit": 10}),
}


def resolver(accion_id):
    """→ (label, tool, argumentos). Solo ids registrados; nada viene del cliente."""
    if not isinstance(accion_id, str) or accion_id not in QUICK_ACTIONS:
        raise AccionInvalida(accion_id)
    label, tool, argumentos = QUICK_ACTIONS[accion_id]
    return label, tool, (argumentos() if callable(argumentos) else dict(argumentos))
