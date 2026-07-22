from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('iniciar-sesion/', views.iniciar_sesion, name='login'),
    path('registrarse/', views.registro, name='registro'),
    path('cerrar-sesion/', views.cerrar_sesion, name='logout'),
    path('verificar-codigo/', views.verificar_codigo, name='verificar_codigo'),
    path('reenviar-codigo/', views.reenviar_codigo, name='reenviar_codigo'),
]
