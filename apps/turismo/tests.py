import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.interacciones.models import Resena
from apps.ubicaciones.models import Departamento, Distrito, Provincia

from .models import CategoriaLugarTuristico, LugarTuristico


class LugarTuristicoGetAbsoluteUrlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        departamento = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        provincia = Provincia.objects.create(nombre_oficial="Huánuco", slug="huanuco", departamento=departamento)
        cls.distrito = Distrito.objects.create(
            nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101", provincia=provincia,
        )
        cls.categoria = CategoriaLugarTuristico.objects.create(nombre="Plazas", slug="plazas")

    def test_get_absolute_url(self):
        lugar = LugarTuristico.objects.create(
            categoria_principal=self.categoria, nombre="Plaza de Armas", slug="plaza-de-armas", distrito=self.distrito,
        )
        self.assertEqual(lugar.get_absolute_url(), reverse("turismo:detalle_lugar", kwargs={"slug": "plaza-de-armas"}))


class ResenaLugarTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(username="turista1", password="clave12345")
        cls.otro_usuario = User.objects.create_user(username="turista2", password="clave12345")
        departamento = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        provincia = Provincia.objects.create(nombre_oficial="Huánuco", slug="huanuco", departamento=departamento)
        distrito = Distrito.objects.create(
            nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101", provincia=provincia,
        )
        categoria = CategoriaLugarTuristico.objects.create(nombre="Plazas", slug="plazas")
        cls.lugar = LugarTuristico.objects.create(
            categoria_principal=categoria, nombre="Plaza de Armas", slug="plaza-de-armas", distrito=distrito,
        )

    def _url(self):
        return self.lugar.get_absolute_url()

    def _post(self, valoracion, comentario=""):
        return self.client.post(self._url(), {"valoracion": valoracion, "comentario": comentario})


class PublicarResenaLugarTests(ResenaLugarTestBase):
    def setUp(self):
        self.client.login(username="turista1", password="clave12345")

    def test_autenticado_publica_resena(self):
        response = self._post(5, "Hermosa plaza")
        self.assertRedirects(response, f"{self._url()}#resenas")
        resena = Resena.objects.get(usuario=self.usuario, lugar_turistico=self.lugar)
        self.assertEqual(resena.valoracion, 5)
        self.assertEqual(resena.comentario, "Hermosa plaza")

    def test_target_correcto(self):
        self._post(4)
        resena = Resena.objects.get(usuario=self.usuario)
        self.assertEqual(resena.lugar_turistico, self.lugar)
        self.assertIsNone(resena.establecimiento)

    def test_anonimo_no_puede_publicar(self):
        self.client.logout()
        response = self._post(5)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertFalse(Resena.objects.filter(lugar_turistico=self.lugar).exists())

    def test_get_no_crea_resena(self):
        self.client.get(self._url())
        self.assertFalse(Resena.objects.filter(lugar_turistico=self.lugar).exists())

    def test_segunda_publicacion_actualiza_misma_fila(self):
        self._post(3, "Bonito")
        self._post(5, "Excelente")
        self.assertEqual(Resena.objects.filter(usuario=self.usuario, lugar_turistico=self.lugar).count(), 1)
        resena = Resena.objects.get(usuario=self.usuario, lugar_turistico=self.lugar)
        self.assertEqual(resena.valoracion, 5)

    def test_editar_conserva_creado_y_estado(self):
        self._post(3, "Bonito")
        resena = Resena.objects.get(usuario=self.usuario)
        resena.estado = Resena.ESTADO_OCULTO
        resena.save(update_fields=["estado"])
        creado_original = resena.creado

        self._post(4, "Mejor de lo esperado")

        resena.refresh_from_db()
        self.assertEqual(resena.creado, creado_original)
        self.assertEqual(resena.estado, Resena.ESTADO_OCULTO)

    def test_post_invalido_reabre_formulario_conserva_comentario(self):
        response = self._post("", "Muy bonito")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Muy bonito")

    def test_carrera_integrity_error_no_produce_500(self):
        Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=2)
        with patch("apps.turismo.views.Resena.objects") as mock_manager:
            mock_manager.filter.return_value.first.return_value = None
            response = self._post(5, "Nuevo intento")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Resena.objects.filter(lugar_turistico=self.lugar).count(), 1)


class ListadoPublicoResenaLugarTests(ResenaLugarTestBase):
    def test_excluye_ocultas(self):
        Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=5)
        Resena.objects.create(
            usuario=self.otro_usuario, lugar_turistico=self.lugar, valoracion=1, estado=Resena.ESTADO_OCULTO,
        )
        response = self.client.get(self._url())
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertEqual(len(ids), 1)

    def test_tu_resena_aparece_en_el_listado(self):
        self.client.login(username="turista1", password="clave12345")
        mi_resena = Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, lugar_turistico=self.lugar, valoracion=3)
        response = self.client.get(self._url())
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertIn(mi_resena.pk, ids)
        self.assertEqual(response.context["resumen_resenas"]["total"], 2)

    def test_xss_en_comentario_se_escapa(self):
        Resena.objects.create(
            usuario=self.usuario, lugar_turistico=self.lugar, valoracion=4,
            comentario="<script>alert(1)</script>",
        )
        response = self.client.get(self._url())
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_queries_no_crecen_entre_1_y_20_resenas(self):
        Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=4)
        with CaptureQueriesContext(connection) as una:
            self.client.get(self._url())
        queries_con_una = len(una.captured_queries)

        for i in range(19):
            usuario = User.objects.create_user(username=f"turista_n_{i}", password="clave12345")
            Resena.objects.create(usuario=usuario, lugar_turistico=self.lugar, valoracion=4)

        with CaptureQueriesContext(connection) as veinte:
            self.client.get(self._url())
        queries_con_veinte = len(veinte.captured_queries)

        self.assertEqual(queries_con_una, queries_con_veinte)

    def test_orden_por_querystring_mas_antiguas(self):
        primera = Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=3)
        segunda = Resena.objects.create(usuario=self.otro_usuario, lugar_turistico=self.lugar, valoracion=4)
        response = self.client.get(self._url(), {"orden": "antiguas"})
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertEqual(ids, [primera.pk, segunda.pk])


class SelectorUiverseLugarTests(ResenaLugarTestBase):
    def setUp(self):
        self.client.login(username="turista1", password="clave12345")

    def test_existen_exactamente_5_radios_en_orden_5_a_1(self):
        html = self.client.get(self._url()).content.decode()
        radios = re.findall(r'<input[^>]*name="valoracion"[^>]*value="(\d)"', html)
        self.assertEqual(radios, ["5", "4", "3", "2", "1"])

    def test_post_valoracion_1_deja_ese_radio_marcado(self):
        self._post(1, "")
        html = self.client.get(self._url()).content.decode()
        self.assertIsNotNone(re.search(r'<input[^>]*value="1"[^>]*checked', html))
