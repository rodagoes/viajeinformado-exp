from django.urls import path

from . import views

app_name = 'eventos'

urlpatterns = [
    path('', views.listado_eventos, name='listado_eventos'),
    path('promocionar/', views.promocionar_evento, name='promocionar_evento'),
    path('reportar/', views.reportar_problema_evento, name='reportar_problema_evento'),
]
