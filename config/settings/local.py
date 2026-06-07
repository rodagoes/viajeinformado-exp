from .base import *

DEBUG = env.bool('DEBUG', default=True)

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
