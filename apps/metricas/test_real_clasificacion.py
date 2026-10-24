from django.test import SimpleTestCase

from .choices import DispositivoAcceso as D
from .choices import FuenteTrafico as F
from .services.clasificacion import clasificar_dispositivo, clasificar_fuente, es_bot

UA_CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
UA_ANDROID_MOVIL = "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
UA_ANDROID_TABLET = "Mozilla/5.0 (Linux; Android 13; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
UA_IPAD = "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
HOST = "viajeinformado.digital"


class BotsTests(SimpleTestCase):
    def test_agentes_automatizados(self):
        for ua in (
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "bingbot/2.0",
            "Mozilla/5.0 (compatible; Yahoo! Slurp)", "curl/8.4.0", "Wget/1.21", "SomeSpider/1.0",
            "Mozilla/5.0 HeadlessChrome/126", "AhrefsCrawler",
        ):
            self.assertTrue(es_bot(ua), ua)

    def test_navegadores_normales_y_ua_vacio(self):
        for ua in (UA_CHROME_WIN, UA_IPHONE, UA_ANDROID_MOVIL, UA_IPAD, "", None):
            self.assertFalse(es_bot(ua), ua)


class DispositivoTests(SimpleTestCase):
    def test_categorias(self):
        self.assertEqual(clasificar_dispositivo(UA_IPHONE), D.MOVIL)
        self.assertEqual(clasificar_dispositivo(UA_ANDROID_MOVIL), D.MOVIL)
        self.assertEqual(clasificar_dispositivo(UA_IPAD), D.TABLET)
        self.assertEqual(clasificar_dispositivo(UA_ANDROID_TABLET), D.TABLET)
        self.assertEqual(clasificar_dispositivo(UA_CHROME_WIN), D.ESCRITORIO)
        self.assertEqual(clasificar_dispositivo("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605"), D.ESCRITORIO)

    def test_sin_user_agent_es_escritorio(self):
        self.assertEqual(clasificar_dispositivo(""), D.ESCRITORIO)
        self.assertEqual(clasificar_dispositivo(None), D.ESCRITORIO)


class FuenteTests(SimpleTestCase):
    def fuente(self, referrer="", utm_source="", utm_medium=""):
        return clasificar_fuente(referrer, HOST, utm_source, utm_medium)

    def test_directo_sin_referrer(self):
        self.assertEqual(self.fuente(), (F.DIRECTO, ""))
        self.assertEqual(self.fuente("no es una url"), (F.DIRECTO, ""))

    def test_organico_buscadores(self):
        self.assertEqual(self.fuente("https://www.google.com/search?q=huanuco+turismo"), (F.ORGANICO, "www.google.com"))
        self.assertEqual(self.fuente("https://www.google.com.pe/"), (F.ORGANICO, "www.google.com.pe"))
        self.assertEqual(self.fuente("https://www.bing.com/search?q=x")[0], F.ORGANICO)
        self.assertEqual(self.fuente("https://duckduckgo.com/")[0], F.ORGANICO)

    def test_social(self):
        for url in ("https://l.facebook.com/l.php?u=x", "https://www.instagram.com/", "https://t.co/abc",
                    "https://www.tiktok.com/", "https://api.whatsapp.com/send", "https://wa.me/519"):
            self.assertEqual(self.fuente(url)[0], F.SOCIAL, url)

    def test_referido_otro_sitio_externo(self):
        self.assertEqual(self.fuente("https://blog-de-viajes.pe/huanuco/post"), (F.REFERIDO, "blog-de-viajes.pe"))
        self.assertEqual(self.fuente("https://notgoogle.com/")[0], F.REFERIDO)  # coincidencia por etiqueta exacta

    def test_login_oauth_de_google_no_es_busqueda(self):
        self.assertEqual(self.fuente("https://accounts.google.com/o/oauth2/auth")[0], F.REFERIDO)

    def test_referrer_interno_no_es_adquisicion(self):
        self.assertEqual(self.fuente(f"https://{HOST}/lugares-turisticos/"), (F.DIRECTO, ""))
        self.assertEqual(clasificar_fuente(f"https://{HOST}/x", f"{HOST}:8000"), (F.DIRECTO, ""))

    def test_solo_se_guarda_el_host_nunca_la_url(self):
        _, host = self.fuente("https://www.google.com/search?q=dato+sensible&hl=es#frag")
        self.assertEqual(host, "www.google.com")

    def test_utm_en_memoria(self):
        self.assertEqual(self.fuente(utm_source="facebook", utm_medium="social")[0], F.SOCIAL)
        self.assertEqual(self.fuente(utm_source="instagram")[0], F.SOCIAL)
        self.assertEqual(self.fuente(utm_source="google", utm_medium="cpc")[0], F.OTROS)
        self.assertEqual(self.fuente(utm_source="boletin", utm_medium="email")[0], F.OTROS)
        self.assertEqual(self.fuente(utm_source="google", utm_medium="organic")[0], F.ORGANICO)
        self.assertEqual(self.fuente("https://aliado.pe/", utm_medium="referral"), (F.REFERIDO, "aliado.pe"))
        self.assertEqual(self.fuente(utm_source="algo-raro")[0], F.OTROS)  # UTM sin referrer ni categoría

    def test_utm_no_reconocible_con_referrer_externo_usa_el_referrer(self):
        self.assertEqual(self.fuente("https://www.google.com/", utm_source="x")[0], F.ORGANICO)
