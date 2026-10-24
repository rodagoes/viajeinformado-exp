import shutil
import subprocess
import unittest
import uuid
from datetime import datetime, timedelta, timezone as tz
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from .models import EventoMetrica, SesionMetrica, VisitanteMetrica
from .services import real
from .test_real_seguimiento import PAGINA, UA_CHROME_WIN

ACTIVO = override_settings(METRICAS_REAL_HABILITADAS=True)
URL = "/metricas/duracion/"
T0 = datetime(2026, 10, 21, 15, 0, tzinfo=tz.utc)


def en(segundos):
    return mock.patch.object(real, "ahora", return_value=T0 + timedelta(seconds=segundos))


@ACTIVO
class EndpointDuracionTests(TestCase):
    def setUp(self):
        self.c = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
        with en(0):
            self.c.get(PAGINA)  # crea visitante y sesión; la sesión empieza en T0

    def enviar(self, valor, cliente=None, momento=None, **extra):
        cliente = cliente or self.c
        datos = {"segundos": valor, **extra}
        token = cliente.cookies.get("csrftoken")
        if "csrfmiddlewaretoken" not in datos and token:
            datos["csrfmiddlewaretoken"] = getattr(token, "value", token)
        if momento is None:
            return cliente.post(URL, datos)
        with en(momento):
            return cliente.post(URL, datos)

    def sesion(self):
        return SesionMetrica.objects.get()

    def copiar_cookies(self, destino):
        for nombre, morsel in self.c.cookies.items():
            destino.cookies[nombre] = morsel.value

    # ---- caso normal
    def test_heartbeat_normal_suma_tiempo_visible_y_mueve_fin(self):
        r = self.enviar(30, momento=30)
        s = self.sesion()
        self.assertEqual((r.status_code, r.content), (204, b""))
        self.assertEqual((s.duracion_seg, s.fin, s.paginas_vistas), (30, T0 + timedelta(seconds=30), 1))
        self.assertEqual(r.cookies["vi_sid"]["max-age"], 1800)  # actividad: renueva la cookie de la sesión

    def test_heartbeats_sucesivos_se_acumulan(self):
        for momento in (30, 60, 90):
            self.assertEqual(self.enviar(30, momento=momento).status_code, 204)
        self.assertEqual(self.sesion().duracion_seg, 90)

    def test_valores_limite_validos(self):
        self.assertEqual(self.enviar(1, momento=100).status_code, 204)
        self.assertEqual(self.enviar(60, momento=200).status_code, 204)
        self.assertEqual(self.sesion().duracion_seg, 61)

    # ---- protección contra inflación
    def test_el_incremento_se_acota_al_tiempo_real_transcurrido(self):
        self.enviar(60, momento=10)  # solo han pasado 10 s desde el inicio de la sesión
        self.assertEqual(self.sesion().duracion_seg, 10)

    def test_doble_envio_inmediato_no_infla(self):
        self.enviar(30, momento=30)
        self.enviar(30, momento=30)  # el mismo tramo reenviado: el reloj real no lo permite
        self.enviar(30, momento=30)
        self.assertEqual(self.sesion().duracion_seg, 30)

    def test_rafaga_de_envios_nunca_supera_el_reloj(self):
        for _ in range(20):
            self.enviar(60, momento=45)
        self.assertEqual(self.sesion().duracion_seg, 45)

    def test_tope_absoluto_por_sesion(self):
        with mock.patch.object(real, "MAX_DURACION_SESION_SEG", 100):
            self.enviar(60, momento=1000)
            self.enviar(60, momento=1000)
            self.enviar(60, momento=1000)
        self.assertEqual(self.sesion().duracion_seg, 100)

    def test_la_duracion_nunca_decrece(self):
        SesionMetrica.objects.update(duracion_seg=500)  # p. ej. un valor previo mayor que el reloj actual
        self.enviar(30, momento=100)
        self.assertEqual(self.sesion().duracion_seg, 500)

    def test_el_tiempo_oculto_no_se_suma_porque_el_cliente_no_lo_reporta(self):
        self.enviar(30, momento=30)
        self.enviar(20, momento=1800 - 1)  # 29 min después, el navegador solo reportó 20 s con la pestaña visible
        self.assertEqual(self.sesion().duracion_seg, 50)  # 30 + 20 visibles, no ~1800 s de reloj

    # ---- valores inválidos
    def test_valores_invalidos_se_rechazan_sin_modificar_nada(self):
        for valor in ("0", "-5", "61", "1000", "abc", "", "30.5", " 30", "1e2", "٣٠", "+30"):
            with self.subTest(valor=valor):
                r = self.enviar(valor, momento=30)
                self.assertEqual((r.status_code, r.json()), (400, {"ok": False}))
        r = self.c.post(URL, {"csrfmiddlewaretoken": self.c.cookies["csrftoken"].value})
        self.assertEqual(r.status_code, 400)  # sin `segundos`
        self.assertEqual(self.sesion().duracion_seg, 0)

    def test_el_cliente_no_puede_enviar_marcas_de_tiempo_ni_ids(self):
        self.enviar(30, momento=30, fin="2030-01-01T00:00:00Z", sesion=str(uuid.uuid4()), duracion_seg=99999, inicio="2000-01-01")
        s = self.sesion()
        self.assertEqual((s.duracion_seg, s.fin), (30, T0 + timedelta(seconds=30)))

    # ---- sesión / visitante
    def test_sin_visitante_o_con_cookies_invalidas_responde_410_y_no_crea_nada(self):
        antes = (VisitanteMetrica.objects.count(), SesionMetrica.objects.count())
        sin_cookies = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
        sin_cookies.cookies["csrftoken"] = "x" * 32
        for cliente in (sin_cookies,):
            r = cliente.post(URL, {"segundos": 30, "csrfmiddlewaretoken": "x" * 32})
            self.assertEqual(r.status_code, 410)
            self.assertNotIn("vi_vid", r.cookies)
            self.assertNotIn("vi_sid", r.cookies)
        for nombre, valor in (("vi_vid", "no-uuid"), ("vi_vid", str(uuid.uuid4())), ("vi_sid", "no-uuid"), ("vi_sid", str(uuid.uuid4()))):
            with self.subTest(cookie=nombre, valor=valor):
                cliente = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
                self.copiar_cookies(cliente)
                cliente.cookies[nombre] = valor
                self.assertEqual(self.enviar(30, cliente=cliente, momento=30).status_code, 410)
        self.assertEqual((VisitanteMetrica.objects.count(), SesionMetrica.objects.count()), antes)
        self.assertEqual(self.sesion().duracion_seg, 0)

    def test_sesion_de_otro_visitante_no_se_usa(self):
        otro = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
        with en(0):
            otro.get(PAGINA)
        mezclado = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
        mezclado.cookies["vi_vid"] = self.c.cookies["vi_vid"].value
        mezclado.cookies["vi_sid"] = otro.cookies["vi_sid"].value
        mezclado.cookies["csrftoken"] = self.c.cookies["csrftoken"].value
        r = mezclado.post(URL, {"segundos": 30, "csrfmiddlewaretoken": self.c.cookies["csrftoken"].value})
        self.assertEqual(r.status_code, 410)
        self.assertEqual(list(SesionMetrica.objects.values_list("duracion_seg", flat=True)), [0, 0])

    def test_sesion_expirada_se_ignora_no_se_revive_ni_se_crea_otra(self):
        r = self.enviar(30, momento=31 * 60)  # 31 min después del único hit
        self.assertEqual(r.status_code, 410)
        self.assertNotIn("vi_sid", r.cookies)  # no renueva la cookie de una sesión muerta
        s = self.sesion()
        self.assertEqual((SesionMetrica.objects.count(), s.duracion_seg, s.fin), (1, 0, T0))
        with en(31 * 60 + 5):  # la siguiente navegación normal sí abre una sesión nueva
            self.c.get("/terminos/")
        self.assertEqual(SesionMetrica.objects.count(), 2)

    def test_no_crea_paginas_vistas(self):
        self.enviar(30, momento=30)
        self.assertEqual(self.sesion().paginas_vistas, 1)

    def test_eventos_y_heartbeat_no_se_duplican(self):
        with en(20):
            real.registrar_evento_real(self._peticion(), "idioma_cambiado")
        self.enviar(30, momento=40)
        s = self.sesion()
        self.assertEqual((s.duracion_seg, s.fin, EventoMetrica.objects.count()), (30, T0 + timedelta(seconds=40), 1))

    def _peticion(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        p = RequestFactory().post("/x/", HTTP_USER_AGENT=UA_CHROME_WIN)
        p.user = AnonymousUser()
        p.COOKIES = {k: m.value for k, m in self.c.cookies.items()}
        return p

    # ---- apagado, staff, bots
    def test_flag_apagado_staff_y_bots_se_ignoran(self):
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            self.assertEqual(self.enviar(30, momento=30).status_code, 204)
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        logueado = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
        self.copiar_cookies(logueado)
        logueado.force_login(staff)
        self.assertEqual(self.enviar(30, cliente=logueado, momento=30).status_code, 204)
        bot = Client(HTTP_USER_AGENT="Googlebot/2.1")
        self.copiar_cookies(bot)
        self.assertEqual(self.enviar(30, cliente=bot, momento=30).status_code, 204)
        self.assertEqual(self.sesion().duracion_seg, 0)

    # ---- CSRF y método
    def test_csrf_obligatorio_sin_csrf_exempt(self):
        c = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)
        with en(0):
            c.get(PAGINA)
        self.assertEqual(c.post(URL, {"segundos": 30}).status_code, 403)
        self.assertEqual(c.post(URL, {"segundos": 30, "csrfmiddlewaretoken": "falso"}).status_code, 403)
        token = c.cookies["csrftoken"].value
        with en(30):
            self.assertEqual(c.post(URL, {"segundos": 30, "csrfmiddlewaretoken": token}).status_code, 204)
            self.assertEqual(c.post(URL, {"segundos": 5}, HTTP_X_CSRFTOKEN=token).status_code, 204)  # fallback fetch
        self.assertEqual(SesionMetrica.objects.get(visitante__uuid=c.cookies["vi_vid"].value).duracion_seg, 30)

    def test_solo_post(self):
        for metodo in (self.c.get, self.c.put, self.c.delete):
            self.assertEqual(metodo(URL).status_code, 405)

    # ---- resiliencia
    def test_un_fallo_no_rompe_la_navegacion_ni_detiene_al_cliente(self):
        with mock.patch("apps.metricas.views.registrar_tiempo_visible", side_effect=RuntimeError("bd caída")):
            with self.assertLogs("apps.metricas.views", level="ERROR"):
                r = self.enviar(30, momento=30)
        self.assertEqual(r.status_code, 204)

    def test_consultas_por_heartbeat(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.enviar(30, momento=30)
        consultas = [q["sql"] for q in ctx.captured_queries if not q["sql"].startswith(("SAVEPOINT", "RELEASE SAVEPOINT"))]
        self.assertEqual(len(consultas), 3, consultas)  # leer visitante, leer sesión y un UPDATE atómico
        self.assertTrue(consultas[-1].startswith("UPDATE"))

    def test_la_ruta_no_cuenta_como_pagina_vista(self):
        self.enviar(30, momento=30)
        self.c.get(URL)  # 405, no HTML
        self.assertEqual(self.sesion().paginas_vistas, 1)


@ACTIVO
class PlantillaDuracionTests(TestCase):
    def test_script_declara_el_endpoint_de_duracion_solo_si_el_seguimiento_esta_activo(self):
        html = self.client.get(PAGINA).content.decode()
        self.assertIn('data-duracion="/metricas/duracion/"', html)
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            self.assertNotIn("data-duracion", self.client.get(PAGINA).content.decode())
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        c = Client()
        c.force_login(staff)
        self.assertNotIn("data-duracion", c.get(PAGINA).content.decode())


class ContratoMetricasJsTests(TestCase):
    """metricas.js suma el tiempo visible sin duplicar ni alterar la lógica de clics de la Fase F."""

    def setUp(self):
        self.js = (settings.BASE_DIR / "static/assets/js/metricas.js").read_text(encoding="utf-8")

    def test_la_logica_de_clics_de_la_fase_f_no_se_duplica(self):
        self.assertEqual(self.js.count("document.addEventListener('click', alHacerClic)"), 1)
        self.assertEqual(self.js.count("function enviar(datos)"), 1)
        self.assertEqual(self.js.count("function registrar(evento, opciones)"), 1)
        self.assertNotIn("'/metricas/", self.js)  # los endpoints llegan por data-* desde la plantilla, no fijos en el JS

    def test_senales_del_navegador_previstas(self):
        for requerido in ("visibilitychange", "pagehide", "setInterval", "HEARTBEAT_MS = 30000", "MAX_ENVIO_S = 60",
                          "INACTIVIDAD_MS", "script.dataset.duracion", "respuesta.status === 410", "sendBeacon", "keepalive"):
            self.assertIn(requerido, self.js)
        self.assertNotIn("addEventListener('beforeunload'", self.js)  # no es el mecanismo de cierre
        self.assertNotIn("preventDefault", self.js)

    def test_no_se_envian_marcas_de_tiempo_ni_ids(self):
        envio = self.js[self.js.index("function enviarTiempo"):self.js.index("function alInteractuar")]
        self.assertIn("segundos: String(segundos)", envio)
        for prohibido in ("Date.now()", "toISOString", "getTime", "sesion", "uuid"):
            self.assertNotIn(prohibido, envio.replace("acumular(Date.now())", ""))


@unittest.skipUnless(shutil.which("node"), "Node no está instalado: se omiten las pruebas de comportamiento de JavaScript")
class JsDuracionNodeTests(TestCase):
    def test_tiempo_visible(self):
        resultado = subprocess.run(
            ["node", "apps/metricas/tests_js/duracion.test.js"], cwd=settings.BASE_DIR, capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("OK 12 pruebas", resultado.stdout)
