from django.urls import path
from . import views

app_name = 'establecimientos'

urlpatterns = [
    path('restaurantes/', views.listado_restaurantes, name='listado_restaurantes'),
    path(
        'restaurantes/<slug:slug>/',
        views.detalle_establecimiento,
        {'tipo_establecimiento': 'restaurante'},
        name='detalle_restaurante'
    ),
    path('alojamientos/', views.listado_alojamientos, name='listado_alojamientos'),
    path(
        'alojamientos/<slug:slug>/',
        views.detalle_establecimiento,
        {'tipo_establecimiento': 'alojamiento'},
        name='detalle_alojamiento'
    ),
]
