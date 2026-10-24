from .base import *

DEBUG = False

# Seguimiento REAL: APAGADO si la variable no existe. Activar (METRICAS_REAL_HABILITADAS=True en .env)
# solo después de la validación final y con autorización expresa.
METRICAS_REAL_HABILITADAS = env.bool('METRICAS_REAL_HABILITADAS', default=False)

# Producción: sin herramientas de tesis en el Admin y cifras del Home (si se activan) solo con datos REALES.
METRICAS_ADMIN_PRUEBAS_VISIBLE = env.bool('METRICAS_ADMIN_PRUEBAS_VISIBLE', default=False)
METRICAS_HOME_ORIGEN = env('METRICAS_HOME_ORIGEN', default='REAL')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('DB_NAME'),
        'USER': env('DB_USER_NAME'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST_NAME'),
        'PORT': env('DB_PORT'),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    }
}

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
