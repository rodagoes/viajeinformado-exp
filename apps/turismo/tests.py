import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.utils import translation
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.chatbot.services.providers import turismo as prov_turismo
from apps.interacciones.models import Resena
from apps.ubicaciones.models import Departamento, Distrito, Localidad, Provincia

from django.core.exceptions import ValidationError

from .admin import LugarTuristicoAdminForm
from .models import DURACION_MAX_MINUTOS, CategoriaLugarTuristico, LugarTuristico, formatear_duracion


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


class DuracionEstructuradaTests(TestCase):
    """Duración mínima/máxima en minutos: validación del modelo y formulario del Admin."""

    @classmethod
    def setUpTestData(cls):
        departamento = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        provincia = Provincia.objects.create(nombre_oficial="Huánuco", slug="huanuco", departamento=departamento)
        cls.distrito = Distrito.objects.create(
            nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101", provincia=provincia,
        )
        cls.categoria = CategoriaLugarTuristico.objects.create(nombre="Plazas", slug="plazas")
        cls.admin_user = User.objects.create_superuser("admin-dur", "a@example.com", "clave12345")

    def _lugar(self, **extra):
        datos = dict(categoria_principal=self.categoria, slug="lugar", distrito=self.distrito)
        datos.update(extra)
        datos.setdefault("nombre", datos["slug"])  # el par (distrito, nombre) es único
        return LugarTuristico.objects.create(**datos)

    def _error_campo(self, lugar, campo):
        with self.assertRaises(ValidationError) as ctx:
            lugar.full_clean()
        self.assertIn(campo, ctx.exception.message_dict)

    def test_registro_antiguo_conserva_texto_y_campos_nuevos_nulos(self):
        lugar = self._lugar(tiempo_visita_estimado="medio día")
        lugar.refresh_from_db()
        self.assertEqual(lugar.tiempo_visita_estimado, "medio día")
        self.assertEqual(lugar.tiempo_visita_estimado_es, "medio día")
        self.assertIsNone(lugar.duracion_min_minutos)
        self.assertIsNone(lugar.duracion_max_minutos)

    def test_combinaciones_validas(self):
        casos = ((None, None), (30, None), (60, 60), (5, 15), (1, DURACION_MAX_MINUTOS), (DURACION_MAX_MINUTOS, None))
        for i, (minimo, maximo) in enumerate(casos):
            with self.subTest(minimo=minimo, maximo=maximo):
                self._lugar(slug=f"v-{i}", duracion_min_minutos=minimo, duracion_max_minutos=maximo).full_clean()

    def test_combinaciones_invalidas(self):
        casos = (
            (None, 30, "duracion_max_minutos"),
            (60, 30, "duracion_max_minutos"),
            (0, None, "duracion_min_minutos"),
            (DURACION_MAX_MINUTOS + 1, None, "duracion_min_minutos"),
            (5, DURACION_MAX_MINUTOS + 1, "duracion_max_minutos"),
        )
        for i, (minimo, maximo, campo) in enumerate(casos):
            with self.subTest(minimo=minimo, maximo=maximo):
                lugar = self._lugar(slug=f"i-{i}", duracion_min_minutos=minimo, duracion_max_minutos=maximo)
                self._error_campo(lugar, campo)

    def test_validacion_de_precios_se_mantiene(self):
        lugar = self._lugar(precio_desde=10, precio_hasta=5)
        with self.assertRaises(ValidationError) as ctx:
            lugar.full_clean()
        self.assertIn("El precio hasta no puede ser menor que el precio desde.", ctx.exception.message_dict["__all__"])

    # --- formulario del Admin ---

    def _form(self, instancia=None, **datos):
        base = dict(
            categoria_principal=self.categoria.pk, slug="lugar", distrito=self.distrito.pk,
            tipo_costo="consultar", dificultad="no_aplica", activo="on", duracion_unidad="minutos",
        )
        base.update(datos)
        base.setdefault("nombre", base["slug"])  # el par (distrito, nombre) es único
        return LugarTuristicoAdminForm(base, instance=instancia)

    def _guardar(self, **datos):
        form = self._form(**datos)
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def test_unidades_se_convierten_a_minutos(self):
        for unidad, factor in (("minutos", 1), ("horas", 60), ("dias", 1440)):
            with self.subTest(unidad=unidad):
                lugar = self._guardar(duracion_minima=2, duracion_maxima=3, duracion_unidad=unidad, slug=f"u-{unidad}")
                self.assertEqual((lugar.duracion_min_minutos, lugar.duracion_max_minutos), (2 * factor, 3 * factor))

    def test_limite_se_comprueba_tras_convertir(self):
        self.assertEqual(self._guardar(duracion_minima=7, duracion_unidad="dias").duracion_min_minutos, DURACION_MAX_MINUTOS)
        form = self._form(duracion_minima=8, duracion_unidad="dias", slug="ocho-dias")
        self.assertFalse(form.is_valid())
        self.assertIn("duracion_minima", form.errors)

    def test_entradas_no_validas_dan_error_de_formulario(self):
        casos = (
            dict(duracion_minima="abc"), dict(duracion_minima="1.5"), dict(duracion_minima=0), dict(duracion_minima=-3),
            dict(duracion_maxima=10), dict(duracion_minima=10, duracion_maxima=5), dict(duracion_minima=5, duracion_unidad="semanas"),
        )
        for i, datos in enumerate(casos):
            with self.subTest(datos=datos):
                self.assertFalse(self._form(slug=f"inv-{i}", **datos).is_valid())

    def test_sin_duracion_es_valido_y_deja_nulos(self):
        lugar = self._guardar()
        self.assertIsNone(lugar.duracion_min_minutos)
        self.assertIsNone(lugar.duracion_max_minutos)

    def test_edicion_sin_cambios_conserva_los_minutos(self):
        casos = ((90, None), (120, None), (1440, None), (45, 90), (60, 120), (1440, 2880), (1, 1))
        for i, (minimo, maximo) in enumerate(casos):
            with self.subTest(minimo=minimo, maximo=maximo):
                lugar = self._lugar(slug=f"ed-{i}", duracion_min_minutos=minimo, duracion_max_minutos=maximo)
                inicial = self._form(instancia=lugar, slug=f"ed-{i}").initial
                datos = dict(duracion_minima=inicial["duracion_minima"], duracion_unidad=inicial["duracion_unidad"])
                if maximo:
                    datos["duracion_maxima"] = inicial["duracion_maxima"]
                form = self._form(instancia=lugar, slug=f"ed-{i}", **datos)
                self.assertTrue(form.is_valid(), form.errors)
                guardado = form.save()
                self.assertEqual((guardado.duracion_min_minutos, guardado.duracion_max_minutos), (minimo, maximo))

    def test_unidad_inicial_es_la_mayor_exacta(self):
        casos = ((90, None, "minutos", 90), (120, None, "horas", 2), (2880, None, "dias", 2), (1440, 1450, "minutos", 1440), (60, 120, "horas", 1))
        for minimo, maximo, unidad, valor in casos:
            with self.subTest(minimo=minimo, maximo=maximo):
                lugar = self._lugar(slug=f"in-{minimo}-{maximo}", duracion_min_minutos=minimo, duracion_max_minutos=maximo)
                form = self._form(instancia=lugar)
                self.assertEqual((form.initial["duracion_unidad"], form.initial["duracion_minima"]), (unidad, valor))

    def test_guardar_duracion_no_altera_el_texto_anterior(self):
        lugar = self._lugar(tiempo_visita_estimado="medio día")
        lugar.tiempo_visita_estimado_en = "half a day"
        lugar.save()
        form = self._form(instancia=lugar, duracion_minima=2, duracion_unidad="horas",
                          tiempo_visita_estimado_es="medio día", tiempo_visita_estimado_en="half a day")
        self.assertTrue(form.is_valid(), form.errors)
        guardado = LugarTuristico.objects.get(pk=form.save().pk)
        self.assertEqual((guardado.tiempo_visita_estimado_es, guardado.tiempo_visita_estimado_en), ("medio día", "half a day"))
        self.assertEqual(guardado.duracion_min_minutos, 120)

    # --- Admin completo (TranslationAdmin) ---

    def test_admin_renderiza_y_guarda_campos_traducibles_y_duracion(self):
        lugar = self._lugar(tiempo_visita_estimado="medio día")
        self.client.force_login(self.admin_user)
        url = reverse("admin:turismo_lugarturistico_change", args=[lugar.pk])
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Texto anterior de duración (respaldo)")
        self.assertContains(respuesta, 'name="duracion_unidad"')

        datos = {}
        for campo in respuesta.context["adminform"].form:
            valor = campo.value()
            if valor is None or hasattr(valor, "name") or valor is False:
                continue
            datos[campo.html_name] = "on" if valor is True else valor
        for inline in respuesta.context["inline_admin_formsets"]:
            for clave, valor in inline.formset.management_form.initial.items():
                datos[f"{inline.formset.prefix}-{clave}"] = valor
        datos.update({"duracion_minima": 1, "duracion_maxima": 2, "duracion_unidad": "horas", "descripcion_corta_en": "Short"})
        respuesta = self.client.post(url, datos)
        self.assertEqual(respuesta.status_code, 302)
        lugar.refresh_from_db()
        self.assertEqual((lugar.duracion_min_minutos, lugar.duracion_max_minutos), (60, 120))
        self.assertEqual(lugar.descripcion_corta_en, "Short")
        self.assertEqual(lugar.tiempo_visita_estimado_es, "medio día")


class TiempoVisitaTextoTests(TestCase):
    """Fase 2.2: formateador único ES/EN y precedencia estructurado → histórico → vacío."""

    @classmethod
    def setUpTestData(cls):
        departamento = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        provincia = Provincia.objects.create(nombre_oficial="Huánuco", slug="huanuco", departamento=departamento)
        cls.distrito = Distrito.objects.create(
            nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101", provincia=provincia,
        )
        cls.categoria = CategoriaLugarTuristico.objects.create(nombre="Plazas", slug="plazas")

    def setUp(self):
        # Las peticiones del cliente en inglés dejan el idioma activo; cada prueba parte en español.
        translation.activate("es")
        self.addCleanup(translation.activate, "es")

    def _lugar(self, slug="lugar", **extra):
        return LugarTuristico.objects.create(
            categoria_principal=self.categoria, nombre=slug, slug=slug, distrito=self.distrito, **extra
        )

    def test_formato_es_y_en(self):
        casos = (
            (5, 15, "5 a 15 min", "5 to 15 min"),
            (30, None, "30 min", "30 min"),
            (60, None, "1 hora", "1 hour"),
            (120, None, "2 horas", "2 hours"),
            (60, 120, "1 a 2 horas", "1 to 2 hours"),
            (90, None, "1 h 30 min", "1 h 30 min"),
            (45, 90, "45 min a 1 h 30 min", "45 min to 1 h 30 min"),
            (1440, None, "1 día", "1 day"),
            (2880, 4320, "2 a 3 días", "2 to 3 days"),
            (1440, 2880, "1 a 2 días", "1 to 2 days"),
            (60, 180, "1 a 3 horas", "1 to 3 hours"),
            (45, 45, "45 min", "45 min"),
            (60, 60, "1 hora", "1 hour"),
            (1560, None, "1 día 2 horas", "1 day 2 hours"),
            (10080, None, "7 días", "7 days"),
            (30, 120, "30 min a 2 horas", "30 min to 2 hours"),
        )
        for minimo, maximo, es, en in casos:
            with self.subTest(minimo=minimo, maximo=maximo):
                with translation.override("es"):
                    self.assertEqual(formatear_duracion(minimo, maximo), es)
                with translation.override("en"):
                    self.assertEqual(formatear_duracion(minimo, maximo), en)

    def test_sin_duracion_devuelve_vacio(self):
        for minimo, maximo in ((None, None), (0, None), (None, 30)):
            self.assertEqual(formatear_duracion(minimo, maximo), "")

    def test_el_idioma_se_toma_al_usar_la_propiedad(self):
        lugar = self._lugar(duracion_min_minutos=60, duracion_max_minutos=120)
        with translation.override("en"):
            self.assertEqual(lugar.tiempo_visita_texto, "1 to 2 hours")
        with translation.override("es"):
            self.assertEqual(lugar.tiempo_visita_texto, "1 a 2 horas")

    def test_precedencia_estructurado_historico_vacio(self):
        lugar = self._lugar(tiempo_visita_estimado="5 min - 15 min", duracion_min_minutos=60, duracion_max_minutos=180)
        self.assertEqual(lugar.tiempo_visita_texto, "1 a 3 horas")
        lugar.duracion_min_minutos = lugar.duracion_max_minutos = None
        self.assertEqual(lugar.tiempo_visita_texto, "5 min - 15 min")
        lugar.tiempo_visita_estimado = ""
        self.assertEqual(lugar.tiempo_visita_texto, "")

    def test_historico_respeta_el_idioma_y_el_fallback_a_es(self):
        lugar = self._lugar(tiempo_visita_estimado_es="medio día", tiempo_visita_estimado_en="half a day")
        lugar.refresh_from_db()
        with translation.override("en"):
            self.assertEqual(lugar.tiempo_visita_texto, "half a day")
        lugar.tiempo_visita_estimado_en = ""
        lugar.save()
        lugar.refresh_from_db()
        with translation.override("en"):
            self.assertEqual(lugar.tiempo_visita_texto, "medio día")

    def _get(self, url, idioma):
        self.client.cookies["django_language"] = idioma
        return self.client.get(url, HTTP_ACCEPT_LANGUAGE=idioma)

    def test_listado_y_detalle_usan_la_duracion_estructurada(self):
        lugar = self._lugar(tiempo_visita_estimado="5 min - 15 min", duracion_min_minutos=60, duracion_max_minutos=180)
        for url in (reverse("turismo:listado_lugares"), lugar.get_absolute_url()):
            with self.subTest(url=url):
                es = self._get(url, "es")
                self.assertContains(es, "1 a 3 horas")
                self.assertNotContains(es, "5 min - 15 min")
                en = self._get(url, "en")
                self.assertContains(en, "1 to 3 hours")
                self.assertNotContains(en, "5 min - 15 min")

    def test_listado_y_detalle_con_solo_duracion_estructurada_muestran_la_fila(self):
        lugar = self._lugar(duracion_min_minutos=90)
        self.assertContains(self._get(reverse("turismo:listado_lugares"), "es"), "1 h 30 min")
        self.assertContains(self._get(lugar.get_absolute_url(), "es"), "1 h 30 min")

    def test_listado_y_detalle_con_texto_historico_como_respaldo(self):
        lugar = self._lugar(tiempo_visita_estimado_es="medio día", tiempo_visita_estimado_en="half a day")
        for url in (reverse("turismo:listado_lugares"), lugar.get_absolute_url()):
            with self.subTest(url=url):
                self.assertContains(self._get(url, "es"), "medio día")
                self.assertContains(self._get(url, "en"), "half a day")

    def test_sin_ninguna_duracion_no_se_renderiza_la_fila(self):
        lugar = self._lugar()
        self.assertNotContains(self._get(reverse("turismo:listado_lugares"), "es"), "Visita estimada:")
        self.assertNotContains(self._get(lugar.get_absolute_url(), "es"), "Recorrido estimado")

    def test_chatbot_devuelve_la_duracion_formateada(self):
        self._lugar(slug="con-duracion", tiempo_visita_estimado="5 min - 15 min", duracion_min_minutos=60, duracion_max_minutos=180)
        self._lugar(slug="historico", tiempo_visita_estimado="medio día")
        self._lugar(slug="sin-duracion")
        with translation.override("es"):
            self.assertEqual(prov_turismo.obtener_lugar("con-duracion")["item"]["tiempo_visita_estimado"], "1 a 3 horas")
            self.assertEqual(prov_turismo.obtener_lugar("historico")["item"]["tiempo_visita_estimado"], "medio día")
            self.assertEqual(prov_turismo.obtener_lugar("sin-duracion")["item"]["tiempo_visita_estimado"], "")
        with translation.override("en"):
            self.assertEqual(prov_turismo.obtener_lugar("con-duracion")["item"]["tiempo_visita_estimado"], "1 to 3 hours")


class UbicacionLugarTests(TestCase):
    """Pill del listado (un topónimo) y ubicación descriptiva del detalle (máx. dos)."""

    def setUp(self):
        translation.activate("es")
        self.addCleanup(translation.deactivate)

    @classmethod
    def setUpTestData(cls):
        departamento = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        cls.provincia = Provincia.objects.create(nombre_oficial="Leoncio Prado", slug="leoncio-prado", departamento=departamento)
        cls.distrito = Distrito.objects.create(
            nombre_oficial="Mariano Dámaso Beraún", slug="mdb", codigo_inei="100601", provincia=cls.provincia,
        )
        cls.localidad = Localidad.objects.create(distrito=cls.distrito, nombre="Tingo María", slug="tingo-maria", tipo="Ciudad")
        cls.categoria = CategoriaLugarTuristico.objects.create(nombre="Plazas", slug="plazas")

    def _lugar(self, slug="lugar", **extra):
        return LugarTuristico.objects.create(
            categoria_principal=self.categoria, nombre=slug, slug=slug, distrito=self.distrito, **extra
        )

    def test_pill_prioriza_localidad_luego_distrito_luego_provincia(self):
        self.assertEqual(self._lugar("a", localidad=self.localidad).ubicacion_corta, "Tingo María")
        self.assertEqual(self._lugar("b").ubicacion_corta, "Mariano Dámaso Beraún")
        sin_nombre = self._lugar("c")
        sin_nombre.distrito.nombre_oficial = " "
        self.assertEqual(sin_nombre.ubicacion_corta, "Leoncio Prado")
        self.assertEqual(LugarTuristico().ubicacion_corta, "")

    def test_ubicacion_descriptiva(self):
        self.assertEqual(self._lugar("a", localidad=self.localidad).ubicacion_descriptiva, "Tingo María, Leoncio Prado")
        self.assertEqual(self._lugar("b").ubicacion_descriptiva, "Mariano Dámaso Beraún, Leoncio Prado")
        self.assertEqual(LugarTuristico().ubicacion_descriptiva, "")

    def test_ubicacion_descriptiva_no_duplica_equivalentes(self):
        provincia = Provincia.objects.create(nombre_oficial="Huánuco", slug="hco", departamento=self.provincia.departamento)
        distrito = Distrito.objects.create(nombre_oficial="HUÁNUCO", slug="hco", codigo_inei="100101", provincia=provincia)
        lugar = LugarTuristico.objects.create(categoria_principal=self.categoria, nombre="x", slug="x", distrito=distrito)
        self.assertEqual(lugar.ubicacion_descriptiva, "HUÁNUCO")

    def test_listado_muestra_un_solo_toponimo_en_la_pill(self):
        self._lugar("a", localidad=self.localidad)
        self._lugar("b")
        html = self.client.get(reverse("turismo:listado_lugares")).content.decode()
        pills = re.findall(r'<span class="lugar-ubicacion" title="([^"]*)">.*?<span>([^<]*)</span>', html, re.S)
        self.assertEqual(sorted(p[1] for p in pills), ["Mariano Dámaso Beraún", "Tingo María"])
        self.assertTrue(all(t == v for t, v in pills))
        self.assertNotIn("Tingo María, ", html)

    def test_detalle_muestra_ubicacion_descriptiva_y_etiqueta_corta(self):
        lugar = self._lugar("a", duracion_min_minutos=60, duracion_max_minutos=180)
        html = self.client.get(lugar.get_absolute_url()).content.decode()
        self.assertIn('<p class="dl-dato-val">Mariano Dámaso Beraún, Leoncio Prado</p>', html)
        self.assertIn('<span class="dl-label-short">Recorrido</span>', html)
        self.assertIn("1 a 3 horas", html)
