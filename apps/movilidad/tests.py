import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CategoriaMovilidad, ConsejoMovilidad, OperadorMovilidad, RutaMovilidad, TransportePublico
from .services.como_llegar import (
    obtener_consejos_aereos,
    obtener_consejos_terrestres,
    obtener_rutas_aereas,
    obtener_rutas_terrestres,
)
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


class ComoLlegarViewTests(TestCase):
    """Las categorías, consejos y rutas base ya existen vía la migración de datos 0005."""

    def setUp(self):
        self.categoria_terrestre = CategoriaMovilidad.objects.get(slug="via-terrestre")
        self.categoria_aerea = CategoriaMovilidad.objects.get(slug="via-aerea")

    def test_reverse_resuelve_ruta_publica(self):
        self.assertEqual(reverse("movilidad:como_llegar"), "/planifica/como-llegar/")

    def test_ruta_publica_responde_200(self):
        response = self.client.get("/planifica/como-llegar/")
        self.assertEqual(response.status_code, 200)

    def test_usa_template_correcto(self):
        response = self.client.get(reverse("movilidad:como_llegar"))
        self.assertTemplateUsed(response, "movilidad/como_llegar.html")

    def test_solo_muestra_rutas_activas(self):
        RutaMovilidad.objects.create(
            nombre="Ruta terrestre inactiva de prueba",
            slug="ruta-terrestre-inactiva-prueba",
            seccion="como_llegar",
            categoria_principal=self.categoria_terrestre,
            activo=False,
        )
        nombres = [r.nombre for r in obtener_rutas_terrestres()]
        self.assertNotIn("Ruta terrestre inactiva de prueba", nombres)

    def test_no_muestra_rutas_de_seccion_general(self):
        RutaMovilidad.objects.create(
            nombre="Ruta general de prueba",
            slug="ruta-general-prueba",
            seccion="general",
            categoria_principal=self.categoria_terrestre,
            activo=True,
        )
        nombres = [r.nombre for r in obtener_rutas_terrestres()]
        self.assertNotIn("Ruta general de prueba", nombres)

    def test_separa_rutas_terrestres_y_aereas(self):
        terrestres = obtener_rutas_terrestres()
        aereas = obtener_rutas_aereas()
        self.assertTrue(all(r.categoria_principal_id == self.categoria_terrestre.id for r in terrestres))
        self.assertTrue(all(r.categoria_principal_id == self.categoria_aerea.id for r in aereas))

    def test_respeta_orden(self):
        nombres = [r.nombre for r in obtener_rutas_terrestres()]
        ordenes = list(
            RutaMovilidad.objects.filter(seccion="como_llegar", categoria_principal=self.categoria_terrestre)
            .order_by("orden", "nombre")
            .values_list("nombre", flat=True)
        )
        self.assertEqual(nombres, ordenes)

    def test_no_muestra_consejos_inactivos(self):
        ConsejoMovilidad.objects.create(
            texto="Consejo terrestre oculto de prueba",
            seccion="como_llegar_terrestre",
            activo=False,
        )
        textos = obtener_consejos_terrestres()
        self.assertNotIn("Consejo terrestre oculto de prueba", textos)

    def test_no_mezcla_consejos_entre_secciones(self):
        consejos_tarifas = set(obtener_consejos_movilidad())
        consejos_terrestres = set(obtener_consejos_terrestres())
        consejos_aereos = set(obtener_consejos_aereos())

        self.assertEqual(consejos_tarifas & consejos_terrestres, set())
        self.assertEqual(consejos_tarifas & consejos_aereos, set())
        self.assertEqual(consejos_terrestres & consejos_aereos, set())

    def test_funciona_sin_duracion_bus(self):
        ruta = obtener_rutas_terrestres().first()
        ruta.duracion_bus = ""
        ruta.save()
        response = self.client.get(reverse("movilidad:como_llegar"))
        self.assertEqual(response.status_code, 200)

    def test_funciona_sin_duracion_automovil(self):
        ruta = obtener_rutas_terrestres().first()
        ruta.duracion_automovil = ""
        ruta.save()
        response = self.client.get(reverse("movilidad:como_llegar"))
        self.assertEqual(response.status_code, 200)

    def test_no_requiere_operador_movilidad(self):
        self.assertEqual(OperadorMovilidad.objects.count(), 0)
        response = self.client.get(reverse("movilidad:como_llegar"))
        self.assertEqual(response.status_code, 200)

    def test_carga_correctamente_sin_rutas(self):
        RutaMovilidad.objects.filter(seccion="como_llegar").delete()
        response = self.client.get(reverse("movilidad:como_llegar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pronto publicaremos")

    def test_migracion_de_datos_no_crea_duplicados(self):
        import importlib

        from django.apps import apps as global_apps

        modulo = importlib.import_module("apps.movilidad.migrations.0005_como_llegar_datos")

        total_rutas_antes = RutaMovilidad.objects.filter(seccion="como_llegar").count()
        total_consejos_antes = ConsejoMovilidad.objects.filter(
            seccion__in=["como_llegar_terrestre", "como_llegar_aerea"]
        ).count()
        total_categorias_antes = CategoriaMovilidad.objects.filter(
            slug__in=["via-terrestre", "via-aerea"]
        ).count()

        modulo.seed(global_apps, None)

        self.assertEqual(
            RutaMovilidad.objects.filter(seccion="como_llegar").count(), total_rutas_antes
        )
        self.assertEqual(
            ConsejoMovilidad.objects.filter(
                seccion__in=["como_llegar_terrestre", "como_llegar_aerea"]
            ).count(),
            total_consejos_antes,
        )
        self.assertEqual(
            CategoriaMovilidad.objects.filter(slug__in=["via-terrestre", "via-aerea"]).count(),
            total_categorias_antes,
        )
