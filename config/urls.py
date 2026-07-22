"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.base.urls')),
    path('', include('apps.accounts.urls')),
    path('cuentas/', include('allauth.urls')),
    path('', include('apps.establecimientos.urls')),
    path('', include('apps.turismo.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Using STATICFILES_DIRS[0] is typically not needed for STATIC_URL in urls.py as runserver handles it,
    # but added as per normal fallback, actually better to just use static for media.
