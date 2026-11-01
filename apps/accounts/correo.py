"""Correo saliente de accounts: una sola fuente para el Reply-To (settings.EMAIL_REPLY_TO).
El From sale siempre de DEFAULT_FROM_EMAIL (from_email=None)."""
from django.conf import settings
from django.core.mail import EmailMessage


def reply_to():
    return [settings.EMAIL_REPLY_TO] if settings.EMAIL_REPLY_TO else []


def enviar_correo(asunto, cuerpo, destinos):
    EmailMessage(asunto, cuerpo, to=destinos, reply_to=reply_to()).send()
