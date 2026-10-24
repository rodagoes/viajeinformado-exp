"""METRICAS_REAL_HABILITADAS en producción: se lee de la variable de entorno y por defecto está APAGADA."""
import importlib
import os
from unittest import mock

from django.test import SimpleTestCase

BD = {"DB_NAME": "x", "DB_USER_NAME": "x", "DB_PASSWORD": "x", "DB_HOST_NAME": "x", "DB_PORT": "3306"}


def cargar_produccion(**entorno):
    """Importa config.settings.production con un entorno controlado (ignora el .env del desarrollador)."""
    from config.settings import production

    with mock.patch.dict(os.environ, {**BD, **entorno}):
        for nombre in ("METRICAS_REAL_HABILITADAS", "METRICAS_ADMIN_PRUEBAS_VISIBLE", "METRICAS_HOME_ORIGEN"):
            if nombre not in entorno:
                os.environ.pop(nombre, None)
        return importlib.reload(production)


class ProduccionTrackingEnvTests(SimpleTestCase):
    def test_variable_ausente_deja_el_tracking_apagado(self):
        self.assertIs(cargar_produccion().METRICAS_REAL_HABILITADAS, False)

    def test_false_explicito_apagado(self):
        self.assertIs(cargar_produccion(METRICAS_REAL_HABILITADAS="False").METRICAS_REAL_HABILITADAS, False)

    def test_true_explicito_encendido(self):
        self.assertIs(cargar_produccion(METRICAS_REAL_HABILITADAS="True").METRICAS_REAL_HABILITADAS, True)

    def test_otras_variables_siguen_con_su_valor_seguro(self):
        m = cargar_produccion()
        self.assertIs(m.METRICAS_ADMIN_PRUEBAS_VISIBLE, False)
        self.assertEqual(m.METRICAS_HOME_ORIGEN, "REAL")
