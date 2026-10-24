from django.db import models


class OrigenDato(models.TextChoices):
    SIMULADO = "SIMULADO", "Simulado"
    REAL = "REAL", "Real"
    GA4 = "GA4", "Google Analytics 4"


class AlcancePeriodo(models.TextChoices):
    MUESTRA_REGISTRADA = "MUESTRA_REGISTRADA", "Muestra de usuarios registrados"
    TODOS_VISITANTES = "TODOS_VISITANTES", "Todos los visitantes"


class FuenteTrafico(models.TextChoices):
    DIRECTO = "DIRECTO", "Acceso directo"
    ORGANICO = "ORGANICO", "Búsqueda orgánica"
    SOCIAL = "SOCIAL", "Redes sociales"
    REFERIDO = "REFERIDO", "Referidos"
    OTROS = "OTROS", "Otros"


class DispositivoAcceso(models.TextChoices):
    MOVIL = "MOVIL", "Móvil"
    ESCRITORIO = "ESCRITORIO", "Escritorio"
    TABLET = "TABLET", "Tablet"


class GranularidadUnicos(models.TextChoices):
    SEMANA = "SEMANA", "Semana"
    MES = "MES", "Mes"


class TipoInteraccion(models.TextChoices):
    CHATBOT_CONSULTA = "chatbot_consulta", "Consulta al chatbot"
    LUGAR_DETALLE_CLICK = "lugar_detalle_click", "Lugar turístico: abrir detalle"
    RESTAURANTE_DETALLE_CLICK = "restaurante_detalle_click", "Restaurante: abrir detalle"
    ALOJAMIENTO_DETALLE_CLICK = "alojamiento_detalle_click", "Alojamiento: abrir detalle"
    EVENTO_DETALLE_CLICK = "evento_detalle_click", "Evento: abrir detalle"
    GASTRONOMIA_DONDE_COMER_CLICK = "gastronomia_donde_comer_click", "Gastronomía: Dónde comer"
    FAVORITO_AGREGADO = "favorito_agregado", "Favorito agregado"
    UBICACION_CLICK = "ubicacion_click", "Ubicación / mapa / Cómo llegar"
    IDIOMA_CAMBIADO = "idioma_cambiado", "Cambio de idioma"


class EstadoGeneracion(models.TextChoices):
    PREVISUALIZADA = "PREVISUALIZADA", "Previsualizada"
    GENERADA = "GENERADA", "Generada"
    REEMPLAZADA = "REEMPLAZADA", "Reemplazada"
    FALLIDA = "FALLIDA", "Fallida"
