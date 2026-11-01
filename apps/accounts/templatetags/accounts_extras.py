from django.core.exceptions import ObjectDoesNotExist
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

from apps.accounts import recuperacion

register = template.Library()

MAX_CHARS = 15


@register.filter
def header_display_name(user):
    """Primera palabra del nombre del usuario, recortada a MAX_CHARS.
    No modifica ningún dato guardado, solo el texto mostrado en el header."""
    if not getattr(user, 'is_authenticated', False):
        return ''

    raw = (user.first_name or '').strip()
    if not raw:
        try:
            raw = (user.perfil.nombres_apellidos or '').strip()
        except ObjectDoesNotExist:
            raw = ''
    if not raw:
        raw = (user.username or '').strip()
    if not raw:
        raw = (user.email or '').split('@')[0].strip()

    palabras = raw.split()
    if not palabras:
        return ''

    primera = palabras[0]
    if len(primera) > MAX_CHARS:
        return primera[:MAX_CHARS - 1] + '…'
    return primera


@register.simple_tag(takes_context=True)
def cooldown_recuperacion(context):
    """Segundos para poder reenviar el correo de recuperación (None si no hay solicitud en sesión)."""
    return recuperacion.segundos_restantes(context['request'].session)


@register.filter
def mmss(segundos):
    return f'{segundos // 60:02d}:{segundos % 60:02d}'


@register.simple_tag
def static_v(path):
    """static() con ?v=<mtime>: el navegador recarga el archivo en cuanto cambia.
    Sin esto, un auth.js viejo en caché puede quedar activo tras un despliegue."""
    url = static(path)
    ruta = finders.find(path)
    return f'{url}?v={int(os.path.getmtime(ruta))}' if ruta else url
