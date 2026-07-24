from django.core.exceptions import ObjectDoesNotExist
from django import template

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
