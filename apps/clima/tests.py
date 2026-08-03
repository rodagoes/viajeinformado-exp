from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .services import clima_actual as servicio

REQUESTS_GET_PATH = "apps.clima.services.clima_actual.requests.get"

SETTINGS_CON_COORDENADAS = dict(
    CLIMA_HUANUCO_LATITUD="-9.9295",
    CLIMA_HUANUCO_LONGITUD="-76.2397",
    CLIMA_TINGO_MARIA_LATITUD="-9.2984",
    CLIMA_TINGO_MARIA_LONGITUD="-76.00027",
)


def _payload_valido(weather_code=2, is_day=0, time="2026-08-01T01:15", temperature_2m=19.8,
                     apparent_temperature=21.6, relative_humidity_2m=86,
                     precipitation_probability=20, precipitation=0.0,
                     cloud_cover=47, wind_speed_10m=5.6):
    return {
        "latitude": -9.2984,
        "longitude": -76.00027,
        "generationtime_ms": 0.1,
        "utc_offset_seconds": -18000,
        "timezone": "America/Lima",
        "current_units": {
            "time": "iso8601",
            "temperature_2m": "°C",
            "apparent_temperature": "°C",
            "relative_humidity_2m": "%",
            "precipitation_probability": "%",
            "precipitation": "mm",
            "weather_code": "wmo code",
            "cloud_cover": "%",
            "wind_speed_10m": "km/h",
            "is_day": "",
        },
        "current": {
            "time": time,
            "interval": 900,
            "temperature_2m": temperature_2m,
            "apparent_temperature": apparent_temperature,
            "relative_humidity_2m": relative_humidity_2m,
            "precipitation_probability": precipitation_probability,
            "precipitation": precipitation,
            "weather_code": weather_code,
            "cloud_cover": cloud_cover,
            "wind_speed_10m": wind_speed_10m,
            "is_day": is_day,
        },
    }


def _mock_response(json_data=None, http_error=None, json_error=None):
    respuesta = Mock()
    if http_error:
        respuesta.raise_for_status.side_effect = http_error
    else:
        respuesta.raise_for_status.return_value = None
    if json_error:
        respuesta.json.side_effect = json_error
    else:
        respuesta.json.return_value = json_data
    return respuesta


@override_settings(**SETTINGS_CON_COORDENADAS)
class ClimaActualServicioTests(TestCase):
    """Pruebas del cliente Open-Meteo y del flujo de caché/respaldo. No se
    hace ninguna llamada real a Internet: requests.get siempre está mockeado."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    # -- Consulta y parámetros de la petición --------------------------------

    @patch(REQUESTS_GET_PATH)
    def test_consulta_correcta_huanuco(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertEqual(datos["ciudad_slug"], "huanuco")

    @patch(REQUESTS_GET_PATH)
    def test_consulta_correcta_tingo_maria(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        datos = servicio.obtener_clima_actual("tingo-maria")
        self.assertTrue(datos["disponible"])
        self.assertEqual(datos["ciudad_slug"], "tingo-maria")

    @patch(REQUESTS_GET_PATH)
    def test_coordenadas_correctas_huanuco(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], "-9.9295")
        self.assertEqual(params["longitude"], "-76.2397")

    @patch(REQUESTS_GET_PATH)
    def test_coordenadas_correctas_tingo_maria(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("tingo-maria")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], "-9.2984")
        self.assertEqual(params["longitude"], "-76.00027")

    @patch(REQUESTS_GET_PATH)
    def test_endpoint_correcto_open_meteo(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        url = mock_get.call_args.args[0] if mock_get.call_args.args else mock_get.call_args.kwargs.get("url")
        self.assertEqual(url, "https://api.open-meteo.com/v1/forecast")
        self.assertEqual(servicio.OPEN_METEO_URL, "https://api.open-meteo.com/v1/forecast")

    @patch(REQUESTS_GET_PATH)
    def test_sin_api_key_en_parametros(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        params = mock_get.call_args.kwargs["params"]
        self.assertNotIn("key", params)
        self.assertNotIn("apikey", params)
        self.assertNotIn("api_key", params)

    @patch(REQUESTS_GET_PATH)
    def test_usa_unidades_metricas(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["temperature_unit"], "celsius")
        self.assertEqual(params["wind_speed_unit"], "kmh")
        self.assertEqual(params["precipitation_unit"], "mm")

    @patch(REQUESTS_GET_PATH)
    def test_usa_timezone_america_lima(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["timezone"], "America/Lima")

    @patch(REQUESTS_GET_PATH)
    def test_usa_forecast_days_uno(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["forecast_days"], 1)

    # -- Lectura de campos normalizados ---------------------------------------

    @patch(REQUESTS_GET_PATH)
    def test_lectura_temperatura(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(temperature_2m=19.8))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["temperatura_c"], 19.8)

    @patch(REQUESTS_GET_PATH)
    def test_lectura_sensacion_termica(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(apparent_temperature=21.6))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["sensacion_c"], 21.6)

    @patch(REQUESTS_GET_PATH)
    def test_lectura_humedad(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(relative_humidity_2m=86))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["humedad_pct"], 86)

    @patch(REQUESTS_GET_PATH)
    def test_lectura_probabilidad_lluvia(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(precipitation_probability=20))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["probabilidad_lluvia_pct"], 20)

    @patch(REQUESTS_GET_PATH)
    def test_lectura_precipitacion_mm(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(precipitation=3.4))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["precipitacion_mm"], 3.4)

    @patch(REQUESTS_GET_PATH)
    def test_lectura_viento(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(wind_speed_10m=5.6))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["viento_kph"], 5.6)

    @patch(REQUESTS_GET_PATH)
    def test_lectura_nubosidad(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(cloud_cover=47))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["nubosidad_pct"], 47)

    @patch(REQUESTS_GET_PATH)
    def test_lectura_codigo_wmo(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=61))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "lluvia")
        self.assertEqual(datos["estado_texto"], "Lluvia ligera")

    @patch(REQUESTS_GET_PATH)
    def test_lectura_es_dia(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(is_day=0))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertFalse(datos["es_dia"])

    @patch(REQUESTS_GET_PATH)
    def test_lectura_hora_dato(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(time="2026-08-01T01:15"))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["hora_dato"], "2026-08-01T01:15")
        self.assertEqual(datos["actualizado_local"], "1:15 a. m.")

    # -- Mapeo de códigos WMO --------------------------------------------------

    @patch(REQUESTS_GET_PATH)
    def test_mapeo_despejado(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=0))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "soleado")
        self.assertEqual(datos["estado_texto"], "Despejado")

    @patch(REQUESTS_GET_PATH)
    def test_mapeo_parcialmente_nublado(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=2))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "parcialmente-nublado")
        self.assertEqual(datos["estado_texto"], "Parcialmente nublado")

    @patch(REQUESTS_GET_PATH)
    def test_mapeo_nublado(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=3))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "nublado")
        self.assertEqual(datos["estado_texto"], "Nublado")

    @patch(REQUESTS_GET_PATH)
    def test_mapeo_neblina(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=45))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "neblina")
        self.assertEqual(datos["estado_texto"], "Neblina")

    @patch(REQUESTS_GET_PATH)
    def test_mapeo_lluvia(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=63))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "lluvia")
        self.assertEqual(datos["estado_texto"], "Lluvia moderada")

    @patch(REQUESTS_GET_PATH)
    def test_mapeo_tormenta(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=95))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "tormenta")
        self.assertEqual(datos["estado_texto"], "Tormenta eléctrica")

    @patch(REQUESTS_GET_PATH)
    def test_mapeo_codigo_desconocido(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(weather_code=9999))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos["estado_slug"], "variable")
        self.assertEqual(datos["estado_texto"], "Condición variable")

    # -- Manejo de errores y respaldo ------------------------------------------

    @patch(REQUESTS_GET_PATH)
    def test_timeout_usa_ultimo_resultado_valido(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        cache.delete(servicio.cache_key_reciente("huanuco"))

        mock_get.side_effect = requests.exceptions.Timeout()
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertTrue(datos["es_respaldo"])

    @patch(REQUESTS_GET_PATH)
    def test_error_conexion_usa_ultimo_resultado_valido(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        cache.delete(servicio.cache_key_reciente("huanuco"))

        mock_get.side_effect = requests.exceptions.ConnectionError()
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertTrue(datos["es_respaldo"])

    @patch(REQUESTS_GET_PATH)
    def test_http_no_exitoso_usa_ultimo_resultado_valido(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        cache.delete(servicio.cache_key_reciente("huanuco"))

        mock_get.return_value = _mock_response(http_error=requests.exceptions.HTTPError())
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertTrue(datos["es_respaldo"])

    @patch(REQUESTS_GET_PATH)
    def test_json_invalido_usa_ultimo_resultado_valido(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        cache.delete(servicio.cache_key_reciente("huanuco"))

        mock_get.return_value = _mock_response(json_error=ValueError("json inválido"))
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertTrue(datos["es_respaldo"])

    @patch(REQUESTS_GET_PATH)
    def test_current_ausente_usa_respaldo(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        cache.delete(servicio.cache_key_reciente("huanuco"))

        payload_sin_current = {"latitude": -9.9295, "longitude": -76.2397}
        mock_get.return_value = _mock_response(payload_sin_current)
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertTrue(datos["es_respaldo"])

    @patch(REQUESTS_GET_PATH)
    def test_temperatura_ausente_usa_respaldo(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("huanuco")
        cache.delete(servicio.cache_key_reciente("huanuco"))

        payload = _payload_valido()
        del payload["current"]["temperature_2m"]
        mock_get.return_value = _mock_response(payload)
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertTrue(datos["es_respaldo"])

    def test_sin_coordenadas_y_sin_respaldo_devuelve_no_disponible(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            datos = servicio.obtener_clima_actual("huanuco")
        self.assertFalse(datos["disponible"])
        self.assertFalse(datos["es_respaldo"])

    @patch(REQUESTS_GET_PATH)
    def test_valor_no_numerico_no_rompe_el_servicio(self, mock_get):
        payload = _payload_valido()
        payload["current"]["relative_humidity_2m"] = "no-numero"
        mock_get.return_value = _mock_response(payload)
        datos = servicio.obtener_clima_actual("huanuco")
        self.assertTrue(datos["disponible"])
        self.assertIsNone(datos["humedad_pct"])

    def test_mensaje_de_error_no_expone_datos_sensibles(self):
        from apps.clima.ubicaciones import obtener_ciudad

        with patch(REQUESTS_GET_PATH) as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            try:
                servicio._consultar_open_meteo(obtener_ciudad("huanuco"))
            except servicio.ClimaAPIError as exc:
                self.assertNotIn("-9.9295", str(exc))
            else:
                self.fail("Se esperaba ClimaAPIError")

    # -- Multi-ciudad: aislamiento de caché y respaldo -------------------------

    def test_claves_cache_distintas_por_ciudad(self):
        self.assertNotEqual(
            servicio.cache_key_reciente("huanuco"),
            servicio.cache_key_reciente("tingo-maria"),
        )
        self.assertNotEqual(
            servicio.cache_key_ultimo_valido("huanuco"),
            servicio.cache_key_ultimo_valido("tingo-maria"),
        )

    @patch(REQUESTS_GET_PATH)
    def test_cache_independiente_por_ciudad(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(temperature_2m=19.8))
        servicio.obtener_clima_actual("huanuco")
        self.assertEqual(mock_get.call_count, 1)
        self.assertIsNone(cache.get(servicio.cache_key_reciente("tingo-maria")))

        mock_get.return_value = _mock_response(_payload_valido(temperature_2m=27.3))
        datos_tingo = servicio.obtener_clima_actual("tingo-maria")
        self.assertEqual(datos_tingo["temperatura_c"], 27.3)

        # El de Huánuco sigue viniendo de su propia caché reciente, sin una
        # nueva llamada a la red.
        datos_huanuco = servicio.obtener_clima_actual("huanuco")
        self.assertEqual(datos_huanuco["temperatura_c"], 19.8)
        self.assertEqual(mock_get.call_count, 2)

    @patch(REQUESTS_GET_PATH)
    def test_ultimo_valido_independiente_por_ciudad(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(temperature_2m=19.8))
        servicio.obtener_clima_actual("huanuco")

        mock_get.return_value = _mock_response(_payload_valido(temperature_2m=27.3))
        servicio.obtener_clima_actual("tingo-maria")

        self.assertEqual(cache.get(servicio.cache_key_ultimo_valido("huanuco"))["temperatura_c"], 19.8)
        self.assertEqual(cache.get(servicio.cache_key_ultimo_valido("tingo-maria"))["temperatura_c"], 27.3)

    @patch(REQUESTS_GET_PATH)
    def test_tingo_maria_no_hereda_respaldo_de_huanuco(self, mock_get):
        # Huánuco obtiene un resultado válido que queda como su propio respaldo.
        mock_get.return_value = _mock_response(_payload_valido(temperature_2m=19.8))
        servicio.obtener_clima_actual("huanuco")
        cache.delete(servicio.cache_key_reciente("huanuco"))

        # Tingo María nunca tuvo un resultado válido: si Open-Meteo falla,
        # no debe heredar el respaldo de Huánuco.
        mock_get.side_effect = requests.exceptions.Timeout()
        datos_tingo = servicio.obtener_clima_actual("tingo-maria")
        self.assertFalse(datos_tingo["disponible"])

    @patch(REQUESTS_GET_PATH)
    def test_huanuco_no_hereda_respaldo_de_tingo_maria(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido(temperature_2m=27.3))
        servicio.obtener_clima_actual("tingo-maria")
        cache.delete(servicio.cache_key_reciente("tingo-maria"))

        mock_get.side_effect = requests.exceptions.Timeout()
        datos_huanuco = servicio.obtener_clima_actual("huanuco")
        self.assertFalse(datos_huanuco["disponible"])

    @patch(REQUESTS_GET_PATH)
    def test_ciudad_invalida_usa_huanuco(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        servicio.obtener_clima_actual("marte")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], "-9.9295")
        self.assertEqual(params["longitude"], "-76.2397")


class ClimaTemporadasViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_url_resuelve_con_namespace_correcto(self):
        self.assertEqual(reverse("clima:clima_temporadas"), "/planifica/clima-temporadas/")

    @patch(REQUESTS_GET_PATH)
    def test_vista_responde_200(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        with override_settings(**SETTINGS_CON_COORDENADAS):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertEqual(response.status_code, 200)

    @patch(REQUESTS_GET_PATH)
    def test_vista_usa_template_correcto(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        with override_settings(**SETTINGS_CON_COORDENADAS):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertTemplateUsed(response, "clima/clima_temporadas.html")

    def test_navegacion_resuelve_clima_temporadas(self):
        from apps.base.navegacion import HEADER_NAV_ITEMS

        item = next(
            hijo
            for seccion in HEADER_NAV_ITEMS
            for hijo in seccion.get("children", [])
            if hijo["key"] == "clima-temporadas"
        )
        self.assertEqual(item["url_name"], "clima:clima_temporadas")
        self.assertEqual(reverse(item["url_name"]), "/planifica/clima-temporadas/")

    def test_pagina_sin_coordenadas_renderiza_igual(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Información meteorológica temporalmente no disponible")

    def test_pagina_sin_datos_sigue_mostrando_temporadas(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertContains(response, "Temporada seca")
        self.assertContains(response, "Temporada de lluvias")

    def test_pagina_sin_datos_sigue_mostrando_nota_tingo_maria(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertContains(response, "Tingo María")

    def test_pagina_sin_datos_sigue_mostrando_tips(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertContains(response, "Consulta el clima")
        self.assertContains(response, "Empaca versátil")
        self.assertContains(response, "Calzado adecuado")
        self.assertContains(response, "Mantente hidratado")

    def test_html_contiene_distintivos(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertContains(response, "MEJOR ÉPOCA PARA VISITAR")
        self.assertContains(response, "IDEAL POR SUS FESTIVIDADES")

    def test_html_no_contiene_temperaturas_promedio_mensuales(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertNotContains(response, "Temperaturas promedio")

    def test_html_no_contiene_pronostico_de_siete_dias(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        for dia in ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"):
            self.assertNotContains(response, f'"{dia}"')

    # -- Selector de ciudad y ruteo por ?ciudad= -------------------------------

    def test_sin_parametro_usa_huanuco(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertEqual(response.context["ciudad"]["slug"], "huanuco")

    def test_parametro_huanuco_usa_huanuco(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "huanuco"})
        self.assertEqual(response.context["ciudad"]["slug"], "huanuco")

    def test_parametro_tingo_maria_usa_tingo_maria(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertEqual(response.context["ciudad"]["slug"], "tingo-maria")
        self.assertContains(response, "Clima en Tingo María")

    def test_parametro_invalido_usa_huanuco(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "otra-cosa"})
        self.assertEqual(response.context["ciudad"]["slug"], "huanuco")

    def test_selector_muestra_ambas_ciudades(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertContains(response, "?ciudad=huanuco")
        self.assertContains(response, "?ciudad=tingo-maria")
        self.assertContains(response, "Huánuco")
        self.assertContains(response, "Tingo María")

    def test_selector_marca_ciudad_activa(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "selector-ciudad__opcion--activo")

    def test_titulo_cambia_tingo_maria(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertContains(response, "<h1")
        self.assertContains(response, "Clima en Tingo María")
        self.assertEqual(response.content.decode().count("<h1"), 1)

    def test_subtitulo_cambia_tingo_maria(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertContains(response, "Naturaleza y clima tropical")
        self.assertContains(response, "selva alta")

    @patch(REQUESTS_GET_PATH)
    def test_ubicacion_normalizada_cambia_por_ciudad(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        with override_settings(**SETTINGS_CON_COORDENADAS):
            response_huanuco = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "huanuco"})
            response_tingo = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertEqual(response_huanuco.context["clima"]["ubicacion"], "Huánuco (Ciudad)")
        self.assertEqual(response_tingo.context["clima"]["ubicacion"], "Tingo María (Ciudad)")

    def test_ausencia_coordenadas_tingo_maria_no_rompe_pagina(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Información meteorológica temporalmente no disponible")
        self.assertContains(response, "Tingo María (Ciudad)")

    def test_tingo_maria_sin_datos_muestra_temporadas(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertContains(response, "Temporada seca")
        self.assertContains(response, "Temporada de lluvias")

    def test_tingo_maria_sin_datos_muestra_tips(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertContains(response, "Lleva repelente")
        self.assertContains(response, "Calzado adecuado")
        self.assertContains(response, "Mantente hidratado")

    def test_html_huanuco_conserva_contenido_aprobado(self):
        with override_settings(CLIMA_HUANUCO_LATITUD="", CLIMA_HUANUCO_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "huanuco"})
        self.assertContains(response, "Temporada seca")
        self.assertContains(response, "Temporada de lluvias")
        self.assertContains(response, "MEJOR ÉPOCA PARA VISITAR")
        self.assertContains(response, "IDEAL POR SUS FESTIVIDADES")

    def test_html_tingo_maria_contiene_textos_especificos(self):
        with override_settings(CLIMA_TINGO_MARIA_LATITUD="", CLIMA_TINGO_MARIA_LONGITUD=""):
            response = self.client.get(reverse("clima:clima_temporadas"), {"ciudad": "tingo-maria"})
        self.assertContains(response, "Temporada seca")
        self.assertContains(response, "Temporada de lluvias")
        self.assertContains(response, "IDEAL PARA ACTIVIDADES AL AIRE LIBRE")
        self.assertContains(response, "PAISAJES MÁS VERDES Y CAUDALOSOS")

    # -- Atribución a Open-Meteo ------------------------------------------------

    @patch(REQUESTS_GET_PATH)
    def test_plantilla_contiene_atribucion_open_meteo(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        with override_settings(**SETTINGS_CON_COORDENADAS):
            response = self.client.get(reverse("clima:clima_temporadas"))
        self.assertContains(response, "Open-Meteo")
        self.assertContains(response, "https://open-meteo.com/")

    @patch(REQUESTS_GET_PATH)
    def test_no_se_envia_parametro_key_en_la_peticion_real(self, mock_get):
        mock_get.return_value = _mock_response(_payload_valido())
        with override_settings(**SETTINGS_CON_COORDENADAS):
            self.client.get(reverse("clima:clima_temporadas"))
        params = mock_get.call_args.kwargs["params"]
        self.assertNotIn("key", params)
