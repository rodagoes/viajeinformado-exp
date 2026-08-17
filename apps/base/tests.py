from decimal import Decimal
from unittest import TestCase

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
