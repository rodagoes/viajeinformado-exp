from django.urls import path

from .views import servicios_utiles

app_name = "servicios_turista"

urlpatterns = [
    path("servicios-utiles/", servicios_utiles, name="servicios_utiles"),
]
