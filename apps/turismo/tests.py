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


class ListadoLugaresFiltrosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        dep = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        prov_h = Provincia.objects.create(nombre_oficial="Huánuco", slug="huanuco", departamento=dep)
        prov_a = Provincia.objects.create(nombre_oficial="Ambo", slug="ambo", departamento=dep)
        cls.d_huanuco = Distrito.objects.create(nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101", provincia=prov_h)
        cls.d_ambo = Distrito.objects.create(nombre_oficial="Ambo", slug="ambo", codigo_inei="100201", provincia=prov_a)
        cls.d_vacio = Distrito.objects.create(nombre_oficial="Amarilis", slug="amarilis", codigo_inei="100102", provincia=prov_h)
        cat = CategoriaLugarTuristico.objects.create(nombre="Plazas", slug="plazas")
        cls.plaza = LugarTuristico.objects.create(
            categoria_principal=cat, nombre="Plaza", slug="plaza", distrito=cls.d_huanuco,
            dificultad="facil", destacado=True)
        cls.puente = LugarTuristico.objects.create(
            categoria_principal=cat, nombre="Puente", slug="puente", distrito=cls.d_ambo, dificultad="dificil")
        cls.url = reverse("turismo:listado_lugares")

    def _nombres(self, response):
        return [l.nombre for l in response.context["page_obj"]]

    def test_filtra_por_distrito_y_conserva_seleccion(self):
        r = self.client.get(self.url, {"distrito": self.d_ambo.pk, "orden": "nombre_asc"})
        self.assertEqual(self._nombres(r), ["Puente"])
        self.assertEqual(r.context["query_filtros"], f"distrito={self.d_ambo.pk}&orden=nombre_asc")

    def test_solo_ofrece_distritos_con_datos_agrupados_por_provincia(self):
        grupos = self.client.get(self.url).context["distritos_agrupados"]
        self.assertEqual([g["provincia"] for g in grupos], ["Ambo", "Huánuco"])
        self.assertNotIn("Amarilis", [d["nombre"] for g in grupos for d in g["distritos"]])

    def test_distrito_invalido_o_sin_datos_se_ignora(self):
        for valor in ("abc", str(self.d_vacio.pk), "99999"):
            r = self.client.get(self.url, {"distrito": valor})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(len(self._nombres(r)), 2)

    def test_dificultad_y_costo_ya_no_filtran_ni_se_muestran(self):
        r = self.client.get(self.url, {"dificultad": "facil", "tipo_costo": "gratis"})
        self.assertEqual(len(self._nombres(r)), 2)  # params antiguos ignorados
        html = r.content.decode()
        self.assertNotIn('name="dificultad"', html)
        self.assertNotIn('name="tipo_costo"', html)
        self.assertNotIn("lugar-badge-dificultad", html)
        self.assertNotIn("lugar-servicio", html)

    def test_destacado_se_muestra_como_recomendado(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Recomendado", html)
        self.assertNotIn("Destacado", html)
        self.assertEqual(html.count("lugar-badge-destacado"), 1)
        self.assertTrue(LugarTuristico.objects.get(pk=self.plaza.pk).destacado)  # el dato no cambia
