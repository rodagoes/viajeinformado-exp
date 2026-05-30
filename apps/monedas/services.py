from datetime import date
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.utils import timezone

from .models import TipoCambio


class TipoCambioAPIError(Exception):
    """Error controlado al consultar o procesar el tipo de cambio."""
    pass


def _extraer_valor(payload, nombres):
    for nombre in nombres:
        if nombre in payload and payload[nombre] not in (None, ""):
            return payload[nombre]
    return None


def _parse_decimal(valor, nombre_campo):
    if valor in (None, ""):
        raise TipoCambioAPIError(f"No se encontró el campo {nombre_campo} en la respuesta de la API.")

    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise TipoCambioAPIError(f"El campo {nombre_campo} no tiene un valor decimal válido.") from exc


def _parse_fecha(valor):
    if not valor:
        return timezone.localdate()

    if isinstance(valor, date):
        return valor

    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return timezone.localdate()


def consultar_tipo_cambio_sunat(fecha=None):
    """
    Consulta el tipo de cambio SUNAT/SBS desde Decolecta / apis.net.pe.

    Retorna:
    {
        "fecha": date,
        "compra": Decimal,
        "venta": Decimal,
        "payload": dict
    }
    """

    url = getattr(
        settings,
        "DECOLECTA_TIPO_CAMBIO_URL",
        "https://api.decolecta.com/v1/tipo-cambio/sunat"
    )

    params = {}
    if fecha:
        if hasattr(fecha, "strftime"):
            params["date"] = fecha.strftime("%Y-%m-%d")
        else:
            params["date"] = str(fecha)

    headers = {
        "Accept": "application/json",
        "Referer": "https://apis.net.pe/tipo-de-cambio-sunat-api",
    }

    token = getattr(settings, "DECOLECTA_API_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=12
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TipoCambioAPIError("No se pudo consultar la API de tipo de cambio.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise TipoCambioAPIError("La API no devolvió una respuesta JSON válida.") from exc

    if isinstance(payload, list):
        if not payload:
            raise TipoCambioAPIError("La API devolvió una lista vacía.")
        payload = payload[0]

    if not isinstance(payload, dict):
        raise TipoCambioAPIError("La estructura de respuesta de la API no es válida.")

    compra_raw = _extraer_valor(
        payload,
        (
            "buy_price",
            "precioCompra",
            "precio_compra",
            "compra",
            "buy",
            "purchase",
        )
    )
    venta_raw = _extraer_valor(
        payload,
        (
            "sell_price",
            "precioVenta",
            "precio_venta",
            "venta",
            "sell",
            "sale",
        )
    )
    fecha_raw = _extraer_valor(
        payload,
        (
            "date",
            "fecha",
        )
    )

    compra = _parse_decimal(compra_raw, "compra")
    venta = _parse_decimal(venta_raw, "venta")
    fecha_api = _parse_fecha(fecha_raw)

    return {
        "fecha": fecha_api,
        "compra": compra,
        "venta": venta,
        "payload": payload,
    }


def actualizar_tipo_cambio_sunat(fecha=None, activar=True):
    """
    Consulta la API y guarda/actualiza el tipo de cambio en BD.
    Si activar=True, deja este registro como activo y desactiva los demás.
    """

    data = consultar_tipo_cambio_sunat(fecha=fecha)

    tipo_cambio, _created = TipoCambio.objects.update_or_create(
        fecha=data["fecha"],
        defaults={
            "moneda_origen": "USD",
            "moneda_destino": "PEN",
            "compra": data["compra"],
            "venta": data["venta"],
            "fuente": "SUNAT/SBS - Decolecta",
            "respuesta_api": data["payload"],
            "activo": True,
        }
    )

    if activar:
        TipoCambio.objects.exclude(pk=tipo_cambio.pk).update(activo=False)

    return tipo_cambio
