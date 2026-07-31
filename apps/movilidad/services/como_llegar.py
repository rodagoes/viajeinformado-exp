"""
Lógica de datos para la pantalla Planifica → ¿Cómo llegar a Huánuco?

Mantiene la vista y el template libres de consultas ORM.
"""
from ..models import ConsejoMovilidad, RutaMovilidad


def _rutas_como_llegar(slug_categoria):
    return (
        RutaMovilidad.objects.filter(
            seccion="como_llegar",
            categoria_principal__slug=slug_categoria,
            activo=True,
        )
        .select_related("categoria_principal")
        .prefetch_related("imagenes")
        .order_by("orden", "nombre")
    )


def obtener_rutas_terrestres():
    return _rutas_como_llegar("via-terrestre")


def obtener_rutas_aereas():
    return _rutas_como_llegar("via-aerea")


def _consejos_como_llegar(seccion):
    return list(
        ConsejoMovilidad.objects.filter(activo=True, seccion=seccion)
        .order_by("orden", "id")
        .values_list("texto", flat=True)
    )


def obtener_consejos_terrestres():
    return _consejos_como_llegar("como_llegar_terrestre")


def obtener_consejos_aereos():
    return _consejos_como_llegar("como_llegar_aerea")
