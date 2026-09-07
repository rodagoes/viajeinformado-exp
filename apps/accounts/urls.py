from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('iniciar-sesion/', views.iniciar_sesion, name='login'),
    path('registrarse/', views.registro, name='registro'),
    path('cerrar-sesion/', views.cerrar_sesion, name='logout'),
    path('verificar-codigo/', views.verificar_codigo, name='verificar_codigo'),
    path('reenviar-codigo/', views.reenviar_codigo, name='reenviar_codigo'),
    path('mi-cuenta/perfil/', views.perfil, name='perfil'),
    path('mi-cuenta/cuenta/', views.cuenta, name='cuenta'),
    path('mi-cuenta/cuenta/email/', views.cambiar_email, name='cambiar_email'),
    path('mi-cuenta/cuenta/email/verificar/', views.verificar_nuevo_email, name='verificar_nuevo_email'),
    path('mi-cuenta/cuenta/email/reenviar/', views.reenviar_codigo_email, name='reenviar_codigo_email'),
    path('mi-cuenta/cuenta/password/', views.gestionar_password, name='gestionar_password'),
    path('mi-cuenta/cuenta/social/<str:provider>/desconectar/', views.desconectar_social, name='desconectar_social'),
    path('mi-cuenta/cuenta/reauth/', views.reauth, name='reauth'),
    path('mi-cuenta/cuenta/reauth/reenviar/', views.reenviar_codigo_reauth, name='reenviar_codigo_reauth'),
    path('mi-cuenta/cuenta/eliminar/', views.eliminar_cuenta, name='eliminar_cuenta'),
    path('cuenta-eliminada/', views.cuenta_eliminada, name='cuenta_eliminada'),
]
