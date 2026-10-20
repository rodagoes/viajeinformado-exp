"""Mapa, apertura y ruta por sede: validación segura y fiabilidad de cada destino.

Las URL e iframes de estas pruebas son FIXTURES SINTÉTICAS (coordenadas y nombre
inventados a propósito, fuera de Huánuco): sirven para probar patrones de texto, no son
fichas reales de Google Maps. La prueba con fichas reales es manual (ver informe M1).
"""
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import CategoriaServicioTurista, ServicioTurista, SedeServicioTurista
from .services import mapas_sede as m
from .test_horarios import AdminSedeMixin
from .tests import DatosTerritorialesMixin, agregar_sede, crear_sede

LAT, LNG = "-1.2345678", "-2.3456789"
LAT2, LNG2 = "-1.3000000", "-2.4000000"  # ~9 km del anterior


def url_ficha(lat=LAT, lng=LNG, nombre="Sintetico", fid="0xAAAA:0xBBBB", pin=None):
    plat, plng = pin or (lat, lng)  # `@` = centro de la vista; el pin va en !8m2!3d!4d
    return (f"https://www.google.com/maps/place/{nombre}/@{lat},{lng},17z/data=!3m1!4b1!4m6!3m5!1s{fid}"
            f"!8m2!3d{plat}!4d{plng}!16s%2Fg%2F1abc")


def src_embed(lat=LAT, lng=LNG, fid="0xAAAA%3A0xBBBB"):
    return (f"https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d1000!2d{lng}!3d{lat}!2m3!1f0!2f0!3f0!3m2!1i1024"
            f"!2i768!4f13.1!3m3!1m2!1s{fid}!2sSintetico!5e0!3m2!1ses!2spe!4v1")


def iframe(lat=LAT, lng=LNG, fid="0xAAAA%3A0xBBBB"):
    return (f'<iframe src="{src_embed(lat, lng, fid)}" width="600" height="450" style="border:0;" allowfullscreen="" '
            'loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe>')


class ValidarEmbedTests(SimpleTestCase):
    def test_iframe_de_google_es_valido(self):
        self.assertEqual(m.validar_embed(iframe()), (src_embed(), ""))

    def test_url_directa_y_entidades_html(self):
        self.assertEqual(m.validar_embed(src_embed().replace("&", "&amp;"))[1], "")
        src, error = m.validar_embed(f'<iframe src="{src_embed()}&amp;hl=es"></iframe>')
        self.assertEqual((src, error), (src_embed() + "&hl=es", ""))

    def test_vacio_no_es_error(self):
        self.assertEqual(m.validar_embed("  "), ("", ""))

    def test_rechaza_origenes_y_esquemas_inseguros(self):
        for malo in (
            "http://www.google.com/maps/embed?pb=1",
            "javascript:alert(1)",
            "https://www.google.com.evil.com/maps/embed?pb=1",
            "https://evil.com/maps/embed?pb=1",
            "https://google.com@evil.com/maps/embed?pb=1",
            "https://www.google.com:8443/maps/embed?pb=1",
            "https://www.google.com/search?q=x",
            "https://www.google.com/maps/embed?pb=1 onload=x",
            f'<iframe src="javascript:alert(1)"></iframe>',
            '<iframe src="http://www.google.com/maps/embed?pb=1"></iframe>',
            '<iframe src="https://evil.com/maps/embed?pb=1"></iframe>',
        ):
            self.assertNotEqual(m.validar_embed(malo)[1], "", malo)

    def test_rechaza_atributos_y_contenido_no_autorizados(self):
        base = src_embed()
        for malo in (
            f'<iframe src="{base}" onload="alert(1)"></iframe>',
            f'<iframe src="{base}" srcdoc="<script>1</script>"></iframe>',
            f'<iframe src="{base}" sandbox=""></iframe>',
            f'<iframe src="{base}" src="{base}"></iframe>',
            f'<iframe src="{base}"></iframe><iframe src="{base}"></iframe>',
            f'<iframe src="{base}"></iframe><script>alert(1)</script>',
            f'<div><iframe src="{base}"></iframe></div>',
            f'<iframe src="{base}">texto</iframe>',
        ):
            self.assertNotEqual(m.validar_embed(malo)[1], "", malo)

    def test_iframe_canonico_solo_lleva_atributos_permitidos(self):
        canonico = m.iframe_canonico(src_embed())
        self.assertEqual(m.validar_embed(canonico)[0], src_embed())
        self.assertNotIn("onload", canonico)


class ValidarMapsUrlTests(SimpleTestCase):
    def test_urls_validas(self):
        self.assertEqual(m.validar_maps_url(url_ficha())[1:], ("larga", ""))
        self.assertEqual(m.validar_maps_url("https://www.google.com.pe/maps/place/X")[1], "larga")
        self.assertEqual(m.validar_maps_url("https://maps.app.goo.gl/AbC123")[1], "corta")
        self.assertEqual(m.validar_maps_url("https://goo.gl/maps/AbC123")[1], "corta")
        self.assertEqual(m.validar_maps_url("")[1:], ("", ""))

    def test_rechazos(self):
        for malo in (
            "http://www.google.com/maps/place/X",
            "javascript:alert(1)",
            "https://www.google.com/search?q=x",
            "https://maps.google.com.evil.com/maps",
            "https://evil.com/maps/place/X",
            "https://google.com@evil.com/maps/place/X",
            "https://goo.gl/otra-cosa",
            "https://maps.app.goo.gl/",
            "https://www.google.com/maps/place/X con espacios",
            '<a href="https://www.google.com/maps">x</a>',
        ):
            self.assertNotEqual(m.validar_maps_url(malo)[2], "", malo)

    def test_entidades_html_se_deshacen(self):
        self.assertEqual(m.validar_maps_url("https://www.google.com/maps?q=a&amp;b=c")[0], "https://www.google.com/maps?q=a&b=c")


class ExtraccionTests(SimpleTestCase):
    def test_pin_solo_con_estructura_8m2(self):
        self.assertEqual(m.pin_de_ficha(url_ficha()), (LAT, LNG))

    def test_3d4d_sueltos_y_arroba_no_son_pin(self):
        self.assertIsNone(m.pin_de_ficha(f"https://www.google.com/maps/place/X/@{LAT},{LNG},17z/data=!3d{LAT}!4d{LNG}"))
        self.assertIsNone(m.pin_de_ficha(f"https://www.google.com/maps/@{LAT},{LNG},15z"))

    def test_rango_invalido_se_descarta(self):
        self.assertIsNone(m.pin_de_ficha("https://www.google.com/maps/place/X/data=!8m2!3d-95.1234!4d-2.3456"))

    def test_centro_de_iframe_orden_lat_lng(self):
        self.assertEqual(m.centro_de_iframe(src_embed()), (LAT, LNG))
        self.assertIsNone(m.centro_de_iframe("https://www.google.com/maps/embed?pb=sin-datos"))

    def test_place_id_solo_formato_chij(self):
        self.assertEqual(m.place_id_de_url("https://www.google.com/maps/search/?api=1&query=x&query_place_id=ChIJabcdefghijk123"),
                         "ChIJabcdefghijk123")
        self.assertIsNone(m.place_id_de_url("https://www.google.com/maps/search/?api=1&query_place_id=0x1234:0x5678"))

    def test_feature_id_igual_con_o_sin_codificar_y_cero_es_ausente(self):
        self.assertEqual(m.feature_id(url_ficha()), m.feature_id(src_embed()))
        self.assertIsNone(m.feature_id(url_ficha(fid="0x0:0x0")))
        self.assertIsNone(m.feature_id("https://www.google.com/maps/place/X/data=!1sBanco+de+la+Nacion!8m2!3d-1.1!4d-2.2"))

    def test_distancia(self):
        self.assertLess(m.distancia_m((LAT, LNG), (LAT, LNG)), 1)
        self.assertGreater(m.distancia_m((LAT, LNG), (LAT2, LNG2)), 5000)


class ResolverMapaTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Bancos", slug="bancos")
        cls.entidad = ServicioTurista.objects.create(categoria_principal=cls.categoria, nombre="Banco Sintético", slug="banco-sintetico")

    def sede(self, **kw):
        kw.setdefault("direccion", "Jr. Prueba 100")
        return agregar_sede(self.entidad, self.distrito_huanuco, nombre=f"S{SedeServicioTurista.objects.count()}", **kw)

    def test_solo_direccion_es_aproximada_y_se_dice(self):
        r = m.resolver_mapa(self.sede())
        self.assertEqual(r["fuentes"], {"embed": "direccion_aproximada", "open": "direccion_aproximada", "route": "direccion_aproximada"})
        self.assertEqual(r["estado"], "aproximado")
        self.assertTrue(any("Solo hay dirección" in a for a in r["avisos"]))

    def test_sin_datos_no_hay_mapa(self):
        self.assertFalse(m.resolver_mapa(self.sede(direccion=""))["hay_mapa"])

    def test_solo_maps_url_con_pin_es_completo(self):
        r = m.resolver_mapa(self.sede(maps_url=url_ficha()))
        self.assertEqual(r["fuentes"], {"embed": "pin_ficha", "open": "ficha_admin", "route": "pin_ficha"})
        self.assertEqual(r["open_url"], url_ficha())
        self.assertIn(f"destination={LAT}%2C{LNG}", r["route_url"])
        self.assertEqual(r["estado"], "completo")

    def test_solo_iframe_ficha_en_el_mapa_y_referencia_honesta(self):
        r = m.resolver_mapa(self.sede(embed_maps=iframe()))
        self.assertEqual(r["embed_url"], src_embed())
        self.assertEqual(r["fuentes"], {"embed": "ficha_admin", "open": "referencial", "route": "referencial"})
        self.assertEqual(r["estado"], "parcial")
        self.assertTrue(any("Solo hay código de inserción" in a for a in r["avisos"]))

    def test_iframe_y_url_coherentes(self):
        r = m.resolver_mapa(self.sede(maps_url=url_ficha(), embed_maps=iframe()))
        self.assertEqual((r["estado"], r["precision"], r["conflicto"]), ("completo", "pin_ficha", False))
        self.assertEqual(r["embed_url"], src_embed())
        self.assertEqual(r["open_url"], url_ficha())

    def test_arroba_y_3d4d_sueltos_no_generan_ruta_exacta(self):
        url = f"https://www.google.com/maps/place/X/@{LAT},{LNG},17z/data=!3d{LAT}!4d{LNG}"
        r = m.resolver_mapa(self.sede(maps_url=url))
        self.assertEqual(r["fuentes"]["route"], "no_determinable")
        self.assertNotIn(LAT, r["route_url"].replace(url, ""))  # no se construyó destino con esas coordenadas
        self.assertTrue(r["route_url"].startswith(url))
        self.assertIn("?", r["route_url"])  # el JS añade &travelmode=...
        self.assertEqual(r["estado"], "parcial")

    def test_enlace_corto_se_abre_pero_la_ruta_no_es_exacta(self):
        r = m.resolver_mapa(self.sede(maps_url="https://maps.app.goo.gl/AbC123"))
        self.assertEqual(r["open_url"], "https://maps.app.goo.gl/AbC123")
        self.assertEqual(r["fuentes"]["route"], "no_determinable")
        self.assertIsNone(r["pin_ficha"])
        self.assertTrue(any("Enlace corto" in a for a in r["avisos"]))

    def test_coordenadas_del_admin_dan_ruta_exacta(self):
        from decimal import Decimal
        r = m.resolver_mapa(self.sede(latitud=Decimal(LAT), longitud=Decimal(LNG)))
        self.assertEqual(r["fuentes"], {"embed": "pin_admin", "open": "pin_admin", "route": "pin_admin"})
        self.assertEqual(r["estado"], "completo")

    def test_coordenadas_del_admin_con_ficha_coherente(self):
        from decimal import Decimal
        r = m.resolver_mapa(self.sede(maps_url=url_ficha(), latitud=Decimal(LAT), longitud=Decimal(LNG)))
        self.assertFalse(r["conflicto"])
        self.assertEqual(r["fuentes"]["route"], "pin_admin")

    def test_discrepancia_pin_vs_coordenadas_exige_revision_y_no_elige(self):
        from decimal import Decimal
        r = m.resolver_mapa(self.sede(maps_url=url_ficha(), latitud=Decimal(LAT2), longitud=Decimal(LNG2)))
        self.assertTrue(r["conflicto"])
        self.assertEqual(r["estado"], "conflicto")
        self.assertEqual(r["fuentes"]["route"], "no_determinable")  # abre la ficha, sin escoger una coordenada
        self.assertNotIn("destination=-1.3", r["route_url"])

    def test_iframe_de_otra_ficha_es_conflicto_aunque_este_cerca(self):
        r = m.resolver_mapa(self.sede(maps_url=url_ficha(), embed_maps=iframe(fid="0xCCCC%3A0xDDDD")))
        self.assertEqual((r["estado"], r["conflicto"], r["misma_ficha"]), ("conflicto", True, False))
        self.assertTrue(any("fichas distintas" in a for a in r["avisos"]))

    def test_misma_ficha_con_centro_de_vista_lejos_del_pin_no_es_conflicto(self):
        # Caso real observado: el centro del iframe (vista) quedó a ~520 m del pin de la ficha.
        lat_vista, lng_vista = "-1.2345678", "-2.3410000"
        r = m.resolver_mapa(self.sede(
            maps_url=url_ficha(lat_vista, lng_vista, pin=(LAT, LNG)), embed_maps=iframe(lat_vista, lng_vista),
        ))
        self.assertGreater(m.distancia_m(m.centro_de_iframe(src_embed(lat_vista, lng_vista)), (LAT, LNG)), 500)
        self.assertEqual((r["estado"], r["conflicto"], r["misma_ficha"]), ("completo", False, True))
        self.assertEqual(r["fuentes"], {"embed": "ficha_admin", "open": "ficha_admin", "route": "pin_ficha"})
        self.assertIn(f"destination={LAT}%2C{LNG}", r["route_url"])  # ruta al pin, no al centro de la vista

    def test_sin_identificador_solo_discrepancias_enormes_son_conflicto(self):
        sin_fid = "0x0%3A0x0"
        lejos = m.resolver_mapa(self.sede(maps_url=url_ficha(fid="0x0:0x0"), embed_maps=iframe("-5.0", "-70.0", fid=sin_fid)))
        self.assertTrue(lejos["conflicto"])
        cerca = m.resolver_mapa(self.sede(maps_url=url_ficha(fid="0x0:0x0"), embed_maps=iframe(LAT, "-2.3410000", fid=sin_fid)))
        self.assertFalse(cerca["conflicto"])

    def test_entradas_invalidas_se_ignoran_con_aviso_y_no_llegan_a_los_enlaces(self):
        r = m.resolver_mapa(self.sede(maps_url="javascript:alert(1)", embed_maps="<iframe src='javascript:alert(1)'></iframe>"))
        self.assertEqual(r["fuentes"]["embed"], "direccion_aproximada")
        self.assertNotIn("javascript", r["embed_url"] + r["open_url"] + r["route_url"])
        self.assertEqual(sum("ignorad" in a for a in r["avisos"]), 2)

    def test_place_id_documentado_para_la_ruta(self):
        url = "https://www.google.com/maps/search/?api=1&query=x&query_place_id=ChIJabcdefghijk123"
        r = m.resolver_mapa(self.sede(maps_url=url))
        self.assertEqual(r["fuentes"]["route"], "place_id")
        self.assertIn("destination_place_id=ChIJabcdefghijk123", r["route_url"])

    def test_dos_sedes_misma_direccion_fichas_distintas(self):
        a = self.sede(direccion="Plaza Principal 1", maps_url=url_ficha(LAT, LNG), embed_maps=iframe(LAT, LNG))
        b = self.sede(direccion="Plaza Principal 1 ", maps_url=url_ficha(LAT2, LNG2), embed_maps=iframe(LAT2, LNG2))
        ra, rb = m.resolver_mapa(a), m.resolver_mapa(b)
        self.assertNotEqual(ra["embed_url"], rb["embed_url"])
        self.assertNotEqual(ra["open_url"], rb["open_url"])
        self.assertNotEqual(ra["route_url"], rb["route_url"])
        self.assertIn(f"{LAT2}%2C{LNG2}", rb["route_url"])


class MapaEnModeloYVistaTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Bancos", slug="bancos")
        cls.entidad = ServicioTurista.objects.create(categoria_principal=cls.categoria, nombre="Banco Sintético", slug="banco-sintetico")

    def test_clean_normaliza_el_iframe_y_rechaza_lo_inseguro(self):
        sede = SedeServicioTurista(servicio=self.entidad, distrito=self.distrito_huanuco)
        sede.embed_maps = iframe() + "  "
        sede.full_clean()
        self.assertEqual(sede.embed_maps, m.iframe_canonico(src_embed()))
        sede.embed_maps = '<iframe src="https://evil.com/maps/embed"></iframe>'
        with self.assertRaises(ValidationError) as ctx:
            sede.full_clean()
        self.assertIn("embed_maps", ctx.exception.message_dict)
        sede.embed_maps, sede.maps_url = "", "javascript:alert(1)"
        with self.assertRaises(ValidationError) as ctx:
            sede.full_clean()
        self.assertIn("maps_url", ctx.exception.message_dict)

    def test_tarjeta_usa_los_enlaces_de_su_propia_sede(self):
        a = agregar_sede(self.entidad, self.distrito_huanuco, nombre="Uno", direccion="Misma 1", maps_url=url_ficha(LAT, LNG))
        b = agregar_sede(self.entidad, self.distrito_huanuco, nombre="Dos", direccion="Misma 1", maps_url=url_ficha(LAT2, LNG2))
        sin = agregar_sede(self.entidad, self.distrito_huanuco, nombre="Tres")
        response = self.client.get(reverse("servicios_turista:servicios_utiles"))
        tarjetas = {t["id"]: t for t in response.context["tarjetas"]}
        self.assertEqual(tarjetas[a.id]["mapa"]["open_url"], url_ficha(LAT, LNG))
        self.assertEqual(tarjetas[b.id]["mapa"]["open_url"], url_ficha(LAT2, LNG2))
        self.assertEqual(tarjetas[b.id]["mapa"]["precision"], "pin_ficha")
        self.assertIsNone(tarjetas[sin.id]["mapa"])
        self.assertContains(response, f'data-open-url="{url_ficha(LAT2, LNG2)}"')

    def test_el_html_nunca_recibe_un_iframe_ni_url_inseguros(self):
        sede = agregar_sede(self.entidad, self.distrito_huanuco, nombre="Mal", direccion="Jr. X 1",
                            embed_maps='<iframe src="javascript:alert(1)"></iframe>', maps_url="javascript:alert(1)")
        response = self.client.get(reverse("servicios_turista:servicios_utiles"))
        self.assertNotContains(response, "javascript:alert")
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == sede.id)
        self.assertEqual(tarjeta["mapa"]["precision"], "direccion_aproximada")


class MapasEnAdminTests(AdminSedeMixin, TestCase):
    """El Admin ya no muestra el diagnóstico «Comprobación del mapa», pero sigue rechazando con
    errores claros lo inseguro o contradictorio (nunca un éxito silencioso)."""

    def test_no_hay_comprobacion_del_mapa_en_la_ficha(self):
        s = self.nueva(maps_url=url_ficha(), embed_maps=iframe())
        html = self.client.get(f"/admin/servicios_turista/sedeservicioturista/{s.pk}/change/").content.decode()
        for texto in ("Comprobación del mapa", "Ubicación completa", "Ficha indicada por el administrador", "(probar", "corresponden a la misma ficha"):
            self.assertNotIn(texto, html)
        self.assertIn('name="maps_url"', html)
        self.assertIn('name="embed_maps"', html)

    def test_campos_de_maps_con_ayuda_breve_y_area_amplia(self):
        s = self.nueva()
        html = self.client.get(f"/admin/servicios_turista/sedeservicioturista/{s.pk}/change/").content.decode()
        self.assertIn("URL de la ficha de Google Maps", html)
        self.assertIn("Código de inserción (iframe)", html)
        self.assertIn('rows="6"', html)

    def test_guardar_url_e_iframe_validos_los_almacena_normalizados(self):
        s = self.nueva()
        r = self.post(s, maps_url=url_ficha(), embed_maps=iframe())
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual(s.maps_url, url_ficha())
        self.assertEqual(s.embed_maps, m.iframe_canonico(src_embed()))
        self.assertEqual(m.resolver_mapa(s)["estado"], "completo")

    def test_enlace_inseguro_se_rechaza_con_mensaje_claro(self):
        s = self.nueva(maps_url=url_ficha())
        for malo in ("javascript:alert(1)", "http://www.google.com/maps/place/X", "https://evil.com/maps/place/X"):
            r = self.post(s, maps_url=malo)
            self.assertEqual(r.status_code, 200, malo)
            self.assertIn("enlace https de Google Maps", self.errores(r))
            s.refresh_from_db()
            self.assertEqual(s.maps_url, url_ficha())  # no se sobrescribe lo ya guardado

    def test_iframe_invalido_se_rechaza_con_mensaje_claro(self):
        s = self.nueva(embed_maps=iframe())
        previo = SedeServicioTurista.objects.get(pk=s.pk).embed_maps
        for malo in ('<iframe src="https://evil.com/maps/embed?pb=1"></iframe>',
                     f'<iframe src="{src_embed()}" onload="alert(1)"></iframe>',
                     f'<iframe src="{src_embed()}"></iframe><script>alert(1)</script>'):
            r = self.post(s, embed_maps=malo)
            self.assertEqual(r.status_code, 200, malo)
            errores = self.errores(r)
            self.assertTrue(any(t in errores for t in ("URL https://www.google.com/maps/embed", "atributos no permitidos", "únicamente")), errores)
            s.refresh_from_db()
            self.assertEqual(s.embed_maps, previo)

    def test_contradiccion_url_vs_iframe_bloquea_el_guardado(self):
        s = self.nueva()
        r = self.post(s, maps_url=url_ficha(), embed_maps=iframe(fid="0xCCCC%3A0xDDDD"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("fichas distintas", self.errores(r))
        s.refresh_from_db()
        self.assertEqual((s.maps_url, s.embed_maps), ("", ""))

    def test_contradiccion_pin_vs_coordenadas_bloquea_el_guardado(self):
        s = self.nueva()
        r = self.post(s, maps_url=url_ficha(), latitud=LAT2, longitud=LNG2)
        self.assertEqual(r.status_code, 200)
        self.assertIn("apuntan a lugares distintos", self.errores(r))

    def test_misma_ficha_con_centro_de_vista_lejos_se_guarda(self):
        s = self.nueva()
        lat_v, lng_v = "-1.2345678", "-2.3410000"
        r = self.post(s, maps_url=url_ficha(lat_v, lng_v, pin=(LAT, LNG)), embed_maps=iframe(lat_v, lng_v))
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))

    def test_dos_sedes_con_fichas_distintas_conservan_su_precision(self):
        a, b = self.nueva(direccion="Plaza Principal 1"), self.nueva(direccion="Plaza Principal 1-A")
        self.assertEqual(self.post(a, maps_url=url_ficha(LAT, LNG, fid="0xAAAA:0xBBBB"), embed_maps=iframe(LAT, LNG)).status_code, 302)
        self.assertEqual(self.post(b, maps_url=url_ficha(LAT2, LNG2, fid="0xEEEE:0xFFFF"), embed_maps=iframe(LAT2, LNG2, fid="0xEEEE%3A0xFFFF")).status_code, 302)
        a.refresh_from_db()
        b.refresh_from_db()
        ra, rb = m.resolver_mapa(a), m.resolver_mapa(b)
        self.assertEqual((ra["estado"], rb["estado"]), ("completo", "completo"))
        self.assertIn(f"destination={LAT}%2C{LNG}", ra["route_url"])
        self.assertIn(f"destination={LAT2}%2C{LNG2}", rb["route_url"])
