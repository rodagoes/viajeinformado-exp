from django.urls import path
from . import views

app_name = 'turismo'

urlpatterns = [
    path('lugares-turisticos/', views.listado_lugares, name='listado_lugares'),
    path('lugares-turisticos/<slug:slug>/', views.detalle_lugar, name='detalle_lugar'),
]
