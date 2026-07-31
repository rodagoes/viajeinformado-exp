"""
Lógica de datos para la pantalla Planifica → Tarifas de Taxi.

Mantiene la vista y el template libres de consultas, conversión de
moneda y resolución de imágenes.
"""
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.templatetags.static import static

from apps.monedas.models import TipoCambio

from ..models import ConsejoMovilidad, TransportePublico

logger = logging.getLogger(__name__)

# Fallback temporal mientras un transporte no tenga fotografía cargada
# desde Django Admin. Solo rutas de respaldo: nada de nombres/precios aquí.
IMAGENES_FALLBACK = {
    "mototaxi": "assets/img/tarifataxi/vi-transporte1.png",
    "colectivos": "assets/img/tarifataxi/vi-transporte2.png",
    "microbuses": "assets/img/tarifataxi/vi-transporte3.png",
}


def _convertir_pen_a_usd(monto_pen, tipo_cambio):
    if not tipo_cambio or not tipo_cambio.venta:
        return None
    try:
        venta = Decimal(tipo_cambio.venta)
        if venta <= 0:
            return None
        return (monto_pen / venta).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        logger.exception(
            "No se pudo convertir S/. %s a USD con el tipo de cambio %s",
            monto_pen, tipo_cambio,
        )
        return None


def _resolver_imagen(transporte):
    if transporte.imagen:
        return transporte.imagen.url, (transporte.texto_alt_imagen or transporte.nombre)

    ruta_fallback = IMAGENES_FALLBACK.get(transporte.slug)
    if ruta_fallback:
        return static(ruta_fallback), transporte.nombre

    return "", transporte.nombre


def _tipo_cambio_vigente():
    try:
        return TipoCambio.vigente()
    except Exception:
        logger.exception("No se pudo obtener el tipo de cambio vigente para Tarifas de Taxi.")
        return None


def obtener_transportes_con_tarifas():
    """Transportes activos, ordenados, con imagen resuelta y conversión PEN→USD."""
    tipo_cambio = _tipo_cambio_vigente()
    transportes = TransportePublico.objects.filter(activo=True).order_by("orden", "nombre")

    resultado = []
    for transporte in transportes:
        imagen_url, imagen_alt = _resolver_imagen(transporte)
        precio_usd = _convertir_pen_a_usd(transporte.tarifa_minima, tipo_cambio)
        resultado.append({
            "nombre": transporte.nombre,
            "nombre_alternativo": transporte.nombre_alternativo,
            "descripcion": transporte.descripcion,
            "imagen_url": imagen_url,
            "imagen_alt": imagen_alt,
            "precio_desde_txt": f"{transporte.tarifa_minima:.2f}",
            "precio_usd_txt": f"{precio_usd:.2f}" if precio_usd is not None else None,
        })
    return resultado


def obtener_consejos_movilidad():
    """Textos de los consejos activos de Transporte y tarifas, en orden."""
    return list(
        ConsejoMovilidad.objects.filter(activo=True, seccion="tarifas_taxi")
        .order_by("orden", "id")
        .values_list("texto", flat=True)
    )
