import re

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.base import AuthProcess
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse

from .forms import USERNAME_RE
from .security import tiene_reauth_reciente

USERNAME_MIN_LENGTH = 4
USERNAME_MAX_LENGTH = 30


def _limpiar_username_base(texto):
    base = (texto or '').split('@')[0].lower()
    base = re.sub(r'[^a-z0-9._-]', '', base)
    base = re.sub(r'[._-]{2,}', '-', base)  # colapsa combinaciones como "..", "--", "._"
    return base.strip('._-')


def generar_username_unico(email_o_texto):
    """Genera un username único a partir de un correo, reutilizando USERNAME_RE
    (las mismas reglas que el registro normal). No cuenta como cambio manual."""
    base = _limpiar_username_base(email_o_texto)
    if len(base) < USERNAME_MIN_LENGTH:
        base = (base + 'usuario')[:USERNAME_MIN_LENGTH] if base else 'usuario'
    base = base[:USERNAME_MAX_LENGTH]
    if not USERNAME_RE.fullmatch(base):
        base = 'usuario'

    candidato = base
    sufijo = 1
    while User.objects.filter(username__iexact=candidato).exists():
        sufijo_str = str(sufijo)
        candidato = f'{base[:USERNAME_MAX_LENGTH - len(sufijo_str)]}{sufijo_str}'
        sufijo += 1
    return candidato


class ViajeInformadoSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Adapter de django-allauth para Google/Facebook.

    Objetivo: completar el signup social automáticamente (sin pasar por
    /cuentas/3rdparty/signup/), generar username único, y dejar al usuario
    como Turista verificado sin pedir OTP. Misma lógica para ambos proveedores.
    """

    def pre_social_login(self, request, sociallogin):
        """Si ya existe un usuario local con ese correo y el proveedor lo
        entrega verificado, conecta la cuenta social a ese usuario en vez
        de intentar crear uno nuevo (evita duplicados e IntegrityError)."""
        es_connect = sociallogin.state.get('process') == AuthProcess.CONNECT
        if es_connect and not (request.user.is_authenticated and tiene_reauth_reciente(request)):
            # Vincular un nuevo proveedor social a una cuenta existente es una
            # acción sensible (F4): exige reauth reciente, igual que cambiar
            # email/password o eliminar la cuenta. Esto se aplica ANTES de que
            # se cree o actualice cualquier SocialAccount, y solo afecta a
            # process=connect — login/alta social normales no pasan por aquí.
            raise ImmediateHttpResponse(redirect(reverse('accounts:reauth')))
        if sociallogin.is_existing:
            return
        email = None
        for direccion in sociallogin.email_addresses:
            if direccion.verified:
                email = direccion.email
                break
        if not email:
            return
        existente = User.objects.filter(email__iexact=email).first()
        if not existente:
            return
        sociallogin.connect(request, existente)
        from .models import PerfilUsuario
        PerfilUsuario.sincronizar_desde_social(existente)

    def populate_user(self, request, sociallogin, data):
        """Nombres/apellidos: allauth ya usa given_name/family_name si el
        proveedor los entrega, y separa 'name' por el primer espacio si no.
        Aquí solo se recorta espacios y longitud para no bloquear el login
        con un nombre inusual (ej. "Tripulante Bob Esponja")."""
        user = super().populate_user(request, sociallogin, data)
        user.first_name = (user.first_name or '').strip()[:150]
        user.last_name = (user.last_name or '').strip()[:150]
        return user

    def save_user(self, request, sociallogin, form=None):
        """Crea el usuario social sin contraseña utilizable y con username
        generado automáticamente (no el algoritmo genérico de allauth)."""
        user = sociallogin.user
        user.set_unusable_password()
        if form:
            from allauth.account.adapter import get_adapter as get_account_adapter
            get_account_adapter().save_user(request, user, form)
        else:
            user.username = generar_username_unico(user.email or user.username)
        sociallogin.save(request)
        return user
