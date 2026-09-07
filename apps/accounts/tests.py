import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import unquote

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount, SocialLogin
from allauth.socialaccount.providers.base import AuthProcess
from django.contrib.auth.models import AnonymousUser, User
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.establecimientos.models import CategoriaEstablecimiento, Establecimiento

from .adapters import ViajeInformadoSocialAccountAdapter
from .models import CodigoOTP, PerfilUsuario
from .security import marcar_reauth

DATOS_VALIDOS = {
    'nombres': 'Rodrigo',
    'apellidos': 'Acuña Gonzales',
    'username': 'rodrigo.acuna',
    'email': 'rodrigo@example.com',
    'password1': 'Clave123!',
    'password2': 'Clave123!',
}


def datos_registro(**overrides):
    datos = DATOS_VALIDOS.copy()
    datos.update(overrides)
    return datos


def extraer_codigo_otp():
    cuerpo = mail.outbox[-1].body
    match = re.search(r'código de verificación es: (\d{4})', cuerpo)
    return match.group(1)


class RegistroNextTests(TestCase):
    def test_next_seguro_se_conserva(self):
        url = reverse('accounts:registro') + '?next=/mi-cuenta/favoritos/'
        self.client.post(url, datos_registro())
        self.assertEqual(self.client.session.get('otp_next'), '/mi-cuenta/favoritos/')

        codigo = extraer_codigo_otp()
        response = self.client.post(reverse('accounts:verificar_codigo'), {'codigo': codigo})
        redirect_url = response.context['redirect_url']
        self.assertIn('next=', redirect_url)
        self.assertIn('/mi-cuenta/favoritos/', unquote(redirect_url))

    def test_next_externo_se_rechaza(self):
        url = reverse('accounts:registro') + '?next=https://evil.example.com/robar'
        self.client.post(url, datos_registro())
        self.assertIsNone(self.client.session.get('otp_next'))

        codigo = extraer_codigo_otp()
        response = self.client.post(reverse('accounts:verificar_codigo'), {'codigo': codigo})
        self.assertEqual(response.context['redirect_url'], reverse('accounts:login'))

    def test_otp_recupera_next_de_sesion(self):
        url = reverse('accounts:registro') + '?next=/mi-cuenta/favoritos/'
        self.client.post(url, datos_registro())
        codigo = extraer_codigo_otp()
        response = self.client.post(reverse('accounts:verificar_codigo'), {'codigo': codigo})
        self.assertIn('%2Fmi-cuenta%2Ffavoritos%2F', response.context['redirect_url'])

    def test_otp_next_se_elimina_de_sesion_al_consumirse(self):
        url = reverse('accounts:registro') + '?next=/mi-cuenta/favoritos/'
        self.client.post(url, datos_registro())
        codigo = extraer_codigo_otp()
        self.client.post(reverse('accounts:verificar_codigo'), {'codigo': codigo})
        self.assertIsNone(self.client.session.get('otp_next'))

    def test_sin_next_mantiene_flujo_actual(self):
        self.client.post(reverse('accounts:registro'), datos_registro())
        self.assertIsNone(self.client.session.get('otp_next'))

        codigo = extraer_codigo_otp()
        response = self.client.post(reverse('accounts:verificar_codigo'), {'codigo': codigo})
        self.assertEqual(response.context['redirect_url'], reverse('accounts:login'))

    def test_otp_next_residual_se_limpia_en_nuevo_registro(self):
        url_con_next = reverse('accounts:registro') + '?next=/mi-cuenta/favoritos/'
        self.client.post(url_con_next, datos_registro())
        self.assertEqual(self.client.session.get('otp_next'), '/mi-cuenta/favoritos/')

        # Abandona la verificación y empieza un segundo registro, esta vez sin next.
        self.client.post(reverse('accounts:registro'), datos_registro(
            username='otro.usuario', email='otro@example.com',
        ))
        self.assertIsNone(self.client.session.get('otp_next'))


class PerfilTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(
            username='rodrigoacuna', password='Clave123!', email='rodrigo@example.com',
            first_name='Rodrigo', last_name='Acuña Gonzales',
        )
        cls.otro_usuario = User.objects.create_user(
            username='mariaperez', password='Clave123!', email='maria@example.com',
            first_name='María', last_name='Pérez',
        )

    def setUp(self):
        self.client.login(username='rodrigoacuna', password='Clave123!')

    def post_perfil(self, accion, **campos):
        datos = {'accion': accion}
        datos.update(campos)
        return self.client.post(reverse('accounts:perfil'), datos)


class PerfilAccesoTests(PerfilTestBase):
    def test_anonimo_redirige_a_login_con_next(self):
        self.client.logout()
        response = self.client.get(reverse('accounts:perfil'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
        self.assertIn('next=', response.url)

    def test_autenticado_puede_abrir_perfil(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertEqual(response.status_code, 200)

    def test_solo_se_muestran_datos_de_request_user(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertContains(response, 'Rodrigo')
        self.assertNotContains(response, 'María')


class PerfilNombreTests(PerfilTestBase):
    def test_valor_actual_se_muestra(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertContains(response, 'Rodrigo')

    def test_puede_cambiar_first_name(self):
        response = self.post_perfil('nombres', first_name='Carlos')
        self.assertRedirects(response, reverse('accounts:perfil'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Carlos')

    def test_no_modifica_last_name_ni_username(self):
        self.post_perfil('nombres', first_name='Carlos')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.last_name, 'Acuña Gonzales')
        self.assertEqual(self.usuario.username, 'rodrigoacuna')

    def test_vacio_rechazado(self):
        response = self.post_perfil('nombres', first_name='   ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['campo_en_edicion'], 'nombres')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Rodrigo')

    def test_acepta_acentos_guiones_apostrofes(self):
        for valor in ["O'Connor", 'Pérez-Ríos', 'De la Cruz', 'Ñañez']:
            response = self.post_perfil('nombres', first_name=valor)
            self.assertRedirects(response, reverse('accounts:perfil'))
            self.usuario.refresh_from_db()
            self.assertEqual(self.usuario.first_name, valor)

    def test_solo_guiones_o_apostrofes_rechazado(self):
        response = self.post_perfil('nombres', first_name="-'-")
        self.assertEqual(response.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Rodrigo')

    def test_no_puede_empezar_o_terminar_con_guion(self):
        response = self.post_perfil('nombres', first_name='-Rodrigo')
        self.assertEqual(response.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Rodrigo')

    def test_error_no_corrompe_datos_mostrados_al_usuario(self):
        # request.user.refresh_from_db() en la vista debe restaurar el valor
        # persistido tras un intento inválido (aunque ModelForm mutó la
        # instancia en memoria durante full_clean()).
        response = self.post_perfil('nombres', first_name='   ')
        self.assertContains(response, 'Rodrigo')


class PerfilApellidoTests(PerfilTestBase):
    def test_valor_actual_se_muestra(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertContains(response, 'Acuña Gonzales')

    def test_puede_cambiar_last_name(self):
        response = self.post_perfil('apellidos', last_name='Ramírez')
        self.assertRedirects(response, reverse('accounts:perfil'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.last_name, 'Ramírez')

    def test_no_modifica_first_name(self):
        self.post_perfil('apellidos', last_name='Ramírez')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Rodrigo')

    def test_nombres_compuestos_aceptados(self):
        response = self.post_perfil('apellidos', last_name='De la Cruz')
        self.assertRedirects(response, reverse('accounts:perfil'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.last_name, 'De la Cruz')


class PerfilUsernameTests(PerfilTestBase):
    def test_username_actual_visible(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertContains(response, 'rodrigoacuna')

    def test_puede_cambiar_username(self):
        response = self.post_perfil('username', username='rodrigo.nuevo')
        self.assertRedirects(response, reverse('accounts:perfil'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.username, 'rodrigo.nuevo')

    def test_mismo_username_propio_permitido(self):
        response = self.post_perfil('username', username='rodrigoacuna')
        self.assertRedirects(response, reverse('accounts:perfil'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.username, 'rodrigoacuna')

    def test_username_duplicado_rechazado_sin_500(self):
        response = self.post_perfil('username', username='mariaperez')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['campo_en_edicion'], 'username')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.username, 'rodrigoacuna')

    def test_username_invalido_rechazado(self):
        response = self.post_perfil('username', username='a b')
        self.assertEqual(response.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.username, 'rodrigoacuna')

    def test_cambio_no_afecta_email_ni_password(self):
        password_hash_previo = self.usuario.password
        self.post_perfil('username', username='rodrigo.nuevo')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'rodrigo@example.com')
        self.assertEqual(self.usuario.password, password_hash_previo)

    def test_username_actualizado_en_se_actualiza_solo_si_cambia(self):
        PerfilUsuario.objects.create(user=self.usuario, nombres_apellidos='Rodrigo Acuña Gonzales')

        self.post_perfil('username', username='rodrigoacuna')  # mismo valor
        perfil = PerfilUsuario.objects.get(user=self.usuario)
        self.assertIsNone(perfil.username_actualizado_en)

        self.post_perfil('username', username='rodrigo.nuevo')  # cambio real
        perfil.refresh_from_db()
        self.assertIsNotNone(perfil.username_actualizado_en)


class PerfilDateJoinedTests(PerfilTestBase):
    def test_visible_y_formateado_en_espanol(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertContains(response, 'Registrado desde')
        self.assertContains(response, str(self.usuario.date_joined.year))

    def test_sin_control_de_edicion(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertNotIn('date_joined', response.content.decode())

    def test_accion_fuera_de_whitelist_no_causa_500(self):
        fecha_original = self.usuario.date_joined
        response = self.post_perfil('date_joined', date_joined='2000-01-01')
        self.assertEqual(response.status_code, 400)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.date_joined, fecha_original)


class PerfilAislamientoTests(PerfilTestBase):
    def test_usuario_a_no_puede_modificar_a_b(self):
        self.post_perfil('nombres', first_name='Carlos')
        self.otro_usuario.refresh_from_db()
        self.assertEqual(self.otro_usuario.first_name, 'María')


class PerfilSocialTests(PerfilTestBase):
    def setUp(self):
        self.usuario_social = User.objects.create_user(
            username='social.user', email='social@example.com',
            first_name='Social', last_name='User',
        )
        self.usuario_social.set_unusable_password()
        self.usuario_social.save()
        SocialAccount.objects.create(user=self.usuario_social, provider='google', uid='1234567890')
        self.client.force_login(self.usuario_social)

    def test_usuario_social_puede_abrir_perfil(self):
        response = self.client.get(reverse('accounts:perfil'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Social')

    def test_usuario_social_puede_editar_datos(self):
        response = self.client.post(reverse('accounts:perfil'), {'accion': 'nombres', 'first_name': 'Nuevo'})
        self.assertRedirects(response, reverse('accounts:perfil'))
        self.usuario_social.refresh_from_db()
        self.assertEqual(self.usuario_social.first_name, 'Nuevo')

    def test_socialaccount_permanece_vinculado(self):
        self.client.post(reverse('accounts:perfil'), {'accion': 'username', 'username': 'social.nuevo'})
        self.assertTrue(SocialAccount.objects.filter(user=self.usuario_social, provider='google').exists())


class CuentaTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(
            username='cuentaqa', password='Clave123!', email='cuentaqa@example.com',
            first_name='Cuenta', last_name='QA',
        )
        PerfilUsuario.objects.create(user=cls.usuario, nombres_apellidos='Cuenta QA', verificado=True)
        cls.otro_usuario = User.objects.create_user(
            username='otrocuentaqa', password='Clave123!', email='otro@example.com',
        )
        PerfilUsuario.objects.create(user=cls.otro_usuario, nombres_apellidos='Otro QA', verificado=True)

    def setUp(self):
        self.client.login(username='cuentaqa', password='Clave123!')

    def marcar_reauth_cliente(self):
        session = self.client.session
        session['cuenta_reauth_at'] = timezone.now().isoformat()
        session.save()


class CuentaAccesoTests(CuentaTestBase):
    def test_anonimo_redirige_a_login_con_next(self):
        self.client.logout()
        response = self.client.get(reverse('accounts:cuenta'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
        self.assertIn('next=', response.url)

    def test_autenticado_ve_su_pagina(self):
        response = self.client.get(reverse('accounts:cuenta'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cuentaqa@example.com')
        self.assertContains(response, 'Verificado')
        self.assertContains(response, 'Contraseña configurada')
        self.assertContains(response, 'No conectado')

    def test_no_expone_datos_sensibles(self):
        SocialAccount.objects.create(
            user=self.usuario, provider='google', uid='uid-secreto-123',
            extra_data={'email': 'cuentaqa@gmail.com', 'sub': 'uid-secreto-123', 'access_token_would_be': 'nope'},
        )
        response = self.client.get(reverse('accounts:cuenta'))
        contenido = response.content.decode()
        self.assertNotIn('uid-secreto-123', contenido)
        self.assertNotIn('access_token_would_be', contenido)


class CambiarEmailTests(CuentaTestBase):
    def _extraer_codigo(self):
        cuerpo = mail.outbox[-1].body
        return re.search(r'código de verificación es: (\d{4})', cuerpo).group(1)

    def test_sin_reauth_redirige_a_reauth(self):
        response = self.client.get(reverse('accounts:cambiar_email'))
        self.assertRedirects(response, f"{reverse('accounts:reauth')}?next=email")

    def test_email_valido_inicia_verificacion_sin_tocar_user_email(self):
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        self.assertRedirects(response, reverse('accounts:verificar_nuevo_email'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cuentaqa@example.com')
        self.assertEqual(self.client.session.get('cuenta_email_pendiente'), 'nuevo@example.com')

    def test_email_duplicado_rechazado(self):
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'otro@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ya existe una cuenta registrada con este correo.')

    def test_mismo_email_actual_rechazado(self):
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'cuentaqa@example.com'})
        self.assertContains(response, 'Este ya es tu correo electrónico actual.')

    def test_otp_correcto_actualiza_email_y_verificado(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        codigo = self._extraer_codigo()
        response = self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': codigo})
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'nuevo@example.com')
        self.assertTrue(PerfilUsuario.objects.get(user=self.usuario).verificado)

    def test_otp_incorrecto_no_cambia_email(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': '0000'})
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cuentaqa@example.com')

    def test_otp_expirado_no_cambia_email(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        otp = CodigoOTP.activo(self.usuario, proposito='email_change')
        otp.expira_en = timezone.now() - timedelta(minutes=1)
        otp.save(update_fields=['expira_en'])
        self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': '1234'})
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cuentaqa@example.com')

    def test_email_anterior_verificado_recibe_notificacion(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        codigo = self._extraer_codigo()
        mail.outbox.clear()
        self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': codigo})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('cuentaqa@example.com', mail.outbox[0].to)

    def test_email_anterior_no_verificado_no_recibe_notificacion(self):
        PerfilUsuario.objects.filter(user=self.usuario).update(verificado=False)
        # login_required en las vistas de cuenta no exige perfil.verificado (eso es solo
        # una regla del login normal); se fuerza reauth directamente para probar el caso.
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        codigo = self._extraer_codigo()
        mail.outbox.clear()
        self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': codigo})
        self.assertEqual(len(mail.outbox), 0)

    def test_reauth_expirado_entre_paso_1_y_confirmacion_rechaza(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        codigo = self._extraer_codigo()
        # Expira el reauth manualmente antes de confirmar el OTP.
        session = self.client.session
        session['cuenta_reauth_at'] = (timezone.now() - timedelta(minutes=20)).isoformat()
        session.save()
        response = self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': codigo})
        # No se usa assertRedirects: cambiar_email también exige reauth, así que
        # esto encadena a un segundo redirect hacia accounts:reauth (esperado).
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('accounts:cambiar_email'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cuentaqa@example.com')

    def test_duplicado_registrado_entre_paso_1_y_confirmacion_rechaza(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        codigo = self._extraer_codigo()
        User.objects.create_user(username='intruso', password='Clave123!', email='nuevo@example.com')
        response = self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': codigo})
        self.assertRedirects(response, reverse('accounts:cambiar_email'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cuentaqa@example.com')

    def test_fallo_de_envio_no_impide_actualizar_email(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        codigo = self._extraer_codigo()
        with patch('apps.accounts.views.send_mail', side_effect=Exception('smtp caído')):
            response = self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': codigo})
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'nuevo@example.com')


class EmailAddressCoherenciaTests(CuentaTestBase):
    def test_pre_social_login_empareja_por_email_actualizado(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:cambiar_email'), {'nuevo_email': 'nuevo@example.com'})
        codigo = re.search(r'código de verificación es: (\d{4})', mail.outbox[-1].body).group(1)
        self.client.post(reverse('accounts:verificar_nuevo_email'), {'codigo': codigo})
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'nuevo@example.com')

        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        sociallogin = SocialLogin(account=SocialAccount(provider='google', uid='uid-coherencia'))
        sociallogin.state = {'process': AuthProcess.LOGIN}
        sociallogin.email_addresses = [_EmailAddressFake(email='nuevo@example.com', verified=True)]
        ViajeInformadoSocialAccountAdapter().pre_social_login(request, sociallogin)
        self.assertTrue(sociallogin.is_existing)
        self.assertEqual(sociallogin.user.pk, self.usuario.pk)


class _EmailAddressFake:
    def __init__(self, email, verified):
        self.email = email
        self.verified = verified


class PasswordTests(CuentaTestBase):
    def test_usuario_con_password_actual_correcta_permite_cambio(self):
        response = self.client.post(reverse('accounts:gestionar_password'), {
            'old_password': 'Clave123!', 'new_password1': 'NuevaClave456!', 'new_password2': 'NuevaClave456!',
        })
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('NuevaClave456!'))

    def test_password_actual_incorrecta_rechaza(self):
        response = self.client.post(reverse('accounts:gestionar_password'), {
            'old_password': 'Incorrecta1!', 'new_password1': 'NuevaClave456!', 'new_password2': 'NuevaClave456!',
        })
        self.assertEqual(response.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Clave123!'))

    def test_confirmacion_no_coincide_falla(self):
        response = self.client.post(reverse('accounts:gestionar_password'), {
            'old_password': 'Clave123!', 'new_password1': 'NuevaClave456!', 'new_password2': 'Distinta789!',
        })
        self.assertEqual(response.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Clave123!'))

    def test_sesion_permanece_autenticada_tras_cambio_sin_reauth_explicito(self):
        self.client.post(reverse('accounts:gestionar_password'), {
            'old_password': 'Clave123!', 'new_password1': 'NuevaClave456!', 'new_password2': 'NuevaClave456!',
        })
        response = self.client.get(reverse('accounts:cuenta'))
        self.assertEqual(response.status_code, 200)

    def test_nueva_contrasena_funciona_en_login_posterior(self):
        self.client.post(reverse('accounts:gestionar_password'), {
            'old_password': 'Clave123!', 'new_password1': 'NuevaClave456!', 'new_password2': 'NuevaClave456!',
        })
        self.client.logout()
        entro = self.client.login(username='cuentaqa', password='NuevaClave456!')
        self.assertTrue(entro)

    def test_usuario_sin_password_exige_reauth(self):
        self.usuario.set_unusable_password()
        self.usuario.save()
        self.client.force_login(self.usuario)  # cambiar el password invalida la sesión previa (auth hash)
        response = self.client.get(reverse('accounts:gestionar_password'))
        self.assertRedirects(response, f"{reverse('accounts:reauth')}?next=password")

    def test_usuario_sin_password_puede_crear_una_tras_reauth(self):
        self.usuario.set_unusable_password()
        self.usuario.save()
        self.client.force_login(self.usuario)
        SocialAccount.objects.create(user=self.usuario, provider='google', uid='uid-1')
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:gestionar_password'), {
            'new_password1': 'NuevaClave456!', 'new_password2': 'NuevaClave456!',
        })
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.has_usable_password())
        self.assertTrue(SocialAccount.objects.filter(user=self.usuario, provider='google').exists())

    def test_login_local_funciona_despues_de_crear_password(self):
        self.usuario.set_unusable_password()
        self.usuario.save()
        self.client.force_login(self.usuario)
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:gestionar_password'), {
            'new_password1': 'NuevaClave456!', 'new_password2': 'NuevaClave456!',
        })
        self.client.logout()
        entro = self.client.login(username='cuentaqa', password='NuevaClave456!')
        self.assertTrue(entro)


class MetodosAccesoTests(CuentaTestBase):
    def test_obtener_metodos_acceso_combinaciones(self):
        from .views import obtener_metodos_acceso
        self.assertTrue(obtener_metodos_acceso(self.usuario)['password'])
        self.assertIsNone(obtener_metodos_acceso(self.usuario)['google'])
        SocialAccount.objects.create(user=self.usuario, provider='google', uid='uid-1')
        SocialAccount.objects.create(user=self.usuario, provider='facebook', uid='uid-2')
        metodos = obtener_metodos_acceso(self.usuario)
        self.assertTrue(metodos['password'])
        self.assertIsNotNone(metodos['google'])
        self.assertIsNotNone(metodos['facebook'])

    def test_desconectar_exige_reauth_reciente(self):
        SocialAccount.objects.create(user=self.usuario, provider='google', uid='uid-1')
        response = self.client.post(reverse('accounts:desconectar_social', args=['google']))
        self.assertRedirects(response, reverse('accounts:reauth'))
        self.assertTrue(SocialAccount.objects.filter(user=self.usuario, provider='google').exists())

    def test_desconectar_google_no_toca_facebook_ni_password(self):
        SocialAccount.objects.create(user=self.usuario, provider='google', uid='uid-1')
        SocialAccount.objects.create(user=self.usuario, provider='facebook', uid='uid-2')
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:desconectar_social', args=['google']))
        self.assertFalse(SocialAccount.objects.filter(user=self.usuario, provider='google').exists())
        self.assertTrue(SocialAccount.objects.filter(user=self.usuario, provider='facebook').exists())
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.has_usable_password())

    def test_no_se_puede_desconectar_el_unico_metodo(self):
        self.usuario.set_unusable_password()
        self.usuario.save()
        self.client.force_login(self.usuario)
        SocialAccount.objects.create(user=self.usuario, provider='google', uid='uid-1')
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:desconectar_social', args=['google']))
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.assertTrue(SocialAccount.objects.filter(user=self.usuario, provider='google').exists())

    def test_socialaccount_ajeno_no_puede_desconectarse(self):
        SocialAccount.objects.create(user=self.otro_usuario, provider='google', uid='uid-ajeno')
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:desconectar_social', args=['google']))
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.assertTrue(SocialAccount.objects.filter(user=self.otro_usuario, provider='google').exists())

    def test_provider_fuera_de_whitelist_rechazado(self):
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:desconectar_social', args=['twitter']))
        self.assertEqual(response.status_code, 400)

    def test_mensaje_de_exito_esta_en_espanol(self):
        SocialAccount.objects.create(user=self.usuario, provider='google', uid='uid-1')
        SocialAccount.objects.create(user=self.usuario, provider='facebook', uid='uid-2')
        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:desconectar_social', args=['google']), follow=True)
        self.assertContains(response, 'Cuenta desconectada correctamente.')

    @patch.dict('django.conf.settings.SOCIALACCOUNT_PROVIDERS', {
        'google': {'APP': {'client_id': 'test-client-id', 'secret': 'test-secret', 'key': ''}, 'SCOPE': ['profile', 'email']},
        'facebook': {'APP': {'client_id': '', 'secret': '', 'key': ''}, 'SCOPE': ['email', 'public_profile']},
    })
    def test_enlace_conectar_no_aparece_sin_reauth(self):
        response = self.client.get(reverse('accounts:cuenta'))
        self.assertNotContains(response, 'process=connect')

    @patch.dict('django.conf.settings.SOCIALACCOUNT_PROVIDERS', {
        'google': {'APP': {'client_id': 'test-client-id', 'secret': 'test-secret', 'key': ''}, 'SCOPE': ['profile', 'email']},
        'facebook': {'APP': {'client_id': '', 'secret': '', 'key': ''}, 'SCOPE': ['email', 'public_profile']},
    })
    def test_enlace_conectar_aparece_con_reauth(self):
        self.marcar_reauth_cliente()
        response = self.client.get(reverse('accounts:cuenta'))
        self.assertContains(response, 'process=connect')


class ReauthTests(CuentaTestBase):
    def test_password_correcta_crea_reauth_reciente(self):
        response = self.client.post(reverse('accounts:reauth'), {'password': 'Clave123!'})
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.assertIsNotNone(self.client.session.get('cuenta_reauth_at'))

    def test_password_incorrecta_no_crea_reauth(self):
        response = self.client.post(reverse('accounts:reauth'), {'password': 'Incorrecta1!'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('cuenta_reauth_at'))

    def test_otp_correcto_crea_reauth_para_usuario_sin_password(self):
        self.usuario.set_unusable_password()
        self.usuario.save()
        self.client.force_login(self.usuario)
        self.client.get(reverse('accounts:reauth'))  # dispara el envío del primer OTP
        codigo = re.search(r'código de verificación es: (\d{4})', mail.outbox[-1].body).group(1)
        response = self.client.post(reverse('accounts:reauth'), {'codigo': codigo})
        self.assertRedirects(response, reverse('accounts:cuenta'))
        self.assertIsNotNone(self.client.session.get('cuenta_reauth_at'))

    def test_reauth_expira_pasados_10_minutos(self):
        session = self.client.session
        session['cuenta_reauth_at'] = (timezone.now() - timedelta(minutes=11)).isoformat()
        session.save()
        response = self.client.get(reverse('accounts:cambiar_email'))
        self.assertRedirects(response, f"{reverse('accounts:reauth')}?next=email")

    def test_accion_sensible_sin_reauth_redirige(self):
        response = self.client.get(reverse('accounts:eliminar_cuenta'))
        self.assertRedirects(response, f"{reverse('accounts:reauth')}?next=eliminar")

    def test_accion_sensible_con_reauth_procede(self):
        self.marcar_reauth_cliente()
        response = self.client.get(reverse('accounts:eliminar_cuenta'))
        self.assertEqual(response.status_code, 200)

    def test_reenvio_otp_reauth_respeta_cooldown(self):
        self.usuario.set_unusable_password()
        self.usuario.save()
        self.client.force_login(self.usuario)
        self.client.get(reverse('accounts:reauth'))
        mail.outbox.clear()
        self.client.post(reverse('accounts:reenviar_codigo_reauth'), {'next': ''})
        self.assertEqual(len(mail.outbox), 0)  # cooldown activo, no reenvía de inmediato


class EliminarCuentaTests(CuentaTestBase):
    def test_get_no_elimina(self):
        self.marcar_reauth_cliente()
        self.client.get(reverse('accounts:eliminar_cuenta'))
        self.assertTrue(User.objects.filter(pk=self.usuario.pk).exists())

    def test_post_sin_reauth_no_elimina(self):
        self.client.post(reverse('accounts:eliminar_cuenta'), {'confirmacion': 'cuentaqa'})
        self.assertTrue(User.objects.filter(pk=self.usuario.pk).exists())

    def test_confirmacion_incorrecta_no_elimina(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:eliminar_cuenta'), {'confirmacion': 'nombre-equivocado'})
        self.assertTrue(User.objects.filter(pk=self.usuario.pk).exists())

    def test_confirmacion_correcta_elimina_en_cascada(self):
        from apps.interacciones.models import Favorito, Resena

        categoria = CategoriaEstablecimiento.objects.create(nombre='Cafeterías F4', slug='cafeterias-f4')
        establecimiento = Establecimiento.objects.create(
            tipo='restaurante', categoria_principal=categoria, nombre='Local F4', slug='local-f4',
        )
        Favorito.objects.create(usuario=self.usuario, establecimiento=establecimiento)
        Resena.objects.create(usuario=self.usuario, establecimiento=establecimiento, valoracion=5)
        SocialAccount.objects.create(user=self.usuario, provider='google', uid='uid-1')
        usuario_pk = self.usuario.pk

        self.marcar_reauth_cliente()
        response = self.client.post(reverse('accounts:eliminar_cuenta'), {'confirmacion': 'cuentaqa'})
        self.assertRedirects(response, reverse('accounts:cuenta_eliminada'))

        self.assertFalse(User.objects.filter(pk=usuario_pk).exists())
        self.assertFalse(PerfilUsuario.objects.filter(user_id=usuario_pk).exists())
        self.assertFalse(Favorito.objects.filter(usuario_id=usuario_pk).exists())
        self.assertFalse(Resena.objects.filter(usuario_id=usuario_pk).exists())
        self.assertFalse(SocialAccount.objects.filter(user_id=usuario_pk).exists())
        # El contenido turístico no se toca.
        self.assertTrue(Establecimiento.objects.filter(pk=establecimiento.pk).exists())

    def test_sesion_queda_cerrada_tras_eliminar(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:eliminar_cuenta'), {'confirmacion': 'cuentaqa'})
        response = self.client.get(reverse('accounts:cuenta'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_pantalla_final_publica_sin_sesion(self):
        self.marcar_reauth_cliente()
        self.client.post(reverse('accounts:eliminar_cuenta'), {'confirmacion': 'cuentaqa'})
        self.client.logout()
        response = self.client.get(reverse('accounts:cuenta_eliminada'))
        self.assertEqual(response.status_code, 200)

    def test_notificacion_solo_si_email_verificado(self):
        PerfilUsuario.objects.filter(user=self.usuario).update(verificado=False)
        self.marcar_reauth_cliente()
        mail.outbox.clear()
        self.client.post(reverse('accounts:eliminar_cuenta'), {'confirmacion': 'cuentaqa'})
        self.assertEqual(len(mail.outbox), 0)

    def test_fallo_de_notificacion_no_impide_eliminar(self):
        self.marcar_reauth_cliente()
        usuario_pk = self.usuario.pk
        with patch('apps.accounts.views.send_mail', side_effect=Exception('smtp caído')):
            response = self.client.post(reverse('accounts:eliminar_cuenta'), {'confirmacion': 'cuentaqa'})
        self.assertRedirects(response, reverse('accounts:cuenta_eliminada'))
        self.assertFalse(User.objects.filter(pk=usuario_pk).exists())


def _request_con_sesion(usuario=None):
    from django.contrib.sessions.middleware import SessionMiddleware
    request = RequestFactory().get('/')
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    request.user = usuario or AnonymousUser()
    return request


class ConnectServerSideGuardTests(CuentaTestBase):
    def test_connect_sin_reauth_bloquea(self):
        request = _request_con_sesion(self.usuario)
        sociallogin = SocialLogin()
        sociallogin.state = {'process': AuthProcess.CONNECT}
        with self.assertRaises(ImmediateHttpResponse):
            ViajeInformadoSocialAccountAdapter().pre_social_login(request, sociallogin)
        self.assertFalse(SocialAccount.objects.filter(user=self.usuario).exists())

    def test_connect_anonimo_bloquea(self):
        request = _request_con_sesion(None)
        sociallogin = SocialLogin()
        sociallogin.state = {'process': AuthProcess.CONNECT}
        with self.assertRaises(ImmediateHttpResponse):
            ViajeInformadoSocialAccountAdapter().pre_social_login(request, sociallogin)

    def test_connect_con_reauth_no_bloquea(self):
        request = _request_con_sesion(self.usuario)
        marcar_reauth(request)
        sociallogin = SocialLogin()
        sociallogin.state = {'process': AuthProcess.CONNECT}
        ViajeInformadoSocialAccountAdapter().pre_social_login(request, sociallogin)  # no debe lanzar

    def test_login_social_normal_no_exige_reauth(self):
        request = _request_con_sesion(self.usuario)
        sociallogin = SocialLogin()
        sociallogin.state = {'process': AuthProcess.LOGIN}
        ViajeInformadoSocialAccountAdapter().pre_social_login(request, sociallogin)  # no debe lanzar

    def test_signup_social_sin_process_no_exige_reauth(self):
        request = _request_con_sesion(None)
        sociallogin = SocialLogin()
        sociallogin.state = {}
        ViajeInformadoSocialAccountAdapter().pre_social_login(request, sociallogin)  # no debe lanzar

    def test_href_provider_login_url_incluye_process_y_next(self):
        self.marcar_reauth_cliente()
        with patch.dict('django.conf.settings.SOCIALACCOUNT_PROVIDERS', {
            'google': {'APP': {'client_id': 'test-client-id', 'secret': 'x', 'key': ''}, 'SCOPE': ['profile', 'email']},
            'facebook': {'APP': {'client_id': '', 'secret': '', 'key': ''}, 'SCOPE': ['email', 'public_profile']},
        }):
            response = self.client.get(reverse('accounts:cuenta'))
        contenido = response.content.decode()
        self.assertIn('process=connect', contenido)
        self.assertNotIn('??', contenido)
        match = re.search(r'href="([^"]*google[^"]*process=connect[^"]*)"', contenido)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).count('?'), 1)
