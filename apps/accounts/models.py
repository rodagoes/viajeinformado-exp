import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class PerfilUsuario(models.Model):
    ROL_TURISTA = 'turista'
    ROL_ADMINISTRADOR = 'administrador'
    ROLES = [
        (ROL_TURISTA, 'Turista'),
        (ROL_ADMINISTRADOR, 'Administrador'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    nombres_apellidos = models.CharField(max_length=150)
    rol = models.CharField(max_length=20, choices=ROLES, default=ROL_TURISTA)
    verificado = models.BooleanField(default=False)
    foto_perfil = models.ImageField(upload_to='usuarios/perfiles/', blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil de usuario'
        verbose_name_plural = 'Perfiles de usuario'

    def __str__(self):
        return f'{self.user.username} ({self.get_rol_display()})'


class CodigoOTP(models.Model):
    PROPOSITO_VERIFICACION = 'account_verification'

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='codigos_otp')
    otp_hash = models.CharField(max_length=128)
    proposito = models.CharField(max_length=40, default=PROPOSITO_VERIFICACION)
    creado_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField()
    usado = models.BooleanField(default=False)
    intentos = models.PositiveSmallIntegerField(default=0)
    ultimo_reenvio = models.DateTimeField(null=True, blank=True)
    fecha_uso = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Código OTP'
        verbose_name_plural = 'Códigos OTP'
        ordering = ['-creado_en']

    def __str__(self):
        return f'OTP {self.usuario.username} ({self.proposito})'

    @property
    def expirado(self):
        return timezone.now() >= self.expira_en

    @classmethod
    def generar(cls, usuario, proposito=PROPOSITO_VERIFICACION):
        """Invalida códigos previos, crea uno nuevo y devuelve el código en claro (solo para enviarlo por correo)."""
        cls.objects.filter(usuario=usuario, proposito=proposito, usado=False).update(usado=True)
        codigo = f'{secrets.randbelow(10000):04d}'
        cls.objects.create(
            usuario=usuario,
            proposito=proposito,
            otp_hash=make_password(codigo),
            expira_en=timezone.now() + timedelta(minutes=settings.OTP_EXPIRATION_MINUTES),
        )
        return codigo

    @classmethod
    def activo(cls, usuario, proposito=PROPOSITO_VERIFICACION):
        return cls.objects.filter(usuario=usuario, proposito=proposito, usado=False).first()

    @classmethod
    def verificar(cls, usuario, codigo, proposito=PROPOSITO_VERIFICACION):
        """Devuelve (ok, mensaje_error)."""
        otp = cls.activo(usuario, proposito)
        if otp is None or otp.expirado:
            return False, 'El código ha expirado. Solicita uno nuevo.'
        if otp.intentos >= settings.OTP_MAX_ATTEMPTS:
            return False, 'Has superado el número máximo de intentos. Solicita un nuevo código.'
        if not check_password(codigo, otp.otp_hash):
            otp.intentos += 1
            otp.save(update_fields=['intentos'])
            restantes = settings.OTP_MAX_ATTEMPTS - otp.intentos
            if restantes <= 0:
                return False, 'Has superado el número máximo de intentos. Solicita un nuevo código.'
            return False, f'Código incorrecto. Te quedan {restantes} intentos.'
        otp.usado = True
        otp.fecha_uso = timezone.now()
        otp.save(update_fields=['usado', 'fecha_uso'])
        return True, ''

    def segundos_para_reenvio(self):
        base = self.ultimo_reenvio or self.creado_en
        transcurrido = (timezone.now() - base).total_seconds()
        return max(0, int(settings.OTP_RESEND_COOLDOWN_SECONDS - transcurrido))
