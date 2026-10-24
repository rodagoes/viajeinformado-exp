from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings

from apps.base.models import ConfiguracionPublica
from django.test.utils import CaptureQueriesContext

from .choices import OrigenDato, TipoInteraccion
from .models import InteraccionDiaria, VisitanteMetrica
from .services.publico import cifras_home, usuarios_registrados
from .test_servicios import D, diaria, periodo_corto


class CifrasHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = periodo_corto()
        diaria(cls.periodo, D(2026, 6, 1), nuevos=5, sesiones=10)
        diaria(cls.periodo, D(2026, 6, 2), nuevos=3, sesiones=7)
        for tipo, n in ((TipoInteraccion.LUGAR_DETALLE_CLICK, 4), (TipoInteraccion.CHATBOT_CONSULTA, 6)):
            InteraccionDiaria.objects.create(
                periodo=cls.periodo, origen=OrigenDato.SIMULADO, fecha=D(2026, 6, 1), tipo=tipo, cantidad=n)
        # REAL no debe mezclarse con SIMULADO
        diaria(cls.periodo, D(2026, 6, 3), nuevos=9, sesiones=99, origen=OrigenDato.REAL)
        U = get_user_model()
        U.objects.create_user("turista1", password="x")
        U.objects.create_user("turista2", password="x")
        U.objects.create_user("equipo", password="x", is_staff=True)
        U.objects.create_superuser("admin-pub", "a@example.com", "x")
        U.objects.create_user("baja", password="x", is_active=False)

    def test_valores_simulados_sin_mezclar_real(self):
        self.assertEqual(cifras_home(), {"viajeros": 2, "exploraciones": 4, "consultas": 6, "visitas": 17})

    def test_numero_fijo_de_consultas(self):
        with CaptureQueriesContext(connection) as ctx:
            cifras_home()
        self.assertLessEqual(len(ctx), 8)

    def test_home_muestra_seccion_y_formato(self):
        ConfiguracionPublica.objects.update_or_create(pk=1, defaults={"mostrar_metricas_home": True})
        html = self.client.get("/").content.decode()
        self.assertIn("home-metricas", html)
        self.assertIn('data-count="17"', html)
        self.assertEqual(html.count("home-metricas__card"), 4)

    def test_home_sin_seccion_si_el_interruptor_esta_apagado(self):
        ConfiguracionPublica.objects.filter(pk=1).update(mostrar_metricas_home=False)
        self.assertNotIn("home-metricas", self.client.get("/").content.decode())

    def test_sin_datos_no_hay_seccion(self):
        ConfiguracionPublica.objects.update_or_create(pk=1, defaults={"mostrar_metricas_home": True})
        from .models import MetricaDiaria
        MetricaDiaria.objects.all().delete()
        self.assertIsNone(cifras_home())
        self.assertNotIn("home-metricas", self.client.get("/").content.decode())

    def test_usuarios_registrados_son_cuentas_django_activas_no_staff(self):
        # turista1 y turista2 cuentan; staff, superusuario e inactivo no; usuarios_nuevos (8) no es la fuente
        self.assertEqual(usuarios_registrados(), 2)
        self.assertNotEqual(cifras_home()["viajeros"], 8)

    def test_visitantes_no_sustituyen_a_las_cuentas(self):
        VisitanteMetrica.objects.create(origen=OrigenDato.REAL, primera_visita=D(2026, 6, 1), es_registrado=True)
        VisitanteMetrica.objects.create(origen=OrigenDato.REAL, primera_visita=D(2026, 6, 1))  # anónimo
        self.assertEqual(usuarios_registrados(), 2)

    def test_una_cuenta_nueva_activa_suma_y_desactivarla_resta(self):
        U = get_user_model()
        nuevo = U.objects.create_user("turista3", password="x")
        self.assertEqual(usuarios_registrados(), 3)
        nuevo.is_active = False
        nuevo.save()
        self.assertEqual(usuarios_registrados(), 2)
