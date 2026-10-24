"""Cifras públicas del home (solo lectura). Reutiliza resumen_total; no agrega lógica de agregación propia."""
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.metricas.choices import OrigenDato, TipoInteraccion
from apps.metricas.models import MetricaDiaria

from .resumenes import resumen_total


def usuarios_registrados():
    """Cuentas reales de Django: activas y que no son staff ni superusuarios (las del equipo no son turistas).

    No sale de VisitanteMetrica ni de `usuarios_nuevos` (visitantes nuevos por cookie, incluso anónimos).
    """
    return get_user_model().objects.filter(is_active=True, is_staff=False, is_superuser=False).count()


def cifras_home():
    """Cuatro cifras del periodo más reciente con datos del origen METRICAS_HOME_ORIGEN, o None si no hay.

    La decisión de mostrar la sección es del interruptor "Mostrar estadísticas en Home" (apps.base.ConfiguracionPublica),
    que aplica la vista del Home. Origen: settings.METRICAS_HOME_ORIGEN (SIMULADO en local, REAL en producción).
    Número fijo de consultas (1 para elegir periodo + las 6 de cargar_datos + 1 de cuentas), sin consultas por tarjeta.
    """
    origen = getattr(settings, "METRICAS_HOME_ORIGEN", OrigenDato.SIMULADO)
    ultima = MetricaDiaria.objects.filter(origen=origen).select_related("periodo").order_by(
        "-periodo__fecha_inicio", "-fecha").first()
    if ultima is None:
        return None
    total = resumen_total(ultima.periodo, origen)
    return {
        "viajeros": usuarios_registrados(),  # cuentas Django, NO visitantes nuevos por cookie
        "exploraciones": total.interacciones.get(TipoInteraccion.LUGAR_DETALLE_CLICK, 0),
        "consultas": total.interacciones.get(TipoInteraccion.CHATBOT_CONSULTA, 0),
        "visitas": total.sesiones,
    }
