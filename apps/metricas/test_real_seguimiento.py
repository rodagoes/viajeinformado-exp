import json
import uuid
from datetime import datetime, timedelta, timezone as tz
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.chatbot.models import Mensaje
from apps.chatbot.services import chatbot_service, llm_client
from apps.interacciones.models import Favorito
from apps.interacciones.tests import InteraccionesTestBase

from .choices import FuenteTrafico, OrigenDato, TipoInteraccion
from .middleware import MetricasMiddleware
from .models import EventoMetrica, MetricaDiaria, SesionMetrica, VisitanteMetrica
from .services import real
from .test_real_clasificacion import UA_CHROME_WIN, UA_IPAD, UA_IPHONE

ACTIVO = override_settings(METRICAS_REAL_HABILITADAS=True)
PAGINA = "/historia/"
REAL = OrigenDato.REAL
T0 = datetime(2026, 10, 21, 15, 0, tzinfo=tz.utc)  # 10:00 hora de Lima


def consultas(ctx):
    """Consultas del request sin los SAVEPOINT/RELEASE de los atomic() de las pruebas."""
    return [q["sql"] for q in ctx.captured_queries if not q["sql"].startswith(("SAVEPOINT", "RELEASE SAVEPOINT"))]


@ACTIVO
class CookiesYPaginasTests(TestCase):
    def test_flag_apagado_no_registra_nada_ni_pone_cookies(self):
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            r = self.client.get(PAGINA)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((VisitanteMetrica.objects.count(), SesionMetrica.objects.count()), (0, 0))
        self.assertNotIn("vi_vid", r.cookies)
        self.assertNotIn("vi_sid", r.cookies)

    def test_flag_apagado_por_defecto_y_en_produccion(self):
        from django.conf import settings

        configuracion = settings.BASE_DIR / "config" / "settings"
        self.assertIn("METRICAS_REAL_HABILITADAS = False", (configuracion / "base.py").read_text(encoding="utf-8"))
        # producción lo lee de .env y, sin variable, queda apagado (ver test_settings_produccion)
        self.assertIn(
            "METRICAS_REAL_HABILITADAS = env.bool('METRICAS_REAL_HABILITADAS', default=False)",
            (configuracion / "production.py").read_text(encoding="utf-8"))
        self.assertNotIn("METRICAS_REAL_HABILITADAS = True", (configuracion / "production.py").read_text(encoding="utf-8"))

    def test_primera_visita_crea_visitante_sesion_y_cookies(self):
        r = self.client.get(PAGINA, HTTP_USER_AGENT=UA_IPHONE)
        v, s = VisitanteMetrica.objects.get(), SesionMetrica.objects.get()
        self.assertEqual((v.origen, v.es_registrado, v.usuario), (REAL, False, None))
        self.assertEqual(v.primera_visita, timezone.localdate())
        self.assertEqual((s.visitante, s.origen, s.paginas_vistas, s.duracion_seg), (v, REAL, 1, 0))
        self.assertEqual((s.fuente, s.dispositivo, s.idioma, s.es_nueva, s.referrer_host), ("DIRECTO", "MOVIL", "es", True, ""))
        self.assertEqual(s.fecha, timezone.localdate(s.inicio))
        self.assertEqual(s.fin, s.inicio)
        self.assertEqual(r.cookies["vi_vid"].value, str(v.uuid))
        self.assertEqual(r.cookies["vi_sid"].value, str(s.uuid))

    def test_banderas_y_vida_de_las_cookies(self):
        r = self.client.get(PAGINA)
        for nombre, vida in (("vi_vid", 365 * 24 * 3600), ("vi_sid", 1800)):
            c = r.cookies[nombre]
            self.assertTrue(c["httponly"], nombre)
            self.assertEqual(c["samesite"], "Lax")
            self.assertEqual(c["max-age"], vida)
            self.assertEqual(c["path"], "/")
            self.assertTrue(c["secure"], nombre)  # DEBUG=False en los tests
        with override_settings(DEBUG=True):
            r = Client().get(PAGINA)
        self.assertFalse(r.cookies["vi_vid"]["secure"])

    def test_cookies_sin_datos_personales(self):
        r = self.client.get(PAGINA)
        for nombre in ("vi_vid", "vi_sid"):
            uuid.UUID(r.cookies[nombre].value)  # solo un UUID aleatorio

    def test_segunda_pagina_suma_sin_duplicar_y_renueva_cookies(self):
        self.client.get(PAGINA)
        r = self.client.get("/terminos/")
        s = SesionMetrica.objects.get()
        self.assertEqual((VisitanteMetrica.objects.count(), SesionMetrica.objects.count(), s.paginas_vistas), (1, 1, 2))
        self.assertEqual(r.cookies["vi_sid"]["max-age"], 1800)
        self.assertEqual(r.cookies["vi_vid"]["max-age"], 365 * 24 * 3600)
        self.assertGreaterEqual(s.fin, s.inicio)

    def test_los_hits_del_servidor_mueven_fin_pero_no_suman_duracion(self):
        # Fase G: duracion_seg es tiempo visible reportado por el navegador; fin = última actividad conocida.
        with mock.patch.object(real, "ahora", return_value=T0):
            self.client.get(PAGINA)
        with mock.patch.object(real, "ahora", return_value=T0 + timedelta(seconds=125)):
            self.client.get("/terminos/")
        s = SesionMetrica.objects.get()
        self.assertEqual((s.duracion_seg, s.fin, s.paginas_vistas), (0, T0 + timedelta(seconds=125), 2))

    def test_sesion_de_una_pagina_queda_con_duracion_cero(self):
        self.client.get(PAGINA)
        self.assertEqual(SesionMetrica.objects.get().duracion_seg, 0)

    def test_cookie_de_visitante_invalida_o_desconocida_crea_otro_visitante(self):
        for valor in ("abc", "", str(uuid.uuid4())):
            with self.subTest(valor=valor):
                VisitanteMetrica.objects.all().delete()
                cliente = Client()
                cliente.cookies["vi_vid"] = valor
                r = cliente.get(PAGINA)
                v = VisitanteMetrica.objects.get()
                self.assertEqual(r.cookies["vi_vid"].value, str(v.uuid))
                self.assertNotEqual(str(v.uuid), valor)

    def test_visitante_existente_se_reutiliza(self):
        v = VisitanteMetrica.objects.create(origen=REAL, primera_visita=timezone.localdate() - timedelta(days=3))
        cliente = Client()
        cliente.cookies["vi_vid"] = str(v.uuid)
        cliente.get(PAGINA)
        s = SesionMetrica.objects.get()
        self.assertEqual((VisitanteMetrica.objects.count(), s.visitante, s.es_nueva), (1, v, False))

    def test_cookie_de_un_visitante_simulado_o_ga4_no_se_acepta(self):
        # Los hechos detallados son REAL; un uuid ajeno nunca se reutiliza (y VisitanteMetrica solo admite REAL).
        cliente = Client()
        cliente.cookies["vi_vid"] = str(uuid.uuid4())
        cliente.get(PAGINA)
        self.assertEqual(VisitanteMetrica.objects.count(), 1)


@ACTIVO
class SesionTests(TestCase):
    def hit(self, momento, cliente=None, ruta=PAGINA):
        with mock.patch.object(real, "ahora", return_value=momento):
            return (cliente or self.client).get(ruta)

    def test_reutiliza_dentro_de_30_minutos_y_renueva_con_la_actividad(self):
        self.hit(T0)
        self.hit(T0 + timedelta(minutes=20))
        self.hit(T0 + timedelta(minutes=40))  # 20 min después del último hit: sigue la misma sesión
        s = SesionMetrica.objects.get()
        self.assertEqual((SesionMetrica.objects.count(), s.paginas_vistas, s.fin), (1, 3, T0 + timedelta(minutes=40)))
        self.assertEqual(s.duracion_seg, 0)  # sin señales del navegador no hay tiempo visible

    def test_30_minutos_exactos_siguen_en_la_sesion_y_31_no(self):
        self.hit(T0)
        self.hit(T0 + timedelta(minutes=30))
        self.assertEqual(SesionMetrica.objects.count(), 1)
        self.hit(T0 + timedelta(minutes=61))
        self.assertEqual(SesionMetrica.objects.count(), 2)

    def test_sesion_nueva_tras_expirar_mismo_visitante_y_es_nueva(self):
        self.hit(T0)
        self.hit(T0 + timedelta(minutes=45))
        primera, segunda = SesionMetrica.objects.order_by("id")
        self.assertEqual((primera.visitante, segunda.visitante), (VisitanteMetrica.objects.get(),) * 2)
        self.assertNotEqual(primera.uuid, segunda.uuid)
        self.assertEqual((primera.paginas_vistas, segunda.paginas_vistas), (1, 1))
        self.assertTrue(primera.es_nueva)
        self.assertTrue(segunda.es_nueva)  # mismo día que la primera visita del visitante

    def test_es_nueva_false_en_dias_posteriores(self):
        self.hit(T0)
        VisitanteMetrica.objects.update(primera_visita=timezone.localdate(T0) - timedelta(days=2))
        self.hit(T0 + timedelta(hours=2))
        self.assertEqual(list(SesionMetrica.objects.order_by("id").values_list("es_nueva", flat=True)), [True, False])

    def test_sesion_de_otro_visitante_no_se_reutiliza(self):
        self.hit(T0)
        ajena = SesionMetrica.objects.get()
        otro = Client()
        otro.cookies["vi_sid"] = str(ajena.uuid)
        self.hit(T0 + timedelta(minutes=1), cliente=otro)
        ajena.refresh_from_db()
        self.assertEqual((SesionMetrica.objects.count(), VisitanteMetrica.objects.count(), ajena.paginas_vistas), (2, 2, 1))

    def test_cookie_de_sesion_invalida_o_inexistente(self):
        for valor in ("zzz", str(uuid.uuid4())):
            cliente = Client()
            self.hit(T0, cliente=cliente)
            cliente.cookies["vi_sid"] = valor
            self.hit(T0 + timedelta(minutes=1), cliente=cliente)
        self.assertEqual(SesionMetrica.objects.count(), 4)

    def test_fuente_y_referrer_host_desde_el_referer(self):
        with mock.patch.object(real, "ahora", return_value=T0):
            self.client.get(PAGINA + "?utm_source=x&q=privado", HTTP_REFERER="https://www.google.com/search?q=huanuco+secreto")
        s = SesionMetrica.objects.get()
        self.assertEqual((s.fuente, s.referrer_host), (FuenteTrafico.ORGANICO, "www.google.com"))

    def test_referer_interno_es_directo(self):
        self.client.get(PAGINA, HTTP_REFERER="http://testserver/terminos/")
        self.assertEqual(SesionMetrica.objects.get().fuente, FuenteTrafico.DIRECTO)
        self.assertEqual(SesionMetrica.objects.get().referrer_host, "")

    def test_fuente_se_decide_solo_al_iniciar_la_sesion(self):
        self.client.get(PAGINA)
        self.client.get("/terminos/", HTTP_REFERER="https://www.facebook.com/")
        self.assertEqual(SesionMetrica.objects.get().fuente, FuenteTrafico.DIRECTO)

    def test_dispositivo_por_user_agent_sin_guardarlo(self):
        self.client.get(PAGINA, HTTP_USER_AGENT=UA_IPAD)
        self.assertEqual(SesionMetrica.objects.get().dispositivo, "TABLET")
        campos = {f.name for m in (SesionMetrica, VisitanteMetrica, EventoMetrica) for f in m._meta.get_fields()}
        for prohibido in ("ip", "user_agent", "ua", "referrer", "url", "query", "email", "nombre"):
            self.assertNotIn(prohibido, campos)
        self.assertNotIn(UA_IPAD, json.dumps(list(SesionMetrica.objects.values()), default=str))

    def test_idioma_de_la_sesion(self):
        self.client.cookies["django_language"] = "en"
        self.client.get(PAGINA)
        self.assertEqual(SesionMetrica.objects.get().idioma, "en")

    def test_concurrencia_el_incremento_es_atomico_en_la_bd(self):
        self.client.get(PAGINA)
        copia_a = SesionMetrica.objects.get()
        copia_b = SesionMetrica.objects.get()  # dos procesos con la misma lectura obsoleta
        real._tocar_sesion(copia_a, T0 + timedelta(minutes=1), paginas=1)
        real._tocar_sesion(copia_b, T0 + timedelta(minutes=2), paginas=1)
        self.assertEqual(SesionMetrica.objects.get().paginas_vistas, 3)  # no se pierde ninguno

    def test_fin_no_retrocede_y_los_hits_no_tocan_la_duracion(self):
        self.client.get(PAGINA)
        s = SesionMetrica.objects.get()
        real._tocar_sesion(s, s.inicio + timedelta(seconds=300))
        real._tocar_sesion(s, s.inicio + timedelta(seconds=100))  # llegada fuera de orden
        s.refresh_from_db()
        self.assertEqual(s.fin, s.inicio + timedelta(seconds=300))
        self.assertEqual(s.duracion_seg, 0)


@ACTIVO
class ElegibilidadTests(TestCase):
    """Lo que NO es una página vista."""

    def assert_sin_registro(self):
        self.assertEqual((VisitanteMetrica.objects.count(), SesionMetrica.objects.count()), (0, 0))

    def test_rutas_internas_y_no_html_no_cuentan(self):
        self.client.get("/admin/login/")
        self.client.get("/robots.txt")
        self.client.get("/favicon.ico")
        self.assert_sin_registro()

    def test_head_options_y_post_no_cuentan(self):
        self.client.head(PAGINA)
        self.client.options(PAGINA)
        self.client.post(PAGINA)
        self.assert_sin_registro()

    def test_redirect_404_y_error_no_cuentan(self):
        self.assertEqual(self.client.get("/mi-cuenta/favoritos/").status_code, 302)
        self.assertEqual(self.client.get("/esta-pagina-no-existe/").status_code, 404)
        self.assert_sin_registro()

    def test_no_se_ponen_cookies_cuando_no_hay_seguimiento(self):
        r = self.client.get("/esta-pagina-no-existe/")
        self.assertNotIn("vi_vid", r.cookies)
        self.assertNotIn("vi_sid", r.cookies)

    def test_staff_y_superusuario_no_cuentan(self):
        for datos in ({"is_staff": True}, {"is_superuser": True}):
            u = User.objects.create_user(username=f"u{len(datos)}{list(datos)[0]}", password="x", **datos)
            self.client.force_login(u)
            r = self.client.get(PAGINA)
            self.assertNotIn("vi_vid", r.cookies)
        self.assert_sin_registro()

    def test_bots_no_cuentan(self):
        for ua in ("Googlebot/2.1", "curl/8.0", "Mozilla/5.0 HeadlessChrome/120"):
            self.client.get(PAGINA, HTTP_USER_AGENT=ua)
        self.assert_sin_registro()

    def test_no_son_paginas_fetch_iframe_ajax_ni_prefetch(self):
        self.client.get(PAGINA, HTTP_SEC_FETCH_DEST="iframe")
        self.client.get(PAGINA, HTTP_SEC_FETCH_DEST="empty")
        self.client.get(PAGINA, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.client.get(PAGINA, HTTP_SEC_PURPOSE="prefetch;prerender")
        self.assert_sin_registro()
        self.client.get(PAGINA, HTTP_SEC_FETCH_DEST="document")
        self.assertEqual(SesionMetrica.objects.count(), 1)

    def test_prefijos_estaticos_y_respuestas_no_html_en_el_middleware(self):
        rf = RequestFactory()

        def correr(ruta, respuesta, metodo="get"):
            peticion = getattr(rf, metodo)(ruta)
            peticion.user = AnonymousUser()
            return MetricasMiddleware(lambda r: respuesta)(peticion)

        html = lambda: HttpResponse("<p>x</p>", content_type="text/html; charset=utf-8")  # noqa: E731
        correr("/static/css/app.css", html())
        correr("/media/foto.jpg", html())
        correr("/metricas/evento/", html())
        correr("/chatbot/mensaje/", html())
        correr("/algo/", JsonResponse({"ok": True}))
        correr("/algo/", HttpResponse("texto", content_type="text/plain"))
        correr("/algo/", HttpResponse("<p>x</p>", content_type="text/html", status=500))
        correr("/algo/", HttpResponse(status=204))
        self.assert_sin_registro()
        correr("/algo/", html())
        self.assertEqual(SesionMetrica.objects.count(), 1)

    def test_un_fallo_de_metricas_no_rompe_la_pagina(self):
        with mock.patch.object(real, "_crear_sesion", side_effect=RuntimeError("falla analítica")):
            with self.assertLogs("apps.metricas.services.real", level="ERROR"):
                r = self.client.get(PAGINA)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((VisitanteMetrica.objects.count(), SesionMetrica.objects.count()), (0, 0))  # atomic revirtió

    def test_no_toca_el_dataset_simulado(self):
        self.client.get(PAGINA)
        self.assertEqual(MetricaDiaria.objects.count(), 0)


@ACTIVO
class VisitanteUsuarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user(username="ana", password="clave12345")
        cls.beto = User.objects.create_user(username="beto", password="clave12345")

    def test_usuario_autenticado_normal_es_registrado(self):
        self.client.force_login(self.ana)
        self.client.get(PAGINA)
        v = VisitanteMetrica.objects.get()
        self.assertEqual((v.es_registrado, v.usuario), (True, self.ana))

    def test_vinculo_posterior_al_iniciar_sesion(self):
        self.client.get(PAGINA)
        v = VisitanteMetrica.objects.get()
        self.assertEqual((v.es_registrado, v.usuario_id), (False, None))
        self.client.force_login(self.ana)  # misma cookie vi_vid
        self.client.get("/terminos/")
        v.refresh_from_db()
        self.assertEqual((VisitanteMetrica.objects.count(), v.es_registrado, v.usuario), (1, True, self.ana))

    def test_conflicto_de_usuario_no_mezcla_identidades_ni_rompe(self):
        self.client.force_login(self.ana)
        self.client.get(PAGINA)
        self.client.force_login(self.beto)  # mismo navegador, otra cuenta
        with self.assertLogs("apps.metricas.services.real", level="INFO") as logs:
            r = self.client.get("/terminos/")
        self.assertEqual(r.status_code, 200)
        v = VisitanteMetrica.objects.get()
        self.assertEqual(v.usuario, self.ana)
        self.assertTrue(any("no se mezclan identidades" in linea for linea in logs.output))

    def test_usuario_anonimo_no_vincula(self):
        self.client.get(PAGINA)
        self.assertIsNone(VisitanteMetrica.objects.get().usuario)


@ACTIVO
class ConsultasPorPaginaTests(TestCase):
    def test_consultas_adicionales(self):
        from django.test.utils import CaptureQueriesContext

        rf = RequestFactory()

        def pedir(cookies=None):
            peticion = rf.get("/algo/")
            peticion.user = AnonymousUser()
            peticion.COOKIES = dict(cookies or {})
            respuesta = HttpResponse("<p>x</p>", content_type="text/html")
            with CaptureQueriesContext(connection) as ctx:
                MetricasMiddleware(lambda r: respuesta)(peticion)
            return respuesta, consultas(ctx)

        r1, q1 = pedir()
        cookies = {n: r1.cookies[n].value for n in ("vi_vid", "vi_sid")}
        r2, q2 = pedir(cookies)
        self.assertEqual(len(q1), 2, q1)  # INSERT visitante + INSERT sesión (sin SELECT: no había cookies)
        self.assertEqual(len(q2), 3, q2)  # SELECT visitante + SELECT sesión + UPDATE atómico
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            _, q0 = pedir()
        self.assertEqual(q0, [])


# ---------------------------------------------------------------- eventos

@ACTIVO
class ServicioEventosTests(TestCase):
    def peticion(self, user=None, cookies=None, ua=UA_CHROME_WIN):
        p = RequestFactory().post("/x/", HTTP_USER_AGENT=ua)
        p.user = user or AnonymousUser()
        p.COOKIES = dict(cookies or {})
        return p

    def test_evento_sin_sesion_queda_con_visitante_y_sesion_nula(self):
        p = self.peticion()
        e = real.registrar_evento_real(p, TipoInteraccion.IDIOMA_CAMBIADO, meta={"de": "es", "a": "en"})
        self.assertEqual((e.origen, e.tipo, e.sesion, e.fecha), (REAL, "idioma_cambiado", None, timezone.localdate()))
        self.assertEqual(e.visitante, VisitanteMetrica.objects.get())
        self.assertEqual(SesionMetrica.objects.count(), 0)  # no inventa sesiones ni páginas
        self.assertEqual(e.meta, {"de": "es", "a": "en"})
        self.assertIn("vi_vid", p._metricas.cookies)
        self.assertNotIn("vi_sid", p._metricas.cookies)

    def test_evento_con_sesion_vigente_la_asocia_y_la_extiende(self):
        with mock.patch.object(real, "ahora", return_value=T0):
            r = Client().get(PAGINA)
        cookies = {n: r.cookies[n].value for n in ("vi_vid", "vi_sid")}
        with mock.patch.object(real, "ahora", return_value=T0 + timedelta(minutes=25)):
            p = self.peticion(cookies=cookies)
            e = real.registrar_evento_real(p, TipoInteraccion.UBICACION_CLICK)
        s = SesionMetrica.objects.get()
        self.assertEqual((e.sesion, s.paginas_vistas, s.duracion_seg, s.fin), (s, 1, 0, T0 + timedelta(minutes=25)))
        self.assertEqual(p._metricas.cookies["vi_sid"][1], 1800)

    def test_evento_no_reutiliza_una_sesion_expirada(self):
        with mock.patch.object(real, "ahora", return_value=T0):
            r = Client().get(PAGINA)
        cookies = {n: r.cookies[n].value for n in ("vi_vid", "vi_sid")}
        with mock.patch.object(real, "ahora", return_value=T0 + timedelta(minutes=50)):
            e = real.registrar_evento_real(self.peticion(cookies=cookies), TipoInteraccion.UBICACION_CLICK)
        self.assertIsNone(e.sesion)

    def test_meta_segura(self):
        meta = real.meta_segura({
            "via": "chip", "n": 3, "ok": True, "largo": "x" * 100, "anidado": {"a": 1}, "lista": [1],
            "k" * 30: "clave larga", 5: "no es str",
        })
        self.assertEqual(meta, {"via": "chip", "n": 3, "ok": True, "largo": "x" * 40})
        self.assertEqual(len(real.meta_segura({f"k{i}": i for i in range(20)})), real.MAX_ITEMS_META)
        self.assertEqual(real.meta_segura(None), {})

    def test_tipo_invalido_staff_bot_y_flag_apagado_no_registran(self):
        staff = User.objects.create_user(username="st", password="x", is_staff=True)
        self.assertIsNone(real.registrar_evento_real(self.peticion(), "scroll"))
        self.assertIsNone(real.registrar_evento_real(self.peticion(user=staff), "idioma_cambiado"))
        self.assertIsNone(real.registrar_evento_real(self.peticion(ua="Googlebot/2.1"), "idioma_cambiado"))
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            self.assertIsNone(real.registrar_evento_real(self.peticion(), "idioma_cambiado"))
        self.assertEqual((EventoMetrica.objects.count(), VisitanteMetrica.objects.count()), (0, 0))

    def test_click_id_es_idempotente(self):
        clic = uuid.uuid4()
        a = real.registrar_evento_real(self.peticion(), "ubicacion_click", click_id=clic)
        b = real.registrar_evento_real(self.peticion(), "ubicacion_click", click_id=clic)
        self.assertEqual((a.pk, b.pk, EventoMetrica.objects.count()), (a.pk, a.pk, 1))

    def test_nunca_lanza_hacia_el_llamador(self):
        with mock.patch.object(EventoMetrica.objects, "create", side_effect=RuntimeError("bd caída")):
            with self.assertLogs("apps.metricas.services.real", level="ERROR"):
                self.assertIsNone(real.registrar_evento_real(self.peticion(), "idioma_cambiado"))
        real.actualizar_meta_evento(None, resultado="ok")  # no hace nada ni lanza

    def test_actualizar_meta(self):
        e = real.registrar_evento_real(self.peticion(), "chatbot_consulta", meta={"via": "texto"})
        real.actualizar_meta_evento(e, resultado="ok")
        e.refresh_from_db()
        self.assertEqual(e.meta, {"via": "texto", "resultado": "ok"})


# ---------------------------------------------------------------- chatbot

@ACTIVO
class ChatbotMetricasTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("chatbot:enviar_mensaje")
        p = mock.patch.object(chatbot_service, "generar_respuesta", return_value=("Respuesta de prueba", "", None))
        self.generar = p.start()
        self.addCleanup(p.stop)

    def enviar(self, payload, cliente=None):
        return (cliente or self.client).post(self.url, data=payload, content_type="application/json")

    def eventos(self):
        return list(EventoMetrica.objects.filter(tipo="chatbot_consulta"))

    def test_texto_valido_cuenta_una_vez_sin_copiar_el_contenido(self):
        secreto = "mi dato privado 12345"
        r = self.enviar({"mensaje": secreto})
        self.assertEqual(r.status_code, 200)
        (e,) = self.eventos()
        self.assertEqual(e.meta, {"via": "texto", "resultado": "ok"})
        self.assertNotIn(secreto, json.dumps(list(EventoMetrica.objects.values()), default=str))
        self.assertIn("vi_vid", r.cookies)  # el visitante queda identificado
        self.assertIsNone(e.sesion)  # el chatbot no inventa sesiones ni páginas
        self.assertEqual(SesionMetrica.objects.count(), 0)

    def test_chip_cuenta_como_consulta(self):
        def falsa(conversacion, accion_id):
            return None, Mensaje.objects.create(conversacion=conversacion, rol="asistente", contenido="Listo")

        with mock.patch.object(chatbot_service, "procesar_accion", side_effect=falsa):
            r = self.enviar({"accion": "clima_huanuco"})
        self.assertEqual(r.status_code, 200)
        (e,) = self.eventos()
        self.assertEqual(e.meta["via"], "chip")

    def test_con_sesion_analitica_el_evento_se_asocia(self):
        self.client.get(PAGINA)
        self.enviar({"mensaje": "Hola"})
        (e,) = self.eventos()
        self.assertEqual(e.sesion, SesionMetrica.objects.get())
        self.assertEqual(SesionMetrica.objects.get().paginas_vistas, 1)  # el POST no suma páginas

    def test_solicitudes_invalidas_no_cuentan(self):
        for payload in ({"mensaje": ""}, {"mensaje": "   "}, {"mensaje": "x" * 5000}, {"accion": "no-existe"},
                        {"mensaje": "a", "accion": "clima_huanuco"}, {}, [1, 2]):
            self.assertGreaterEqual(self.enviar(payload).status_code, 400, payload)
        self.client.post(self.url, data="no es json", content_type="application/json")
        self.assertEqual(self.eventos(), [])

    @override_settings(CHATBOT_RATE_LIMIT_REQUESTS=1)
    def test_rate_limit_rechazado_no_cuenta(self):
        self.assertEqual(self.enviar({"mensaje": "uno"}).status_code, 200)
        self.assertEqual(self.enviar({"mensaje": "dos"}).status_code, 429)
        self.assertEqual(len(self.eventos()), 1)

    def test_proveedor_falla_cuenta_igual_con_resultado(self):
        casos = [
            (llm_client.ProveedorIATimeout("x"), 504, "error_proveedor"),
            (llm_client.ProveedorIAError("x"), 502, "error_proveedor"),
            (llm_client.ChatbotNoConfigurado("x"), 503, "error_proveedor"),
            (RuntimeError("bug"), 500, "error_interno"),
        ]
        for excepcion, status, resultado in casos:
            with self.subTest(status=status):
                EventoMetrica.objects.all().delete()
                self.generar.side_effect = excepcion
                self.assertEqual(self.enviar({"mensaje": "Hola"}, cliente=Client()).status_code, status)
                (e,) = self.eventos()
                self.assertEqual(e.meta["resultado"], resultado)

    def test_exactamente_un_evento_por_solicitud(self):
        for i in range(3):
            self.enviar({"mensaje": f"m{i}"})
        self.assertEqual(len(self.eventos()), 3)

    def test_un_fallo_de_metricas_no_afecta_al_chatbot(self):
        with mock.patch.object(EventoMetrica.objects, "create", side_effect=RuntimeError("bd caída")):
            with self.assertLogs("apps.metricas.services.real", level="ERROR"):
                r = self.enviar({"mensaje": "Hola"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ok"], True)

    def test_flag_apagado_el_chatbot_funciona_sin_eventos(self):
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            r = self.enviar({"mensaje": "Hola"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EventoMetrica.objects.count(), 0)

    def test_staff_no_cuenta(self):
        self.client.force_login(User.objects.create_user(username="st", password="x", is_staff=True))
        self.assertEqual(self.enviar({"mensaje": "Hola"}).status_code, 200)
        self.assertEqual(self.eventos(), [])

    def test_usuario_normal_cuenta_y_se_vincula(self):
        ana = User.objects.create_user(username="ana", password="x")
        self.client.force_login(ana)
        self.enviar({"mensaje": "Hola"})
        (e,) = self.eventos()
        self.assertEqual(e.visitante.usuario, ana)


# ---------------------------------------------------------------- favoritos

@ACTIVO
class FavoritosMetricasTests(InteraccionesTestBase):
    def setUp(self):
        self.client.login(username="turista1", password="clave12345")

    def toggle(self, tipo, pk):
        return self.client.post(reverse("interacciones:toggle_favorito", kwargs={"tipo": tipo, "pk": pk}))

    def eventos(self):
        return list(EventoMetrica.objects.filter(tipo="favorito_agregado"))

    def test_agregar_cuenta_una_vez_con_entidad(self):
        self.assertEqual(self.toggle("establecimiento", self.establecimiento.pk).json()["accion"], "agregado")
        (e,) = self.eventos()
        self.assertEqual((e.entidad_tipo, e.entidad_id, e.meta), ("establecimiento", self.establecimiento.pk, {"tipo": "restaurante"}))
        self.assertEqual(e.visitante.usuario, self.usuario)
        self.toggle("lugar", self.lugar.pk)
        self.assertEqual(len(self.eventos()), 2)
        self.assertEqual(self.eventos()[1].entidad_tipo, "lugar")

    def test_eliminar_no_cuenta(self):
        self.toggle("lugar", self.lugar.pk)
        self.assertEqual(self.toggle("lugar", self.lugar.pk).json()["accion"], "eliminado")
        self.assertEqual(len(self.eventos()), 1)  # solo el alta

    def test_volver_a_agregar_cuenta_otra_vez(self):
        for _ in range(3):  # agregar, quitar, agregar
            self.toggle("lugar", self.lugar.pk)
        self.assertEqual(len(self.eventos()), 2)

    def test_integrity_error_no_cuenta(self):
        from django.db import IntegrityError

        with mock.patch.object(Favorito.objects, "create", side_effect=IntegrityError("carrera")):
            r = self.toggle("lugar", self.lugar.pk)
        self.assertEqual(r.json()["accion"], "agregado")
        self.assertEqual(self.eventos(), [])

    def test_recursos_o_tipos_invalidos_y_anonimo_no_cuentan(self):
        self.assertEqual(self.toggle("lugar", 99999).status_code, 404)
        self.assertEqual(self.toggle("otro", 1).status_code, 400)
        self.client.logout()
        self.assertEqual(self.toggle("lugar", self.lugar.pk).status_code, 401)
        self.assertEqual(self.eventos(), [])

    def test_fallo_de_metricas_no_rompe_el_favorito(self):
        with mock.patch.object(EventoMetrica.objects, "create", side_effect=RuntimeError("bd caída")):
            with self.assertLogs("apps.metricas.services.real", level="ERROR"):
                r = self.toggle("lugar", self.lugar.pk)
        self.assertEqual(r.json(), {"ok": True, "es_favorito": True, "accion": "agregado"})
        self.assertTrue(Favorito.objects.filter(usuario=self.usuario, lugar_turistico=self.lugar).exists())

    def test_flag_apagado_no_registra(self):
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            self.toggle("lugar", self.lugar.pk)
        self.assertEqual(EventoMetrica.objects.count(), 0)


# ---------------------------------------------------------------- idioma

@ACTIVO
class IdiomaMetricasTests(TestCase):
    def cambiar(self, idioma, cliente=None, **extra):
        return (cliente or self.client).post(reverse("set_language"), {"language": idioma, "next": "/historia/"}, **extra)

    def eventos(self):
        return list(EventoMetrica.objects.filter(tipo="idioma_cambiado"))

    def test_la_url_y_el_nombre_siguen_igual(self):
        self.assertEqual(reverse("set_language"), "/i18n/setlang/")

    def test_es_a_en_cuenta_uno_con_meta(self):
        r = self.cambiar("en")
        self.assertEqual((r.status_code, r["Location"], r.cookies["django_language"].value), (302, "/historia/", "en"))
        (e,) = self.eventos()
        self.assertEqual(e.meta, {"de": "es", "a": "en"})
        self.assertEqual(e.entidad_tipo, "")

    def test_en_a_es_cuenta_uno(self):
        self.client.cookies["django_language"] = "en"
        self.cambiar("es")
        (e,) = self.eventos()
        self.assertEqual(e.meta, {"de": "en", "a": "es"})

    def test_mismo_idioma_no_cuenta(self):
        self.cambiar("es")  # sin cookie el idioma activo es ES
        self.client.cookies["django_language"] = "en"
        self.cambiar("en")
        self.assertEqual(self.eventos(), [])

    def test_recarga_get_e_idiomas_invalidos_no_cuentan(self):
        self.client.cookies["django_language"] = "en"
        self.client.get(PAGINA)  # recarga
        self.client.get(reverse("set_language"), {"language": "es", "next": "/historia/"})  # GET no cambia nada
        self.cambiar("xx")
        self.cambiar("fr")  # idioma que Django conoce pero el sitio no ofrece
        self.cambiar("")
        self.assertEqual(self.eventos(), [])

    def test_comportamiento_original_intacto(self):
        r = self.cambiar("en", HTTP_REFERER="https://externo.com/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/historia/")
        # next externo se descarta como en Django
        r = self.client.post(reverse("set_language"), {"language": "es", "next": "https://malo.com/"})
        self.assertEqual(r["Location"], "/")
        # y el idioma efectivamente cambia el sitio
        self.assertEqual(self.client.get(PAGINA).wsgi_request.LANGUAGE_CODE, "es")

    def test_flag_apagado_cambia_idioma_sin_evento(self):
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            r = self.cambiar("en")
        self.assertEqual(r.cookies["django_language"].value, "en")
        self.assertEqual(EventoMetrica.objects.count(), 0)

    def test_cookies_analiticas_viajan_en_la_respuesta_del_cambio(self):
        r = self.cambiar("en")
        self.assertIn("vi_vid", r.cookies)

    def test_fallo_de_metricas_no_impide_el_cambio(self):
        with mock.patch.object(EventoMetrica.objects, "create", side_effect=RuntimeError("bd caída")):
            with self.assertLogs("apps.metricas.services.real", level="ERROR"):
                r = self.cambiar("en")
        self.assertEqual((r.status_code, r.cookies["django_language"].value), (302, "en"))


class AislamientoTests(TestCase):
    def test_flag_apagado_ningun_hecho_real(self):
        self.client.get(PAGINA)
        self.client.post(reverse("set_language"), {"language": "en"})
        self.assertEqual((VisitanteMetrica.objects.count(), SesionMetrica.objects.count(), EventoMetrica.objects.count()), (0, 0, 0))

    @ACTIVO
    def test_el_seguimiento_real_no_toca_los_agregados(self):
        self.client.get(PAGINA)
        self.assertEqual(MetricaDiaria.objects.count(), 0)
