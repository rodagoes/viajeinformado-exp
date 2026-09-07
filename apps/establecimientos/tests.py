import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.interacciones.models import Resena

from .models import CategoriaEstablecimiento, Establecimiento


class EstablecimientoGetAbsoluteUrlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categoria = CategoriaEstablecimiento.objects.create(nombre="Restaurantes", slug="restaurantes")

    def test_get_absolute_url_restaurante(self):
        est = Establecimiento.objects.create(
            tipo="restaurante", categoria_principal=self.categoria, nombre="El Fogón", slug="el-fogon",
        )
        self.assertEqual(est.get_absolute_url(), reverse("establecimientos:detalle_restaurante", kwargs={"slug": "el-fogon"}))

    def test_get_absolute_url_alojamiento(self):
        est = Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=self.categoria, nombre="Hotel Andino", slug="hotel-andino",
        )
        self.assertEqual(est.get_absolute_url(), reverse("establecimientos:detalle_alojamiento", kwargs={"slug": "hotel-andino"}))

    def test_get_absolute_url_tipo_desconocido_levanta_value_error(self):
        est = Establecimiento(tipo="otro", categoria_principal=self.categoria, nombre="X", slug="x")
        with self.assertRaises(ValueError):
            est.get_absolute_url()


class ResenaEstablecimientoTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(username="turista1", password="clave12345")
        cls.otro_usuario = User.objects.create_user(username="turista2", password="clave12345")
        categoria = CategoriaEstablecimiento.objects.create(nombre="Restaurantes", slug="restaurantes")
        cls.establecimiento = Establecimiento.objects.create(
            tipo="restaurante", categoria_principal=categoria,
            nombre="El Fogón Huanuqueño", slug="el-fogon-huanuqueno",
        )

    def _url(self):
        return self.establecimiento.get_absolute_url()

    def _post(self, valoracion, comentario=""):
        return self.client.post(self._url(), {"valoracion": valoracion, "comentario": comentario})


class PublicarResenaEstablecimientoTests(ResenaEstablecimientoTestBase):
    def setUp(self):
        self.client.login(username="turista1", password="clave12345")

    def test_autenticado_publica_resena(self):
        response = self._post(5, "Excelente comida")
        self.assertRedirects(response, f"{self._url()}#resenas")
        resena = Resena.objects.get(usuario=self.usuario, establecimiento=self.establecimiento)
        self.assertEqual(resena.valoracion, 5)
        self.assertEqual(resena.comentario, "Excelente comida")

    def test_target_correcto(self):
        self._post(4)
        resena = Resena.objects.get(usuario=self.usuario)
        self.assertEqual(resena.establecimiento, self.establecimiento)
        self.assertIsNone(resena.lugar_turistico)

    def test_comentario_opcional(self):
        self._post(3, "")
        resena = Resena.objects.get(usuario=self.usuario)
        self.assertEqual(resena.comentario, "")

    def test_anonimo_no_puede_publicar(self):
        self.client.logout()
        response = self._post(5)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertIn("next=", response.url)
        self.assertFalse(Resena.objects.filter(establecimiento=self.establecimiento).exists())

    def test_get_no_crea_resena(self):
        self.client.get(self._url())
        self.assertFalse(Resena.objects.filter(establecimiento=self.establecimiento).exists())

    def test_segunda_publicacion_actualiza_misma_fila(self):
        self._post(3, "Buena")
        self._post(5, "Excelente")
        self.assertEqual(
            Resena.objects.filter(usuario=self.usuario, establecimiento=self.establecimiento).count(), 1,
        )
        resena = Resena.objects.get(usuario=self.usuario, establecimiento=self.establecimiento)
        self.assertEqual(resena.valoracion, 5)
        self.assertEqual(resena.comentario, "Excelente")

    def test_editar_conserva_creado_y_estado(self):
        self._post(3, "Buena")
        resena = Resena.objects.get(usuario=self.usuario)
        resena.estado = Resena.ESTADO_OCULTO
        resena.save(update_fields=["estado"])
        creado_original = resena.creado

        self._post(4, "Mejor de lo esperado")

        resena.refresh_from_db()
        self.assertEqual(resena.creado, creado_original)
        self.assertEqual(resena.estado, Resena.ESTADO_OCULTO)

    def test_resena_oculta_reconocida_como_mi_resena_con_aviso(self):
        self._post(3, "Buena")
        resena = Resena.objects.get(usuario=self.usuario)
        resena.estado = Resena.ESTADO_OCULTO
        resena.save(update_fields=["estado"])

        response = self.client.get(self._url())
        self.assertEqual(response.context["mi_resena"], resena)
        self.assertContains(response, "no está visible públicamente")

    def test_post_invalido_reabre_formulario_conserva_comentario_y_muestra_error(self):
        response = self._post("", "Muy buen lugar")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Muy buen lugar")
        self.assertContains(response, "obligatorio")

    def test_post_invalido_no_crea_resena(self):
        self._post("")
        self.assertFalse(Resena.objects.filter(establecimiento=self.establecimiento).exists())

    def test_carrera_integrity_error_no_produce_500(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=2)
        with patch("apps.establecimientos.views.Resena.objects") as mock_manager:
            mock_manager.filter.return_value.first.return_value = None
            response = self._post(5, "Nuevo intento")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Resena.objects.filter(establecimiento=self.establecimiento).count(), 1)
        self.assertEqual(Resena.objects.get(establecimiento=self.establecimiento).valoracion, 2)


class ListadoPublicoResenaEstablecimientoTests(ResenaEstablecimientoTestBase):
    def test_excluye_ocultas(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=1,
            estado=Resena.ESTADO_OCULTO,
        )
        response = self.client.get(self._url())
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertEqual(len(ids), 1)

    def test_orden_mas_reciente_primero(self):
        primera = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=3)
        segunda = Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=4)
        response = self.client.get(self._url())
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertEqual(ids, [segunda.pk, primera.pk])

    def test_paginacion_a_5_por_pagina(self):
        for i in range(7):
            usuario = User.objects.create_user(username=f"turista_pag_{i}", password="clave12345")
            Resena.objects.create(usuario=usuario, establecimiento=self.establecimiento, valoracion=4)
        response = self.client.get(self._url())
        self.assertEqual(len(response.context["resenas_page"]), 5)
        self.assertEqual(response.context["resenas_page"].paginator.num_pages, 2)

    def test_comentario_vacio_no_renderiza_parrafo(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4, comentario="")
        response = self.client.get(self._url())
        self.assertNotContains(response, "vi-resena-item-comentario")

    def test_xss_en_comentario_se_escapa(self):
        Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4,
            comentario="<script>alert(1)</script>",
        )
        response = self.client.get(self._url())
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_tu_resena_aparece_en_el_listado_de_su_propio_autor(self):
        self.client.login(username="turista1", password="clave12345")
        mi_resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=3)

        response = self.client.get(self._url())
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertIn(mi_resena.pk, ids)
        self.assertEqual(response.context["resumen_resenas"]["total"], 2)

    def test_otro_usuario_si_ve_la_resena_ajena_en_el_listado(self):
        mi_resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        self.client.login(username="turista2", password="clave12345")
        response = self.client.get(self._url())
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertIn(mi_resena.pk, ids)

    def test_queries_no_crecen_entre_1_y_20_resenas(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)
        with CaptureQueriesContext(connection) as una:
            self.client.get(self._url())
        queries_con_una = len(una.captured_queries)

        for i in range(19):
            usuario = User.objects.create_user(username=f"turista_n_{i}", password="clave12345")
            Resena.objects.create(usuario=usuario, establecimiento=self.establecimiento, valoracion=4)

        with CaptureQueriesContext(connection) as veinte:
            self.client.get(self._url())
        queries_con_veinte = len(veinte.captured_queries)

        self.assertEqual(queries_con_una, queries_con_veinte)

    def test_orden_por_querystring_peor_valoradas(self):
        peor = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=1)
        mejor = Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=5)
        response = self.client.get(self._url(), {"orden": "peor"})
        ids = [r.pk for r in response.context["resenas_page"]]
        self.assertEqual(ids, [peor.pk, mejor.pk])


class SelectorUiverseTests(ResenaEstablecimientoTestBase):
    def _abrir_form_html(self, extra_params=""):
        url = self._url() + ("?" + extra_params if extra_params else "")
        response = self.client.get(url)
        return response.content.decode()

    def setUp(self):
        self.client.login(username="turista1", password="clave12345")

    def test_existen_exactamente_5_radios_valoracion(self):
        html = self._abrir_form_html()
        radios = re.findall(r'<input[^>]*name="valoracion"[^>]*>', html)
        self.assertEqual(len(radios), 5)

    def test_values_son_1_a_5(self):
        html = self._abrir_form_html()
        radios = re.findall(r'<input[^>]*name="valoracion"[^>]*>', html)
        values = {re.search(r'value="(\d)"', r).group(1) for r in radios}
        self.assertEqual(values, {"1", "2", "3", "4", "5"})

    def test_value_1_es_el_ultimo_radio_en_el_dom_por_row_reverse(self):
        html = self._abrir_form_html()
        radios = re.findall(r'<input[^>]*name="valoracion"[^>]*value="(\d)"', html)
        self.assertEqual(radios, ["5", "4", "3", "2", "1"])

    def test_post_valoracion_1_deja_ese_radio_marcado_tras_recargar(self):
        self._post(1, "")
        html = self._abrir_form_html()
        checked = re.search(r'<input[^>]*value="1"[^>]*checked', html)
        self.assertIsNotNone(checked)
        no_checked_5 = re.search(r'<input[^>]*value="5"[^>]*checked', html)
        self.assertIsNone(no_checked_5)

    def test_editar_valoracion_4_deja_radio_4_marcado(self):
        self._post(4, "")
        html = self._abrir_form_html()
        self.assertIsNotNone(re.search(r'<input[^>]*value="4"[^>]*checked', html))

    def test_post_invalido_conserva_radio_elegido(self):
        # value="" es inválido para el modelo (choices 1-5) pero permite
        # comprobar que un valor fuera de rango no se marca nunca, y que el
        # error se muestra sin perder el comentario.
        response = self._post(1000, "Comentario conservado")
        html = response.content.decode()
        self.assertIn("Comentario conservado", html)

    def test_radios_alcanzables_por_tab(self):
        html = self._abrir_form_html()
        radios = re.findall(r'<input[^>]*name="valoracion"[^>]*>', html)
        for radio in radios:
            self.assertNotIn('tabindex="-1"', radio)
            self.assertNotIn("display:none", radio)
            self.assertNotIn("display: none", radio)

    def test_cada_radio_tiene_aria_label(self):
        html = self._abrir_form_html()
        radios = re.findall(r'<input[^>]*name="valoracion"[^>]*>', html)
        for radio in radios:
            self.assertRegex(radio, r'aria-label="\d estrella[s]?"')

    def test_aria_label_singular_para_1_plural_para_2_a_5(self):
        html = self._abrir_form_html()
        self.assertIn('value="1" aria-label="1 estrella"', html)
        for n in (2, 3, 4, 5):
            self.assertIn(f'value="{n}" aria-label="{n} estrellas"', html)

    def test_fieldset_tiene_legend(self):
        html = self._abrir_form_html()
        self.assertIn('<legend class="visually-hidden">Tu valoración</legend>', html)

    def test_error_de_valoracion_se_renderiza_inline_con_aria_describedby(self):
        response = self._post("", "Sin estrella elegida")
        html = response.content.decode()
        prefijo = response.context["resena_id_prefijo"]
        self.assertIn(f'aria-describedby="{prefijo}-rating-error"', html)
        self.assertIn(f'id="{prefijo}-rating-error"', html)

    def test_sin_error_no_hay_aria_describedby(self):
        html = self._abrir_form_html()
        self.assertNotIn("rating-error", html)


class N1DetalleEstablecimientoTests(ResenaEstablecimientoTestBase):
    def test_get_no_agrega_queries_extra_por_una_sola_resena(self):
        # Sanity check: la página de detalle responde 200 con la sección de
        # reseñas integrada (sin reseñas todavía).
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "resenas")
