"""Filtros de plantilla exclusivos de "Clima y temporadas".

Traducen el estado interno normalizado (ver services/clima_actual.py) a un
ícono de Bootstrap Icons, sin que el template conozca nada del proveedor
meteorológico (Open-Meteo).
"""
from django import template

register = template.Library()

_ICONOS_POR_ESTADO = {
    "soleado": ("bi-brightness-high-fill", "bi-moon-stars-fill"),
    "mayormente-despejado": ("bi-brightness-high-fill", "bi-moon-stars-fill"),
    "parcialmente-nublado": ("bi-cloud-sun-fill", "bi-cloud-moon-fill"),
    "nublado": ("bi-clouds-fill", "bi-clouds-fill"),
    "neblina": ("bi-cloud-haze2-fill", "bi-cloud-haze2-fill"),
    "llovizna": ("bi-cloud-drizzle-fill", "bi-cloud-drizzle-fill"),
    "lluvia": ("bi-cloud-rain-heavy-fill", "bi-cloud-rain-heavy-fill"),
    "lluvia-intensa": ("bi-cloud-rain-heavy-fill", "bi-cloud-rain-heavy-fill"),
    "nieve": ("bi-cloud-snow-fill", "bi-cloud-snow-fill"),
    "tormenta": ("bi-cloud-lightning-rain-fill", "bi-cloud-lightning-rain-fill"),
}
_ICONO_PREDETERMINADO = "bi-clouds-fill"


@register.filter(name="icono_clima")
def icono_clima(estado_slug, es_dia):
    icono_dia, icono_noche = _ICONOS_POR_ESTADO.get(estado_slug, (_ICONO_PREDETERMINADO, _ICONO_PREDETERMINADO))
    return icono_dia if es_dia else icono_noche
