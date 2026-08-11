from django.urls import path

from .views import TipoCambioView

app_name = "monedas"

urlpatterns = [
    path("tipo-cambio/", TipoCambioView.as_view(), name="tipo_cambio"),
]
