from django.urls import path

from . import views

app_name = "ubicaciones"

urlpatterns = [
    path("provincia/<slug:slug>/", views.provincia_detalle, name="provincia_detalle"),
]
