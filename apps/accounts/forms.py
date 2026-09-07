import re

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

USERNAME_RE = re.compile(r'^[A-Za-z0-9](?:[._-]?[A-Za-z0-9])+$')
PASSWORD_SYMBOLS = r'!@#%&*?$.\-_+=,;:()\[\]{}/\\|~^<>\'"`'


class RegistroForm(forms.Form):
    nombres = forms.CharField(
        label='Nombres', max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. Rodrigo', 'autocomplete': 'given-name'}),
    )
    apellidos = forms.CharField(
        label='Apellidos', max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. Acuña Gonzales', 'autocomplete': 'family-name'}),
    )
    username = forms.CharField(
        label='Nombre de usuario', min_length=4, max_length=30,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. rodrigo.acuna', 'autocomplete': 'username'}),
    )
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'placeholder': 'tucorreo@ejemplo.com', 'autocomplete': 'email', 'inputmode': 'email'}),
    )
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'placeholder': 'Mínimo 8 caracteres', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={'placeholder': 'Repite tu contraseña', 'autocomplete': 'new-password'}),
    )

    def _limpiar_solo_letras(self, valor, etiqueta):
        texto = re.sub(r'\s+', ' ', valor.strip())
        if not texto or not all(c.isalpha() or c == ' ' for c in texto):
            raise forms.ValidationError(f'El {etiqueta} solo debe contener letras y espacios.')
        return texto

    def clean_nombres(self):
        return self._limpiar_solo_letras(self.cleaned_data['nombres'], 'nombre')

    def clean_apellidos(self):
        return self._limpiar_solo_letras(self.cleaned_data['apellidos'], 'apellido')

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if not USERNAME_RE.fullmatch(username):
            raise forms.ValidationError(
                'El nombre de usuario solo puede contener letras, números, punto, guion o guion bajo. '
                'No puede empezar ni terminar con punto, guion o guion bajo.'
            )
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Este nombre de usuario ya está en uso. Elige otro.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta registrada con este correo.')
        return email

    def clean_password1(self):
        password = self.cleaned_data['password1']
        errores = []
        if len(password) < 8:
            errores.append('Tu contraseña debe tener al menos 8 caracteres.')
        if not re.search(r'[A-ZÁÉÍÓÚÑ]', password):
            errores.append('Debe incluir una letra mayúscula.')
        if not re.search(r'[a-záéíóúñ]', password):
            errores.append('Debe incluir una letra minúscula.')
        if not re.search(r'\d', password):
            errores.append('Debe incluir al menos un número.')
        if not re.search(f'[{PASSWORD_SYMBOLS}]', password):
            errores.append('Debe incluir al menos un símbolo (! @ # % & * ? $ . -).')
        if errores:
            raise forms.ValidationError(errores)
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Ambas contraseñas deben coincidir.')
        return cleaned

    def save(self):
        from .models import PerfilUsuario
        datos = self.cleaned_data
        user = User.objects.create_user(
            username=datos['username'],
            email=datos['email'],
            password=datos['password1'],
            first_name=datos['nombres'],
            last_name=datos['apellidos'],
        )
        PerfilUsuario.objects.create(
            user=user,
            nombres_apellidos=f"{datos['nombres']} {datos['apellidos']}",
        )
        return user


class LoginForm(forms.Form):
    identificador = forms.CharField(
        label='Usuario o correo',
        widget=forms.TextInput(attrs={'placeholder': 'Ingresa tu usuario o correo', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'placeholder': 'Ingresa tu contraseña', 'autocomplete': 'current-password'}),
    )


NOMBRE_APELLIDO_CARACTERES_EXTRA = " '’-"


def limpiar_nombre_persona(valor, etiqueta):
    """Exige al menos una letra y que empiece/termine en letra (Unicode) —
    rechaza valores formados solo por guiones/apóstrofes o que empiecen/
    terminen con ellos, pero permite 'O'Connor', 'Pérez-Ríos', 'De la Cruz'."""
    texto = re.sub(r'\s+', ' ', (valor or '').strip())
    valido = (
        bool(texto)
        and all(c.isalpha() or c in NOMBRE_APELLIDO_CARACTERES_EXTRA for c in texto)
        and texto[0].isalpha()
        and texto[-1].isalpha()
    )
    if not valido:
        raise forms.ValidationError(
            f'El {etiqueta} debe contener solo letras, espacios, guiones o apóstrofes, '
            'y empezar y terminar con una letra.'
        )
    return texto


class NombreForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name']
        widgets = {'first_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'given-name'})}

    def clean_first_name(self):
        return limpiar_nombre_persona(self.cleaned_data['first_name'], 'nombre')


class ApellidoForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['last_name']
        widgets = {'last_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'family-name'})}

    def clean_last_name(self):
        return limpiar_nombre_persona(self.cleaned_data['last_name'], 'apellido')


class UsernameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username']
        widgets = {'username': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'username'})}

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if not USERNAME_RE.fullmatch(username):
            raise forms.ValidationError(
                'El nombre de usuario solo puede contener letras, números, punto, guion o guion bajo. '
                'No puede empezar ni terminar con punto, guion o guion bajo.'
            )
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Este nombre de usuario ya está en uso. Elige otro.')
        return username


class CambiarEmailForm(forms.Form):
    nuevo_email = forms.EmailField(
        label='Nuevo correo electrónico',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'email', 'inputmode': 'email'}),
    )

    def __init__(self, *args, usuario_actual, **kwargs):
        self.usuario_actual = usuario_actual
        super().__init__(*args, **kwargs)

    def clean_nuevo_email(self):
        email = self.cleaned_data['nuevo_email'].strip().lower()
        if email == (self.usuario_actual.email or '').lower():
            raise forms.ValidationError('Este ya es tu correo electrónico actual.')
        if User.objects.filter(email__iexact=email).exclude(pk=self.usuario_actual.pk).exists():
            raise forms.ValidationError('Ya existe una cuenta registrada con este correo.')
        return email


class ReauthPasswordForm(forms.Form):
    password = forms.CharField(
        label='Contraseña actual',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'current-password'}),
    )


class EliminarCuentaForm(forms.Form):
    confirmacion = forms.CharField(
        label='Escribe tu nombre de usuario para confirmar',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)

    def clean_confirmacion(self):
        valor = self.cleaned_data['confirmacion'].strip()
        if valor != self.usuario.username:
            raise forms.ValidationError('El nombre de usuario no coincide.')
        return valor


class OTPForm(forms.Form):
    codigo = forms.CharField(
        label='Código de verificación', min_length=4, max_length=4,
        widget=forms.TextInput(attrs={
            'placeholder': '••••', 'inputmode': 'numeric', 'pattern': '[0-9]*',
            'autocomplete': 'one-time-code', 'maxlength': '4',
        }),
    )

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip()
        if not codigo.isdigit():
            raise forms.ValidationError('El código debe tener 4 dígitos.')
        return codigo
