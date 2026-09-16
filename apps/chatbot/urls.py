from django.urls import path

from . import views

app_name = "chatbot"

urlpatterns = [
    path("mensaje/", views.enviar_mensaje, name="enviar_mensaje"),
]
