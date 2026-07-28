from django.urls import path

from .views import TarifasTaxiView

app_name = "movilidad"

urlpatterns = [
    path("tarifas-taxi/", TarifasTaxiView.as_view(), name="tarifas_taxi"),
]
