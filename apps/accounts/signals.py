from allauth.account.signals import user_signed_up
from django.dispatch import receiver

from .models import PerfilUsuario


@receiver(user_signed_up)
def crear_perfil_social(sender, request, user, **kwargs):
    """Usuarios creados vía Google/Facebook: el proveedor ya verificó el correo."""
    if kwargs.get('sociallogin'):
        PerfilUsuario.sincronizar_desde_social(user)
