import environ
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Initialize environ
env = environ.Env()

# Read .env file
environ.Env.read_env(BASE_DIR / '.env')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG', default=False)

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

# API tipo de cambio SUNAT/SBS - Decolecta / apis.net.pe
DECOLECTA_TIPO_CAMBIO_URL = env(
    "DECOLECTA_TIPO_CAMBIO_URL",
    default="https://api.decolecta.com/v1/tipo-cambio/sunat"
)

# Token opcional. Si Decolecta lo exige en producción, agrégalo en el .env.
DECOLECTA_API_TOKEN = env("DECOLECTA_API_TOKEN", default="")

# Clima y temporadas (Huánuco y Tingo María) - proveedor Open-Meteo,
# no requiere API key.
CLIMA_HUANUCO_LATITUD = env("CLIMA_HUANUCO_LATITUD", default="")
CLIMA_HUANUCO_LONGITUD = env("CLIMA_HUANUCO_LONGITUD", default="")
CLIMA_TINGO_MARIA_LATITUD = env("CLIMA_TINGO_MARIA_LATITUD", default="")
CLIMA_TINGO_MARIA_LONGITUD = env("CLIMA_TINGO_MARIA_LONGITUD", default="")

# Pillco Bot (apps.chatbot) - Google Gemini. La API key solo vive en el
# entorno del servidor; con default vacío el sitio arranca sin chatbot.
CHATBOT_AI_PROVIDER = env("CHATBOT_AI_PROVIDER", default="gemini")
CHATBOT_AI_MODEL = env("CHATBOT_AI_MODEL", default="gemini-3.6-flash")
CHATBOT_AI_API_KEY = env("CHATBOT_AI_API_KEY", default="")
# Límite máximo por llamada HTTP al proveedor, no una espera artificial.
CHATBOT_AI_TIMEOUT_MS = env.int("CHATBOT_AI_TIMEOUT_MS", default=60000)
# minimal | low | medium | high. Pillco solo interpreta, elige tool y redacta.
CHATBOT_AI_THINKING_LEVEL = env("CHATBOT_AI_THINKING_LEVEL", default="low")
# Proveedor alternativo (CHATBOT_AI_PROVIDER=deepseek). Key independiente de Gemini;
# sin key solo falla si DeepSeek es el proveedor seleccionado.
CHATBOT_DEEPSEEK_API_KEY = env("CHATBOT_DEEPSEEK_API_KEY", default="")
CHATBOT_DEEPSEEK_MODEL = env("CHATBOT_DEEPSEEK_MODEL", default="deepseek-v4-flash")
# Fallback a fuentes oficiales (Gemini Grounding with Google Search). Desactivado
# por defecto: consume cuota del proyecto Gemini. Independiente del proveedor
# conversacional (CHATBOT_AI_PROVIDER).
CHATBOT_EXTERNAL_SEARCH_ENABLED = env.bool("CHATBOT_EXTERNAL_SEARCH_ENABLED", default=False)
CHATBOT_EXTERNAL_SEARCH_PROVIDER = env("CHATBOT_EXTERNAL_SEARCH_PROVIDER", default="gemini")
# Rate limit simple de /chatbot/mensaje/ (ventana fija, django.core.cache).
CHATBOT_RATE_LIMIT_REQUESTS = env.int("CHATBOT_RATE_LIMIT_REQUESTS", default=20)
CHATBOT_RATE_LIMIT_WINDOW_SECONDS = env.int("CHATBOT_RATE_LIMIT_WINDOW_SECONDS", default=60)

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.humanize',

    # Autenticación social
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.facebook',

    # Apps
    'apps.base',
    'apps.accounts',
    'apps.ubicaciones',
    'apps.turismo',
    'apps.establecimientos',
    'apps.gastronomia',
    'apps.eventos',
    'apps.interacciones',
    'apps.movilidad',
    'apps.clima',
    'apps.emergencias',
    'apps.itinerarios',
    'apps.servicios_turista',
    'apps.monedas',
    'apps.chatbot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

SITE_ID = 1

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.base.context_processors.header_nav_items',
                'apps.base.context_processors.active_nav',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'es'

TIME_ZONE = 'America/Lima'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

# STATIC_URL = 'static/'
# STATICFILES_DIRS = [BASE_DIR / 'static']

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# MEDIA_URL = 'media/'
# MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==========================================================
# Autenticación
# ==========================================================

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# django-allauth: solo se usa para login social (Google/Facebook).
# El registro/login normal usa las vistas propias de apps.accounts.
ACCOUNT_EMAIL_VERIFICATION = 'none'
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_ADAPTER = 'apps.accounts.adapters.ViajeInformadoSocialAccountAdapter'
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': env('GOOGLE_CLIENT_ID', default=''),
            'secret': env('GOOGLE_CLIENT_SECRET', default=''),
            'key': '',
        },
        'SCOPE': ['profile', 'email'],
    },
    'facebook': {
        'APP': {
            'client_id': env('FACEBOOK_CLIENT_ID', default=''),
            'secret': env('FACEBOOK_CLIENT_SECRET', default=''),
            'key': '',
        },
        'SCOPE': ['email', 'public_profile'],
    },
}

# ==========================================================
# Correo (OTP). En desarrollo usa consola; en producción SMTP vía .env
# ==========================================================

EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Viaje Informado <no-responder@viajeinformado.digital>')

# Destinatario de los formularios de "Promociona tu evento" / "Reportar un
# problema" del módulo Eventos. Reutiliza el backend/credenciales SMTP de
# arriba (no hay una segunda config de correo) — solo el destinatario es
# específico de este módulo y configurable por entorno.
EVENTOS_CONTACT_EMAIL = env('EVENTOS_CONTACT_EMAIL', default='viajeinformadohuanuco@gmail.com')

# ==========================================================
# OTP
# ==========================================================

OTP_EXPIRATION_MINUTES = env.int('OTP_EXPIRATION_MINUTES', default=10)
OTP_RESEND_COOLDOWN_SECONDS = env.int('OTP_RESEND_COOLDOWN_SECONDS', default=120)
OTP_MAX_ATTEMPTS = env.int('OTP_MAX_ATTEMPTS', default=3)

# ==========================================================
# Cambio de username (preparado para "Configuración de cuenta", aún no implementado)
# ==========================================================

USERNAME_CHANGE_COOLDOWN_DAYS = 20

# ==========================================================
# Sesiones: expiración por inactividad
# ==========================================================
# La sesión dura 4 horas, pero SESSION_SAVE_EVERY_REQUEST renueva ese
# plazo en cada request, así que en la práctica expira por inactividad
# (4 horas sin navegar), no 4 horas fijas desde el login.
SESSION_COOKIE_AGE = 60 * 60 * 4  # 4 horas
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
