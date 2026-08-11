from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import TipoCambio
from .services import (
    TipoCambioAPIError,
    actualizar_tipo_cambio_sunat,
    consultar_tipo_cambio_sunat,
)

REQUESTS_GET_PATH = "apps.monedas.services.requests.get"


def _mock_response(json_data=None, http_error=None, json_error=None):
    respuesta = Mock()
    if http_error:
        respuesta.raise_for_status.side_effect = http_error
    else:
        respuesta.raise_for_status.return_value = None
    if json_error:
        respuesta.json.side_effect = json_error
    else:
        respuesta.json.return_value = json_data
    return respuesta


class TipoCambioModelTests(TestCase):
    def test_vigente_devuelve_el_registro_activo_mas_reciente(self):
        TipoCambio.objects.create(
            fecha=date(2026, 8, 9), compra=Decimal("3.30"), venta=Decimal("3.35"), activo=True
        )
        mas_reciente = TipoCambio.objects.create(
            fecha=date(2026, 8, 10), compra=Decimal("3.374"), venta=Decimal("3.391"), activo=True
        )
        self.assertEqual(TipoCambio.vigente(), mas_reciente)

    def test_vigente_devuelve_none_sin_datos(self):
        self.assertIsNone(TipoCambio.vigente())

    def test_vigente_ignora_registros_inactivos(self):
        TipoCambio.objects.create(
            fecha=date(2026, 8, 10), compra=Decimal("3.374"), venta=Decimal("3.391"), activo=False
        )
        self.assertIsNone(TipoCambio.vigente())


class TipoCambioServicioTests(TestCase):
    """No se hace ninguna llamada real a Internet: requests.get está mockeado."""

    @patch(REQUESTS_GET_PATH)
    def test_consulta_exitosa_devuelve_compra_venta_fecha(self, mock_get):
        mock_get.return_value = _mock_response(
            {"buy_price": "3.374", "sell_price": "3.391", "date": "2026-08-10"}
        )
        datos = consultar_tipo_cambio_sunat()
        self.assertEqual(datos["compra"], Decimal("3.374"))
        self.assertEqual(datos["venta"], Decimal("3.391"))
        self.assertEqual(datos["fecha"], date(2026, 8, 10))

    @patch(REQUESTS_GET_PATH)
    def test_alias_de_campos_en_espanol_tambien_se_reconoce(self, mock_get):
        mock_get.return_value = _mock_response(
            {"precio_compra": "3.30", "precio_venta": "3.35", "fecha": "2026-08-01"}
        )
        datos = consultar_tipo_cambio_sunat()
        self.assertEqual(datos["compra"], Decimal("3.30"))
        self.assertEqual(datos["venta"], Decimal("3.35"))

    @patch(REQUESTS_GET_PATH)
    def test_timeout_lanza_tipocambioapierror(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        with self.assertRaises(TipoCambioAPIError):
            consultar_tipo_cambio_sunat()

    @patch(REQUESTS_GET_PATH)
    def test_http_error_lanza_tipocambioapierror(self, mock_get):
        mock_get.return_value = _mock_response(http_error=requests.exceptions.HTTPError())
        with self.assertRaises(TipoCambioAPIError):
            consultar_tipo_cambio_sunat()

    @patch(REQUESTS_GET_PATH)
    def test_json_invalido_lanza_tipocambioapierror(self, mock_get):
        mock_get.return_value = _mock_response(json_error=ValueError("json inválido"))
        with self.assertRaises(TipoCambioAPIError):
            consultar_tipo_cambio_sunat()

    @patch(REQUESTS_GET_PATH)
    def test_payload_lista_vacia_lanza_error(self, mock_get):
        mock_get.return_value = _mock_response([])
        with self.assertRaises(TipoCambioAPIError):
            consultar_tipo_cambio_sunat()

    @patch(REQUESTS_GET_PATH)
    def test_compra_faltante_lanza_error(self, mock_get):
        mock_get.return_value = _mock_response({"sell_price": "3.391", "date": "2026-08-10"})
        with self.assertRaises(TipoCambioAPIError):
            consultar_tipo_cambio_sunat()

    @patch(REQUESTS_GET_PATH)
    def test_venta_faltante_lanza_error(self, mock_get):
        mock_get.return_value = _mock_response({"buy_price": "3.374", "date": "2026-08-10"})
        with self.assertRaises(TipoCambioAPIError):
            consultar_tipo_cambio_sunat()

    @patch(REQUESTS_GET_PATH)
    def test_fecha_ausente_usa_fecha_local(self, mock_get):
        mock_get.return_value = _mock_response({"buy_price": "3.374", "sell_price": "3.391"})
        with patch("apps.monedas.services.timezone.localdate", return_value=date(2026, 8, 11)):
            datos = consultar_tipo_cambio_sunat()
        self.assertEqual(datos["fecha"], date(2026, 8, 11))

    @patch(REQUESTS_GET_PATH)
    def test_actualizar_guarda_en_bd_y_desactiva_anteriores(self, mock_get):
        anterior = TipoCambio.objects.create(
            fecha=date(2026, 8, 9), compra=Decimal("3.30"), venta=Decimal("3.35"), activo=True
        )
        mock_get.return_value = _mock_response(
            {"buy_price": "3.374", "sell_price": "3.391", "date": "2026-08-10"}
        )
        actualizar_tipo_cambio_sunat()

        anterior.refresh_from_db()
        self.assertFalse(anterior.activo)

        vigente = TipoCambio.vigente()
        self.assertEqual(vigente.fecha, date(2026, 8, 10))
        self.assertEqual(vigente.compra, Decimal("3.374"))
        self.assertEqual(vigente.venta, Decimal("3.391"))


class TipoCambioViewTests(TestCase):
    def test_url_resuelve_con_namespace_correcto(self):
        self.assertEqual(reverse("monedas:tipo_cambio"), "/planifica/tipo-cambio/")

    def test_get_responde_200(self):
        response = self.client.get(reverse("monedas:tipo_cambio"))
        self.assertEqual(response.status_code, 200)

    def test_usa_template_correcto(self):
        response = self.client.get(reverse("monedas:tipo_cambio"))
        self.assertTemplateUsed(response, "monedas/tipo_cambio.html")

    def test_con_tipo_cambio_expone_compra_venta_fecha_en_contexto(self):
        TipoCambio.objects.create(
            fecha=date(2026, 8, 10), compra=Decimal("3.3740"), venta=Decimal("3.3910"), activo=True
        )
        response = self.client.get(reverse("monedas:tipo_cambio"))
        self.assertTrue(response.context["tipo_cambio_disponible"])
        self.assertEqual(response.context["compra_txt"], "3.374")
        self.assertEqual(response.context["venta_txt"], "3.391")
        self.assertEqual(response.context["fecha_tipo_cambio_txt"], "10/08/2026")

    def test_mensaje_de_actualizacion_aparece_con_tasa(self):
        TipoCambio.objects.create(
            fecha=date(2026, 8, 10), compra=Decimal("3.374"), venta=Decimal("3.391"), activo=True
        )
        response = self.client.get(reverse("monedas:tipo_cambio"))
        self.assertContains(response, "Tipo de cambio actualizado al")
        self.assertContains(response, "10/08/2026")

    def test_sin_tipo_cambio_muestra_mensaje_no_disponible(self):
        response = self.client.get(reverse("monedas:tipo_cambio"))
        self.assertFalse(response.context["tipo_cambio_disponible"])
        self.assertContains(response, "Tipo de cambio temporalmente no disponible")

    def test_sin_tipo_cambio_no_expone_tasas_falsas(self):
        response = self.client.get(reverse("monedas:tipo_cambio"))
        self.assertNotContains(response, "Tasa referencial")

    def test_no_expone_fuente_decolecta_en_html(self):
        TipoCambio.objects.create(
            fecha=date(2026, 8, 10), compra=Decimal("3.374"), venta=Decimal("3.391"), activo=True
        )
        response = self.client.get(reverse("monedas:tipo_cambio"))
        self.assertNotContains(response, "Decolecta")
        self.assertNotContains(response, "SUNAT/SBS - Decolecta")

    def test_navegacion_resuelve_tipo_cambio(self):
        from apps.base.navegacion import HEADER_NAV_ITEMS

        item = next(
            hijo
            for seccion in HEADER_NAV_ITEMS
            for hijo in seccion.get("children", [])
            if hijo["key"] == "tipo-cambio"
        )
        self.assertEqual(item["url_name"], "monedas:tipo_cambio")
        self.assertEqual(reverse(item["url_name"]), "/planifica/tipo-cambio/")
