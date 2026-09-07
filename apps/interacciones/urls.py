from django.urls import path

from . import views

app_name = "interacciones"

urlpatterns = [
    path("favoritos/", views.favoritos, name="favoritos"),
    path("favoritos/toggle/<str:tipo>/<int:pk>/", views.toggle_favorito, name="toggle_favorito"),
    path("resenas/<str:tipo>/<int:pk>/eliminar/", views.eliminar_resena, name="eliminar_resena"),
]
