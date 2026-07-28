import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ConsejoMovilidad, TransportePublico
from .services.tarifas_taxi import (
    obtener_consejos_movilidad,
    obtener_transportes_con_tarifas,
)

TIPO_CAMBIO_PATH = "apps.movilidad.services.tarifas_taxi.TipoCambio.vigente"


class TarifasTaxiViewTests(TestCase):
    """Los 3 transportes y 5 consejos ya existen vía la migración de datos 0003."""

    def test_reverse_resuelve_ruta_publica(self):
        self.assertEqual(reverse("movilidad:tarifas_taxi"), "/planifica/tarifas-taxi/")

    def test_ruta_publica_responde_200(self):
        response = self.client.get("/planifica/tarifas-taxi/")
        self.assertEqual(response.status_code, 200)

    def test_usa_template_correcto(self):
        response = self.client.get(reverse("movilidad:tarifas_taxi"))
        self.assertTemplateUsed(response, "movilidad/tarifas_taxi.html")

    def test_solo_muestra_transportes_activos(self):
        TransportePublico.objects.create(
            nombre="Transporte inactivo de prueba",
            slug="inactivo-prueba",
            descripcion="No debe mostrarse.",
            tarifa_minima=Decimal("5.00"),
            activo=False,
        )
        nombres = [t["nombre"] for t in obtener_transportes_con_tarifas()]
        self.assertNotIn("Transporte inactivo de prueba", nombres)

    def test_respeta_orden(self):
        nombres = [t["nombre"] for t in obtener_transportes_con_tarifas()]
        self.assertEqual(nombres, ["Mototaxi", "Colectivos", "Microbuses"])

    def test_tarifa_microbuses_en_un_sol(self):
        microbuses = TransportePublico.objects.get(slug="microbuses")
        self.assertEqual(microbuses.tarifa_minima, Decimal("1.00"))

        datos = {t["nombre"]: t for t in obtener_transportes_con_tarifas()}
        self.assertEqual(datos["Microbuses"]["precio_desde_txt"], "1.00")

    def test_consejos_activos_se_muestran(self):
        textos = obtener_consejos_movilidad()
        self.assertIn("Lleva siempre efectivo en soles para facilitar tus pagos.", textos)

    def test_consejo_inactivo_no_se_muestra(self):
        ConsejoMovilidad.objects.create(texto="Consejo oculto de prueba", activo=False)
        textos = obtener_consejos_movilidad()
        self.assertNotIn("Consejo oculto de prueba", textos)

        response = self.client.get(reverse("movilidad:tarifas_taxi"))
        self.assertNotContains(response, "Consejo oculto de prueba")

    @patch(TIPO_CAMBIO_PATH, return_value=None)
    def test_fallback_sin_tipo_de_cambio_vigente(self, _mock_vigente):
        transportes = obtener_transportes_con_tarifas()
        self.assertTrue(transportes)
        self.assertTrue(all(t["precio_usd_txt"] is None for t in transportes))
        self.assertTrue(all(t["precio_desde_txt"] for t in transportes))

        response = self.client.get(reverse("movilidad:tarifas_taxi"))
        self.assertContains(response, "Conversión temporalmente no disponible")

    def test_convierte_pen_a_usd_cuando_hay_tipo_de_cambio(self):
        tipo_cambio_falso = type("TipoCambioFalso", (), {"venta": Decimal("3.50")})()
        with patch(TIPO_CAMBIO_PATH, return_value=tipo_cambio_falso):
            datos = {t["nombre"]: t for t in obtener_transportes_con_tarifas()}
        self.assertEqual(datos["Mototaxi"]["precio_usd_txt"], "0.86")

    def test_fallback_imagen_estatica_cuando_no_hay_carga_en_admin(self):
        mototaxi = TransportePublico.objects.get(slug="mototaxi")
        self.assertFalse(mototaxi.imagen)

        datos = {t["nombre"]: t for t in obtener_transportes_con_tarifas()}
        self.assertIn("vi-transporte1.png", datos["Mototaxi"]["imagen_url"])

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_imagen_de_admin_tiene_prioridad_sobre_fallback(self):
        colectivos = TransportePublico.objects.get(slug="colectivos")
        colectivos.imagen = SimpleUploadedFile(
            "colectivo-prueba.png", b"contenido-fake-png", content_type="image/png"
        )
        colectivos.save()

        datos = {t["nombre"]: t for t in obtener_transportes_con_tarifas()}
        self.assertIn("colectivo-prueba", datos["Colectivos"]["imagen_url"])
        self.assertNotIn("vi-transporte2.png", datos["Colectivos"]["imagen_url"])
