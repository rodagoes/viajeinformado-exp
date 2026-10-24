from django.urls import path

from . import views

app_name = "metricas"

urlpatterns = [
    path("evento/", views.registrar_evento_frontend, name="evento"),
    path("duracion/", views.registrar_duracion, name="duracion"),
]
