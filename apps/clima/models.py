from django.db import models  # noqa: F401

# El contenido de "Clima y temporadas" es estático (ver templates/clima) y el
# dato meteorológico dinámico viene de Open-Meteo (ver services/clima_actual.py).
# Esta app no requiere modelos.
