import logging

from allauth.socialaccount.forms import DisconnectForm
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from .forms import (
    ApellidoForm, CambiarEmailForm, EliminarCuentaForm, LoginForm, NombreForm,
    OTPForm, ReauthPasswordForm, RegistroForm, UsernameForm,
)
from .models import CodigoOTP, PerfilUsuario
from .security import marcar_reauth, tiene_reauth_reciente

logger = logging.getLogger(__name__)

CAMPOS_PERFIL = {
    'nombres': ('first_name', NombreForm),
    'apellidos': ('last_name', ApellidoForm),
    'username': ('username', UsernameForm),
}

REAUTH_DESTINOS = {  # whitelist cerrada, nunca se redirige a una URL arbitraria del querystring
    'email': 'accounts:cambiar_email',
    'password': 'accounts:gestionar_password',
    'eliminar': 'accounts:eliminar_cuenta',
}

SESSION_OTP_USER = 'otp_user_id'
SESSION_EMAIL_PENDIENTE = 'cuenta_email_pendiente'


def _enviar_otp(user, destino=None, proposito=CodigoOTP.PROPOSITO_VERIFICACION,
                 asunto='Tu código de verificación - Viaje Informado'):
    codigo = CodigoOTP.generar(user, proposito=proposito)
    send_mail(
        asunto,
        f'Hola {user.first_name or user.username},\n\n'
        f'Tu código de verificación es: {codigo}\n\n'
        f'Este código expira en {settings.OTP_EXPIRATION_MINUTES} minutos.\n\n'
        'Si no solicitaste este código, ignora este correo.\n\n'
        'Equipo de Viaje Informado',
        None,
        [destino or user.email],
    )


def _notificar_best_effort(destino, asunto, cuerpo):
    try:
        send_mail(asunto, cuerpo, None, [destino])
    except Exception:
        logger.exception('No se pudo enviar una notificación de seguridad: %s', asunto)


def _reenviar_otp_generico(request, proposito, destino, asunto):
    otp = CodigoOTP.activo(request.user, proposito=proposito)
    if otp and otp.segundos_para_reenvio() > 0:
        messages.warning(
            request,
            f'Debes esperar {settings.OTP_RESEND_COOLDOWN_SECONDS} segundos antes de solicitar otro código.',
        )
    else:
        _enviar_otp(request.user, destino=destino, proposito=proposito, asunto=asunto)
        messages.success(request, 'Código reenviado correctamente.')


def obtener_metodos_acceso(user):
    sociales = {sa.provider: sa for sa in SocialAccount.objects.filter(user=user)}
    return {
        'password': user.has_usable_password(),
        'google': sociales.get('google'),
        'facebook': sociales.get('facebook'),
    }


def _usuario_pendiente(request):
    user_id = request.session.get(SESSION_OTP_USER)
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


def registro(request):
    if request.user.is_authenticated:
        return redirect('base:home')
    siguiente = request.GET.get('next', '')
    form = RegistroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        _enviar_otp(user)
        request.session[SESSION_OTP_USER] = user.pk
        # Limpia cualquier next residual de un registro anterior en la misma sesión.
        request.session.pop('otp_next', None)
        if siguiente and url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
            request.session['otp_next'] = siguiente
        messages.success(request, 'Te enviamos un código de verificación a tu correo. Revisa también tu bandeja de spam o correo no deseado.')
        return redirect('accounts:verificar_codigo')
    return render(request, 'accounts/registro.html', {'form': form})


def iniciar_sesion(request):
    if request.user.is_authenticated:
        return redirect('base:home')
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        identificador = form.cleaned_data['identificador'].strip()
        password = form.cleaned_data['password']
        username = identificador
        if '@' in identificador:
            user_por_email = User.objects.filter(email__iexact=identificador).first()
            username = user_por_email.username if user_por_email else identificador
        user = authenticate(request, username=username, password=password)
        if user is None:
            messages.error(request, 'Usuario o contraseña incorrectos.', extra_tags='login_error')
        else:
            perfil = PerfilUsuario.objects.filter(user=user).first()
            if perfil and not perfil.verificado and not user.is_staff:
                request.session[SESSION_OTP_USER] = user.pk
                messages.warning(request, 'Tu cuenta aún no está verificada. Revisa tu correo o solicita un nuevo código.')
                return redirect('accounts:verificar_codigo')
            auth_login(request, user)
            siguiente = request.GET.get('next')
            if siguiente and url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
                return redirect(siguiente)
            return redirect('base:home')
    return render(request, 'accounts/login.html', {'form': form})


def cerrar_sesion(request):
    auth_logout(request)
    messages.info(request, 'Cerraste sesión correctamente.')
    return redirect('base:home')


def verificar_codigo(request):
    user = _usuario_pendiente(request)
    if user is None:
        messages.error(request, 'No hay ninguna verificación pendiente. Inicia sesión o regístrate.')
        return redirect('accounts:login')
    form = OTPForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ok, error = CodigoOTP.verificar(user, form.cleaned_data['codigo'])
        if ok:
            PerfilUsuario.objects.filter(user=user).update(verificado=True)
            del request.session[SESSION_OTP_USER]
            siguiente = request.session.pop('otp_next', None)
            redirect_url = reverse('accounts:login')
            if siguiente:
                redirect_url = f'{redirect_url}?{urlencode({"next": siguiente})}'
            return render(request, 'accounts/verificar_otp.html', {
                'verificacion_exitosa': True,
                'redirect_url': redirect_url,
                'redirect_seconds': 4,
            })
        messages.error(request, error)
    otp = CodigoOTP.activo(user)
    cooldown = otp.segundos_para_reenvio() if otp else 0
    return render(request, 'accounts/verificar_otp.html', {
        'form': form,
        'email_destino': user.email,
        'cooldown': cooldown,
    })


@require_POST
def reenviar_codigo(request):
    user = _usuario_pendiente(request)
    if user is None:
        messages.error(request, 'No hay ninguna verificación pendiente. Inicia sesión o regístrate.')
        return redirect('accounts:login')
    otp = CodigoOTP.activo(user)
    if otp and otp.segundos_para_reenvio() > 0:
        messages.warning(
            request,
            f'Debes esperar {settings.OTP_RESEND_COOLDOWN_SECONDS} segundos antes de solicitar otro código.',
        )
    else:
        _enviar_otp(user)
        messages.success(request, 'Código reenviado correctamente.')
    return redirect('accounts:verificar_codigo')


@login_required
def perfil(request):
    campo_en_edicion = None
    forms_por_campo = {
        clave: FormClass(instance=request.user)
        for clave, (_, FormClass) in CAMPOS_PERFIL.items()
    }

    if request.method == 'POST':
        accion = request.POST.get('accion')
        entrada = CAMPOS_PERFIL.get(accion)
        if entrada is None:
            return HttpResponseBadRequest('Acción no reconocida.')
        _, FormClass = entrada
        form = FormClass(request.POST, instance=request.user)
        if form.is_valid():
            username_anterior = User.objects.get(pk=request.user.pk).username
            form.save()
            if accion == 'username' and username_anterior != request.user.username:
                PerfilUsuario.objects.filter(user=request.user).update(username_actualizado_en=timezone.now())
            messages.success(request, 'Cambios guardados.')
            return redirect('accounts:perfil')
        # ModelForm._post_clean() ya escribió el intento inválido en
        # request.user (misma instancia que form.instance) aunque is_valid()
        # sea False. Sin este refresh, el header u otra parte de la página
        # que lea request.user.<campo> directamente mostraría el valor
        # inválido en vez del persistido. form.errors/form.data no se ven
        # afectados por el refresh (el widget bound lee de form.data).
        request.user.refresh_from_db()
        forms_por_campo[accion] = form
        campo_en_edicion = accion

    return render(request, 'accounts/perfil.html', {
        'forms_por_campo': forms_por_campo,
        'campo_en_edicion': campo_en_edicion,
    })


def _provider_configurado(provider):
    app = settings.SOCIALACCOUNT_PROVIDERS.get(provider, {}).get('APP', {})
    return bool(app.get('client_id'))


@login_required
def cuenta(request):
    perfil_usuario = PerfilUsuario.objects.filter(user=request.user).first()
    return render(request, 'accounts/cuenta.html', {
        'email_verificado': bool(perfil_usuario and perfil_usuario.verificado),
        'metodos': obtener_metodos_acceso(request.user),
        'reauth_reciente': tiene_reauth_reciente(request),
        'settings_google_client_id': _provider_configurado('google'),
        'settings_facebook_client_id': _provider_configurado('facebook'),
    })


@login_required
def cambiar_email(request):
    if not tiene_reauth_reciente(request):
        return redirect(f"{reverse('accounts:reauth')}?next=email")
    form = CambiarEmailForm(request.POST or None, usuario_actual=request.user)
    if request.method == 'POST' and form.is_valid():
        nuevo_email = form.cleaned_data['nuevo_email']
        request.session[SESSION_EMAIL_PENDIENTE] = nuevo_email
        _enviar_otp(request.user, destino=nuevo_email, proposito='email_change',
                    asunto='Confirma tu nuevo correo - Viaje Informado')
        return redirect('accounts:verificar_nuevo_email')
    return render(request, 'accounts/cambiar_email.html', {'form': form})


@login_required
def verificar_nuevo_email(request):
    nuevo_email = request.session.get(SESSION_EMAIL_PENDIENTE)
    if not nuevo_email:
        messages.error(request, 'No hay un cambio de correo pendiente.')
        return redirect('accounts:cuenta')

    form = OTPForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ok, error = CodigoOTP.verificar(request.user, form.cleaned_data['codigo'], proposito='email_change')
        if ok:
            if not tiene_reauth_reciente(request):
                del request.session[SESSION_EMAIL_PENDIENTE]
                messages.error(request, 'Tu verificación expiró por seguridad. Vuelve a intentarlo.')
                return redirect('accounts:cambiar_email')
            if User.objects.filter(email__iexact=nuevo_email).exclude(pk=request.user.pk).exists():
                del request.session[SESSION_EMAIL_PENDIENTE]
                messages.error(request, 'Ese correo ya pertenece a otra cuenta. Intenta con otro.')
                return redirect('accounts:cambiar_email')

            perfil_usuario = PerfilUsuario.objects.filter(user=request.user).first()
            verificado_anterior = bool(perfil_usuario and perfil_usuario.verificado)
            email_anterior = request.user.email

            with transaction.atomic():
                request.user.email = nuevo_email
                request.user.save(update_fields=['email'])
                PerfilUsuario.objects.filter(user=request.user).update(verificado=True)

            del request.session[SESSION_EMAIL_PENDIENTE]
            if email_anterior and verificado_anterior:
                _notificar_best_effort(
                    email_anterior, 'Tu correo fue actualizado - Viaje Informado',
                    'El correo electrónico de tu cuenta de Viaje Informado fue cambiado.\n\n'
                    'Si no fuiste tú, contáctanos de inmediato.',
                )
            messages.success(request, 'Correo actualizado.')
            return redirect('accounts:cuenta')
        messages.error(request, error)

    otp = CodigoOTP.activo(request.user, proposito='email_change')
    return render(request, 'accounts/verificar_nuevo_email.html', {
        'form': form, 'nuevo_email': nuevo_email,
        'cooldown': otp.segundos_para_reenvio() if otp else 0,
    })


@login_required
@require_POST
def reenviar_codigo_email(request):
    pendiente = request.session.get(SESSION_EMAIL_PENDIENTE)
    if not pendiente:
        messages.error(request, 'No hay un cambio de correo pendiente.')
        return redirect('accounts:cuenta')
    if not tiene_reauth_reciente(request):
        del request.session[SESSION_EMAIL_PENDIENTE]
        messages.error(request, 'Tu verificación expiró por seguridad. Vuelve a intentarlo.')
        return redirect('accounts:cambiar_email')
    _reenviar_otp_generico(request, proposito='email_change', destino=pendiente,
                            asunto='Confirma tu nuevo correo - Viaje Informado')
    return redirect('accounts:verificar_nuevo_email')


@login_required
def gestionar_password(request):
    tiene_password = request.user.has_usable_password()
    if not tiene_password and not tiene_reauth_reciente(request):
        return redirect(f"{reverse('accounts:reauth')}?next=password")
    FormClass = PasswordChangeForm if tiene_password else SetPasswordForm
    form = FormClass(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        update_session_auth_hash(request, request.user)  # no cierra la sesión actual
        perfil_usuario = PerfilUsuario.objects.filter(user=request.user).first()
        if request.user.email and perfil_usuario and perfil_usuario.verificado:
            _notificar_best_effort(
                request.user.email, 'Tu contraseña fue actualizada - Viaje Informado',
                'La contraseña de tu cuenta de Viaje Informado fue actualizada.\n\n'
                'Si no fuiste tú, contáctanos de inmediato.',
            )
        messages.success(request, 'Contraseña creada.' if not tiene_password else 'Contraseña actualizada.')
        return redirect('accounts:cuenta')
    return render(request, 'accounts/gestionar_password.html', {'form': form, 'tiene_password': tiene_password})


@login_required
@require_POST
def desconectar_social(request, provider):
    if provider not in {'google', 'facebook'}:
        return HttpResponseBadRequest()
    if not tiene_reauth_reciente(request):
        return redirect(reverse('accounts:reauth'))
    cuenta_social = SocialAccount.objects.filter(user=request.user, provider=provider).first()
    if cuenta_social is None:
        messages.error(request, 'No tienes esa cuenta conectada.')
        return redirect('accounts:cuenta')
    form = DisconnectForm(data={'account': cuenta_social.pk}, request=request)
    if form.is_valid():
        form.save()  # el mensaje de éxito lo agrega allauth (plantilla propia sobrescrita en español)
    else:
        messages.error(request, 'No puedes desconectar tu único método de acceso.')
    return redirect('accounts:cuenta')


@login_required
def reauth(request):
    destino_clave = request.GET.get('next') or request.POST.get('next')
    destino_url = reverse(REAUTH_DESTINOS.get(destino_clave, 'accounts:cuenta'))
    perfil_usuario = PerfilUsuario.objects.filter(user=request.user).first()
    email_verificado = bool(perfil_usuario and perfil_usuario.verificado and request.user.email)

    if request.user.has_usable_password():
        form = ReauthPasswordForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            if request.user.check_password(form.cleaned_data['password']):
                marcar_reauth(request)
                return redirect(destino_url)
            form.add_error('password', 'Contraseña incorrecta.')
        return render(request, 'accounts/reauth.html', {'form': form, 'metodo': 'password'})

    if not email_verificado:
        # Caso inalcanzable con los flujos actuales (ver adapters.py/views.py:
        # login local exige perfil.verificado, alta social siempre lo fija True),
        # pero se defiende igual en vez de degradar seguridad silenciosamente.
        messages.error(request, 'No podemos confirmar tu identidad de forma segura en este momento. Contáctanos para continuar.')
        return redirect('accounts:cuenta')

    form = OTPForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ok, error = CodigoOTP.verificar(request.user, form.cleaned_data['codigo'], proposito='reauth')
        if ok:
            marcar_reauth(request)
            return redirect(destino_url)
        messages.error(request, error)
    elif not CodigoOTP.activo(request.user, proposito='reauth'):
        _enviar_otp(request.user, proposito='reauth', asunto='Confirma tu identidad - Viaje Informado')
    otp = CodigoOTP.activo(request.user, proposito='reauth')
    return render(request, 'accounts/reauth.html', {
        'form': form, 'metodo': 'otp', 'cooldown': otp.segundos_para_reenvio() if otp else 0,
        'next': destino_clave if destino_clave in REAUTH_DESTINOS else '',
    })


@login_required
@require_POST
def reenviar_codigo_reauth(request):
    _reenviar_otp_generico(request, proposito='reauth', destino=request.user.email,
                            asunto='Confirma tu identidad - Viaje Informado')
    destino_clave = request.POST.get('next')
    query = urlencode({'next': destino_clave}) if destino_clave in REAUTH_DESTINOS else ''
    url = reverse('accounts:reauth')
    return redirect(f'{url}?{query}' if query else url)


@login_required
def eliminar_cuenta(request):
    if not tiene_reauth_reciente(request):
        return redirect(f"{reverse('accounts:reauth')}?next=eliminar")
    form = EliminarCuentaForm(request.POST or None, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        usuario = request.user
        perfil_usuario = PerfilUsuario.objects.filter(user=usuario).first()
        email_anterior, username_anterior = usuario.email, usuario.username
        verificado_anterior = bool(perfil_usuario and perfil_usuario.verificado)
        usuario.delete()  # CASCADE: PerfilUsuario, CodigoOTP, Favorito, Resena, SocialAccount, ...
        auth_logout(request)
        if email_anterior and verificado_anterior:
            _notificar_best_effort(
                email_anterior, 'Tu cuenta fue eliminada - Viaje Informado',
                f'Hola {username_anterior},\n\nTu cuenta de Viaje Informado fue eliminada correctamente.\n\n'
                'Equipo de Viaje Informado',
            )
        return redirect('accounts:cuenta_eliminada')
    return render(request, 'accounts/eliminar_cuenta.html', {'form': form})


def cuenta_eliminada(request):
    return render(request, 'accounts/cuenta_eliminada.html')
