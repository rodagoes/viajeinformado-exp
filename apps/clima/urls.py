from django.urls import path

from .views import ClimaTemporadasView

app_name = "clima"

urlpatterns = [
    path("clima-temporadas/", ClimaTemporadasView.as_view(), name="clima_temporadas"),
]
