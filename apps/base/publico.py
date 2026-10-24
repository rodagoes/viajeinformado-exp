"""Configuración pública del sitio, resuelta una sola vez por petición (Home y footer comparten la consulta)."""
from django.utils.functional import SimpleLazyObject

from .models import ConfiguracionPublica, Sponsor


def obtener_config(request):
    if not hasattr(request, "_config_publica"):
        request._config_publica = ConfiguracionPublica.leer()
    return request._config_publica


def sponsors_footer(request):
    """Sponsors activos (orden, nombre, id) solo si el interruptor del footer está en ON; si no, lista vacía sin consulta."""
    if not hasattr(request, "_sponsors_footer"):
        activa = obtener_config(request).mostrar_sponsors_footer
        request._sponsors_footer = list(Sponsor.objects.filter(activo=True)) if activa else []
    return request._sponsors_footer


def config_publica(request):
    """Context processor perezoso: no consulta la BD si ninguna plantilla usa estas variables."""
    return {
        "config_publica": SimpleLazyObject(lambda: obtener_config(request)),
        "footer_sponsors": SimpleLazyObject(lambda: sponsors_footer(request)),
    }
