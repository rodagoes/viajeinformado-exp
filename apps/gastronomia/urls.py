from django.urls import path

from . import views

app_name = 'gastronomia'

urlpatterns = [
    path('platos-tipicos/', views.platos_tipicos, name='platos_tipicos'),
]
