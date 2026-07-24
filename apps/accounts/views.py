from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import LoginForm, OTPForm, RegistroForm
from .models import CodigoOTP, PerfilUsuario

SESSION_OTP_USER = 'otp_user_id'


def _enviar_otp(user):
    codigo = CodigoOTP.generar(user)
    send_mail(
        'Tu código de verificación - Viaje Informado',
        f'Hola {user.first_name or user.username},\n\n'
        f'Tu código de verificación es: {codigo}\n\n'
        f'Este código expira en {settings.OTP_EXPIRATION_MINUTES} minutos.\n\n'
        'Si no solicitaste este código, ignora este correo.\n\n'
        'Equipo de Viaje Informado',
        None,
        [user.email],
    )


def _usuario_pendiente(request):
    user_id = request.session.get(SESSION_OTP_USER)
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


def registro(request):
    if request.user.is_authenticated:
        return redirect('base:home')
    form = RegistroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        _enviar_otp(user)
        request.session[SESSION_OTP_USER] = user.pk
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
            return render(request, 'accounts/verificar_otp.html', {
                'verificacion_exitosa': True,
                'redirect_url': reverse('accounts:login'),
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
