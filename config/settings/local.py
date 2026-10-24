import sys

from .base import *

DEBUG = env.bool('DEBUG', default=True)

# Métricas REALES activas solo en desarrollo local. Se apagan durante `manage.py test` para no alterar
# los tests de otras apps (consultas, filas creadas); los tests de apps.metricas lo activan con override_settings.
METRICAS_REAL_HABILITADAS = 'test' not in sys.argv
# Herramientas de tesis/prueba visibles en el Admin local (en producción quedan ocultas).
METRICAS_ADMIN_PRUEBAS_VISIBLE = env.bool('METRICAS_ADMIN_PRUEBAS_VISIBLE', default=True)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('DB_NAME'),
        'USER': env('DB_USER_NAME'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST_NAME'),
        'PORT': env('DB_PORT'),
    }
}
