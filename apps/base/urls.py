from django.urls import path
from . import views

app_name = 'base'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('historia/', views.HistoriaView.as_view(), name='historia'),
    path('privacidad/', views.PrivacidadView.as_view(), name='privacidad'),
    path('terminos/', views.TerminosView.as_view(), name='terminos'),
    path('contacto/', views.ContactoView.as_view(), name='contacto'),
    path('login-preview/', views.LoginVisualView.as_view(), name='login_visual'),
]
