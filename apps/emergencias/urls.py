from django.urls import path

from .views import EmergenciasView, ReportarProblemaEmergenciasView

app_name = "emergencias"

urlpatterns = [
    path("emergencias/", EmergenciasView.as_view(), name="emergencias"),
    path("emergencias/reportar/", ReportarProblemaEmergenciasView.as_view(), name="reportar_problema"),
]
