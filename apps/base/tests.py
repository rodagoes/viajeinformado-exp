from decimal import Decimal
from unittest import TestCase

from django.test import TestCase as DjangoTestCase
from django.urls import resolve, reverse

from apps.base.navegacion import resolver_seccion_activa
from apps.base.services.mapas import coord_a_texto, construir_urls_mapa


class CoordATextoTests(TestCase):
    def test_none_devuelve_cadena_vacia(self):
        self.assertEqual(coord_a_texto(None), "")

    def test_cadena_vacia_devuelve_cadena_vacia(self):
        self.assertEqual(coord_a_texto(""), "")

    def test_decimal_se_formatea_con_punto(self):
        self.assertEqual(coord_a_texto(Decimal("-9.9320000")), "-9.9320000")


class ConstruirUrlsMapaTests(TestCase):
    def test_sin_ningun_dato_devuelve_urls_vacias(self):
        embed_url, open_url, route_url = construir_urls_mapa()
        self.assertEqual(embed_url, "")
        self.assertEqual(open_url, "")
        self.assertEqual(route_url, "")

    def test_solo_lat_lng(self):
        embed_url, open_url, route_url = construir_urls_mapa(
            latitud="-9.9281900", longitud="-76.2405600", zoom_coordenadas=17
        )
        self.assertEqual(
            embed_url,
            "https://www.google.com/maps?q=-9.9281900%2C-76.2405600&z=17&hl=es&output=embed",
        )
        self.assertEqual(
            open_url,
            "https://www.google.com/maps/search/?api=1&query=-9.9281900%2C-76.2405600",
        )
        self.assertEqual(
            route_url,
            "https://www.google.com/maps/dir/?api=1&destination=-9.9281900%2C-76.2405600",
        )

    def test_solo_direccion(self):
        embed_url, open_url, route_url = construir_urls_mapa(
            direccion_mapa="Jr. Dos de Mayo 1234, Huánuco, Perú", zoom_direccion=15
        )
        self.assertIn("q=Jr.%20Dos%20de%20Mayo", embed_url)
        self.assertIn("&z=15&hl=es&output=embed", embed_url)
        self.assertIn(
            "https://www.google.com/maps/search/?api=1&query=Jr.%20Dos%20de%20Mayo",
            open_url,
        )
        self.assertIn(
            "https://www.google.com/maps/dir/?api=1&destination=Jr.%20Dos%20de%20Mayo",
            route_url,
        )

    def test_maps_url_tiene_prioridad_sobre_lat_lng_para_open_url(self):
        _, open_url, _ = construir_urls_mapa(
            latitud="-9.9", longitud="-76.2",
            maps_url="https://maps.google.com/?cid=12345",
        )
        self.assertEqual(open_url, "https://maps.google.com/?cid=12345")

    def test_embed_maps_tiene_prioridad_sobre_lat_lng_para_embed_url(self):
        embed_url, _, _ = construir_urls_mapa(
            latitud="-9.9", longitud="-76.2",
            embed_maps='<iframe src="https://www.google.com/maps/embed?pb=XYZ"></iframe>',
        )
        self.assertEqual(embed_url, "https://www.google.com/maps/embed?pb=XYZ")

    def test_embed_maps_solo_url_sin_iframe(self):
        embed_url, _, _ = construir_urls_mapa(
            embed_maps="https://www.google.com/maps/embed?pb=DIRECTA",
        )
        self.assertEqual(embed_url, "https://www.google.com/maps/embed?pb=DIRECTA")

    def test_route_url_extrae_3d4d_de_maps_url_con_prioridad_sobre_lat_lng(self):
        _, _, route_url = construir_urls_mapa(
            latitud="-9.0", longitud="-76.0",
            maps_url="https://www.google.com/maps/place/Foo/@-9.1,-76.1,17z/data=!4m5!3m4!1s0x0:0x0!8m2!3d-9.9299!4d-76.2422",
        )
        self.assertEqual(
            route_url,
            "https://www.google.com/maps/dir/?api=1&destination=-9.9299%2C-76.2422",
        )

    def test_route_url_extrae_arroba_lat_lng_de_maps_url_si_no_hay_3d4d(self):
        _, _, route_url = construir_urls_mapa(
            maps_url="https://www.google.com/maps/@-9.93,-76.24,15z",
        )
        self.assertEqual(
            route_url,
            "https://www.google.com/maps/dir/?api=1&destination=-9.93%2C-76.24",
        )

    def test_zoom_por_defecto_es_diecisiete(self):
        embed_url, _, _ = construir_urls_mapa(latitud="-9.9", longitud="-76.2")
        self.assertIn("&z=17&hl=es&output=embed", embed_url)

    def test_zoom_personalizado_por_direccion_distinto_de_coordenadas(self):
        embed_url, _, _ = construir_urls_mapa(
            direccion_mapa="Huánuco, Perú", zoom_coordenadas=16, zoom_direccion=15
        )
        self.assertIn("&z=15&hl=es&output=embed", embed_url)


class HistoriaViewTests(DjangoTestCase):
    def test_responde_200_y_usa_el_template_correcto(self):
        response = self.client.get(reverse("base:historia"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "base/historia.html")

    def test_h1_principal_presente(self):
        response = self.client.get(reverse("base:historia"))
        self.assertContains(response, '<h1 class="his-hero__title">Historia de Huánuco</h1>')

    def test_cta_enlaza_a_lugares_turisticos(self):
        response = self.client.get(reverse("base:historia"))
        self.assertContains(response, reverse("turismo:listado_lugares"))

    def test_no_requiere_autenticacion(self):
        response = self.client.get(reverse("base:historia"))
        self.assertNotIn(response.status_code, (302, 401, 403))


class ResolverSeccionActivaTests(DjangoTestCase):
    """Verifica que la sección activa del header se resuelva por
    namespace/url_name (nunca por request.path) para cada ruta pública
    real de cada sección del menú."""

    def _seccion_para(self, url_name):
        match = resolve(reverse(url_name))
        return resolver_seccion_activa(match)

    def test_home_resuelve_a_inicio(self):
        self.assertEqual(self._seccion_para("base:home"), "inicio")

    def test_historia_resuelve_a_explorar(self):
        self.assertEqual(self._seccion_para("base:historia"), "explorar")

    def test_lugares_turisticos_resuelve_a_explorar(self):
        self.assertEqual(self._seccion_para("turismo:listado_lugares"), "explorar")

    def test_restaurantes_resuelve_a_gastronomia(self):
        self.assertEqual(self._seccion_para("establecimientos:listado_restaurantes"), "gastronomia")

    def test_platos_tipicos_resuelve_a_gastronomia(self):
        self.assertEqual(self._seccion_para("gastronomia:platos_tipicos"), "gastronomia")

    def test_alojamientos_resuelve_a_gastronomia(self):
        self.assertEqual(self._seccion_para("establecimientos:listado_alojamientos"), "gastronomia")

    def test_tarifas_taxi_resuelve_a_planifica(self):
        self.assertEqual(self._seccion_para("movilidad:tarifas_taxi"), "planifica")

    def test_como_llegar_resuelve_a_planifica(self):
        self.assertEqual(self._seccion_para("movilidad:como_llegar"), "planifica")

    def test_clima_temporadas_resuelve_a_planifica(self):
        self.assertEqual(self._seccion_para("clima:clima_temporadas"), "planifica")

    def test_tipo_cambio_resuelve_a_planifica(self):
        self.assertEqual(self._seccion_para("monedas:tipo_cambio"), "planifica")

    def test_servicios_utiles_resuelve_a_planifica(self):
        self.assertEqual(self._seccion_para("servicios_turista:servicios_utiles"), "planifica")

    def test_emergencias_resuelve_a_planifica(self):
        self.assertEqual(self._seccion_para("emergencias:emergencias"), "planifica")

    def test_eventos_resuelve_a_eventos(self):
        self.assertEqual(self._seccion_para("eventos:listado_eventos"), "eventos")

    def test_pagina_sin_seccion_no_marca_ninguna(self):
        self.assertIsNone(self._seccion_para("base:privacidad"))

    def test_resolver_match_none_no_marca_ninguna(self):
        self.assertIsNone(resolver_seccion_activa(None))


class ActiveNavContextProcessorTests(DjangoTestCase):
    """Confirma que el context processor global (no cada vista) es quien
    deja `active_nav` correcto en el template — la causa real de la
    inconsistencia reportada."""

    def test_header_marca_explorar_activo_en_historia(self):
        response = self.client.get(reverse("base:historia"))
        self.assertEqual(response.context["active_nav"], "explorar")

    def test_header_marca_planifica_activo_en_servicios_utiles(self):
        response = self.client.get(reverse("servicios_turista:servicios_utiles"))
        self.assertEqual(response.context["active_nav"], "planifica")

    def test_header_marca_eventos_activo_en_eventos(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertEqual(response.context["active_nav"], "eventos")

    def test_header_marca_inicio_activo_solo_en_inicio(self):
        response = self.client.get(reverse("base:home"))
        self.assertEqual(response.context["active_nav"], "inicio")

        response = self.client.get(reverse("base:historia"))
        self.assertNotEqual(response.context["active_nav"], "inicio")
