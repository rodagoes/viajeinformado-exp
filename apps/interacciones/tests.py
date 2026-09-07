import json

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.establecimientos.models import CategoriaEstablecimiento, Establecimiento
from apps.turismo.models import CategoriaLugarTuristico, LugarTuristico
from apps.ubicaciones.models import Departamento, Distrito, Provincia

from .forms import ResenaForm
from .models import Favorito, Resena
from .services import _filtro_recurso, construir_contexto_resenas, obtener_resumen_resenas, resolver_recurso


class InteraccionesTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(username="turista1", password="clave12345")
        cls.otro_usuario = User.objects.create_user(username="turista2", password="clave12345")

        categoria_est = CategoriaEstablecimiento.objects.create(nombre="Restaurantes", slug="restaurantes")
        cls.establecimiento = Establecimiento.objects.create(
            tipo="restaurante",
            categoria_principal=categoria_est,
            nombre="El Fogón Huanuqueño",
            slug="el-fogon-huanuqueno",
        )
        cls.otro_establecimiento = Establecimiento.objects.create(
            tipo="restaurante",
            categoria_principal=categoria_est,
            nombre="Sabor Andino",
            slug="sabor-andino",
        )

        departamento = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        provincia = Provincia.objects.create(nombre_oficial="Huánuco", slug="huanuco", departamento=departamento)
        distrito = Distrito.objects.create(
            nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101", provincia=provincia,
        )
        categoria_lugar = CategoriaLugarTuristico.objects.create(nombre="Plazas", slug="plazas")
        cls.lugar = LugarTuristico.objects.create(
            categoria_principal=categoria_lugar,
            nombre="Plaza de Armas",
            slug="plaza-de-armas",
            distrito=distrito,
        )
        cls.otro_lugar = LugarTuristico.objects.create(
            categoria_principal=categoria_lugar,
            nombre="Mirador Paucarbamba",
            slug="mirador-paucarbamba",
            distrito=distrito,
        )


class FavoritoModelTests(InteraccionesTestBase):
    def test_crear_favorito_hacia_establecimiento(self):
        favorito = Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        self.assertEqual(favorito.recurso, self.establecimiento)

    def test_crear_favorito_hacia_lugar_turistico(self):
        favorito = Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)
        self.assertEqual(favorito.recurso, self.lugar)

    def test_ambos_targets_nulos_rechazado(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Favorito.objects.create(usuario=self.usuario)

    def test_ambos_targets_informados_rechazado(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Favorito.objects.create(
                    usuario=self.usuario, establecimiento=self.establecimiento, lugar_turistico=self.lugar,
                )

    def test_duplicado_usuario_establecimiento_rechazado(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)

    def test_duplicado_usuario_lugar_rechazado(self):
        Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)

    def test_mismo_establecimiento_para_usuarios_distintos_permitido(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        Favorito.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento)
        self.assertEqual(Favorito.objects.filter(establecimiento=self.establecimiento).count(), 2)

    def test_mismo_lugar_para_usuarios_distintos_permitido(self):
        Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)
        Favorito.objects.create(usuario=self.otro_usuario, lugar_turistico=self.lugar)
        self.assertEqual(Favorito.objects.filter(lugar_turistico=self.lugar).count(), 2)

    def test_eliminar_establecimiento_elimina_favorito(self):
        favorito = Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        self.establecimiento.delete()
        self.assertFalse(Favorito.objects.filter(pk=favorito.pk).exists())

    def test_eliminar_lugar_elimina_favorito(self):
        favorito = Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)
        self.lugar.delete()
        self.assertFalse(Favorito.objects.filter(pk=favorito.pk).exists())


class ResenaModelTests(InteraccionesTestBase):
    def test_crear_resena_con_valoracion_y_comentario(self):
        resena = Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento,
            valoracion=5, comentario="Excelente atención.",
        )
        self.assertEqual(resena.recurso, self.establecimiento)
        self.assertEqual(resena.estado, Resena.ESTADO_PUBLICADO)

    def test_crear_resena_solo_con_valoracion(self):
        resena = Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=4)
        self.assertEqual(resena.comentario, "")

    def test_valoracion_minima_y_maxima_permitidas(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=1)
        Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=5)

    def test_valoracion_fuera_de_rango_rechazada_por_full_clean(self):
        resena = Resena(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=6)
        with self.assertRaises(ValidationError):
            resena.full_clean()

    def test_valoracion_fuera_de_rango_rechazada_por_constraint_db(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=0)

    def test_ambos_targets_nulos_rechazado(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Resena.objects.create(usuario=self.usuario, valoracion=3)

    def test_ambos_targets_informados_rechazado(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Resena.objects.create(
                    usuario=self.usuario, establecimiento=self.establecimiento,
                    lugar_turistico=self.lugar, valoracion=3,
                )

    def test_duplicado_usuario_establecimiento_rechazado(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)

    def test_duplicado_usuario_lugar_rechazado(self):
        Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=4)

    def test_mismo_recurso_para_usuarios_distintos_permitido(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=2)
        self.assertEqual(Resena.objects.filter(establecimiento=self.establecimiento).count(), 2)

    def test_comentario_mayor_a_1000_caracteres_rechazado(self):
        resena = Resena(
            usuario=self.usuario, establecimiento=self.establecimiento,
            valoracion=3, comentario="a" * 1001,
        )
        with self.assertRaises(ValidationError):
            resena.full_clean()

    def test_eliminar_establecimiento_elimina_resena(self):
        resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=3)
        self.establecimiento.delete()
        self.assertFalse(Resena.objects.filter(pk=resena.pk).exists())

    def test_eliminar_lugar_elimina_resena(self):
        resena = Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=3)
        self.lugar.delete()
        self.assertFalse(Resena.objects.filter(pk=resena.pk).exists())


class ToggleFavoritoViewTests(InteraccionesTestBase):
    def setUp(self):
        self.client.login(username="turista1", password="clave12345")

    def _toggle(self, tipo, pk):
        return self.client.post(reverse("interacciones:toggle_favorito", kwargs={"tipo": tipo, "pk": pk}))

    def test_post_autenticado_agrega_establecimiento(self):
        response = self._toggle("establecimiento", self.establecimiento.pk)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data, {"ok": True, "es_favorito": True, "accion": "agregado"})
        self.assertTrue(Favorito.objects.filter(usuario=self.usuario, establecimiento=self.establecimiento).exists())

    def test_segundo_post_elimina_establecimiento(self):
        self._toggle("establecimiento", self.establecimiento.pk)
        response = self._toggle("establecimiento", self.establecimiento.pk)
        data = json.loads(response.content)
        self.assertEqual(data, {"ok": True, "es_favorito": False, "accion": "eliminado"})
        self.assertFalse(Favorito.objects.filter(usuario=self.usuario, establecimiento=self.establecimiento).exists())

    def test_post_autenticado_agrega_lugar(self):
        response = self._toggle("lugar", self.lugar.pk)
        data = json.loads(response.content)
        self.assertTrue(data["es_favorito"])
        self.assertTrue(Favorito.objects.filter(usuario=self.usuario, lugar_turistico=self.lugar).exists())

    def test_segundo_post_elimina_lugar(self):
        self._toggle("lugar", self.lugar.pk)
        response = self._toggle("lugar", self.lugar.pk)
        data = json.loads(response.content)
        self.assertFalse(data["es_favorito"])
        self.assertFalse(Favorito.objects.filter(usuario=self.usuario, lugar_turistico=self.lugar).exists())

    def test_get_no_permitido(self):
        response = self.client.get(
            reverse("interacciones:toggle_favorito", kwargs={"tipo": "establecimiento", "pk": self.establecimiento.pk})
        )
        self.assertEqual(response.status_code, 405)

    def test_tipo_invalido_rechazado(self):
        response = self._toggle("evento", self.establecimiento.pk)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Favorito.objects.filter(usuario=self.usuario).exists())

    def test_recurso_inexistente_rechazado(self):
        response = self._toggle("establecimiento", 999999)
        self.assertEqual(response.status_code, 404)

    def test_usuarios_mantienen_favoritos_independientes(self):
        self._toggle("establecimiento", self.establecimiento.pk)
        self.client.login(username="turista2", password="clave12345")
        response = self._toggle("establecimiento", self.establecimiento.pk)
        data = json.loads(response.content)
        self.assertTrue(data["es_favorito"])
        self.assertTrue(Favorito.objects.filter(usuario=self.usuario, establecimiento=self.establecimiento).exists())
        self.assertTrue(Favorito.objects.filter(usuario=self.otro_usuario, establecimiento=self.establecimiento).exists())

    def test_anonimo_no_crea_favorito(self):
        self.client.logout()
        response = self._toggle("establecimiento", self.establecimiento.pk)
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.content)
        self.assertEqual(data, {"ok": False, "auth_required": True})
        self.assertFalse(Favorito.objects.filter(establecimiento=self.establecimiento).exists())


class FavoritosPageViewTests(InteraccionesTestBase):
    def setUp(self):
        self.client.login(username="turista1", password="clave12345")

    def _url(self, tipo=None):
        url = reverse("interacciones:favoritos")
        return f"{url}?tipo={tipo}" if tipo else url

    def test_anonimo_redirige_a_login(self):
        self.client.logout()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertIn("next=", response.url)

    def test_usuario_ve_solo_sus_favoritos(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        Favorito.objects.create(usuario=self.otro_usuario, establecimiento=self.otro_establecimiento)
        response = self.client.get(self._url())
        favoritos = response.context["favoritos"]
        self.assertEqual(len(favoritos), 1)
        self.assertEqual(favoritos[0].establecimiento, self.establecimiento)

    def test_orden_mas_reciente_primero(self):
        primero = Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        segundo = Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)
        favoritos = self.client.get(self._url()).context["favoritos"]
        self.assertEqual([f.pk for f in favoritos], [segundo.pk, primero.pk])

    def test_filtro_todos_incluye_ambos_tipos(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)
        favoritos = self.client.get(self._url("todos")).context["favoritos"]
        self.assertEqual(len(favoritos), 2)

    def test_filtro_lugares(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        Favorito.objects.create(usuario=self.usuario, lugar_turistico=self.lugar)
        favoritos = self.client.get(self._url("lugares")).context["favoritos"]
        self.assertEqual(len(favoritos), 1)
        self.assertEqual(favoritos[0].lugar_turistico, self.lugar)

    def test_filtro_restaurantes_y_alojamientos(self):
        categoria = CategoriaEstablecimiento.objects.create(nombre="Hoteles", slug="hoteles")
        alojamiento = Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=categoria, nombre="Hotel Andino", slug="hotel-andino",
        )
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)  # restaurante
        Favorito.objects.create(usuario=self.usuario, establecimiento=alojamiento)

        restaurantes = self.client.get(self._url("restaurantes")).context["favoritos"]
        self.assertEqual([f.establecimiento for f in restaurantes], [self.establecimiento])

        alojamientos = self.client.get(self._url("alojamientos")).context["favoritos"]
        self.assertEqual([f.establecimiento for f in alojamientos], [alojamiento])

    def test_filtro_invalido_no_causa_500(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        response = self.client.get(self._url("no-existe"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tipo"], "todos")
        self.assertEqual(len(response.context["favoritos"]), 1)

    def test_recurso_inactivo_no_se_muestra(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        self.establecimiento.activo = False
        self.establecimiento.save(update_fields=["activo"])
        response = self.client.get(self._url())
        self.assertEqual(len(response.context["favoritos"]), 0)
        self.assertFalse(response.context["tiene_favoritos_globales"])

    def test_card_incluye_enlace_real_de_detalle(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        response = self.client.get(self._url())
        self.assertContains(response, self.establecimiento.get_absolute_url())

    def test_card_no_incluye_precio(self):
        self.establecimiento.precio_desde = 25
        self.establecimiento.precio_hasta = 97
        self.establecimiento.save(update_fields=["precio_desde", "precio_hasta"])
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        response = self.client.get(self._url())
        self.assertNotContains(response, "S/ 25")
        self.assertNotContains(response, "S/ 97")
        self.assertNotContains(response, "Rango de precios")

    def test_rating_agregado_solo_publicadas(self):
        otro = User.objects.create_user(username="turista3", password="clave12345")
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=otro, establecimiento=self.establecimiento, valoracion=3, estado=Resena.ESTADO_OCULTO)
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        favoritos = self.client.get(self._url()).context["favoritos"]
        self.assertEqual(favoritos[0].rating, (5.0, 1))

    def test_sin_resenas_no_tiene_rating(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        favoritos = self.client.get(self._url()).context["favoritos"]
        self.assertIsNone(favoritos[0].rating)

    def test_queries_no_crecen_con_mas_favoritos(self):
        # El número de queries con 1 favorito debe ser el mismo que con 6 —
        # confirma que no hay una query extra por card (N+1).
        categoria = CategoriaEstablecimiento.objects.create(nombre="Cafeterías", slug="cafeterias")
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)

        with CaptureQueriesContext(connection) as una_query:
            self.client.get(self._url())
        queries_con_uno = len(una_query.captured_queries)

        for i in range(5):
            est = Establecimiento.objects.create(
                tipo="restaurante", categoria_principal=categoria, nombre=f"Local {i}", slug=f"local-{i}",
            )
            Favorito.objects.create(usuario=self.usuario, establecimiento=est)

        with CaptureQueriesContext(connection) as varias_queries:
            self.client.get(self._url())
        queries_con_seis = len(varias_queries.captured_queries)

        self.assertEqual(queries_con_uno, queries_con_seis)


class ResenaFormTests(TestCase):
    def test_valoracion_es_obligatoria(self):
        form = ResenaForm(data={"comentario": "Muy bueno"})
        self.assertFalse(form.is_valid())
        self.assertIn("valoracion", form.errors)

    def test_valoracion_1_valida(self):
        self.assertTrue(ResenaForm(data={"valoracion": 1, "comentario": ""}).is_valid())

    def test_valoracion_5_valida(self):
        self.assertTrue(ResenaForm(data={"valoracion": 5, "comentario": ""}).is_valid())

    def test_valoracion_0_invalida(self):
        self.assertFalse(ResenaForm(data={"valoracion": 0, "comentario": ""}).is_valid())

    def test_valoracion_6_invalida(self):
        self.assertFalse(ResenaForm(data={"valoracion": 6, "comentario": ""}).is_valid())

    def test_comentario_vacio_es_valido(self):
        self.assertTrue(ResenaForm(data={"valoracion": 4, "comentario": ""}).is_valid())

    def test_comentario_de_solo_espacios_queda_vacio(self):
        form = ResenaForm(data={"valoracion": 4, "comentario": "    "})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["comentario"], "")

    def test_comentario_1000_caracteres_valido(self):
        self.assertTrue(ResenaForm(data={"valoracion": 3, "comentario": "a" * 1000}).is_valid())

    def test_comentario_1001_caracteres_invalido(self):
        self.assertFalse(ResenaForm(data={"valoracion": 3, "comentario": "a" * 1001}).is_valid())

    def test_campos_sensibles_no_estan_en_el_form(self):
        campos = ResenaForm().fields.keys()
        self.assertNotIn("estado", campos)
        self.assertNotIn("usuario", campos)
        self.assertNotIn("establecimiento", campos)
        self.assertNotIn("lugar_turistico", campos)


class ServiciosResenaTests(InteraccionesTestBase):
    def test_filtro_recurso_establecimiento(self):
        self.assertEqual(_filtro_recurso("establecimiento", self.establecimiento), {"establecimiento": self.establecimiento})

    def test_filtro_recurso_lugar(self):
        self.assertEqual(_filtro_recurso("lugar", self.lugar), {"lugar_turistico": self.lugar})

    def test_filtro_recurso_tipo_invalido_levanta_value_error(self):
        with self.assertRaises(ValueError):
            _filtro_recurso("invalido", self.establecimiento)

    def test_resolver_recurso_tipo_invalido(self):
        modelo, recurso = resolver_recurso("invalido", self.establecimiento.pk)
        self.assertIsNone(modelo)
        self.assertIsNone(recurso)

    def test_resumen_sin_resenas(self):
        resumen = obtener_resumen_resenas("establecimiento", self.establecimiento)
        self.assertEqual(resumen["total"], 0)
        self.assertIsNone(resumen["promedio"])
        self.assertTrue(all(fila["porcentaje"] == 0 for fila in resumen["distribucion"]))

    def test_resumen_con_varias_resenas(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=3)
        resumen = obtener_resumen_resenas("establecimiento", self.establecimiento)
        self.assertEqual(resumen["total"], 2)
        self.assertEqual(resumen["promedio"], 4.0)

    def test_resumen_excluye_ocultas(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=1,
            estado=Resena.ESTADO_OCULTO,
        )
        resumen = obtener_resumen_resenas("establecimiento", self.establecimiento)
        self.assertEqual(resumen["total"], 1)
        self.assertEqual(resumen["promedio"], 5.0)

    def test_resumen_porcentajes_y_sin_division_por_cero(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=5)
        resumen = obtener_resumen_resenas("establecimiento", self.establecimiento)
        fila_5 = next(f for f in resumen["distribucion"] if f["estrella"] == 5)
        self.assertEqual(fila_5["porcentaje"], 100)
        fila_1 = next(f for f in resumen["distribucion"] if f["estrella"] == 1)
        self.assertEqual(fila_1["porcentaje"], 0)

    def _request(self, usuario):
        request = type("_R", (), {})()
        request.user = usuario
        return request

    def test_construir_contexto_form_none_arma_form_vacio(self):
        contexto = construir_contexto_resenas(self._request(self.usuario), "establecimiento", self.establecimiento)
        self.assertIsNone(contexto["resena_form"].instance.pk)

    def test_construir_contexto_form_none_precarga_instancia_existente(self):
        resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)
        contexto = construir_contexto_resenas(self._request(self.usuario), "establecimiento", self.establecimiento)
        self.assertEqual(contexto["resena_form"].instance.pk, resena.pk)

    def test_construir_contexto_form_bound_se_reutiliza_tal_cual(self):
        form_invalido = ResenaForm(data={"valoracion": "", "comentario": "Algo"})
        form_invalido.is_valid()
        contexto = construir_contexto_resenas(
            self._request(self.usuario), "establecimiento", self.establecimiento, form_resena=form_invalido,
        )
        self.assertIs(contexto["resena_form"], form_invalido)

    def test_resena_id_prefijo_presente_en_contexto(self):
        contexto = construir_contexto_resenas(self._request(self.usuario), "establecimiento", self.establecimiento)
        self.assertIn("resena_id_prefijo", contexto)

    def test_resena_id_prefijo_creacion(self):
        contexto = construir_contexto_resenas(self._request(self.usuario), "establecimiento", self.establecimiento)
        self.assertEqual(contexto["resena_id_prefijo"], f"review-create-establecimiento-{self.establecimiento.pk}")

    def test_resena_id_prefijo_edicion(self):
        resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)
        contexto = construir_contexto_resenas(self._request(self.usuario), "establecimiento", self.establecimiento)
        self.assertEqual(contexto["resena_id_prefijo"], f"review-edit-{resena.pk}")

    def test_tu_resena_aparece_en_el_listado_y_cuenta_en_agregados(self):
        mi_resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=3)

        contexto_mio = construir_contexto_resenas(self._request(self.usuario), "establecimiento", self.establecimiento)
        ids_listado = [r.pk for r in contexto_mio["resenas_page"]]
        self.assertIn(mi_resena.pk, ids_listado)
        self.assertEqual(contexto_mio["resumen_resenas"]["total"], 2)

        anonimo = type("_U", (), {"is_authenticated": False})()
        contexto_otro = construir_contexto_resenas(self._request(anonimo), "establecimiento", self.establecimiento)
        ids_listado_otro = [r.pk for r in contexto_otro["resenas_page"]]
        self.assertIn(mi_resena.pk, ids_listado_otro)

    def test_orden_mejor_valoradas_primero(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=2)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=5)
        anonimo = type("_U", (), {"is_authenticated": False})()
        contexto = construir_contexto_resenas(
            self._request(anonimo), "establecimiento", self.establecimiento, orden="mejor",
        )
        valoraciones = [r.valoracion for r in contexto["resenas_page"]]
        self.assertEqual(valoraciones, [5, 2])

    def test_orden_invalido_usa_default_recientes(self):
        anonimo = type("_U", (), {"is_authenticated": False})()
        contexto = construir_contexto_resenas(
            self._request(anonimo), "establecimiento", self.establecimiento, orden="no-existe",
        )
        self.assertEqual(contexto["orden_actual"], "recientes")


class EliminarResenaTests(InteraccionesTestBase):
    def setUp(self):
        self.resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)

    def _url(self, tipo="establecimiento", pk=None):
        return reverse("interacciones:eliminar_resena", kwargs={"tipo": tipo, "pk": pk or self.establecimiento.pk})

    def test_propietario_elimina(self):
        self.client.login(username="turista1", password="clave12345")
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Resena.objects.filter(pk=self.resena.pk).exists())

    def test_anonimo_no_elimina(self):
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertTrue(Resena.objects.filter(pk=self.resena.pk).exists())

    def test_get_no_elimina(self):
        self.client.login(username="turista1", password="clave12345")
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Resena.objects.filter(pk=self.resena.pk).exists())

    def test_usuario_b_no_elimina_la_de_a(self):
        self.client.login(username="turista2", password="clave12345")
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Resena.objects.filter(pk=self.resena.pk).exists())

    def test_tipo_invalido_400(self):
        self.client.login(username="turista1", password="clave12345")
        response = self.client.post(self._url(tipo="evento"))
        self.assertEqual(response.status_code, 400)

    def test_pk_inexistente_404(self):
        self.client.login(username="turista1", password="clave12345")
        response = self.client.post(self._url(pk=999999))
        self.assertEqual(response.status_code, 404)


def _dar_permisos(user, *codenames):
    content_type = ContentType.objects.get_for_model(Resena)
    permisos = Permission.objects.filter(content_type=content_type, codename__in=codenames)
    user.user_permissions.add(*permisos)


class ResenaAdminTestBase(InteraccionesTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin_superuser = User.objects.create_superuser(
            username="admin_qa", password="clave12345", email="admin_qa@example.com",
        )

    def _changelist_url(self):
        return reverse("admin:interacciones_resena_changelist")

    def _change_url(self, pk):
        return reverse("admin:interacciones_resena_change", args=[pk])

    def _add_url(self):
        return reverse("admin:interacciones_resena_add")

    def _delete_url(self, pk):
        return reverse("admin:interacciones_resena_delete", args=[pk])

    def _ejecutar_accion(self, accion, pks):
        data = {"action": accion, "_selected_action": [str(pk) for pk in pks]}
        return self.client.post(self._changelist_url(), data, follow=True)


class ResenaAdminAccionesTests(ResenaAdminTestBase):
    def setUp(self):
        self.client.login(username="admin_qa", password="clave12345")

    def test_ocultar_una_publicada(self):
        r = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        response = self._ejecutar_accion("ocultar_resenas", [r.pk])
        r.refresh_from_db()
        self.assertEqual(r.estado, Resena.ESTADO_OCULTO)
        self.assertContains(response, "1 reseña ocultada.")

    def test_ocultar_varias(self):
        a = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        b = Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=3)
        response = self._ejecutar_accion("ocultar_resenas", [a.pk, b.pk])
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.estado, Resena.ESTADO_OCULTO)
        self.assertEqual(b.estado, Resena.ESTADO_OCULTO)
        self.assertContains(response, "2 reseñas ocultadas.")

    def test_ocultar_mixto_solo_cambia_las_publicadas(self):
        ya_oculta_1 = Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4, estado=Resena.ESTADO_OCULTO,
        )
        ya_oculta_2 = Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=2, estado=Resena.ESTADO_OCULTO,
        )
        publicada = Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=5)
        response = self._ejecutar_accion(
            "ocultar_resenas", [ya_oculta_1.pk, ya_oculta_2.pk, publicada.pk],
        )
        publicada.refresh_from_db()
        self.assertEqual(publicada.estado, Resena.ESTADO_OCULTO)
        self.assertContains(response, "1 reseña ocultada.")

    def test_ocultar_todas_ya_ocultas_reporta_cero(self):
        a = Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4, estado=Resena.ESTADO_OCULTO,
        )
        b = Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=2, estado=Resena.ESTADO_OCULTO,
        )
        c = Resena.objects.create(
            usuario=self.usuario, lugar_turistico=self.lugar, valoracion=1, estado=Resena.ESTADO_OCULTO,
        )
        response = self._ejecutar_accion("ocultar_resenas", [a.pk, b.pk, c.pk])
        self.assertContains(response, "0 reseñas ocultadas.")
        for r in (a, b, c):
            r.refresh_from_db()
            self.assertEqual(r.estado, Resena.ESTADO_OCULTO)

    def test_publicar_una_oculta(self):
        r = Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5, estado=Resena.ESTADO_OCULTO,
        )
        response = self._ejecutar_accion("publicar_resenas", [r.pk])
        r.refresh_from_db()
        self.assertEqual(r.estado, Resena.ESTADO_PUBLICADO)
        self.assertContains(response, "1 reseña publicada.")

    def test_publicar_varias(self):
        a = Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5, estado=Resena.ESTADO_OCULTO,
        )
        b = Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=3, estado=Resena.ESTADO_OCULTO,
        )
        response = self._ejecutar_accion("publicar_resenas", [a.pk, b.pk])
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.estado, Resena.ESTADO_PUBLICADO)
        self.assertEqual(b.estado, Resena.ESTADO_PUBLICADO)
        self.assertContains(response, "2 reseñas publicadas.")

    def test_publicar_mixto_solo_cambia_las_ocultas(self):
        ya_publicada = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)
        oculta = Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=2, estado=Resena.ESTADO_OCULTO,
        )
        response = self._ejecutar_accion("publicar_resenas", [ya_publicada.pk, oculta.pk])
        oculta.refresh_from_db()
        self.assertEqual(oculta.estado, Resena.ESTADO_PUBLICADO)
        self.assertContains(response, "1 reseña publicada.")

    def test_publicar_todas_ya_publicadas_reporta_cero(self):
        a = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)
        b = Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=2)
        response = self._ejecutar_accion("publicar_resenas", [a.pk, b.pk])
        self.assertContains(response, "0 reseñas publicadas.")

    def test_accion_no_cambia_contenido_ni_autoria(self):
        r = Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4, comentario="Muy bueno",
        )
        self._ejecutar_accion("ocultar_resenas", [r.pk])
        r.refresh_from_db()
        self.assertEqual(r.comentario, "Muy bueno")
        self.assertEqual(r.valoracion, 4)
        self.assertEqual(r.usuario, self.usuario)
        self.assertEqual(r.establecimiento, self.establecimiento)
        self.assertIsNone(r.lugar_turistico)

    def test_acciones_bulk_no_cambian_actualizado(self):
        r = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)
        actualizado_original = r.actualizado
        self._ejecutar_accion("ocultar_resenas", [r.pk])
        self._ejecutar_accion("publicar_resenas", [r.pk])
        r.refresh_from_db()
        self.assertEqual(r.actualizado, actualizado_original)


class ResenaAdminChangelistTests(ResenaAdminTestBase):
    def setUp(self):
        self.client.login(username="admin_qa", password="clave12345")

    def test_tipo_recurso_detallado_restaurante(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        response = self.client.get(self._changelist_url())
        self.assertContains(response, "Restaurante")

    def test_tipo_recurso_detallado_alojamiento(self):
        categoria = CategoriaEstablecimiento.objects.create(nombre="Hoteles", slug="hoteles")
        alojamiento = Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=categoria, nombre="Hotel Andino", slug="hotel-andino",
        )
        Resena.objects.create(usuario=self.usuario, establecimiento=alojamiento, valoracion=5)
        response = self.client.get(self._changelist_url())
        self.assertContains(response, "Alojamiento")

    def test_tipo_recurso_detallado_lugar(self):
        Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=5)
        response = self.client.get(self._changelist_url())
        self.assertContains(response, "Lugar turístico")

    def test_comentario_resumido_sin_comentario(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5, comentario="")
        response = self.client.get(self._changelist_url())
        self.assertContains(response, "Sin comentario")

    def test_filtro_tipo_recurso_restaurante(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, lugar_turistico=self.lugar, valoracion=3)
        response = self.client.get(self._changelist_url(), {"tipo_recurso": "restaurante"})
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_filtro_tipo_recurso_lugar(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, lugar_turistico=self.lugar, valoracion=3)
        response = self.client.get(self._changelist_url(), {"tipo_recurso": "lugar"})
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_filtro_estado(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.otro_establecimiento, valoracion=2,
            estado=Resena.ESTADO_OCULTO,
        )
        response = self.client.get(self._changelist_url(), {"estado": Resena.ESTADO_OCULTO})
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_filtro_valoracion(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.otro_establecimiento, valoracion=2)
        response = self.client.get(self._changelist_url(), {"valoracion__exact": "5"})
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_busqueda_por_username(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        response = self.client.get(self._changelist_url(), {"q": "turista1"})
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_busqueda_por_nombre_de_recurso(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        response = self.client.get(self._changelist_url(), {"q": "Fogón"})
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_busqueda_por_comentario(self):
        Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5, comentario="Excelente sazón",
        )
        response = self.client.get(self._changelist_url(), {"q": "sazón"})
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_estado_visual_publicado_y_oculto(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(
            usuario=self.otro_usuario, establecimiento=self.otro_establecimiento, valoracion=2,
            estado=Resena.ESTADO_OCULTO,
        )
        response = self.client.get(self._changelist_url())
        self.assertContains(response, "Publicado")
        self.assertContains(response, "Oculto")

    def test_favorito_admin_sigue_usando_su_propio_filtro_sin_cambios(self):
        Favorito.objects.create(usuario=self.usuario, establecimiento=self.establecimiento)
        response = self.client.get(reverse("admin:interacciones_favorito_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Establecimiento")

    def test_queries_no_crecen_entre_1_y_20_resenas(self):
        Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)
        with CaptureQueriesContext(connection) as una:
            self.client.get(self._changelist_url())
        queries_con_una = len(una.captured_queries)

        for i in range(19):
            usuario = User.objects.create_user(username=f"admin_qa_n_{i}", password="clave12345")
            categoria = CategoriaEstablecimiento.objects.create(nombre=f"Cat {i}", slug=f"cat-{i}")
            establecimiento = Establecimiento.objects.create(
                tipo="restaurante", categoria_principal=categoria, nombre=f"Local {i}", slug=f"local-admin-{i}",
            )
            Resena.objects.create(usuario=usuario, establecimiento=establecimiento, valoracion=4)

        with CaptureQueriesContext(connection) as veinte:
            self.client.get(self._changelist_url())
        queries_con_veinte = len(veinte.captured_queries)

        self.assertEqual(queries_con_una, queries_con_veinte)


class ResenaAdminChangeformTests(ResenaAdminTestBase):
    def setUp(self):
        self.client.login(username="admin_qa", password="clave12345")
        self.resena = Resena.objects.create(
            usuario=self.usuario, establecimiento=self.establecimiento, valoracion=3, comentario="Comentario original",
        )

    def _payload_base(self, **overrides):
        data = {
            "usuario": self.usuario.pk,
            "establecimiento": self.establecimiento.pk,
            "valoracion": 3,
            "comentario": "Comentario original",
            "estado": Resena.ESTADO_PUBLICADO,
        }
        data.update(overrides)
        return data

    def test_get_changeform_no_renderiza_campos_readonly_como_editables(self):
        response = self.client.get(self._change_url(self.resena.pk))
        self.assertNotContains(response, '<textarea name="comentario"')
        self.assertNotContains(response, 'name="valoracion"')
        self.assertNotContains(response, 'name="usuario"')

    def test_get_changeform_estado_si_es_editable(self):
        response = self.client.get(self._change_url(self.resena.pk))
        self.assertContains(response, 'name="estado"')

    def test_post_forjado_no_cambia_campos_readonly(self):
        payload = self._payload_base(
            comentario="Comentario falsificado", valoracion=1, usuario=self.otro_usuario.pk,
        )
        self.client.post(self._change_url(self.resena.pk), payload)
        self.resena.refresh_from_db()
        self.assertEqual(self.resena.comentario, "Comentario original")
        self.assertEqual(self.resena.valoracion, 3)
        self.assertEqual(self.resena.usuario, self.usuario)

    def test_post_cambia_estado(self):
        payload = self._payload_base(estado=Resena.ESTADO_OCULTO)
        self.client.post(self._change_url(self.resena.pk), payload)
        self.resena.refresh_from_db()
        self.assertEqual(self.resena.estado, Resena.ESTADO_OCULTO)

    def test_cambiar_estado_publicado_a_oculto_no_toca_actualizado(self):
        actualizado_original = self.resena.actualizado
        payload = self._payload_base(estado=Resena.ESTADO_OCULTO)
        self.client.post(self._change_url(self.resena.pk), payload)
        self.resena.refresh_from_db()
        self.assertEqual(self.resena.estado, Resena.ESTADO_OCULTO)
        self.assertEqual(self.resena.actualizado, actualizado_original)

    def test_cambiar_estado_oculto_a_publicado_no_toca_actualizado(self):
        self.resena.estado = Resena.ESTADO_OCULTO
        self.resena.save(update_fields=["estado"])
        self.resena.refresh_from_db()
        actualizado_original = self.resena.actualizado

        payload = self._payload_base(estado=Resena.ESTADO_PUBLICADO)
        self.client.post(self._change_url(self.resena.pk), payload)
        self.resena.refresh_from_db()
        self.assertEqual(self.resena.estado, Resena.ESTADO_PUBLICADO)
        self.assertEqual(self.resena.actualizado, actualizado_original)

    def test_enlace_recurso_publico_correcto(self):
        response = self.client.get(self._change_url(self.resena.pk))
        self.assertContains(response, self.establecimiento.get_absolute_url())
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, 'rel="noopener noreferrer"')


class ResenaAdminPermisosTests(ResenaAdminTestBase):
    def setUp(self):
        self.resena = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=4)

    def test_anonimo_redirige_a_login(self):
        response = self.client.get(self._changelist_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_no_staff_redirige_a_login(self):
        self.client.login(username="turista1", password="clave12345")
        response = self.client.get(self._changelist_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_staff_sin_permisos_403(self):
        staff = User.objects.create_user(username="staff_sin_permisos", password="clave12345", is_staff=True)
        self.client.login(username="staff_sin_permisos", password="clave12345")
        response = self.client.get(self._changelist_url())
        self.assertEqual(response.status_code, 403)

    def test_staff_solo_view_no_puede_ejecutar_acciones(self):
        staff = User.objects.create_user(username="staff_view", password="clave12345", is_staff=True)
        _dar_permisos(staff, "view_resena")
        self.client.login(username="staff_view", password="clave12345")
        response = self.client.get(self._changelist_url())
        self.assertEqual(response.status_code, 200)

        # La acción no aparece entre las opciones permitidas para este
        # usuario (permissions=["change"] en el @admin.action) — Django la
        # rechaza como elección inválida del formulario y re-renderiza el
        # changelist con 200 (no la ejecuta), en vez de lanzar 403.
        data = {"action": "ocultar_resenas", "_selected_action": [str(self.resena.pk)]}
        response = self.client.post(self._changelist_url(), data)
        self.assertEqual(response.status_code, 200)
        self.resena.refresh_from_db()
        self.assertEqual(self.resena.estado, Resena.ESTADO_PUBLICADO)

    def test_staff_solo_view_no_puede_guardar_cambios(self):
        staff = User.objects.create_user(username="staff_view_2", password="clave12345", is_staff=True)
        _dar_permisos(staff, "view_resena")
        self.client.login(username="staff_view_2", password="clave12345")
        response = self.client.post(self._change_url(self.resena.pk), {
            "usuario": self.usuario.pk, "establecimiento": self.establecimiento.pk,
            "valoracion": 4, "comentario": "", "estado": Resena.ESTADO_OCULTO,
        })
        self.assertEqual(response.status_code, 403)
        self.resena.refresh_from_db()
        self.assertEqual(self.resena.estado, Resena.ESTADO_PUBLICADO)

    def test_staff_con_view_y_change_puede_moderar(self):
        staff = User.objects.create_user(username="staff_moderador", password="clave12345", is_staff=True)
        _dar_permisos(staff, "view_resena", "change_resena")
        self.client.login(username="staff_moderador", password="clave12345")
        data = {"action": "ocultar_resenas", "_selected_action": [str(self.resena.pk)]}
        response = self.client.post(self._changelist_url(), data, follow=True)
        self.resena.refresh_from_db()
        self.assertEqual(self.resena.estado, Resena.ESTADO_OCULTO)
        self.assertContains(response, "1 reseña ocultada.")

    def test_staff_con_change_no_puede_crear(self):
        staff = User.objects.create_user(username="staff_sin_add", password="clave12345", is_staff=True)
        _dar_permisos(staff, "view_resena", "change_resena")
        self.client.login(username="staff_sin_add", password="clave12345")
        response = self.client.get(self._add_url())
        self.assertEqual(response.status_code, 403)

    def test_staff_con_change_pero_sin_delete_no_puede_borrar(self):
        staff = User.objects.create_user(username="staff_sin_delete", password="clave12345", is_staff=True)
        _dar_permisos(staff, "view_resena", "change_resena")
        self.client.login(username="staff_sin_delete", password="clave12345")
        response = self.client.post(self._delete_url(self.resena.pk), {"post": "yes"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Resena.objects.filter(pk=self.resena.pk).exists())

    def test_staff_con_delete_explicito_puede_borrar(self):
        staff = User.objects.create_user(username="staff_con_delete", password="clave12345", is_staff=True)
        _dar_permisos(staff, "view_resena", "change_resena", "delete_resena")
        self.client.login(username="staff_con_delete", password="clave12345")
        response = self.client.post(self._delete_url(self.resena.pk), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Resena.objects.filter(pk=self.resena.pk).exists())

    def test_superuser_puede_borrar(self):
        self.client.login(username="admin_qa", password="clave12345")
        response = self.client.post(self._delete_url(self.resena.pk), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Resena.objects.filter(pk=self.resena.pk).exists())


class ResenaAdminIntegracionF5Tests(ResenaAdminTestBase):
    def setUp(self):
        self.client_admin = self.client_class()
        self.client_admin.login(username="admin_qa", password="clave12345")

    def test_ciclo_ocultar_publicar_establecimiento(self):
        a = Resena.objects.create(usuario=self.usuario, establecimiento=self.establecimiento, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, establecimiento=self.establecimiento, valoracion=3)

        detalle_url = self.establecimiento.get_absolute_url()
        response = self.client.get(detalle_url)
        self.assertEqual(response.context["resumen_resenas"]["promedio"], 4.0)
        self.assertEqual(response.context["resumen_resenas"]["total"], 2)

        data = {"action": "ocultar_resenas", "_selected_action": [str(a.pk)]}
        self.client_admin.post(reverse("admin:interacciones_resena_changelist"), data)

        response = self.client.get(detalle_url)
        self.assertEqual(response.context["resumen_resenas"]["promedio"], 3.0)
        self.assertEqual(response.context["resumen_resenas"]["total"], 1)
        fila_5 = next(f for f in response.context["resumen_resenas"]["distribucion"] if f["estrella"] == 5)
        self.assertEqual(fila_5["cantidad"], 0)

        self.client.login(username="turista1", password="clave12345")
        response = self.client.get(detalle_url)
        self.assertEqual(response.context["mi_resena"].pk, a.pk)
        self.assertContains(response, "no está visible públicamente")
        self.client.logout()

        data = {"action": "publicar_resenas", "_selected_action": [str(a.pk)]}
        self.client_admin.post(reverse("admin:interacciones_resena_changelist"), data)

        response = self.client.get(detalle_url)
        self.assertEqual(response.context["resumen_resenas"]["promedio"], 4.0)
        self.assertEqual(response.context["resumen_resenas"]["total"], 2)

    def test_ciclo_ocultar_publicar_lugar_turistico(self):
        a = Resena.objects.create(usuario=self.usuario, lugar_turistico=self.lugar, valoracion=5)
        Resena.objects.create(usuario=self.otro_usuario, lugar_turistico=self.lugar, valoracion=3)

        detalle_url = self.lugar.get_absolute_url()
        data = {"action": "ocultar_resenas", "_selected_action": [str(a.pk)]}
        self.client_admin.post(reverse("admin:interacciones_resena_changelist"), data)

        response = self.client.get(detalle_url)
        self.assertEqual(response.context["resumen_resenas"]["promedio"], 3.0)
        self.assertEqual(response.context["resumen_resenas"]["total"], 1)

        data = {"action": "publicar_resenas", "_selected_action": [str(a.pk)]}
        self.client_admin.post(reverse("admin:interacciones_resena_changelist"), data)

        response = self.client.get(detalle_url)
        self.assertEqual(response.context["resumen_resenas"]["promedio"], 4.0)
        self.assertEqual(response.context["resumen_resenas"]["total"], 2)
