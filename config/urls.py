"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.metricas.views import cambiar_idioma

urlpatterns = [
    # Mismo endpoint y nombre que django.conf.urls.i18n, con la métrica de cambio de idioma.
    path('i18n/setlang/', cambiar_idioma, name='set_language'),
    path('admin/', admin.site.urls),
    path('', include('apps.base.urls')),
    path('', include('apps.accounts.urls')),
    path('cuentas/', include('allauth.urls')),
    path('', include('apps.establecimientos.urls')),
    path('gastronomia/', include('apps.gastronomia.urls')),
    path('', include('apps.turismo.urls')),
    path('mi-cuenta/', include('apps.interacciones.urls')),
    path('eventos/', include('apps.eventos.urls')),
    path('planifica/', include('apps.movilidad.urls')),
    path('planifica/', include('apps.clima.urls')),
    path('planifica/', include('apps.emergencias.urls')),
    path('planifica/', include('apps.monedas.urls')),
    path('planifica/', include('apps.servicios_turista.urls')),
    path('ubicaciones/', include('apps.ubicaciones.urls')),
    path('chatbot/', include('apps.chatbot.urls')),
    path('metricas/', include('apps.metricas.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Using STATICFILES_DIRS[0] is typically not needed for STATIC_URL in urls.py as runserver handles it,
    # but added as per normal fallback, actually better to just use static for media.
