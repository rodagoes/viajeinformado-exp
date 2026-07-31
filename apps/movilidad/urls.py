from django.urls import path

from .views import ComoLlegarView, TarifasTaxiView

app_name = "movilidad"

urlpatterns = [
    path("tarifas-taxi/", TarifasTaxiView.as_view(), name="tarifas_taxi"),
    path("como-llegar/", ComoLlegarView.as_view(), name="como_llegar"),
]
