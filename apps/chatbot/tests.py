import inspect
import json
from datetime import date, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import requests
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from google.genai import errors as genai_errors
from google.genai import interactions as genai_interactions

from apps.emergencias.models import (
    ContactoEmergencia,
    NumeroContactoAdicional,
    ZonaAtencionEmergencia,
)
from apps.establecimientos.models import (
    CategoriaEstablecimiento,
    Establecimiento,
    RecomendacionEstablecimiento,
    ServicioEstablecimiento,
    SucursalEstablecimiento,
)
from apps.eventos.models import CategoriaEvento, Evento, EventoQuerySet, TagExperiencia
from apps.interacciones.models import Favorito
from apps.gastronomia.models import (
    CategoriaPlatoTipico,
    IngredienteClavePlato,
    PlatoEstablecimiento,
    PlatoTipico,
)
from apps.monedas.models import TipoCambio
from apps.movilidad.models import (
    CategoriaMovilidad,
    ConsejoMovilidad,
    RutaMovilidad,
    TransportePublico,
)
from apps.servicios_turista.models import (
    CategoriaServicioTurista,
    ContactoServicioTurista,
    ServicioTurista,
)
from apps.turismo.models import (
    TIPO_COSTO_CHOICES,
    CategoriaLugarTuristico,
    LugarTuristico,
    ServicioLugarTuristico,
)
from apps.ubicaciones.models import Departamento, Distrito, Localidad, Provincia

from .models import Conversacion, Mensaje
from .services import (
    ai_provider,
    chatbot_service,
    context_builder,
    deepseek_client,
    external_search,
    gemini_tools,
    llm_client,
    natural_quick_actions,
    presenters,
    quick_actions,
    response_renderers,
    system_prompt,
    tool_catalog,
    tool_schemas,
    trusted_sources,
)
from .services.providers import (
    ArgumentoInvalido,
    establecimientos as prov_establecimientos,
    eventos as prov_eventos,
    gastronomia as prov_gastronomia,
    itinerario as prov_itinerario,
    movilidad as prov_movilidad,
    servicios as prov_servicios,
    turismo as prov_turismo,
    ubicaciones as prov_ubicaciones,
)

# C7: red real bloqueada para todo este módulo. requests.get (clima_actual.py)
# es el único cliente HTTP de bajo nivel del chatbot que no se sustituye por
# clase (Gemini/DeepSeek ya se mockean patcheando genai.Client / httpx.request
# por test); un test que olvide mockear obtener_clima_actual debe fallar aquí
# en vez de alcanzar Open-Meteo real (bug real encontrado y corregido en C7).
# Monkeypatch manual (no unittest.mock.patch): algunos tests existentes usan
# `self.addCleanup(patch.stopall)`, que detiene TODO patch activo del proceso
# — incluido uno de mock.patch instalado aquí en setUpModule — dejando la red
# real desprotegida para el resto de la suite. Una asignación directa es
# invisible a patch.stopall() y sobrevive a esos cleanups.
_requests_get_original = requests.get


def _requests_get_bloqueado(*args, **kwargs):
    raise AssertionError(
        "Red real bloqueada en tests de apps.chatbot: mockea obtener_clima_actual "
        "(o el cliente HTTP correspondiente) en vez de dejar pasar la llamada real."
    )


def setUpModule():
    requests.get = _requests_get_bloqueado


def tearDownModule():
    requests.get = _requests_get_original


class ConversacionTests(TestCase):
    def test_creacion_con_usuario_autenticado(self):
        usuario = User.objects.create_user(username="turista", password="clave-123")
        conversacion = Conversacion.objects.create(usuario=usuario)

        self.assertEqual(conversacion.usuario, usuario)
        self.assertEqual(conversacion.session_key, "")

    def test_creacion_anonima_con_session_key(self):
        conversacion = Conversacion.objects.create(session_key="abc123sesion")

        self.assertIsNone(conversacion.usuario)
        self.assertEqual(conversacion.session_key, "abc123sesion")

    def test_usuario_es_opcional(self):
        conversacion = Conversacion.objects.create()

        self.assertIsNone(conversacion.usuario)

    def test_timestamps_se_autopueblan(self):
        conversacion = Conversacion.objects.create()

        self.assertIsNotNone(conversacion.creado)
        self.assertIsNotNone(conversacion.ultima_actividad)

    def test_str(self):
        usuario = User.objects.create_user(username="turista2", password="clave-123")
        conversacion = Conversacion.objects.create(usuario=usuario)

        self.assertIn(str(conversacion.pk), str(conversacion))


class MensajeTests(TestCase):
    def setUp(self):
        self.conversacion = Conversacion.objects.create(session_key="sesion-mensajes")

    def test_creacion_mensaje_usuario_sin_fuente(self):
        mensaje = Mensaje.objects.create(
            conversacion=self.conversacion,
            rol=Mensaje.Rol.USUARIO,
            contenido="¿Dónde puedo comer pachamanca?",
        )

        self.assertEqual(mensaje.rol, Mensaje.Rol.USUARIO)
        self.assertEqual(mensaje.tipo_fuente, "")

    def test_creacion_mensaje_asistente_con_cada_tipo_fuente(self):
        for tipo_fuente in Mensaje.TipoFuente.values:
            mensaje = Mensaje.objects.create(
                conversacion=self.conversacion,
                rol=Mensaje.Rol.ASISTENTE,
                contenido=f"Respuesta con fuente {tipo_fuente}",
                tipo_fuente=tipo_fuente,
            )
            self.assertEqual(mensaje.tipo_fuente, tipo_fuente)

    def test_relacion_conversacion_mensajes(self):
        Mensaje.objects.create(
            conversacion=self.conversacion,
            rol=Mensaje.Rol.USUARIO,
            contenido="Hola",
        )
        Mensaje.objects.create(
            conversacion=self.conversacion,
            rol=Mensaje.Rol.ASISTENTE,
            contenido="¡Hola! ¿En qué te ayudo?",
            tipo_fuente=Mensaje.TipoFuente.NO_EVIDENCE,
        )

        self.assertEqual(self.conversacion.mensajes.count(), 2)

    def test_tipo_fuente_opcional(self):
        mensaje = Mensaje.objects.create(
            conversacion=self.conversacion,
            rol=Mensaje.Rol.USUARIO,
            contenido="Sin fuente",
        )
        mensaje.full_clean()

    def test_orden_cronologico(self):
        primero = Mensaje.objects.create(
            conversacion=self.conversacion, rol=Mensaje.Rol.USUARIO, contenido="Uno"
        )
        segundo = Mensaje.objects.create(
            conversacion=self.conversacion, rol=Mensaje.Rol.ASISTENTE, contenido="Dos"
        )

        mensajes = list(self.conversacion.mensajes.all())
        self.assertEqual(mensajes, [primero, segundo])

    def test_str(self):
        mensaje = Mensaje.objects.create(
            conversacion=self.conversacion,
            rol=Mensaje.Rol.USUARIO,
            contenido="Un mensaje de prueba",
        )

        self.assertIn("Un mensaje de prueba", str(mensaje))


class AdminRegistrationTests(TestCase):
    def test_modelos_registrados_en_admin(self):
        self.assertIn(Conversacion, admin.site._registry)
        self.assertIn(Mensaje, admin.site._registry)


# ---------------------------------------------------------------------------
# C2 — motor conversacional HTTP (sin IA)
# ---------------------------------------------------------------------------


RESPUESTA_PRUEBA = "Respuesta de prueba de Pillco Bot"


class RespuestaSimuladaMixin:
    """Aísla la capa HTTP/persistencia del ciclo real con Gemini."""

    def setUp(self):
        super().setUp()
        patcher = patch.object(
            chatbot_service, "generar_respuesta", return_value=(RESPUESTA_PRUEBA, "", None)
        )
        self.generar_respuesta_mock = patcher.start()
        self.addCleanup(patcher.stop)


class EnviarMensajeMixin(RespuestaSimuladaMixin):
    def setUp(self):
        super().setUp()
        self.url = reverse("chatbot:enviar_mensaje")

    def enviar(self, mensaje, client=None, **extra):
        client = client or self.client
        return client.post(
            self.url, data={"mensaje": mensaje, **extra}, content_type="application/json"
        )


class EnviarMensajeUrlTests(EnviarMensajeMixin, TestCase):
    def test_url_resuelve(self):
        self.assertEqual(self.url, "/chatbot/mensaje/")

    def test_post_valido_devuelve_200(self):
        respuesta = self.enviar("¿Qué puedo visitar en Huánuco?")

        self.assertEqual(respuesta.status_code, 200)

    def test_get_devuelve_405(self):
        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 405)


class EnviarMensajePayloadTests(EnviarMensajeMixin, TestCase):
    def assert_rechazado(self, respuesta, codigo):
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.json(), {"ok": False, "error": codigo})
        self.assertEqual(Mensaje.objects.count(), 0)
        self.assertEqual(Conversacion.objects.count(), 0)

    def test_json_malformado(self):
        respuesta = self.client.post(self.url, data="{no json", content_type="application/json")

        self.assert_rechazado(respuesta, "json_invalido")

    def test_body_vacio(self):
        respuesta = self.client.post(self.url, data="", content_type="application/json")

        self.assert_rechazado(respuesta, "json_invalido")

    def test_json_que_no_es_objeto(self):
        respuesta = self.client.post(self.url, data="[1, 2]", content_type="application/json")

        self.assert_rechazado(respuesta, "json_invalido")

    def test_sin_campo_mensaje(self):
        respuesta = self.client.post(self.url, data={"otro": "x"}, content_type="application/json")

        self.assert_rechazado(respuesta, "payload_invalido")

    def test_mensaje_no_string(self):
        self.assert_rechazado(self.enviar(123), "mensaje_invalido")

    def test_mensaje_vacio(self):
        self.assert_rechazado(self.enviar(""), "mensaje_vacio")

    def test_mensaje_solo_espacios(self):
        self.assert_rechazado(self.enviar("   \n\t "), "mensaje_vacio")

    def test_mensaje_demasiado_largo(self):
        respuesta = self.enviar("a" * (chatbot_service.MAX_MESSAGE_LENGTH + 1))

        self.assert_rechazado(respuesta, "mensaje_demasiado_largo")

    def test_mensaje_de_longitud_maxima_permitido(self):
        respuesta = self.enviar("a" * chatbot_service.MAX_MESSAGE_LENGTH)

        self.assertEqual(respuesta.status_code, 200)

    def test_espacios_exteriores_se_eliminan(self):
        self.enviar("   ¿Dónde puedo comer pachamanca?   ")

        mensaje = Mensaje.objects.get(rol=Mensaje.Rol.USUARIO)
        self.assertEqual(mensaje.contenido, "¿Dónde puedo comer pachamanca?")

    def test_campos_del_cliente_no_se_confian(self):
        respuesta = self.enviar(
            "Hola", conversation_id=999, session_key="falsa", tipo_fuente="internal"
        )

        self.assertEqual(respuesta.status_code, 200)
        conversacion = Conversacion.objects.get()
        self.assertNotEqual(conversacion.pk, 999)
        self.assertNotEqual(conversacion.session_key, "falsa")
        stub = Mensaje.objects.get(rol=Mensaje.Rol.ASISTENTE)
        self.assertEqual(stub.tipo_fuente, "")


@override_settings(CHATBOT_RATE_LIMIT_REQUESTS=3, CHATBOT_RATE_LIMIT_WINDOW_SECONDS=60)
class RateLimitTests(EnviarMensajeMixin, TestCase):
    """C7: rate limit simple por usuario/sesión sobre django.core.cache."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def test_bajo_limite_no_bloquea(self):
        for _ in range(3):
            self.assertEqual(self.enviar("Hola").status_code, 200)

    def test_supera_limite_devuelve_429_amigable(self):
        for _ in range(3):
            self.enviar("Hola")

        respuesta = self.enviar("Hola")

        self.assertEqual(respuesta.status_code, 429)
        self.assertEqual(respuesta.json(), {"ok": False, "error": "demasiadas_solicitudes"})
        self.assertEqual(Mensaje.objects.count(), 6)  # solo las 3 primeras (usuario+asistente) persistieron

    def test_usuario_a_no_consume_cupo_de_usuario_b(self):
        usuario_a = User.objects.create_user(username="turista-a", password="clave-123")
        usuario_b = User.objects.create_user(username="turista-b", password="clave-123")
        cliente_a, cliente_b = Client(), Client()
        cliente_a.force_login(usuario_a)
        cliente_b.force_login(usuario_b)
        for _ in range(3):
            self.enviar("Hola", client=cliente_a)

        self.assertEqual(self.enviar("Hola", client=cliente_a).status_code, 429)
        self.assertEqual(self.enviar("Hola", client=cliente_b).status_code, 200)

    def test_sesion_anonima_a_no_consume_cupo_de_sesion_b(self):
        cliente_a, cliente_b = Client(), Client()
        for _ in range(3):
            self.enviar("Hola", client=cliente_a)

        self.assertEqual(self.enviar("Hola", client=cliente_a).status_code, 429)
        self.assertEqual(self.enviar("Hola", client=cliente_b).status_code, 200)

    def test_fallo_de_cache_es_fail_open_con_warning(self):
        with patch.object(cache, "add", side_effect=Exception("cache caída")):
            with self.assertLogs("apps.chatbot.views", level="WARNING") as logs:
                respuesta = self.enviar("Hola")

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(any("chatbot_rate_limit_cache_error" in linea for linea in logs.output))

    def test_json_invalido_no_consume_cupo(self):
        for _ in range(3):
            self.client.post(self.url, data="{no json", content_type="application/json")

        self.assertEqual(self.enviar("Hola").status_code, 200)

    def test_accion_invalida_no_consume_cupo(self):
        for _ in range(3):
            self.client.post(self.url, data={"accion": "no-existe"}, content_type="application/json")

        self.assertEqual(self.enviar("Hola").status_code, 200)


class GuardiaRedTests(TestCase):
    """C7: red real bloqueada (ver setUpModule) — este test falla si el
    guardia se rompe, cubriendo el hueco real que dejó pasar Open-Meteo."""

    def test_requests_get_bloqueado_sin_mock_explicito(self):
        with self.assertRaises(AssertionError):
            requests.get("https://api.open-meteo.com/v1/forecast")


class EnviarMensajeUsuarioAutenticadoTests(EnviarMensajeMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.usuario = User.objects.create_user(username="turista", password="clave-123")
        self.client.force_login(self.usuario)

    def test_primer_turno_crea_conversacion_del_usuario(self):
        self.enviar("Hola")

        conversacion = Conversacion.objects.get()
        self.assertEqual(conversacion.usuario, self.usuario)
        self.assertEqual(conversacion.session_key, "")

    def test_turno_persiste_mensaje_usuario_y_asistente(self):
        self.enviar("Hola")

        roles = list(Mensaje.objects.values_list("rol", flat=True))
        self.assertEqual(roles, [Mensaje.Rol.USUARIO, Mensaje.Rol.ASISTENTE])

    def test_segundo_turno_reutiliza_la_conversacion(self):
        primera = self.enviar("Hola").json()["conversation_id"]
        segunda = self.enviar("¿Qué visito?").json()["conversation_id"]

        self.assertEqual(primera, segunda)
        self.assertEqual(Conversacion.objects.count(), 1)

    def test_dos_turnos_dejan_cuatro_mensajes_ordenados(self):
        self.enviar("Uno")
        self.enviar("Dos")

        conversacion = Conversacion.objects.get()
        mensajes = list(conversacion.mensajes.values_list("rol", "contenido"))
        self.assertEqual(
            mensajes,
            [
                (Mensaje.Rol.USUARIO, "Uno"),
                (Mensaje.Rol.ASISTENTE, RESPUESTA_PRUEBA),
                (Mensaje.Rol.USUARIO, "Dos"),
                (Mensaje.Rol.ASISTENTE, RESPUESTA_PRUEBA),
            ],
        )

    def test_conversacion_anonima_ajena_no_se_reutiliza(self):
        Conversacion.objects.create(session_key="otra-sesion")

        self.enviar("Hola")

        self.assertEqual(Conversacion.objects.count(), 2)
        self.assertTrue(Conversacion.objects.filter(usuario=self.usuario).exists())


class EnviarMensajeVisitanteAnonimoTests(EnviarMensajeMixin, TestCase):
    def test_endpoint_crea_sesion_django(self):
        self.assertNotIn(settings.SESSION_COOKIE_NAME, self.client.cookies)

        self.enviar("Hola")

        session_key = self.client.session.session_key
        self.assertTrue(session_key)
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())

    def test_crea_conversacion_anonima_con_session_key_real(self):
        self.enviar("Hola")

        conversacion = Conversacion.objects.get()
        self.assertIsNone(conversacion.usuario)
        self.assertEqual(conversacion.session_key, self.client.session.session_key)

    def test_segundo_turno_mismo_cliente_reutiliza_conversacion(self):
        primera = self.enviar("Hola").json()["conversation_id"]
        segunda = self.enviar("¿Qué visito?").json()["conversation_id"]

        self.assertEqual(primera, segunda)
        self.assertEqual(Conversacion.objects.count(), 1)

    def test_otro_cliente_obtiene_otra_conversacion(self):
        primera = self.enviar("Hola").json()["conversation_id"]
        segunda = self.enviar("Hola", client=Client()).json()["conversation_id"]

        self.assertNotEqual(primera, segunda)
        self.assertEqual(Conversacion.objects.count(), 2)
        claves = set(Conversacion.objects.values_list("session_key", flat=True))
        self.assertEqual(len(claves), 2)

    def test_sesion_caducada_se_recrea(self):
        self.enviar("Hola")
        clave_vieja = self.client.session.session_key
        Session.objects.filter(session_key=clave_vieja).delete()

        respuesta = self.enviar("Sigo aquí")

        self.assertEqual(respuesta.status_code, 200)
        clave_nueva = self.client.session.session_key
        self.assertNotEqual(clave_nueva, clave_vieja)
        self.assertTrue(Conversacion.objects.filter(session_key=clave_nueva).exists())


class EnviarMensajeRespuestaTests(EnviarMensajeMixin, TestCase):
    def test_json_exitoso(self):
        datos = self.enviar("Hola").json()

        conversacion = Conversacion.objects.get()
        stub = Mensaje.objects.get(rol=Mensaje.Rol.ASISTENTE)
        self.assertTrue(datos["ok"])
        self.assertEqual(datos["conversation_id"], conversacion.pk)
        self.assertEqual(
            datos["respuesta"],
            {
                "id": stub.pk,
                "rol": "asistente",
                "contenido": RESPUESTA_PRUEBA,
                "tipo_fuente": None,
                "creado": stub.creado.isoformat(),
            },
        )

    def test_respuesta_no_expone_datos_internos(self):
        datos = self.enviar("Hola").json()

        self.assertEqual(set(datos), {"ok", "conversation_id", "respuesta"})
        self.assertNotIn("session_key", datos)

    def test_mensajes_persistidos_del_turno(self):
        self.enviar("  Hola  ")

        usuario = Mensaje.objects.get(rol=Mensaje.Rol.USUARIO)
        stub = Mensaje.objects.get(rol=Mensaje.Rol.ASISTENTE)
        self.assertEqual(usuario.contenido, "Hola")
        self.assertEqual(usuario.tipo_fuente, "")
        self.assertEqual(stub.contenido, RESPUESTA_PRUEBA)
        self.assertEqual(stub.tipo_fuente, "")


class ChatbotServiceTests(RespuestaSimuladaMixin, TestCase):
    def test_obtener_o_crear_requiere_usuario_o_session_key(self):
        with self.assertRaises(ValueError):
            chatbot_service.obtener_o_crear_conversacion()

    def test_reutiliza_la_conversacion_mas_reciente(self):
        antigua = Conversacion.objects.create(session_key="s1")
        reciente = Conversacion.objects.create(session_key="s1")
        Conversacion.objects.filter(pk=antigua.pk).update(
            ultima_actividad=timezone.now() - timedelta(days=1)
        )

        self.assertEqual(
            chatbot_service.obtener_o_crear_conversacion(session_key="s1"), reciente
        )

    def test_turno_actualiza_ultima_actividad(self):
        conversacion = Conversacion.objects.create(session_key="s1")
        pasado = timezone.now() - timedelta(days=1)
        Conversacion.objects.filter(pk=conversacion.pk).update(ultima_actividad=pasado)
        conversacion.refresh_from_db()

        _, respuesta = chatbot_service.procesar_turno(conversacion, "Hola")

        conversacion.refresh_from_db()
        self.assertGreater(conversacion.ultima_actividad, pasado)
        self.assertGreaterEqual(conversacion.ultima_actividad, respuesta.creado)

    def test_ultima_actividad_no_retrocede_en_turnos_posteriores(self):
        conversacion = Conversacion.objects.create(session_key="s1")
        chatbot_service.procesar_turno(conversacion, "Uno")
        conversacion.refresh_from_db()
        primera = conversacion.ultima_actividad

        _, respuesta = chatbot_service.procesar_turno(conversacion, "Dos")

        conversacion.refresh_from_db()
        self.assertGreaterEqual(conversacion.ultima_actividad, primera)
        self.assertGreaterEqual(conversacion.ultima_actividad, respuesta.creado)

    def test_turno_fallido_no_deja_mensajes_huerfanos(self):
        conversacion = Conversacion.objects.create(session_key="s1")
        pasado = timezone.now() - timedelta(days=1)
        Conversacion.objects.filter(pk=conversacion.pk).update(ultima_actividad=pasado)
        conversacion.refresh_from_db()
        self.generar_respuesta_mock.side_effect = llm_client.ProveedorIAError("fallo")

        with self.assertRaises(llm_client.ProveedorIAError):
            chatbot_service.procesar_turno(conversacion, "Hola")

        self.assertEqual(Mensaje.objects.count(), 0)
        conversacion.refresh_from_db()
        self.assertEqual(conversacion.ultima_actividad, pasado)


class EnviarMensajeCsrfTests(TestCase):
    def test_post_sin_token_csrf_es_rechazado(self):
        client = Client(enforce_csrf_checks=True)

        respuesta = client.post(
            reverse("chatbot:enviar_mensaje"),
            data={"mensaje": "Hola"},
            content_type="application/json",
        )

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Mensaje.objects.count(), 0)


# ---------------------------------------------------------------------------
# C3 — providers/herramientas deterministas (sin IA)
# ---------------------------------------------------------------------------


class ProvidersDataMixin:
    @classmethod
    def setUpTestData(cls):
        # Territorio
        cls.departamento = Departamento.objects.create(nombre_oficial="HUANUCO", slug="huanuco")
        cls.prov_huanuco = Provincia.objects.create(
            departamento=cls.departamento, nombre_oficial="HUANUCO", slug="huanuco", capital="Huánuco"
        )
        cls.prov_leoncio = Provincia.objects.create(
            departamento=cls.departamento, nombre_oficial="LEONCIO PRADO", slug="leoncio-prado"
        )
        cls.dist_huanuco = Distrito.objects.create(
            provincia=cls.prov_huanuco, nombre_oficial="HUANUCO", slug="huanuco", codigo_inei="100101"
        )
        cls.dist_amarilis = Distrito.objects.create(
            provincia=cls.prov_huanuco, nombre_oficial="AMARILIS", slug="amarilis", codigo_inei="100102"
        )
        cls.dist_rupa = Distrito.objects.create(
            provincia=cls.prov_leoncio, nombre_oficial="RUPA-RUPA", slug="rupa-rupa", codigo_inei="100601"
        )
        cls.loc_tingo = Localidad.objects.create(
            distrito=cls.dist_rupa, nombre="Tingo María", slug="tingo-maria", tipo="Ciudad",
            latitud=Decimal("-9.2950000"), longitud=Decimal("-75.9970000"),
        )

        # Turismo
        cls.cat_arqueo = CategoriaLugarTuristico.objects.create(nombre="Arqueológico", slug="arqueologico")
        cls.cat_natural = CategoriaLugarTuristico.objects.create(nombre="Natural", slug="natural")
        cls.serv_guia = ServicioLugarTuristico.objects.create(nombre="Guía", slug="guia")
        cls.kotosh = LugarTuristico.objects.create(
            categoria_principal=cls.cat_arqueo, nombre="Kotosh", slug="kotosh",
            descripcion_corta="Templo de las Manos Cruzadas", distrito=cls.dist_huanuco,
            tipo_costo="pagado", precio_desde=Decimal("5.00"), precio_hasta=Decimal("10.00"),
            dificultad="facil", destacado=True, horario_visita="8:00 a 17:00",
            latitud=Decimal("-9.9400000"), longitud=Decimal("-76.2800000"),
        )
        cls.kotosh.categorias_secundarias.set([cls.cat_arqueo, cls.cat_natural])
        cls.kotosh.servicios.set([cls.serv_guia])
        cls.lechuzas = LugarTuristico.objects.create(
            categoria_principal=cls.cat_natural, nombre="Cueva de las Lechuzas", slug="cueva-lechuzas",
            distrito=cls.dist_rupa, localidad=cls.loc_tingo, tipo_costo="gratis", dificultad="moderada",
        )
        LugarTuristico.objects.create(
            categoria_principal=cls.cat_arqueo, nombre="Lugar oculto", slug="lugar-oculto",
            distrito=cls.dist_huanuco, activo=False,
        )

        # Establecimientos
        cls.cat_criolla = CategoriaEstablecimiento.objects.create(nombre="Criolla", slug="criolla")
        cls.cat_hotel = CategoriaEstablecimiento.objects.create(nombre="Hotel", slug="hotel")
        cls.serv_wifi = ServicioEstablecimiento.objects.create(nombre="Wifi", slug="wifi")
        cls.rest_huanuqueno = Establecimiento.objects.create(
            tipo="restaurante", categoria_principal=cls.cat_criolla, nombre="Restaurante Huanuqueño",
            slug="restaurante-huanuqueno", rango_precio="moderado",
            precio_desde=Decimal("15.00"), precio_hasta=Decimal("40.00"), destacado=True,
        )
        SucursalEstablecimiento.objects.create(
            establecimiento=cls.rest_huanuqueno, nombre="Sucursal Amarilis", slug="amarilis",
            distrito=cls.dist_amarilis,
        )
        cls.suc_principal = SucursalEstablecimiento.objects.create(
            establecimiento=cls.rest_huanuqueno, nombre="Sucursal principal", slug="principal",
            distrito=cls.dist_huanuco, es_principal=True, horario_atencion="12:00 a 22:00",
            direccion="Jr. Dos de Mayo 123",
        )
        RecomendacionEstablecimiento.objects.create(
            establecimiento=cls.rest_huanuqueno, nombre="Pachamanca de la casa", orden=1
        )
        cls.rest_tingo = Establecimiento.objects.create(
            tipo="restaurante", categoria_principal=cls.cat_criolla, nombre="Pollería Tingo",
            slug="polleria-tingo", rango_precio="economico",
        )
        SucursalEstablecimiento.objects.create(
            establecimiento=cls.rest_tingo, nombre="Local", slug="local", distrito=cls.dist_rupa,
            es_principal=True,
        )
        cls.rest_inactivo = Establecimiento.objects.create(
            tipo="restaurante", categoria_principal=cls.cat_criolla, nombre="Restaurante cerrado",
            slug="restaurante-cerrado", activo=False,
        )
        cls.hotel = Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=cls.cat_hotel, nombre="Hotel Real",
            slug="hotel-real", rango_precio="alto",
        )
        cls.hotel.servicios.set([cls.serv_wifi])
        SucursalEstablecimiento.objects.create(
            establecimiento=cls.hotel, nombre="Sede", slug="sede", distrito=cls.dist_huanuco,
            es_principal=True,
        )

        # Gastronomía
        # La migración gastronomia.0002 ya siembra esta categoría
        cls.cat_fondo, _ = CategoriaPlatoTipico.objects.get_or_create(
            nombre="Platos de fondo", defaults={"slug": "platos-de-fondo"}
        )
        cls.pachamanca = PlatoTipico.objects.create(
            categoria=cls.cat_fondo, nombre="Pachamanca", slug="pachamanca", es_plato_bandera=True,
        )
        IngredienteClavePlato.objects.create(plato=cls.pachamanca, nombre="Carne de cerdo")
        cls.locro = PlatoTipico.objects.create(
            categoria=cls.cat_fondo, nombre="Locro de gallina", slug="locro-de-gallina", orden=2
        )
        cls.plato_inactivo = PlatoTipico.objects.create(
            categoria=cls.cat_fondo, nombre="Plato retirado", slug="plato-retirado", activo=False
        )
        PlatoEstablecimiento.objects.create(plato=cls.pachamanca, establecimiento=cls.rest_huanuqueno)
        PlatoEstablecimiento.objects.create(
            plato=cls.pachamanca, establecimiento=cls.rest_tingo, activo=False
        )
        PlatoEstablecimiento.objects.create(plato=cls.pachamanca, establecimiento=cls.rest_inactivo)
        PlatoEstablecimiento.objects.create(plato=cls.locro, establecimiento=cls.rest_tingo)
        PlatoEstablecimiento.objects.create(plato=cls.plato_inactivo, establecimiento=cls.rest_huanuqueno)

        # Eventos
        cls.cat_fest = CategoriaEvento.objects.create(nombre="Festividad", slug="festividad")
        cls.tag_familias = TagExperiencia.objects.create(nombre="Familias", slug="familias")
        cls.ev_concierto = Evento.objects.create(
            categoria_principal=cls.cat_fest, nombre="Concierto", slug="concierto",
            tipo_fecha="exacta", fecha_inicio=date(2026, 10, 10), distrito=cls.dist_huanuco,
            tipo_costo="pagado", precio_desde=Decimal("20.00"), tipo_horario="exacta",
            hora_inicio=time(19, 0),
        )
        cls.ev_concierto.tags_experiencia.set([cls.tag_familias])
        cls.ev_feria = Evento.objects.create(
            categoria_principal=cls.cat_fest, nombre="Feria", slug="feria", tipo_fecha="rango",
            fecha_inicio=date(2026, 10, 20), fecha_fin=date(2026, 10, 25),
            provincia=cls.prov_leoncio, tipo_costo="gratis", tipo_horario="todo_el_dia",
        )
        cls.ev_san_juan = Evento.objects.create(
            categoria_principal=cls.cat_fest, nombre="Fiesta de San Juan", slug="san-juan",
            tipo_fecha="anual_fija", dia_inicio_anual=24, mes_inicio_anual=6, tipo_horario="variable",
        )
        cls.ev_cafe = Evento.objects.create(
            categoria_principal=cls.cat_fest, nombre="Festival del Café", slug="festival-cafe",
            tipo_fecha="mes_aproximado", mes_aproximado=10, anio_aproximado=2026,
            tipo_horario="por_confirmar",
        )
        cls.ev_expo = Evento.objects.create(
            categoria_principal=cls.cat_fest, nombre="Expo Huánuco", slug="expo",
            tipo_fecha="por_confirmar", estado="cancelado", tipo_horario="por_confirmar",
        )
        Evento.objects.create(
            categoria_principal=cls.cat_fest, nombre="Evento oculto", slug="evento-oculto",
            tipo_fecha="exacta", fecha_inicio=date(2026, 10, 11), activo=False,
        )

        # Movilidad: las migraciones 0003/0005 siembran transportes, consejos y
        # rutas; se parte de cero para que las expectativas sean deterministas
        RutaMovilidad.objects.all().delete()
        ConsejoMovilidad.objects.all().delete()
        TransportePublico.objects.all().delete()
        TransportePublico.objects.create(
            nombre="Mototaxi", slug="mototaxi", descripcion="Corto", tarifa_minima=Decimal("3.00")
        )
        ConsejoMovilidad.objects.create(texto="Negocia la tarifa", seccion="tarifas_taxi")
        cls.cat_terrestre, _ = CategoriaMovilidad.objects.get_or_create(
            slug="via-terrestre", defaults={"nombre": "Vía terrestre"}
        )
        cls.cat_aerea, _ = CategoriaMovilidad.objects.get_or_create(
            slug="via-aerea", defaults={"nombre": "Vía aérea"}
        )
        RutaMovilidad.objects.create(
            seccion="como_llegar", categoria_principal=cls.cat_terrestre, nombre="Lima - Huánuco en bus",
            slug="lima-huanuco-bus", origen_texto="Lima", destino_distrito=cls.dist_huanuco,
            duracion_bus="10 horas", tipo_costo="pagado", precio_desde=Decimal("60.00"),
        )
        RutaMovilidad.objects.create(
            seccion="como_llegar", categoria_principal=cls.cat_aerea, nombre="Lima - Huánuco en avión",
            slug="lima-huanuco-avion", origen_texto="Lima", destino_texto="Aeropuerto de Huánuco",
        )
        RutaMovilidad.objects.create(
            seccion="general", categoria_principal=cls.cat_terrestre, nombre="Plaza a Kotosh",
            slug="plaza-kotosh",
        )
        ConsejoMovilidad.objects.create(texto="Lleva abrigo", seccion="como_llegar_terrestre")

        # Servicios útiles
        cls.cat_farmacia = CategoriaServicioTurista.objects.create(nombre="Farmacias", slug="farmacias")
        cls.botica = ServicioTurista.objects.create(
            categoria_principal=cls.cat_farmacia, nombre="Botica Central", slug="botica-central",
            distrito=cls.dist_huanuco, tipo_atencion="presencial", disponibilidad="veinticuatro_horas",
            horario_atencion="24 horas",
        )
        ContactoServicioTurista.objects.create(
            servicio=cls.botica, tipo_contacto="whatsapp", valor="999111222", es_principal=True
        )
        ServicioTurista.objects.create(
            categoria_principal=cls.cat_farmacia, nombre="Botica Tingo", slug="botica-tingo",
            distrito=cls.dist_rupa, disponibilidad="horario",
        )
        ServicioTurista.objects.create(
            categoria_principal=cls.cat_farmacia, nombre="Botica cerrada", slug="botica-cerrada",
            distrito=cls.dist_amarilis, activo=False,
        )

        # Emergencias
        cls.zona_huanuco = ZonaAtencionEmergencia.objects.create(distrito=cls.dist_huanuco, slug="huanuco")
        cls.zona_amarilis = ZonaAtencionEmergencia.objects.create(distrito=cls.dist_amarilis, slug="amarilis")
        cls.pnp = ContactoEmergencia.objects.create(
            ambito="nacional", categoria="policia", nombre="PNP", numero_visible="105",
            numero_tel="105", es_24_horas=True,
        )
        cls.serenazgo = ContactoEmergencia.objects.create(
            ambito="local", categoria="serenazgo", nombre="Serenazgo Huánuco", numero_visible="(062) 111",
            numero_tel="062111", horario="6:00 a 22:00", orden=2,
        )
        cls.serenazgo.zonas.set([cls.zona_huanuco])
        NumeroContactoAdicional.objects.create(
            contacto=cls.serenazgo, etiqueta="Móvil", numero_visible="999 000", numero_tel="999000"
        )
        cls.serenazgo_amarilis = ContactoEmergencia.objects.create(
            ambito="local", categoria="serenazgo", nombre="Serenazgo Amarilis", numero_visible="222",
            numero_tel="222", orden=3,
        )
        cls.serenazgo_amarilis.zonas.set([cls.zona_amarilis])

        # Tipo de cambio
        cls.tipo_cambio = TipoCambio.objects.create(
            fecha=date(2026, 9, 10), compra=Decimal("3.5000"), venta=Decimal("3.5200"),
            respuesta_api={"sell_price": "3.52"},
        )


class TurismoProviderTests(ProvidersDataMixin, TestCase):
    def nombres(self, resultado):
        return [item["nombre"] for item in resultado["items"]]

    def test_solo_devuelve_activos(self):
        resultado = prov_turismo.buscar_lugares()

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["tipo_fuente"], "internal")
        self.assertEqual(self.nombres(resultado), ["Kotosh", "Cueva de las Lechuzas"])

    def test_filtro_q(self):
        self.assertEqual(self.nombres(prov_turismo.buscar_lugares(q="manos cruzadas")), ["Kotosh"])

    def test_filtro_categoria_incluye_secundarias_sin_duplicar(self):
        resultado = prov_turismo.buscar_lugares(categoria="natural")

        self.assertEqual(self.nombres(resultado), ["Kotosh", "Cueva de las Lechuzas"])
        self.assertEqual(self.nombres(prov_turismo.buscar_lugares(categoria="arqueologico")), ["Kotosh"])

    def test_filtro_tipo_costo_y_dificultad(self):
        self.assertEqual(self.nombres(prov_turismo.buscar_lugares(tipo_costo="gratis")), ["Cueva de las Lechuzas"])
        self.assertEqual(self.nombres(prov_turismo.buscar_lugares(dificultad="facil")), ["Kotosh"])

    def test_choice_invalido_es_rechazado(self):
        with self.assertRaises(ArgumentoInvalido):
            prov_turismo.buscar_lugares(tipo_costo="barato")

    def test_filtro_distrito_y_provincia(self):
        self.assertEqual(self.nombres(prov_turismo.buscar_lugares(distrito="rupa-rupa")), ["Cueva de las Lechuzas"])
        self.assertEqual(self.nombres(prov_turismo.buscar_lugares(provincia="huanuco")), ["Kotosh"])

    def test_limit(self):
        self.assertEqual(prov_turismo.buscar_lugares(limit=1)["count"], 1)
        for invalido in (0, 11, "5", True):
            with self.assertRaises(ArgumentoInvalido):
                prov_turismo.buscar_lugares(limit=invalido)

    def test_sin_resultados_no_es_error(self):
        resultado = prov_turismo.buscar_lugares(q="inexistente")

        self.assertEqual(resultado, {
            "ok": True, "tool": "buscar_lugares", "tipo_fuente": "internal", "count": 0, "items": [],
        })

    def test_serializacion_del_listado(self):
        item = prov_turismo.buscar_lugares(q="Kotosh")["items"][0]

        self.assertEqual(item["url"], reverse("turismo:detalle_lugar", kwargs={"slug": "kotosh"}))
        self.assertEqual(item["precio_desde"], "5.00")
        self.assertEqual(item["categoria"], "Arqueológico")
        self.assertEqual(item["distrito"], "HUANUCO")
        self.assertEqual(item["provincia"], "HUANUCO")
        self.assertEqual(item["horario_visita"], "8:00 a 17:00")

    def test_obtener_lugar_activo(self):
        item = prov_turismo.obtener_lugar("kotosh")["item"]

        self.assertEqual(item["nombre"], "Kotosh")
        self.assertEqual(item["servicios"], ["Guía"])
        self.assertCountEqual(item["categorias_secundarias"], ["Arqueológico", "Natural"])
        self.assertEqual(item["latitud"], "-9.9400000")

    def test_obtener_lugar_inexistente_o_inactivo(self):
        self.assertIsNone(prov_turismo.obtener_lugar("no-existe")["item"])
        self.assertIsNone(prov_turismo.obtener_lugar("lugar-oculto")["item"])
        with self.assertRaises(ArgumentoInvalido):
            prov_turismo.obtener_lugar("")

    def test_buscar_lugares_una_sola_query(self):
        with self.assertNumQueries(1):
            prov_turismo.buscar_lugares()


class UbicacionesProviderTests(ProvidersDataMixin, TestCase):
    def test_devuelve_jerarquia_correcta(self):
        items = prov_ubicaciones.buscar_ubicaciones("Huánuco")["items"]

        tipos = {(i["tipo"], i["nombre"]) for i in items}
        self.assertIn(("departamento", "HUANUCO"), tipos)
        self.assertIn(("provincia", "HUANUCO"), tipos)
        self.assertIn(("distrito", "HUANUCO"), tipos)
        distrito = next(i for i in items if i["tipo"] == "distrito")
        self.assertEqual(distrito["provincia_slug"], "huanuco")
        self.assertEqual(distrito["nombre_publico"], "Huánuco")

    def test_localidad_con_padres_y_filtro_tipo(self):
        items = prov_ubicaciones.buscar_ubicaciones("Tingo", tipo="localidad")["items"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["distrito_slug"], "rupa-rupa")
        self.assertEqual(items[0]["provincia"], "LEONCIO PRADO")
        self.assertEqual(items[0]["latitud"], "-9.2950000")

    def test_limita_y_valida(self):
        self.assertEqual(prov_ubicaciones.buscar_ubicaciones("Huánuco", limit=2)["count"], 2)
        with self.assertRaises(ArgumentoInvalido):
            prov_ubicaciones.buscar_ubicaciones("")
        with self.assertRaises(ArgumentoInvalido):
            prov_ubicaciones.buscar_ubicaciones("x", tipo="pais")


class EstablecimientosProviderTests(ProvidersDataMixin, TestCase):
    def nombres(self, resultado):
        return [item["nombre"] for item in resultado["items"]]

    def test_buscar_restaurantes_solo_restaurantes_activos(self):
        self.assertEqual(
            self.nombres(prov_establecimientos.buscar_restaurantes()),
            ["Restaurante Huanuqueño", "Pollería Tingo"],
        )

    def test_buscar_alojamientos_solo_alojamientos(self):
        resultado = prov_establecimientos.buscar_alojamientos()

        self.assertEqual(self.nombres(resultado), ["Hotel Real"])
        self.assertEqual(resultado["items"][0]["url"], reverse("establecimientos:detalle_alojamiento", kwargs={"slug": "hotel-real"}))

    def test_sucursal_principal_es_la_representativa(self):
        item = prov_establecimientos.buscar_restaurantes(q="Huanuqueño")["items"][0]

        self.assertEqual(item["sucursal"]["nombre"], "Sucursal principal")
        self.assertTrue(item["sucursal"]["es_principal"])
        self.assertEqual(item["sucursal"]["horario_atencion"], "12:00 a 22:00")
        self.assertEqual(item["sucursal"]["distrito_slug"], "huanuco")

    def test_ubicacion_filtra_por_sucursal(self):
        self.assertEqual(self.nombres(prov_establecimientos.buscar_restaurantes(distrito="amarilis")), ["Restaurante Huanuqueño"])
        self.assertEqual(self.nombres(prov_establecimientos.buscar_restaurantes(provincia="leoncio-prado")), ["Pollería Tingo"])

    def test_filtros_rango_precio_y_servicio(self):
        self.assertEqual(self.nombres(prov_establecimientos.buscar_restaurantes(rango_precio="economico")), ["Pollería Tingo"])
        self.assertEqual(self.nombres(prov_establecimientos.buscar_alojamientos(servicio="wifi")), ["Hotel Real"])
        with self.assertRaises(ArgumentoInvalido):
            prov_establecimientos.buscar_restaurantes(rango_precio="barato")

    def test_por_plato_reutiliza_relacion_real(self):
        resultado = prov_establecimientos.buscar_restaurantes_por_plato("pachamanca")

        self.assertEqual(resultado["plato"]["slug"], "pachamanca")
        # Pollería (vínculo inactivo) y Restaurante cerrado (inactivo) quedan fuera
        self.assertEqual(self.nombres(resultado), ["Restaurante Huanuqueño"])

    def test_por_plato_resuelve_por_nombre(self):
        self.assertEqual(prov_establecimientos.buscar_restaurantes_por_plato("Pachamanca")["plato"]["slug"], "pachamanca")
        self.assertEqual(prov_establecimientos.buscar_restaurantes_por_plato("locro")["plato"]["slug"], "locro-de-gallina")

    def test_por_plato_inactivo_o_desconocido(self):
        for texto in ("plato-retirado", "ceviche"):
            resultado = prov_establecimientos.buscar_restaurantes_por_plato(texto)
            self.assertTrue(resultado["ok"])
            self.assertIsNone(resultado["plato"])
            self.assertEqual(resultado["count"], 0)

    def test_por_plato_con_ubicacion(self):
        self.assertEqual(prov_establecimientos.buscar_restaurantes_por_plato("pachamanca", distrito="rupa-rupa")["count"], 0)
        self.assertEqual(self.nombres(prov_establecimientos.buscar_restaurantes_por_plato("locro", distrito="rupa-rupa")), ["Pollería Tingo"])

    def test_obtener_establecimiento_detalle(self):
        item = prov_establecimientos.obtener_establecimiento("restaurante-huanuqueno")["item"]

        self.assertEqual([s["nombre"] for s in item["sucursales"]], ["Sucursal principal", "Sucursal Amarilis"])
        self.assertEqual(item["recomendaciones"][0]["nombre"], "Pachamanca de la casa")
        self.assertEqual(item["precio_hasta"], "40.00")
        self.assertIsNone(prov_establecimientos.obtener_establecimiento("restaurante-cerrado")["item"])

    def test_buscar_restaurantes_sin_n_mas_uno(self):
        with self.assertNumQueries(3):  # establecimientos + prefetch sucursales + prefetch especialidades
            prov_establecimientos.buscar_restaurantes()


class GastronomiaProviderTests(ProvidersDataMixin, TestCase):
    def test_buscar_platos_solo_activos_y_bandera(self):
        resultado = prov_gastronomia.buscar_platos()

        self.assertEqual([i["nombre"] for i in resultado["items"]], ["Pachamanca", "Locro de gallina"])
        self.assertEqual(prov_gastronomia.buscar_platos(es_plato_bandera=True)["count"], 1)

    def test_serializacion_sin_url_individual_inventada(self):
        item = prov_gastronomia.buscar_platos(q="pacha")["items"][0]

        self.assertNotIn("url", item)
        self.assertEqual(item["url_listado"], reverse("gastronomia:platos_tipicos"))
        self.assertEqual(item["url_donde_comer"], f"{reverse('establecimientos:listado_restaurantes')}?plato=pachamanca")
        self.assertEqual(item["ingredientes"], ["Carne de cerdo"])

    def test_obtener_plato_con_restaurantes(self):
        item = prov_gastronomia.obtener_plato("pachamanca")["item"]

        self.assertEqual([r["slug"] for r in item["restaurantes"]], ["restaurante-huanuqueno"])
        self.assertIsNone(prov_gastronomia.obtener_plato("plato-retirado")["item"])


class EventosProviderTests(ProvidersDataMixin, TestCase):
    def nombres(self, resultado):
        return [item["nombre"] for item in resultado["items"]]

    def test_usa_publicados_y_excluye_inactivos(self):
        with patch.object(EventoQuerySet, "publicados", autospec=True, side_effect=EventoQuerySet.publicados) as m:
            resultado = prov_eventos.buscar_eventos(limit=10)

        m.assert_called_once()
        self.assertNotIn("Evento oculto", self.nombres(resultado))

    def test_rango_usa_que_solapan(self):
        with patch.object(EventoQuerySet, "que_solapan", autospec=True, side_effect=EventoQuerySet.que_solapan) as m:
            resultado = prov_eventos.buscar_eventos(fecha_desde="2026-10-10", fecha_hasta="2026-10-12")

        m.assert_called_once()
        self.assertEqual(m.call_args.args[1:], (date(2026, 10, 10), date(2026, 10, 12)))
        self.assertEqual(self.nombres(resultado), ["Concierto"])

    def test_evento_fuera_del_rango_no_aparece(self):
        self.assertNotIn("Feria", self.nombres(prov_eventos.buscar_eventos(fecha_desde="2026-10-10", fecha_hasta="2026-10-12")))

    def test_filtros_estructurados(self):
        self.assertEqual(self.nombres(prov_eventos.buscar_eventos(tipo_costo="gratis")), ["Feria"])
        self.assertEqual(self.nombres(prov_eventos.buscar_eventos(provincia="leoncio-prado")), ["Feria"])
        self.assertEqual(self.nombres(prov_eventos.buscar_eventos(distrito="huanuco")), ["Concierto"])
        self.assertEqual(self.nombres(prov_eventos.buscar_eventos(tags="familias")), ["Concierto"])
        self.assertEqual(self.nombres(prov_eventos.buscar_eventos(q="café")), ["Festival del Café"])

    def test_fechas_invalidas(self):
        with self.assertRaises(ArgumentoInvalido):
            prov_eventos.buscar_eventos(fecha_desde="10/10/2026")
        with self.assertRaises(ArgumentoInvalido):
            prov_eventos.buscar_eventos(fecha_desde="2026-10-12", fecha_hasta="2026-10-10")

    def test_aproximados_en_rango_solo_si_se_piden(self):
        rango = {"fecha_desde": "2026-10-10", "fecha_hasta": "2026-10-12"}

        self.assertEqual(self.nombres(prov_eventos.buscar_eventos(**rango)), ["Concierto"])
        con_aprox = self.nombres(prov_eventos.buscar_eventos(incluir_aproximados=True, **rango))
        self.assertEqual(con_aprox, ["Festival del Café", "Concierto", "Expo Huánuco"])

    def test_mes_aproximado_fuera_del_rango_no_aparece(self):
        resultado = prov_eventos.buscar_eventos(fecha_desde="2026-11-01", fecha_hasta="2026-11-30", incluir_aproximados=True)

        self.assertEqual(self.nombres(resultado), ["Expo Huánuco"])

    def test_sin_rango_incluye_aproximados_por_defecto(self):
        nombres = self.nombres(prov_eventos.buscar_eventos(limit=10))

        self.assertIn("Festival del Café", nombres)
        self.assertIn("Expo Huánuco", nombres)
        self.assertNotIn("Expo Huánuco", self.nombres(prov_eventos.buscar_eventos(incluir_aproximados=False, limit=10)))

    def test_estado_real_se_conserva(self):
        expo = next(i for i in prov_eventos.buscar_eventos(q="Expo")["items"])

        self.assertEqual(expo["estado"], "cancelado")
        self.assertEqual(expo["tipo_fecha"], "por_confirmar")
        self.assertIsNone(expo["fecha_inicio"])

    def test_anual_fija_resuelve_ocurrencia_del_rango(self):
        resultado = prov_eventos.buscar_eventos(fecha_desde="2027-06-20", fecha_hasta="2027-06-30")

        self.assertEqual(self.nombres(resultado), ["Fiesta de San Juan"])
        self.assertEqual(resultado["items"][0]["fecha_inicio"], "2027-06-24")

    def test_orden_por_ocurrencia_con_por_confirmar_al_final(self):
        items = prov_eventos.buscar_eventos(fecha_desde="2026-10-01", fecha_hasta="2026-10-31", incluir_aproximados=True, limit=10)["items"]

        fechas = [i["fecha_inicio"] for i in items]
        self.assertEqual(fechas[:-1], sorted(fechas[:-1]))
        self.assertEqual(items[-1]["nombre"], "Expo Huánuco")

    def test_limit_y_serializacion(self):
        resultado = prov_eventos.buscar_eventos(limit=1)

        self.assertEqual(resultado["count"], 1)
        concierto = prov_eventos.buscar_eventos(q="Concierto")["items"][0]
        self.assertEqual(concierto["precio_desde"], "20.00")
        self.assertEqual(concierto["hora_inicio"], "19:00:00")
        self.assertEqual(concierto["tags"], ["Familias"])
        self.assertEqual(concierto["provincia"], "HUANUCO")
        self.assertEqual(concierto["url_listado"], reverse("eventos:listado_eventos"))

    def test_obtener_evento(self):
        item = prov_eventos.obtener_evento("feria")["item"]

        self.assertEqual(item["fecha_fin"], "2026-10-25")
        self.assertEqual(item["provincia"], "LEONCIO PRADO")
        self.assertIsNone(prov_eventos.obtener_evento("evento-oculto")["item"])


class MovilidadProviderTests(ProvidersDataMixin, TestCase):
    def test_tarifas_reutilizan_service_y_son_mixed_con_usd(self):
        with patch.object(prov_movilidad, "obtener_transportes_con_tarifas", wraps=prov_movilidad.obtener_transportes_con_tarifas) as m:
            resultado = prov_movilidad.consultar_tarifas_movilidad()

        m.assert_called_once()
        self.assertEqual(resultado["tipo_fuente"], "mixed")
        self.assertEqual(resultado["items"][0]["tarifa_minima_pen"], "3.00")
        self.assertIsNotNone(resultado["items"][0]["tarifa_minima_usd"])
        self.assertEqual(resultado["consejos"], ["Negocia la tarifa"])
        self.assertEqual(resultado["url"], reverse("movilidad:tarifas_taxi"))

    def test_tarifas_sin_tipo_cambio_son_internal(self):
        TipoCambio.objects.all().delete()

        resultado = prov_movilidad.consultar_tarifas_movilidad()

        self.assertEqual(resultado["tipo_fuente"], "internal")
        self.assertIsNone(resultado["items"][0]["tarifa_minima_usd"])

    def test_como_llegar_por_via(self):
        todas = prov_movilidad.consultar_como_llegar()
        self.assertEqual([(i["via"], i["nombre"]) for i in todas["items"]], [
            ("terrestre", "Lima - Huánuco en bus"), ("aerea", "Lima - Huánuco en avión"),
        ])
        self.assertEqual(todas["items"][0]["destino"], "HUANUCO")
        self.assertEqual(todas["consejos"], {"terrestre": ["Lleva abrigo"], "aerea": []})

        terrestre = prov_movilidad.consultar_como_llegar(via="terrestre")
        self.assertEqual(terrestre["count"], 1)
        self.assertEqual(terrestre["items"][0]["precio_desde"], "60.00")
        with self.assertRaises(ArgumentoInvalido):
            prov_movilidad.consultar_como_llegar(via="maritima")


class ServiciosProviderTests(ProvidersDataMixin, TestCase):
    def nombres(self, resultado):
        return [item["nombre"] for item in resultado["items"]]

    def test_servicios_utiles_filtran_y_serializan(self):
        resultado = prov_servicios.consultar_servicios_utiles(categoria="farmacias")

        self.assertEqual(self.nombres(resultado), ["Botica Central", "Botica Tingo"])
        central = resultado["items"][0]
        self.assertEqual(central["zona"], "Huánuco")
        self.assertEqual(central["contactos"], [{"tipo": "whatsapp", "etiqueta": "", "valor": "999111222"}])
        self.assertEqual(central["url"], reverse("servicios_turista:servicios_utiles"))
        self.assertEqual(self.nombres(prov_servicios.consultar_servicios_utiles(distrito="rupa-rupa")), ["Botica Tingo"])
        self.assertEqual(self.nombres(prov_servicios.consultar_servicios_utiles(disponibilidad="veinticuatro_horas")), ["Botica Central"])
        with self.assertRaises(ArgumentoInvalido):
            prov_servicios.consultar_servicios_utiles(tipo_atencion="drone")

    def test_emergencias_por_categoria_y_24_horas(self):
        self.assertEqual(self.nombres(prov_servicios.consultar_emergencias(categoria="policia")), ["PNP"])
        self.assertEqual(self.nombres(prov_servicios.consultar_emergencias(solo_24_horas=True)), ["PNP"])
        with self.assertRaises(ArgumentoInvalido):
            prov_servicios.consultar_emergencias(categoria="dentista")

    def test_emergencias_por_distrito_incluye_nacionales_y_zona(self):
        resultado = prov_servicios.consultar_emergencias(distrito="huanuco")

        self.assertEqual(self.nombres(resultado), ["PNP", "Serenazgo Huánuco"])
        serenazgo = resultado["items"][1]
        self.assertEqual(serenazgo["horario"], "6:00 a 22:00")
        self.assertEqual(serenazgo["zonas"], ["HUANUCO"])
        self.assertEqual(serenazgo["numeros_adicionales"], [{"etiqueta": "Móvil", "numero": "999 000", "numero_tel": "999000"}])
        self.assertEqual(self.nombres(prov_servicios.consultar_emergencias(distrito="huanuco", ambito="local")), ["Serenazgo Huánuco"])
        self.assertEqual(prov_servicios.consultar_emergencias(limit=1)["count"], 1)

    def test_clima_usa_service_existente_y_es_external_trusted(self):
        datos = {"disponible": True, "es_respaldo": False, "ciudad_slug": "tingo-maria",
                 "temperatura_c": 27.5, "estado_texto": "Nublado", "es_dia": True,
                 "ubicacion": "Tingo María (Ciudad)", "fuente": "Open-Meteo", "hora_dato": "2026-09-14T10:00"}
        with patch.object(prov_servicios, "obtener_clima_actual", return_value=datos) as m:
            resultado = prov_servicios.consultar_clima("tingo-maria")

        m.assert_called_once_with("tingo-maria")
        self.assertEqual(resultado["tipo_fuente"], "external_trusted")
        self.assertEqual(resultado["item"]["temperatura_c"], 27.5)
        self.assertEqual(resultado["item"]["fuente"], "Open-Meteo")
        self.assertEqual(resultado["item"]["url"], reverse("clima:clima_temporadas"))

    def test_clima_ciudad_predeterminada_y_no_soportada(self):
        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": False}) as m:
            resultado = prov_servicios.consultar_clima()

        m.assert_called_once_with("huanuco")
        self.assertFalse(resultado["item"]["disponible"])
        with self.assertRaises(ArgumentoInvalido):
            prov_servicios.consultar_clima("lima")

    def test_tipo_cambio_usa_vigente(self):
        with patch.object(TipoCambio, "vigente", wraps=TipoCambio.vigente) as m:
            resultado = prov_servicios.consultar_tipo_cambio()

        m.assert_called_once()
        self.assertEqual(resultado["tipo_fuente"], "external_trusted")
        self.assertEqual(resultado["item"]["compra"], "3.5000")
        self.assertEqual(resultado["item"]["venta"], "3.5200")
        self.assertEqual(resultado["item"]["fecha"], "2026-09-10")

    def test_tipo_cambio_sin_vigente_y_carga_manual(self):
        TipoCambio.objects.update(respuesta_api=None)
        self.assertEqual(prov_servicios.consultar_tipo_cambio()["tipo_fuente"], "internal")

        TipoCambio.objects.update(activo=False)
        resultado = prov_servicios.consultar_tipo_cambio()
        self.assertTrue(resultado["ok"])
        self.assertIsNone(resultado["item"])


class ToolCatalogTests(ProvidersDataMixin, TestCase):
    ESPERADAS = {
        "buscar_lugares", "obtener_lugar", "buscar_ubicaciones",
        "buscar_restaurantes", "buscar_alojamientos", "obtener_establecimiento",
        "buscar_restaurantes_por_plato", "buscar_platos", "obtener_plato",
        "buscar_eventos", "obtener_evento",
        "consultar_tarifas_movilidad", "consultar_como_llegar",
        "consultar_servicios_utiles", "consultar_emergencias",
        "consultar_clima", "consultar_tipo_cambio",
        "consultar_favoritos", "planificar_itinerario",
    }

    def test_todas_las_herramientas_registradas(self):
        self.assertEqual(set(tool_catalog.TOOL_REGISTRY), self.ESPERADAS)
        listado = tool_catalog.listar_herramientas()
        self.assertEqual({h["name"] for h in listado}, self.ESPERADAS)
        self.assertTrue(all(h["description"] for h in listado))

    def test_obtener_herramienta(self):
        self.assertIs(tool_catalog.obtener_herramienta("buscar_lugares"), prov_turismo.buscar_lugares)
        for nombre in ("inexistente", "__import__", None, 3):
            with self.assertRaises(KeyError):
                tool_catalog.obtener_herramienta(nombre)

    def test_ejecutar_despacha(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_lugares", {"q": "Kotosh"})

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["tool"], "buscar_lugares")
        self.assertEqual(resultado["count"], 1)

    def test_rechaza_fuera_del_registro(self):
        for nombre in ("eval", "__import__", None):
            resultado = tool_catalog.ejecutar_herramienta(nombre, {})
            self.assertEqual((resultado["ok"], resultado["error"]), (False, "herramienta_desconocida"))

    def test_argumentos_deben_ser_dict(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_lugares", ["Kotosh"])

        self.assertEqual(resultado["error"], "argumentos_invalidos")

    def test_argumentos_desconocidos_e_invalidos_controlados(self):
        desconocido = tool_catalog.ejecutar_herramienta("buscar_lugares", {"sql": "DROP"})
        self.assertEqual(desconocido["error"], "argumentos_invalidos")

        invalido = tool_catalog.ejecutar_herramienta("buscar_lugares", {"limit": 99})
        self.assertEqual(invalido["error"], "argumento_invalido")
        self.assertIn("limit", invalido["detail"])

        faltante = tool_catalog.ejecutar_herramienta("obtener_lugar", {})
        self.assertEqual(faltante["error"], "argumentos_invalidos")

    def test_errores_inesperados_no_se_disfrazan(self):
        with patch.dict(tool_catalog.TOOL_REGISTRY, {"buscar_lugares": (lambda **kw: 1 / 0, "x")}):
            with self.assertRaises(ZeroDivisionError):
                tool_catalog.ejecutar_herramienta("buscar_lugares", {})


class SerializacionProvidersTests(ProvidersDataMixin, TestCase):
    def test_resultados_son_json_serializables(self):
        resultados = [
            prov_turismo.buscar_lugares(),
            prov_turismo.obtener_lugar("kotosh"),
            prov_ubicaciones.buscar_ubicaciones("Tingo"),
            prov_establecimientos.obtener_establecimiento("restaurante-huanuqueno"),
            prov_establecimientos.buscar_restaurantes_por_plato("pachamanca"),
            prov_gastronomia.obtener_plato("pachamanca"),
            prov_eventos.buscar_eventos(limit=10),
            prov_eventos.obtener_evento("concierto"),
            prov_movilidad.consultar_tarifas_movilidad(),
            prov_movilidad.consultar_como_llegar(),
            prov_servicios.consultar_servicios_utiles(),
            prov_servicios.consultar_emergencias(),
            prov_servicios.consultar_tipo_cambio(),
            tool_catalog.ejecutar_herramienta("buscar_lugares", {"limit": 99}),
        ]
        for resultado in resultados:
            json.dumps(resultado)  # sin encoder custom: falla si escapa Decimal/date/Model


# ---------------------------------------------------------------------------
# C4 — integración real con Gemini (Interactions API, sin red en tests)
# ---------------------------------------------------------------------------

CLAVE_PRUEBA = "clave-de-prueba-no-real"


def interaccion_falsa(texto=None, llamadas=(), id="int-1", status="completed"):
    pasos = [
        SimpleNamespace(type="function_call", id=f"call-{i}", name=nombre, arguments=args)
        for i, (nombre, args) in enumerate(llamadas)
    ]
    return SimpleNamespace(id=id, status=status, output_text=texto, steps=pasos, usage=None)


@override_settings(CHATBOT_AI_PROVIDER="gemini")
class ConfiguracionGeminiTests(TestCase):
    def setUp(self):
        llm_client._cache.update(config=None, cliente=None)

    @override_settings(CHATBOT_AI_API_KEY="")
    def test_key_ausente_es_error_controlado(self):
        with self.assertRaises(llm_client.ChatbotNoConfigurado):
            llm_client.obtener_cliente()

    @override_settings(CHATBOT_AI_API_KEY="")
    def test_endpoint_sin_key_devuelve_503_seguro(self):
        respuesta = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "Hola"}, content_type="application/json"
        )

        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.json(), {"ok": False, "error": "chatbot_no_disponible"})
        self.assertNotIn("CHATBOT_AI_API_KEY", respuesta.content.decode())
        self.assertEqual(Mensaje.objects.count(), 0)

    @override_settings(CHATBOT_AI_PROVIDER="openai", CHATBOT_AI_API_KEY=CLAVE_PRUEBA)
    def test_provider_no_soportado_es_error_controlado(self):
        with self.assertRaises(llm_client.ChatbotNoConfigurado):
            llm_client.obtener_cliente()

    @override_settings(
        CHATBOT_AI_API_KEY=CLAVE_PRUEBA, CHATBOT_AI_MODEL="gemini-x-prueba", CHATBOT_AI_TIMEOUT_MS=12345
    )
    def test_modelo_timeout_y_api_version_configurados(self):
        with patch.object(llm_client.genai, "Client") as Cliente:
            Cliente.return_value.interactions.create.return_value = interaccion_falsa("ok")
            llm_client.crear_interaccion(input="hola")
            llm_client.crear_interaccion(input="otra vez")

        Cliente.assert_called_once()
        self.assertEqual(Cliente.call_args.kwargs["api_key"], CLAVE_PRUEBA)
        http_options = Cliente.call_args.kwargs["http_options"]
        self.assertEqual(http_options.timeout, 12345)
        self.assertEqual(http_options.api_version, llm_client.API_VERSION)
        create = Cliente.return_value.interactions.create
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args.kwargs["model"], "gemini-x-prueba")

    @override_settings(CHATBOT_AI_API_KEY=CLAVE_PRUEBA)
    def test_errores_del_proveedor_se_traducen_sin_filtrar_la_key(self):
        casos = [
            (httpx.ReadTimeout("lento"), llm_client.ProveedorIATimeout),
            (httpx.ConnectError("sin red"), llm_client.ProveedorIAError),
            (genai_errors.ServerError(503, {"error": {"message": CLAVE_PRUEBA}}), llm_client.ProveedorIAError),
        ]
        for excepcion, esperada in casos:
            with patch.object(llm_client.genai, "Client") as Cliente:
                Cliente.return_value.interactions.create.side_effect = excepcion
                llm_client._cache.update(config=None, cliente=None)
                with self.assertRaises(esperada) as ctx:
                    llm_client.crear_interaccion(input="hola")
            self.assertNotIn(CLAVE_PRUEBA, str(ctx.exception))


class DefaultsGeminiTests(TestCase):
    def test_defaults_en_settings_base(self):
        fuente = (settings.BASE_DIR / "config" / "settings" / "base.py").read_text(encoding="utf-8")

        self.assertIn('env("CHATBOT_AI_MODEL", default="gemini-3.6-flash")', fuente)
        self.assertIn('env.int("CHATBOT_AI_TIMEOUT_MS", default=60000)', fuente)
        self.assertIn('env("CHATBOT_AI_THINKING_LEVEL", default="low")', fuente)
        self.assertNotIn("gemini-2.5-flash", fuente)

    def test_el_modelo_antiguo_no_vuelve_como_default(self):
        fuente = (settings.BASE_DIR / "config" / "settings" / "base.py").read_text(encoding="utf-8")

        self.assertNotIn('default="gemini-2.5-flash"', fuente)
        self.assertIn("gemini-3.6-flash", fuente)


class ThinkingLevelTests(TestCase):
    @override_settings(CHATBOT_AI_THINKING_LEVEL="low")
    def test_default_low_llega_a_generation_config(self):
        self.assertEqual(
            llm_client.configuracion_generacion(), {"tool_choice": "auto", "thinking_level": "low"}
        )

    @override_settings(CHATBOT_AI_THINKING_LEVEL="medium")
    def test_configurable(self):
        self.assertEqual(llm_client.configuracion_generacion()["thinking_level"], "medium")

    @override_settings(CHATBOT_AI_THINKING_LEVEL="turbo")
    def test_invalido_es_error_controlado(self):
        with self.assertRaises(llm_client.ChatbotNoConfigurado):
            llm_client.configuracion_generacion()

    @override_settings(CHATBOT_AI_PROVIDER="gemini", CHATBOT_AI_API_KEY=CLAVE_PRUEBA, CHATBOT_AI_THINKING_LEVEL="turbo")
    def test_invalido_en_endpoint_devuelve_503(self):
        with patch.object(llm_client, "crear_interaccion") as crear:
            respuesta = self.client.post(
                reverse("chatbot:enviar_mensaje"), data={"mensaje": "Hola"}, content_type="application/json"
            )

        crear.assert_not_called()
        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.json(), {"ok": False, "error": "chatbot_no_disponible"})
        self.assertEqual(Mensaje.objects.count(), 0)


@override_settings(CHATBOT_AI_PROVIDER="gemini")
class ErroresPrivadosSdkTests(TestCase):
    """La jerarquía de errores de Interactions solo existe en una ruta privada del SDK 2.23.0."""

    def setUp(self):
        llm_client._cache.update(config=None, cliente=None)
        self.peticion = httpx.Request("POST", "https://proveedor.invalid/v1beta/interactions")

    def _ejecutar_con(self, excepcion):
        with patch.object(llm_client.genai, "Client") as Cliente:
            Cliente.return_value.interactions.create.side_effect = excepcion
            with override_settings(CHATBOT_AI_API_KEY=CLAVE_PRUEBA):
                llm_client.crear_interaccion(input="hola")

    def test_timeout_privado_se_clasifica_como_timeout(self):
        from google.genai._gaos.lib import compat_errors

        with self.assertRaises(llm_client.ProveedorIATimeout):
            self._ejecutar_con(compat_errors.APITimeoutError(request=self.peticion))

    def test_status_y_conexion_privados_se_clasifican_como_error_de_proveedor(self):
        from google.genai._gaos.lib import compat_errors

        respuesta = httpx.Response(500, request=self.peticion)
        for excepcion in (
            compat_errors.InternalServerError("caido", response=respuesta, body=None),
            compat_errors.APIConnectionError(request=self.peticion),
        ):
            with self.assertRaises(llm_client.ProveedorIAError) as ctx:
                self._ejecutar_con(excepcion)
            self.assertNotIsInstance(ctx.exception, (llm_client.ProveedorIATimeout, llm_client.ProveedorIARateLimit))
            self.assertNotIn("proveedor.invalid", str(ctx.exception))

    def test_429_privado_y_publico_se_clasifican_como_rate_limit(self):
        from google.genai._gaos.lib import compat_errors

        respuesta = httpx.Response(429, request=self.peticion, headers={"retry-after": "30"})
        for excepcion in (
            compat_errors.RateLimitError(f"cuota {CLAVE_PRUEBA}", response=respuesta, body={"error": "x"}),
            genai_errors.ClientError(429, {"error": {"message": "quota exceeded"}}),
        ):
            with self.assertLogs("apps.chatbot.services.llm_client", level="DEBUG") as logs:
                with self.assertRaises(llm_client.ProveedorIARateLimit) as ctx:
                    self._ejecutar_con(excepcion)
            self.assertIsInstance(ctx.exception, llm_client.ProveedorIAError)
            self.assertNotIn(CLAVE_PRUEBA, str(ctx.exception))
            self.assertNotIn("proveedor.invalid", str(ctx.exception))
            self.assertTrue(any("chatbot_ai_rate_limit" in linea for linea in logs.output))
            self.assertFalse(any(CLAVE_PRUEBA in linea for linea in logs.output))

    def test_fallback_publico_sigue_cubriendo_timeouts(self):
        with self.assertRaises(llm_client.ProveedorIATimeout):
            self._ejecutar_con(TimeoutError("socket"))


@override_settings(CHATBOT_AI_PROVIDER="gemini")
class RetryPolicyTests(TestCase):
    def setUp(self):
        llm_client._cache.update(config=None, cliente=None)

    def test_politica_explicita_y_breve(self):
        opciones = llm_client.opciones_http(60000).retry_options

        self.assertEqual(opciones.attempts, 1)
        self.assertEqual(opciones.initial_delay, 1.0)
        self.assertEqual(opciones.max_delay, 2.0)
        self.assertIsNone(opciones.http_status_codes)  # conjunto estándar del SDK (408/409/429/5XX)

    def test_el_sdk_traduce_a_maximo_dos_solicitudes(self):
        from google.genai._gaos.google_genai import _translate_retry_config

        config = _translate_retry_config(llm_client.opciones_http(60000))

        self.assertEqual(config.max_retries, 1)  # 1 reintento → 2 solicitudes en total
        self.assertEqual(config.backoff.initial_interval, 1000)
        self.assertEqual(config.backoff.max_interval, 2000)

    @override_settings(CHATBOT_AI_API_KEY=CLAVE_PRUEBA, CHATBOT_AI_TIMEOUT_MS=60000)
    def test_el_cliente_recibe_la_politica(self):
        with patch.object(llm_client.genai, "Client") as Cliente:
            Cliente.return_value.interactions.create.return_value = interaccion_falsa("ok")
            llm_client.crear_interaccion(input="hola")

        http_options = Cliente.call_args.kwargs["http_options"]
        self.assertEqual(http_options.api_version, "v1beta")
        self.assertEqual(http_options.timeout, 60000)
        self.assertEqual(http_options.retry_options.attempts, llm_client.RETRY_ATTEMPTS)


class SystemPromptTests(TestCase):
    def test_contiene_reglas_esenciales(self):
        prompt = system_prompt.construir_system_prompt()

        for fragmento in ("Pillco Bot", "Huánuco", "herramientas", "No reveles", "no inventes"):
            self.assertIn(fragmento, prompt)
        self.assertIn(timezone.localdate().isoformat(), prompt)

    def test_fecha_local_explicita(self):
        self.assertIn("2026-01-02", system_prompt.construir_system_prompt(date(2026, 1, 2)))


class GeminiToolsTests(TestCase):
    def test_declaraciones_coinciden_con_el_registro(self):
        declaraciones = gemini_tools.declaraciones_gemini()

        self.assertEqual(len(declaraciones), 19)
        self.assertEqual({d["name"] for d in declaraciones}, set(tool_catalog.TOOL_REGISTRY))
        self.assertTrue(all(d["type"] == "function" and d["description"] for d in declaraciones))

    def test_schemas_reflejan_las_firmas_reales(self):
        for declaracion in gemini_tools.declaraciones_gemini():
            funcion = tool_catalog.obtener_herramienta(declaracion["name"])
            # C8: los keyword-only (`usuario`, contexto seguro del backend) nunca se exponen al modelo.
            parametros = {
                n: p for n, p in inspect.signature(funcion).parameters.items()
                if p.kind is not inspect.Parameter.KEYWORD_ONLY
            }
            esquema = declaracion["parameters"]
            self.assertEqual(set(esquema["properties"]), set(parametros), declaracion["name"])
            obligatorios = [n for n, p in parametros.items() if p.default is inspect.Parameter.empty]
            self.assertEqual(esquema["required"], obligatorios, declaracion["name"])

    def test_enums_usan_choices_reales(self):
        esquemas = {d["name"]: d["parameters"]["properties"] for d in gemini_tools.declaraciones_gemini()}

        self.assertEqual(esquemas["buscar_lugares"]["tipo_costo"]["enum"], [c[0] for c in TIPO_COSTO_CHOICES])
        self.assertEqual(esquemas["consultar_clima"]["ciudad"]["enum"], ["huanuco", "tingo-maria"])
        self.assertEqual(esquemas["buscar_eventos"]["tags"]["type"], "array")
        self.assertEqual(esquemas["buscar_lugares"]["limit"]["maximum"], 10)

    def test_declaraciones_validas_para_el_sdk(self):
        for declaracion in gemini_tools.declaraciones_gemini():
            json.dumps(declaracion)
            funcion = genai_interactions.Function.model_validate(declaracion)
            self.assertEqual(funcion.name, declaracion["name"])


class ContextBuilderTests(TestCase):
    def test_historial_limitado_y_cronologico(self):
        conversacion = Conversacion.objects.create(session_key="s-historial")
        for i in range(12):
            Mensaje.objects.create(
                conversacion=conversacion,
                rol=Mensaje.Rol.USUARIO if i % 2 == 0 else Mensaje.Rol.ASISTENTE,
                contenido=f"m{i}",
            )

        historial = context_builder.construir_historial(conversacion)

        self.assertEqual(len(historial), context_builder.MAX_HISTORY_MESSAGES)
        self.assertEqual([m["contenido"] for m in historial], [f"m{i}" for i in range(4, 12)])
        self.assertEqual(set(historial[0]), {"rol", "contenido"})

    def test_input_termina_con_el_mensaje_actual(self):
        historial = [
            {"rol": Mensaje.Rol.USUARIO, "contenido": "¿Qué lugares hay?"},
            {"rol": Mensaje.Rol.ASISTENTE, "contenido": "Kotosh y la Cueva."},
        ]

        pasos = context_builder.construir_input(historial, "¿Y cuáles son gratis?")

        self.assertEqual([p["type"] for p in pasos], ["user_input", "model_output", "user_input"])
        self.assertEqual(pasos[-1]["content"], [{"type": "text", "text": "¿Y cuáles son gratis?"}])


class GeminiSimuladoMixin(ProvidersDataMixin):
    def setUp(self):
        super().setUp()
        self.conversacion = Conversacion.objects.create(session_key="s-gemini")
        # Hermético: el proveedor no puede depender del .env local (si este
        # dice deepseek, el mock de Gemini no intercepta y se llamaría a la API real).
        ajustes = override_settings(
            CHATBOT_AI_PROVIDER="gemini", CHATBOT_AI_THINKING_LEVEL="low", CHATBOT_EXTERNAL_SEARCH_ENABLED=False
        )
        ajustes.enable()
        self.addCleanup(ajustes.disable)
        patcher = patch.object(llm_client, "crear_interaccion")
        self.crear = patcher.start()
        self.addCleanup(patcher.stop)

    def responder(self, *interacciones):
        self.crear.side_effect = list(interacciones)

    def turno(self, mensaje):
        return chatbot_service.procesar_turno(self.conversacion, mensaje)


class ToolCallingTests(GeminiSimuladoMixin, TestCase):
    def test_sin_tool_responde_directo(self):
        self.responder(interaccion_falsa("¡Hola! Soy Pillco Bot."))

        with patch.object(tool_catalog, "ejecutar_herramienta") as ejecutar:
            _, respuesta = self.turno("Hola")

        ejecutar.assert_not_called()
        self.crear.assert_called_once()
        kwargs = self.crear.call_args.kwargs
        self.assertEqual(kwargs["input"][-1], {"type": "user_input", "content": [{"type": "text", "text": "Hola"}]})
        self.assertIn("Pillco Bot", kwargs["system_instruction"])
        self.assertEqual(len(kwargs["tools"]), 19)
        self.assertEqual(kwargs["generation_config"], {"tool_choice": "auto", "thinking_level": "low"})
        self.assertEqual(respuesta.contenido, "¡Hola! Soy Pillco Bot.")
        self.assertEqual(respuesta.tipo_fuente, "")

    def test_todas_las_rondas_reenvian_la_misma_configuracion(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"limit": 99})], id="int-1"),
            interaccion_falsa(llamadas=[("buscar_lugares", {"limit": 5})], id="int-2"),
            interaccion_falsa("Estos son los lugares.", id="int-3"),
        )

        self.turno("Muéstrame lugares")

        self.assertEqual(self.crear.call_count, 3)
        for numero, llamada in enumerate(self.crear.call_args_list, start=1):
            kwargs = llamada.kwargs
            self.assertEqual(kwargs["generation_config"]["thinking_level"], "low", numero)
            self.assertEqual(kwargs["generation_config"]["tool_choice"], "auto", numero)
            self.assertEqual(len(kwargs["tools"]), 19, numero)
            self.assertIn("Pillco Bot", kwargs["system_instruction"], numero)
            if numero > 1:
                self.assertEqual(kwargs["previous_interaction_id"], f"int-{numero - 1}")
            else:
                self.assertNotIn("previous_interaction_id", kwargs)

    def test_latencia_se_registra_sin_payloads(self):
        mensaje = "¿Dónde puedo comer pachamanca en Huánuco?"
        self.responder(
            interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "pachamanca"})]),
            interaccion_falsa("En el Restaurante Huanuqueño."),
        )

        with self.assertLogs("apps.chatbot.services.chatbot_service", level="DEBUG") as logs:
            self.turno(mensaje)

        prefijos = [linea.split(":")[-1].split(" ")[0] for linea in logs.output]
        self.assertEqual(prefijos, ["chatbot_ai_round", "chatbot_tool", "chatbot_turn"])
        self.assertIn("ruta=simple", logs.output[-1])
        for linea in logs.output:
            self.assertIn("ms=", linea)
            self.assertNotIn(mensaje, linea)
            self.assertNotIn("Huanuqueño", linea)

    def test_una_tool_direct_render_es_simple_path(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"tipo_costo": "gratis"})], id="int-1"),
            interaccion_falsa("(no debería usarse)", id="int-2"),
        )

        with patch.object(tool_catalog, "ejecutar_herramienta", wraps=tool_catalog.ejecutar_herramienta) as ejecutar:
            _, respuesta = self.turno("¿Qué lugares turísticos gratuitos hay?")

        ejecutar.assert_called_once_with("buscar_lugares", {"tipo_costo": "gratis"})
        self.assertEqual(self.crear.call_count, 1)  # renderer backend, sin segunda llamada
        self.assertIn("Cueva de las Lechuzas", respuesta.contenido)
        self.assertIn("entrada gratuita", respuesta.contenido)
        self.assertEqual(respuesta.tipo_fuente, "internal")
        self.assertEqual(Mensaje.objects.count(), 2)

    def test_tool_no_renderizable_pasa_por_el_registro_y_vuelve_al_modelo(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_ubicaciones", {"q": "Tingo"})], id="int-1"),
            interaccion_falsa("Tingo María está en el distrito de Rupa-Rupa.", id="int-2"),
        )

        with patch.object(tool_catalog, "ejecutar_herramienta", wraps=tool_catalog.ejecutar_herramienta) as ejecutar:
            _, respuesta = self.turno("¿Dónde queda Tingo María?")

        ejecutar.assert_called_once_with("buscar_ubicaciones", {"q": "Tingo"})
        segunda = self.crear.call_args_list[1].kwargs
        self.assertEqual(segunda["previous_interaction_id"], "int-1")
        resultado = segunda["input"][0]
        self.assertEqual((resultado["type"], resultado["call_id"], resultado["name"], resultado["is_error"]),
                         ("function_result", "call-0", "buscar_ubicaciones", False))
        self.assertEqual(json.loads(resultado["result"])["items"][0]["nombre"], "Tingo María")
        self.assertEqual(respuesta.contenido, "Tingo María está en el distrito de Rupa-Rupa.")
        self.assertEqual(respuesta.tipo_fuente, "internal")
        self.assertEqual(Mensaje.objects.count(), 2)

    def test_varias_tools_en_un_turno_son_mixed(self):
        self.responder(
            interaccion_falsa(llamadas=[
                ("buscar_lugares", {"distrito": "rupa-rupa"}),
                ("consultar_clima", {"ciudad": "tingo-maria"}),
            ]),
            interaccion_falsa("Puedes visitar la Cueva; el clima está nublado."),
        )
        clima = {"disponible": True, "temperatura_c": 25.0, "estado_texto": "Nublado", "fuente": "Open-Meteo"}

        with patch.object(prov_servicios, "obtener_clima_actual", return_value=clima):
            _, respuesta = self.turno("¿Qué puedo visitar en Tingo María y cómo está el clima?")

        resultados = self.crear.call_args_list[1].kwargs["input"]
        self.assertEqual([r["name"] for r in resultados], ["buscar_lugares", "consultar_clima"])
        self.assertEqual(respuesta.tipo_fuente, "mixed")

    def test_solo_clima_es_external_trusted(self):
        self.responder(
            interaccion_falsa(llamadas=[("consultar_clima", {})]),
            interaccion_falsa("En Huánuco hay 20 grados."),
        )

        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": True, "temperatura_c": 20.0}):
            _, respuesta = self.turno("¿Cómo está el clima?")

        self.assertEqual(respuesta.tipo_fuente, "external_trusted")

    def test_sin_resultados_es_no_evidence(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"q": "parque de bicicletas"})]),
            interaccion_falsa("No tengo información suficiente en este momento para confirmarte ese dato."),
        )

        _, respuesta = self.turno("¿Hay alquiler de bicicletas cerca de Kotosh?")

        self.assertEqual(self.crear.call_count, 1)  # ausencia factual sin segunda llamada
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)

    def test_argumentos_invalidos_vuelven_al_modelo_y_puede_corregir(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"limit": 99})], id="int-1"),
            interaccion_falsa(llamadas=[("buscar_lugares", {"limit": 5})], id="int-2"),
            interaccion_falsa("Estos son los lugares.", id="int-3"),
        )

        _, respuesta = self.turno("Muéstrame lugares")

        primero = self.crear.call_args_list[1].kwargs["input"][0]
        self.assertTrue(primero["is_error"])
        self.assertEqual(json.loads(primero["result"])["error"], "argumento_invalido")
        segundo = self.crear.call_args_list[2].kwargs["input"][0]
        self.assertFalse(segundo["is_error"])
        self.assertEqual(self.crear.call_args_list[2].kwargs["previous_interaction_id"], "int-2")
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_tool_no_registrada_no_se_ejecuta(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_hoteles_secretos", {"zona": "x"})]),
            interaccion_falsa("No dispongo de esa herramienta."),
        )

        _, respuesta = self.turno("Busca hoteles secretos")

        resultado = self.crear.call_args_list[1].kwargs["input"][0]
        self.assertTrue(resultado["is_error"])
        self.assertEqual(json.loads(resultado["result"])["error"], "herramienta_desconocida")
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_max_tool_rounds_corta_el_ciclo(self):
        self.crear.side_effect = lambda **kwargs: interaccion_falsa(llamadas=[("buscar_ubicaciones", {"q": "x"})])

        with self.assertRaises(chatbot_service.OrquestacionError):
            self.turno("Necesito varias ubicaciones")

        self.assertEqual(self.crear.call_count, chatbot_service.MAX_TOOL_ROUNDS + 1)
        self.assertEqual(Mensaje.objects.count(), 0)

    def test_interaccion_fallida_o_vacia_es_error_controlado(self):
        self.responder(interaccion_falsa(status="failed"))
        with self.assertRaises(llm_client.ProveedorIAError):
            self.turno("Hola")

        self.responder(interaccion_falsa("   "))
        with self.assertRaises(chatbot_service.OrquestacionError):
            self.turno("Hola")

        self.assertEqual(Mensaje.objects.count(), 0)

    def test_error_inesperado_de_provider_se_propaga(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_lugares", {})]))

        with patch.object(tool_catalog, "ejecutar_herramienta", side_effect=RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                self.turno("Lugares")

        self.assertEqual(Mensaje.objects.count(), 0)

    def test_llamada_remota_fuera_de_la_transaccion(self):
        profundidad_base = len(connection.savepoint_ids)
        profundidades = []

        def registrar(**kwargs):
            profundidades.append(len(connection.savepoint_ids))
            return interaccion_falsa("Hola")

        self.crear.side_effect = registrar
        self.turno("Hola")

        self.assertEqual(profundidades, [profundidad_base])
        self.assertEqual(Mensaje.objects.count(), 2)

    def test_contexto_reciente_se_envia_en_el_siguiente_turno(self):
        self.responder(interaccion_falsa("Kotosh y la Cueva de las Lechuzas."))
        self.turno("¿Qué lugares hay en Tingo María?")

        self.responder(interaccion_falsa("Solo la Cueva es gratuita."))
        self.turno("¿Y cuáles son gratis?")

        entrada = self.crear.call_args_list[1].kwargs["input"]
        textos = [(p["type"], p["content"][0]["text"]) for p in entrada]
        self.assertEqual(textos, [
            ("user_input", "¿Qué lugares hay en Tingo María?"),
            ("model_output", "Kotosh y la Cueva de las Lechuzas."),
            ("user_input", "¿Y cuáles son gratis?"),
        ])


class EnviarMensajeErroresProveedorTests(EnviarMensajeMixin, TestCase):
    def assert_error(self, excepcion, status, codigo):
        self.generar_respuesta_mock.side_effect = excepcion

        respuesta = self.enviar("Hola")

        self.assertEqual(respuesta.status_code, status)
        self.assertEqual(respuesta.json(), {"ok": False, "error": codigo})
        self.assertNotIn(CLAVE_PRUEBA, respuesta.content.decode())
        self.assertNotIn("Traceback", respuesta.content.decode())
        self.assertEqual(Mensaje.objects.count(), 0)
        self.assertEqual(Conversacion.objects.count(), 1)

    def test_sin_configuracion_503(self):
        self.assert_error(llm_client.ChatbotNoConfigurado("CHATBOT_AI_API_KEY no configurada"), 503, "chatbot_no_disponible")

    def test_timeout_504(self):
        self.assert_error(llm_client.ProveedorIATimeout(CLAVE_PRUEBA), 504, "proveedor_ia_timeout")

    def test_rate_limit_503_no_disponible(self):
        with self.assertLogs("apps.chatbot.views", level="WARNING") as logs:
            self.assert_error(llm_client.ProveedorIARateLimit("RateLimitError status=429"), 503, "chatbot_no_disponible")
        self.assertTrue(any("chatbot_ai_rate_limit" in linea for linea in logs.output))

    def test_error_proveedor_502(self):
        self.assert_error(llm_client.ProveedorIAError("APIError status=500"), 502, "proveedor_ia_error")

    def test_error_orquestacion_502(self):
        self.assert_error(chatbot_service.OrquestacionError("rondas_agotadas"), 502, "proveedor_ia_error")

    def test_error_interno_500_sin_traceback(self):
        self.assert_error(RuntimeError(f"bug con {CLAVE_PRUEBA}"), 500, "error_interno")

    def test_respuesta_exitosa_incluye_tipo_fuente_calculado(self):
        self.generar_respuesta_mock.return_value = ("Kotosh es pagado.", "internal", None)

        datos = self.enviar("¿Kotosh es gratis?").json()

        self.assertEqual(datos["respuesta"]["tipo_fuente"], "internal")
        self.assertEqual(set(datos), {"ok", "conversation_id", "respuesta"})


# ---------------------------------------------------------------------------
# C4.3 — arquitectura híbrida: schemas neutrales, DeepSeek, quick actions,
# renderers, Simple/Complex Path
# ---------------------------------------------------------------------------

CLAVE_DEEPSEEK_PRUEBA = "clave-deepseek-de-prueba-no-real"
URL_DEEPSEEK = f"{deepseek_client.BASE_URL}{deepseek_client.RUTA_RESPONSES}"


def respuesta_http(status=200, cuerpo=None, texto=None, headers=None):
    peticion = httpx.Request("POST", URL_DEEPSEEK)
    if texto is not None:
        return httpx.Response(status, text=texto, request=peticion, headers=headers)
    return httpx.Response(status, json=cuerpo, request=peticion, headers=headers)


REASONING_PRUEBA = "razonamiento-interno-de-prueba-no-visible"


def salida_deepseek(texto=None, llamadas=(), usage=None, id="resp-1", reasoning=REASONING_PRUEBA, call_ids=None):
    # Forma real de la Responses API: reasoning con `content` reasoning_text,
    # function_call con `id`/`status` internos además de call_id.
    output = [{
        "type": "reasoning", "id": f"rs-{id}", "status": "completed", "summary": [],
        "content": [{"type": "reasoning_text", "text": reasoning}],
    }] if reasoning is not None else []
    for i, (nombre, argumentos) in enumerate(llamadas):
        output.append({
            "type": "function_call", "id": f"fc-{id}-{i}", "status": "completed",
            "call_id": call_ids[i] if call_ids else f"call-{i}", "name": nombre,
            "arguments": argumentos if isinstance(argumentos, str) else json.dumps(argumentos),
        })
    if texto is not None:
        output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": texto}]})
    return {
        "id": id,
        "output": output,
        "usage": usage or {
            "input_tokens": 120, "output_tokens": 30,
            "input_tokens_details": {"cached_tokens": 64},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


class ToolSchemasTests(TestCase):
    def test_una_sola_fuente_neutral_para_ambos_proveedores(self):
        self.assertEqual(set(tool_schemas.TOOL_SCHEMAS), set(tool_catalog.TOOL_REGISTRY))
        gemini = gemini_tools.declaraciones_gemini()
        deepseek = deepseek_client.declaraciones_deepseek()
        self.assertEqual(len(gemini), 19)
        self.assertEqual(len(deepseek), 19)
        self.assertEqual(gemini, deepseek)  # sin drift: misma definición
        self.assertEqual({d["name"] for d in gemini}, set(tool_catalog.TOOL_REGISTRY))
        for schema in tool_schemas.TOOL_SCHEMAS.values():
            self.assertTrue(schema["description"])
            self.assertEqual(schema["parameters"]["type"], "object")


class ProviderSelectorTests(TestCase):
    @override_settings(CHATBOT_AI_PROVIDER="gemini")
    def test_gemini(self):
        self.assertIs(ai_provider.obtener_proveedor_activo(), llm_client)

    @override_settings(CHATBOT_AI_PROVIDER="deepseek")
    def test_deepseek(self):
        self.assertIs(ai_provider.obtener_proveedor_activo(), deepseek_client)

    @override_settings(CHATBOT_AI_PROVIDER="openai")
    def test_invalido(self):
        with self.assertRaises(llm_client.ChatbotNoConfigurado):
            ai_provider.obtener_proveedor_activo()

    @override_settings(CHATBOT_AI_PROVIDER="deepseek", CHATBOT_DEEPSEEK_API_KEY="")
    def test_deepseek_sin_key_solo_falla_si_esta_seleccionado(self):
        with patch.object(deepseek_client.httpx, "request") as request:
            with self.assertRaises(llm_client.ChatbotNoConfigurado):
                deepseek_client.iniciar_turno("sys", [], "Hola")
        request.assert_not_called()

        respuesta = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "Hola"}, content_type="application/json"
        )
        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.json(), {"ok": False, "error": "chatbot_no_disponible"})
        self.assertEqual(Mensaje.objects.count(), 0)

    @override_settings(CHATBOT_AI_PROVIDER="gemini", CHATBOT_DEEPSEEK_API_KEY="")
    def test_gemini_funciona_sin_key_deepseek(self):
        conversacion = Conversacion.objects.create(session_key="s-sel")
        with patch.object(llm_client, "crear_interaccion", return_value=interaccion_falsa("Hola")):
            texto, tipo_fuente, presentacion = chatbot_service.generar_respuesta(conversacion, "Hola")
        self.assertEqual((texto, tipo_fuente, presentacion), ("Hola", "", None))


@override_settings(
    CHATBOT_AI_PROVIDER="deepseek", CHATBOT_DEEPSEEK_API_KEY=CLAVE_DEEPSEEK_PRUEBA,
    CHATBOT_DEEPSEEK_MODEL="deepseek-v4-flash", CHATBOT_AI_TIMEOUT_MS=60000,
)
class DeepSeekClientTests(TestCase):
    def setUp(self):
        patcher = patch.object(deepseek_client.httpx, "request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def cuerpo_enviado(self, indice=0):
        return self.request.call_args_list[indice].kwargs["json"]

    def test_peticion_stateless_con_instrucciones_tools_y_reasoning_none(self):
        self.request.return_value = respuesta_http(cuerpo=salida_deepseek("¡Hola! Soy Pillco Bot."))
        historial = [
            {"rol": Mensaje.Rol.USUARIO, "contenido": "Hola"},
            {"rol": Mensaje.Rol.ASISTENTE, "contenido": "¡Hola!"},
        ]

        estado, respuesta = deepseek_client.iniciar_turno("SYSTEM", historial, "¿Qué visito?")

        self.request.assert_called_once()
        args, kwargs = self.request.call_args
        self.assertEqual(args, ("POST", URL_DEEPSEEK))
        self.assertEqual(kwargs["timeout"], 60.0)
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {CLAVE_DEEPSEEK_PRUEBA}")
        cuerpo = kwargs["json"]
        self.assertEqual(cuerpo["model"], "deepseek-v4-flash")
        self.assertEqual(cuerpo["instructions"], "SYSTEM")
        self.assertEqual(cuerpo["input"], [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¡Hola!"},
            {"role": "user", "content": "¿Qué visito?"},
        ])
        self.assertEqual(len(cuerpo["tools"]), 19)
        self.assertEqual(cuerpo["tool_choice"], "auto")
        self.assertEqual(cuerpo["reasoning"], {"effort": "low"})
        self.assertNotIn("previous_response_id", cuerpo)
        self.assertNotIn("conversation", cuerpo)
        self.assertNotIn("store", cuerpo)
        self.assertEqual(respuesta["texto"], "¡Hola! Soy Pillco Bot.")
        self.assertEqual(respuesta["tool_calls"], [])
        self.assertEqual(respuesta["usage"], {"input_tokens": 120, "output_tokens": 30, "cached_tokens": 64, "reasoning_tokens": 0})

    def test_function_calls_y_continuacion_con_call_id(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_lugares", {"q": "Kotosh"}), ("consultar_clima", {})])),
            respuesta_http(cuerpo=salida_deepseek("Kotosh y clima.", id="resp-2")),
        ]

        estado, respuesta = deepseek_client.iniciar_turno("SYSTEM", [], "Kotosh y clima")
        self.assertEqual([(c["id"], c["name"], c["arguments"]) for c in respuesta["tool_calls"]],
                         [("call-0", "buscar_lugares", {"q": "Kotosh"}), ("call-1", "consultar_clima", {})])

        resultados = [
            {"call_id": "call-0", "name": "buscar_lugares", "result": {"ok": True, "count": 1}, "is_error": False},
            {"call_id": "call-1", "name": "consultar_clima", "result": {"ok": True, "item": {}}, "is_error": False},
        ]
        estado, final = deepseek_client.continuar_turno(estado, resultados)

        cuerpo = self.cuerpo_enviado(1)
        self.assertEqual(cuerpo["reasoning"], {"effort": "low"})
        tipos = [(item.get("type"), item.get("call_id")) for item in cuerpo["input"]]
        self.assertEqual(tipos, [
            (None, None),                       # mensaje del usuario
            ("reasoning", None),
            ("function_call", "call-0"), ("function_call", "call-1"),
            ("function_call_output", "call-0"), ("function_call_output", "call-1"),
        ])
        self.assertEqual(json.loads(cuerpo["input"][4]["output"]), {"ok": True, "count": 1})
        self.assertEqual(final["texto"], "Kotosh y clima.")

    def test_arguments_json_invalido_no_se_ejecuta(self):
        self.request.return_value = respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_lugares", "{no json")]))

        _, respuesta = deepseek_client.iniciar_turno("SYSTEM", [], "x")

        self.assertIsNone(respuesta["tool_calls"][0]["arguments"])
        conversacion = Conversacion.objects.create(session_key="s-ds-args")
        with patch.object(tool_catalog, "ejecutar_herramienta") as ejecutar:
            resultados, pasos = chatbot_service._ejecutar_llamadas(respuesta["tool_calls"], conversacion)
        ejecutar.assert_not_called()
        self.assertEqual(resultados[0]["error"], "argumentos_invalidos")
        self.assertTrue(pasos[0]["is_error"])

    def test_errores_http_se_traducen_sin_filtrar_la_key(self):
        casos = [
            (respuesta_http(401, cuerpo={"error": {"message": CLAVE_DEEPSEEK_PRUEBA}}), llm_client.ChatbotNoConfigurado),
            (respuesta_http(402, cuerpo={"error": {"message": "Insufficient Balance"}}), llm_client.ChatbotNoConfigurado),
            (respuesta_http(429, cuerpo={"error": {"message": "rate"}}), llm_client.ProveedorIARateLimit),
            (respuesta_http(500, cuerpo={"error": "boom"}), llm_client.ProveedorIAError),
            (respuesta_http(200, texto="<html>no json</html>"), llm_client.ProveedorIAError),
            (respuesta_http(200, cuerpo={"id": "x"}), llm_client.ProveedorIAError),
            (httpx.ReadTimeout("lento"), llm_client.ProveedorIATimeout),
            (httpx.ConnectError("sin red"), llm_client.ProveedorIAError),
        ]
        for caso, esperada in casos:
            if isinstance(caso, Exception):
                self.request.side_effect = caso
            else:
                self.request.side_effect = None
                self.request.return_value = caso
            with self.assertRaises(esperada) as ctx:
                deepseek_client.iniciar_turno("SYSTEM", [], "x")
            self.assertNotIn(CLAVE_DEEPSEEK_PRUEBA, str(ctx.exception))
            self.assertNotIn("Insufficient", str(ctx.exception))
            self.assertNotIn("api.deepseek.com", str(ctx.exception))

    def test_endpoint_traduce_402_y_429_a_503(self):
        for cuerpo in (respuesta_http(402, cuerpo={"error": "saldo"}), respuesta_http(429, cuerpo={"error": "rate"})):
            self.request.return_value = cuerpo
            respuesta = self.client.post(
                reverse("chatbot:enviar_mensaje"), data={"mensaje": "Hola"}, content_type="application/json"
            )
            self.assertEqual(respuesta.status_code, 503)
            self.assertEqual(respuesta.json(), {"ok": False, "error": "chatbot_no_disponible"})
        self.assertEqual(Mensaje.objects.count(), 0)

    def test_balance_normalizado(self):
        self.request.return_value = respuesta_http(cuerpo={
            "is_available": True,
            "balance_infos": [{"currency": "USD", "total_balance": "5.00", "granted_balance": "5.00", "topped_up_balance": "0.00"}],
        })

        balance = deepseek_client.consultar_balance()

        self.assertEqual(self.request.call_args.args, ("GET", f"{deepseek_client.BASE_URL}{deepseek_client.RUTA_BALANCE}"))
        self.assertEqual(balance, {
            "is_available": True,
            "balance_infos": [{"currency": "USD", "total_balance": "5.00", "granted_balance": "5.00", "topped_up_balance": "0.00"}],
        })

        self.request.return_value = respuesta_http(cuerpo={"is_available": False, "balance_infos": []})
        self.assertEqual(deepseek_client.consultar_balance(), {"is_available": False, "balance_infos": []})

        self.request.return_value = respuesta_http(401, cuerpo={"error": "auth"})
        with self.assertRaises(llm_client.ChatbotNoConfigurado):
            deepseek_client.consultar_balance()

        self.request.side_effect = httpx.ReadTimeout("lento")
        with self.assertRaises(llm_client.ProveedorIATimeout):
            deepseek_client.consultar_balance()

    def test_balance_no_expuesto_en_urls_publicas(self):
        from django.urls import NoReverseMatch

        with self.assertRaises(NoReverseMatch):
            reverse("chatbot:balance")


class QuickActionsTests(ProvidersDataMixin, TestCase):
    def test_registro_cerrado_coherente_con_tool_registry(self):
        for accion_id in quick_actions.QUICK_ACTIONS:
            label, tool, argumentos = quick_actions.resolver(accion_id)
            self.assertTrue(label)
            self.assertIn(tool, tool_catalog.TOOL_REGISTRY)
            inspect.signature(tool_catalog.obtener_herramienta(tool)).bind(**argumentos)
            self.assertIn(tool, response_renderers.DIRECT_RENDER_TOOLS)

    def test_eventos_proximos_usa_fecha_local(self):
        hoy = timezone.localdate()
        _, tool, argumentos = quick_actions.resolver("eventos_proximos")

        self.assertEqual(tool, "buscar_eventos")
        self.assertEqual(argumentos["fecha_desde"], hoy.isoformat())
        self.assertEqual(argumentos["fecha_hasta"], (hoy + timedelta(days=7)).isoformat())

    def test_accion_invalida(self):
        for valor in ("buscar_lugares", "", None, 3, "eval"):
            with self.assertRaises(quick_actions.AccionInvalida):
                quick_actions.resolver(valor)

    def test_todas_las_acciones_ejecutan_ok_via_registro(self):
        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": True, "temperatura_c": 20.0, "ubicacion": "Huánuco"}):
            for accion_id in quick_actions.QUICK_ACTIONS:
                _, tool, argumentos = quick_actions.resolver(accion_id)
                resultado = tool_catalog.ejecutar_herramienta(tool, argumentos)
                self.assertTrue(resultado["ok"], accion_id)
                self.assertIsInstance(response_renderers.renderizar(tool, resultado), str, accion_id)


@override_settings(CHATBOT_AI_API_KEY="", CHATBOT_DEEPSEEK_API_KEY="", CHATBOT_EXTERNAL_SEARCH_ENABLED=False)
class QuickActionsEndpointTests(ProvidersDataMixin, TestCase):
    def setUp(self):
        self.url = reverse("chatbot:enviar_mensaje")
        self.gemini = patch.object(llm_client, "crear_interaccion").start()
        self.deepseek = patch.object(deepseek_client.httpx, "request").start()
        self.addCleanup(patch.stopall)

    def accion(self, accion_id):
        return self.client.post(self.url, data={"accion": accion_id}, content_type="application/json")

    def assert_sin_ia(self):
        self.gemini.assert_not_called()
        self.deepseek.assert_not_called()

    def test_clima_huanuco_sin_ia_y_external_trusted(self):
        clima = {"disponible": True, "temperatura_c": 21.5, "estado_texto": "Despejado", "ubicacion": "Huánuco (Ciudad)", "fuente": "Open-Meteo"}
        with patch.object(prov_servicios, "obtener_clima_actual", return_value=clima):
            respuesta = self.accion("clima_huanuco")

        self.assertEqual(respuesta.status_code, 200)
        self.assert_sin_ia()
        datos = respuesta.json()
        self.assertEqual(datos["respuesta"]["tipo_fuente"], "external_trusted")
        self.assertIn("Clima actual en Huánuco (Ciudad)", datos["respuesta"]["contenido"])
        self.assertIn("21.5 °C", datos["respuesta"]["contenido"])
        mensajes = list(Mensaje.objects.values_list("rol", "contenido"))
        self.assertEqual(mensajes[0], (Mensaje.Rol.USUARIO, "Clima en Huánuco"))
        self.assertEqual(mensajes[1][0], Mensaje.Rol.ASISTENTE)

    def test_tipo_cambio_usa_clasificacion_real(self):
        respuesta = self.accion("tipo_cambio")

        self.assertEqual(respuesta.status_code, 200)
        self.assert_sin_ia()
        datos = respuesta.json()["respuesta"]
        self.assertEqual(datos["tipo_fuente"], "external_trusted")
        self.assertIn("compra S/ 3.5000, venta S/ 3.5200", datos["contenido"])

    def test_lugares_destacados_es_internal(self):
        respuesta = self.accion("lugares_destacados")

        self.assertEqual(respuesta.status_code, 200)
        self.assert_sin_ia()
        datos = respuesta.json()["respuesta"]
        self.assertEqual(datos["tipo_fuente"], "internal")
        self.assertIn("Kotosh", datos["contenido"])
        self.assertNotIn("Cueva de las Lechuzas", datos["contenido"])

    def test_clima_no_disponible_es_no_evidence(self):
        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": False, "ubicacion": "Huánuco (Ciudad)"}):
            datos = self.accion("clima_huanuco").json()["respuesta"]

        self.assertEqual(datos["tipo_fuente"], "no_evidence")
        self.assertEqual(datos["contenido"], external_search.TEXTO_SIN_EVIDENCIA)

    def test_payloads_invalidos(self):
        casos = [
            ({"accion": "buscar_lugares"}, "accion_invalida"),
            ({"accion": 5}, "accion_invalida"),
            ({"accion": "clima_huanuco", "mensaje": "Hola"}, "payload_invalido"),
            ({}, "payload_invalido"),
        ]
        for payload, codigo in casos:
            respuesta = self.client.post(self.url, data=payload, content_type="application/json")
            self.assertEqual(respuesta.status_code, 400, payload)
            self.assertEqual(respuesta.json(), {"ok": False, "error": codigo})
        self.assert_sin_ia()
        self.assertEqual(Mensaje.objects.count(), 0)

    def test_mensaje_sigue_funcionando(self):
        with patch.object(chatbot_service, "generar_respuesta", return_value=("Hola", "", None)):
            respuesta = self.client.post(self.url, data={"mensaje": "Hola"}, content_type="application/json")
        self.assertEqual(respuesta.status_code, 200)


class SimplePathTests(GeminiSimuladoMixin, TestCase):
    def test_pachamanca_es_simple_path_gemini(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "pachamanca"})]),
            interaccion_falsa("(no debería usarse)"),
        )

        with patch.object(tool_catalog, "ejecutar_herramienta", wraps=tool_catalog.ejecutar_herramienta) as ejecutar:
            _, respuesta = self.turno("¿Dónde puedo comer pachamanca?")

        ejecutar.assert_called_once_with("buscar_restaurantes_por_plato", {"plato": "pachamanca"})
        self.assertEqual(self.crear.call_count, 1)
        self.assertIn("donde sirven Pachamanca", respuesta.contenido)
        self.assertIn("Restaurante Huanuqueño", respuesta.contenido)
        self.assertIn("Horario registrado: 12:00 a 22:00", respuesta.contenido)
        self.assertNotIn("abierto", respuesta.contenido.lower())
        self.assertEqual(respuesta.tipo_fuente, "internal")
        self.assertEqual(Mensaje.objects.count(), 2)

    def test_resultado_vacio_no_evidence_sin_segunda_llamada(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "ceviche"})]))

        _, respuesta = self.turno("¿Dónde como ceviche?")

        self.assertEqual(self.crear.call_count, 1)
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_complex_path_dos_tools_dos_llamadas(self):
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"distrito": "rupa-rupa"}), ("consultar_clima", {"ciudad": "tingo-maria"})]),
            interaccion_falsa("Puedes visitar la Cueva; está nublado."),
        )
        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": True, "temperatura_c": 25.0}):
            _, respuesta = self.turno("¿Qué puedo visitar en Tingo María y cómo está el clima?")

        self.assertEqual(self.crear.call_count, 2)
        self.assertEqual(respuesta.contenido, "Puedes visitar la Cueva; está nublado.")
        self.assertEqual(respuesta.tipo_fuente, "mixed")


@override_settings(CHATBOT_AI_PROVIDER="deepseek", CHATBOT_DEEPSEEK_API_KEY=CLAVE_DEEPSEEK_PRUEBA, CHATBOT_EXTERNAL_SEARCH_ENABLED=False)
class SimplePathDeepSeekTests(ProvidersDataMixin, TestCase):
    def setUp(self):
        self.conversacion = Conversacion.objects.create(session_key="s-ds")
        patcher = patch.object(deepseek_client.httpx, "request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def test_una_function_call_una_request(self):
        self.request.return_value = respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_restaurantes_por_plato", {"plato": "pachamanca"})]))

        with patch.object(tool_catalog, "ejecutar_herramienta", wraps=tool_catalog.ejecutar_herramienta) as ejecutar:
            _, respuesta = chatbot_service.procesar_turno(self.conversacion, "¿Dónde puedo comer pachamanca?")

        self.assertEqual(self.request.call_count, 1)
        ejecutar.assert_called_once_with("buscar_restaurantes_por_plato", {"plato": "pachamanca"})
        self.assertIn("Restaurante Huanuqueño", respuesta.contenido)
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_complex_path_deepseek_sintesis_con_effort_low(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_lugares", {"distrito": "rupa-rupa"}), ("consultar_clima", {"ciudad": "tingo-maria"})])),
            respuesta_http(cuerpo=salida_deepseek("La Cueva y clima nublado.", id="resp-2")),
        ]
        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": True, "temperatura_c": 25.0}):
            _, respuesta = chatbot_service.procesar_turno(self.conversacion, "¿Qué visito en Tingo María y cómo está el clima?")

        self.assertEqual(self.request.call_count, 2)
        segundo = self.request.call_args_list[1].kwargs["json"]
        self.assertEqual(segundo["reasoning"], {"effort": "low"})
        self.assertEqual([i["type"] for i in segundo["input"] if "type" in i],
                         ["reasoning", "function_call", "function_call", "function_call_output", "function_call_output"])
        self.assertEqual(respuesta.tipo_fuente, "mixed")

    def test_contexto_entre_turnos_stateless(self):
        self.request.return_value = respuesta_http(cuerpo=salida_deepseek("Kotosh y la Cueva."))
        chatbot_service.procesar_turno(self.conversacion, "¿Qué lugares hay en Tingo María?")
        self.request.return_value = respuesta_http(cuerpo=salida_deepseek("Solo la Cueva es gratuita."))
        chatbot_service.procesar_turno(self.conversacion, "¿Y cuáles son gratuitos?")

        entrada = self.request.call_args_list[1].kwargs["json"]["input"]
        self.assertEqual([(m["role"], m["content"]) for m in entrada], [
            ("user", "¿Qué lugares hay en Tingo María?"),
            ("assistant", "Kotosh y la Cueva."),
            ("user", "¿Y cuáles son gratuitos?"),
        ])


@override_settings(CHATBOT_AI_PROVIDER="deepseek", CHATBOT_DEEPSEEK_API_KEY=CLAVE_DEEPSEEK_PRUEBA, CHATBOT_EXTERNAL_SEARCH_ENABLED=False)
class DeepSeekMultiRoundTests(ProvidersDataMixin, TestCase):
    """C4.3.1: continuidad stateless multi-round (reasoning + function_call +
    function_call_output reconstruidos en `input`, nunca previous_response_id)."""

    def setUp(self):
        self.conversacion = Conversacion.objects.create(session_key="s-ds-mr")
        patcher = patch.object(deepseek_client.httpx, "request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def cuerpo(self, indice):
        return self.request.call_args_list[indice].kwargs["json"]

    def tipos(self, indice):
        return [(i.get("type"), i.get("call_id")) for i in self.cuerpo(indice)["input"] if "type" in i]

    def assert_sin_estado_remoto(self):
        for llamada in self.request.call_args_list:
            cuerpo = llamada.kwargs["json"]
            for campo in ("previous_response_id", "conversation", "store"):
                self.assertNotIn(campo, cuerpo)

    # Caso A — reasoning + 1 tool (complex path) + final
    def test_reasoning_y_function_call_se_reenvian_en_ronda_2(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_ubicaciones", {"q": "Tingo María"})], call_ids=["call_abc"])),
            respuesta_http(cuerpo=salida_deepseek("Tingo María está en Leoncio Prado.", id="resp-2")),
        ]

        _, respuesta = chatbot_service.procesar_turno(self.conversacion, "¿Dónde queda Tingo María?")

        self.assertEqual(self.request.call_count, 2)
        self.assertEqual(self.tipos(1), [
            ("reasoning", None), ("function_call", "call_abc"), ("function_call_output", "call_abc"),
        ])
        entrada = self.cuerpo(1)["input"]
        reasoning = entrada[1]
        self.assertEqual(reasoning["content"], [{"type": "reasoning_text", "text": REASONING_PRUEBA}])
        self.assertEqual(set(reasoning), {"type", "content", "summary"})  # sin id/status internos
        fc = entrada[2]
        self.assertEqual(set(fc), {"type", "call_id", "name", "arguments"})
        self.assertEqual(fc["arguments"], json.dumps({"q": "Tingo María"}))  # string original
        self.assertEqual(json.loads(entrada[3]["output"])["ok"], True)
        self.assertEqual(respuesta.contenido, "Tingo María está en Leoncio Prado.")
        self.assert_sin_estado_remoto()

    # Caso B — multi-tool paralelo: cada output con su call_id
    def test_multi_tool_outputs_emparejados_por_call_id(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(
                llamadas=[("buscar_lugares", {"distrito": "rupa-rupa"}), ("consultar_clima", {"ciudad": "tingo-maria"})],
                call_ids=["call_lug", "call_cli"],
            )),
            respuesta_http(cuerpo=salida_deepseek("La Cueva; nublado.", id="resp-2")),
        ]
        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": True, "temperatura_c": 25.0}):
            _, respuesta = chatbot_service.procesar_turno(self.conversacion, "¿Qué visito en Tingo María y cómo está el clima?")

        self.assertEqual(self.tipos(1), [
            ("reasoning", None),
            ("function_call", "call_lug"), ("function_call", "call_cli"),
            ("function_call_output", "call_lug"), ("function_call_output", "call_cli"),
        ])
        salidas = {i["call_id"]: json.loads(i["output"]) for i in self.cuerpo(1)["input"] if i.get("type") == "function_call_output"}
        self.assertEqual(salidas["call_lug"]["tool"], "buscar_lugares")
        self.assertEqual(salidas["call_cli"]["tool"], "consultar_clima")
        self.assertEqual(respuesta.tipo_fuente, "mixed")

    # Caso C — argumento inválido → error controlado al mismo call_id → corrección → final
    def test_correccion_de_argumentos_conserva_contexto_por_ronda(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_lugares", {"limit": 99})], call_ids=["call_1"], id="r1")),
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_lugares", {"limit": 5})], call_ids=["call_2"], id="r2", reasoning="segundo-razonamiento")),
            respuesta_http(cuerpo=salida_deepseek("Estos son los lugares.", id="r3")),
        ]

        _, respuesta = chatbot_service.procesar_turno(self.conversacion, "Muéstrame lugares")

        self.assertEqual(self.request.call_count, 3)
        error = next(i for i in self.cuerpo(1)["input"] if i.get("type") == "function_call_output")
        self.assertEqual(error["call_id"], "call_1")
        self.assertEqual(json.loads(error["output"])["error"], "argumento_invalido")
        self.assertEqual(self.tipos(2), [
            ("reasoning", None), ("function_call", "call_1"), ("function_call_output", "call_1"),
            ("reasoning", None), ("function_call", "call_2"), ("function_call_output", "call_2"),
        ])
        ok = [i for i in self.cuerpo(2)["input"] if i.get("call_id") == "call_2" and i["type"] == "function_call_output"]
        self.assertTrue(json.loads(ok[0]["output"])["ok"])
        self.assertEqual(respuesta.contenido, "Estos son los lugares.")
        self.assertEqual(respuesta.tipo_fuente, "internal")

    # Caso D — direct renderer: 1 call, 1 request
    def test_direct_render_sigue_en_una_sola_request(self):
        self.request.return_value = respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_restaurantes_por_plato", {"plato": "pachamanca"})]))

        _, respuesta = chatbot_service.procesar_turno(self.conversacion, "¿Dónde puedo comer pachamanca?")

        self.assertEqual(self.request.call_count, 1)
        self.assertIn("Restaurante Huanuqueño", respuesta.contenido)

    # Caso E — sin tools: 1 request, fin
    def test_sin_tools_una_request(self):
        self.request.return_value = respuesta_http(cuerpo=salida_deepseek("¡Hola!"))

        _, respuesta = chatbot_service.procesar_turno(self.conversacion, "Hola")

        self.assertEqual(self.request.call_count, 1)
        self.assertEqual(respuesta.contenido, "¡Hola!")
        self.assertEqual(respuesta.tipo_fuente, "")

    # Caso F — multi-turn: Django es la fuente de verdad; nada del turno 1 (reasoning/call_id) se reutiliza
    def test_multi_turn_reconstruye_desde_django_sin_reasoning_ni_call_ids_previos(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_ubicaciones", {"q": "Tingo María"})], call_ids=["call_t1"])),
            respuesta_http(cuerpo=salida_deepseek("Kotosh y la Cueva.", id="r2")),
            respuesta_http(cuerpo=salida_deepseek("Solo la Cueva es gratuita.", id="r3")),
        ]
        chatbot_service.procesar_turno(self.conversacion, "¿Qué puedo visitar en Tingo María?")
        chatbot_service.procesar_turno(self.conversacion, "¿Y cuáles de esos lugares son gratuitos?")

        entrada = self.cuerpo(2)["input"]
        self.assertEqual([(m.get("role"), m.get("content")) for m in entrada], [
            ("user", "¿Qué puedo visitar en Tingo María?"),
            ("assistant", "Kotosh y la Cueva."),
            ("user", "¿Y cuáles de esos lugares son gratuitos?"),
        ])
        self.assertFalse(any("type" in i for i in entrada))
        self.assertNotIn("call_t1", json.dumps(entrada))
        self.assert_sin_estado_remoto()

    # Caso G — reasoning nunca se filtra
    def test_reasoning_no_llega_a_respuesta_ni_bd_ni_logs(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_ubicaciones", {"q": "Ambo"})])),
            respuesta_http(cuerpo=salida_deepseek("Ambo está al sur.", id="r2")),
        ]
        with self.assertLogs("apps.chatbot", level="DEBUG") as registro:
            http = self.client.post(
                reverse("chatbot:enviar_mensaje"), data={"mensaje": "¿Dónde queda Ambo?"}, content_type="application/json"
            )

        self.assertEqual(http.status_code, 200)
        self.assertNotIn(REASONING_PRUEBA, http.content.decode())
        self.assertFalse(Mensaje.objects.filter(contenido__contains=REASONING_PRUEBA).exists())
        self.assertNotIn(REASONING_PRUEBA, "\n".join(registro.output))

    # Casos H, I, J — sin estado remoto; tools e instructions reenviadas en cada ronda
    def test_tools_e_instructions_reenviadas_en_todas_las_rondas(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_lugares", {"limit": 99})], id="r1")),
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_lugares", {"limit": 5})], id="r2")),
            respuesta_http(cuerpo=salida_deepseek("Listo.", id="r3")),
        ]

        chatbot_service.procesar_turno(self.conversacion, "Muéstrame lugares")

        self.assertEqual(self.request.call_count, 3)
        for indice in range(3):
            cuerpo = self.cuerpo(indice)
            self.assertEqual(len(cuerpo["tools"]), 19)
            self.assertEqual(cuerpo["tool_choice"], "auto")
            self.assertTrue(cuerpo["instructions"])
            self.assertEqual(cuerpo["instructions"], self.cuerpo(0)["instructions"])
            self.assertEqual(cuerpo["reasoning"], {"effort": deepseek_client.REASONING_EFFORT})
        self.assert_sin_estado_remoto()

    def test_message_del_modelo_junto_a_function_call_tambien_se_reenvia(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek("Voy a consultar.", llamadas=[("buscar_ubicaciones", {"q": "Ambo"})])),
            respuesta_http(cuerpo=salida_deepseek("Ambo está al sur.", id="r2")),
        ]

        chatbot_service.procesar_turno(self.conversacion, "¿Dónde queda Ambo?")

        self.assertEqual([t for t, _ in self.tipos(1)], ["reasoning", "function_call", "message", "function_call_output"])
        mensaje = next(i for i in self.cuerpo(1)["input"] if i.get("type") == "message")
        self.assertEqual(mensaje, {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Voy a consultar."}]})

    def test_max_tool_rounds_se_conserva(self):
        self.request.side_effect = lambda *a, **k: respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_ubicaciones", {"q": "x"})]))

        respuesta = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "bucle"}, content_type="application/json"
        )

        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(self.request.call_count, chatbot_service.MAX_TOOL_ROUNDS + 1)

    def test_error_400_se_loguea_sanitizado_y_frontend_recibe_502(self):
        self.request.side_effect = [
            respuesta_http(cuerpo=salida_deepseek(llamadas=[("buscar_ubicaciones", {"q": "Ambo"})])),
            respuesta_http(400, cuerpo={"error": {
                "type": "invalid_request_error", "code": "invalid_reasoning",
                "message": f"payload {CLAVE_DEEPSEEK_PRUEBA} {REASONING_PRUEBA}",
            }}),
        ]
        with self.assertLogs("apps.chatbot.services.deepseek_client", level="WARNING") as registro:
            http = self.client.post(
                reverse("chatbot:enviar_mensaje"), data={"mensaje": "¿Dónde queda Ambo?"}, content_type="application/json"
            )

        self.assertEqual(http.status_code, 502)
        self.assertEqual(http.json(), {"ok": False, "error": "proveedor_ia_error"})
        linea = next(l for l in registro.output if "deepseek_http_error" in l)
        for esperado in ("ronda=2", "status=400", "error_type=invalid_request_error", "error_code=invalid_reasoning", "num_input_items=4", "num_tool_calls=1"):
            self.assertIn(esperado, linea)
        for prohibido in (CLAVE_DEEPSEEK_PRUEBA, REASONING_PRUEBA, "payload", "Bearer"):
            self.assertNotIn(prohibido, "\n".join(registro.output))
        self.assertEqual(Mensaje.objects.count(), 0)


class StructuredSearchTests(GeminiSimuladoMixin, TestCase):
    """C6.3: precio_max/moneda, categoría tolerante, presentacion alojamientos/
    restaurantes, loop protection y evidencia parcial (orquestación mockeada)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat_hostal = CategoriaEstablecimiento.objects.create(nombre="Hostal", slug="hostal")
        cls.cat_parrillas = CategoriaEstablecimiento.objects.create(nombre="Pollería / Parrillas", slug="polleria-parrillas")
        cls.hostal = Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=cls.cat_hostal, nombre="HOSTAL EL BOSQUE", slug="hostal-el-bosque",
            rango_precio="consultar", precio_desde=Decimal("50.00"), precio_hasta=Decimal("110.00"),
        )
        SucursalEstablecimiento.objects.create(
            establecimiento=cls.hostal, nombre="Sede", slug="sede-bosque", distrito=cls.dist_huanuco, es_principal=True,
        )
        Establecimiento.objects.filter(pk=cls.hotel.pk).update(precio_desde=Decimal("120.00"), precio_hasta=Decimal("220.00"))
        cls.polleria = Establecimiento.objects.create(
            tipo="restaurante", categoria_principal=cls.cat_parrillas, nombre="Pollería Carlos", slug="polleria-carlos",
            rango_precio="consultar", precio_desde=Decimal("19.00"), precio_hasta=Decimal("80.00"),
        )
        SucursalEstablecimiento.objects.create(
            establecimiento=cls.polleria, nombre="Local", slug="local-carlos", distrito=cls.dist_huanuco, es_principal=True,
        )
        cls.rest_huanuqueno.categorias_secundarias.add(cls.cat_parrillas)

    # --- provider / schema / prompt ---

    def test_precio_max_filtra_por_precio_desde_y_marca_exceso(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_alojamientos", {"precio_max": 100})

        self.assertEqual([i["slug"] for i in resultado["items"]], ["hostal-el-bosque"])  # Hotel Real: desde 120
        self.assertEqual(resultado["presupuesto"], {"precio_max_pen": "100.00", "conversion": None})
        texto, p = presenters.presentar_alojamientos(resultado)
        self.assertEqual(p["tipo"], "alojamientos")
        item = p["items"][0]
        self.assertEqual((item["nombre"], item["precio"], item["excede_presupuesto"], item["cta_label"]),
                         ("Hostal el Bosque", "S/ 50.00 – S/ 110.00", True, "Ver alojamiento"))
        self.assertIn("pueden superar tu presupuesto", p["nota"])
        self.assertIn("Presupuesto máximo considerado: S/ 100.00", texto)
        self.assertNotIn("entra en tu presupuesto", texto)

    def test_precio_max_invalido_es_argumento_invalido(self):
        for valor in ("100", -5, 0, True):
            with self.assertRaises(ArgumentoInvalido):
                prov_establecimientos.buscar_alojamientos(precio_max=valor)

    def test_usd_usa_tipo_cambio_vigente_y_sin_tipo_cambio_no_convierte(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_alojamientos", {"precio_max": 50, "moneda": "USD"})

        self.assertEqual(resultado["presupuesto"]["precio_max_pen"], "176.00")  # 50 × venta 3.52
        self.assertEqual(resultado["presupuesto"]["conversion"]["tipo_cambio_venta"], "3.5200")
        self.assertEqual({i["slug"] for i in resultado["items"]}, {"hostal-el-bosque", "hotel-real"})
        _, p = presenters.presentar_alojamientos(resultado)
        self.assertIn("US$ 50.00 ≈ S/ 176.00", p["nota"])

        TipoCambio.objects.all().delete()
        resultado = tool_catalog.ejecutar_herramienta("buscar_alojamientos", {"precio_max": 50, "moneda": "USD"})
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["error"], "argumento_invalido")
        self.assertIn("tipo de cambio", resultado["detail"])

    def test_categoria_tolerante_parrillas_y_especialidades(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_restaurantes", {"categoria": "parrillas"})

        self.assertEqual({i["slug"] for i in resultado["items"]}, {"polleria-carlos", "restaurante-huanuqueno"})
        por_slug = {i["slug"]: i for i in resultado["items"]}
        self.assertEqual(por_slug["restaurante-huanuqueno"]["especialidades"], ["Pollería / Parrillas"])
        self.assertEqual(tool_catalog.ejecutar_herramienta("buscar_restaurantes", {"categoria": "sushi"})["count"], 0)

    def test_schema_y_firma_incluyen_precio_max_y_moneda(self):
        for tool in ("buscar_alojamientos", "buscar_restaurantes"):
            props = tool_schemas.TOOL_SCHEMAS[tool]["parameters"]["properties"]
            self.assertEqual(props["precio_max"]["type"], "number")
            self.assertEqual(props["moneda"]["enum"], ["PEN", "USD"])
            inspect.signature(tool_catalog.obtener_herramienta(tool)).bind(precio_max=100, moneda="USD")

    def test_prompt_reglas_c63(self):
        prompt = system_prompt.construir_system_prompt()
        for regla in (
            "significan alojamiento en general", "categoria=hotel", "moneda=USD", "nunca una tasa de memoria",
            "¿Los US$50 son para toda la estadía o por noche?", "nunca afirmes que \"entra en tu presupuesto\"",
            "nunca \"las mejores\"", "pregunta desde qué fecha", "incluir_aproximados=false",
            "no repitas la misma búsqueda ni la reintentes con otros filtros",
        ):
            self.assertIn(regla, prompt)

    # --- orquestación (LLM mockeado) ---

    def test_hotel_maximo_100_simple_path_con_presentacion(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_alojamientos", {"precio_max": 100})]))

        _, respuesta = self.turno("Busco un hotel en Huánuco por máximo S/100.")

        self.assertEqual(self.crear.call_count, 1)
        self.assertEqual(respuesta.presentacion["tipo"], "alojamientos")
        self.assertEqual([i["nombre"] for i in respuesta.presentacion["items"]], ["Hostal el Bosque"])
        self.assertTrue(respuesta.presentacion["items"][0]["excede_presupuesto"])
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_presupuesto_ambiguo_pregunta_sin_tools(self):
        self.responder(interaccion_falsa("¿Los US$50 son para toda la estadía o por noche?"))

        with patch.object(tool_catalog, "ejecutar_herramienta") as ejecutar:
            _, respuesta = self.turno("Necesito un hotel barato, tengo US$50 y estaré 3 días.")

        ejecutar.assert_not_called()
        self.assertEqual(self.crear.call_count, 1)
        self.assertEqual(respuesta.contenido, "¿Los US$50 son para toda la estadía o por noche?")

    def test_restaurantes_parrillas_y_por_plato_con_presentacion(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_restaurantes", {"categoria": "parrillas"})]))
        _, respuesta = self.turno("¿Qué restaurantes tienen parrillas?")
        self.assertEqual(respuesta.presentacion["tipo"], "restaurantes")
        self.assertEqual({i["nombre"] for i in respuesta.presentacion["items"]}, {"Pollería Carlos", "Restaurante Huanuqueño"})
        self.assertEqual(respuesta.presentacion["items"][0]["cta_label"], "Ver restaurante")

        self.responder(interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "pachamanca"})]))
        _, respuesta = self.turno("Quiero comer pachamanca, ¿qué restaurantes hay?")
        self.assertEqual(respuesta.presentacion["tipo"], "restaurantes")
        self.assertEqual(respuesta.presentacion["titulo"], "Restaurantes donde sirven Pachamanca")
        self.assertEqual([i["nombre"] for i in respuesta.presentacion["items"]], ["Restaurante Huanuqueño"])

    def test_eventos_por_estadia_solo_fechas_confirmadas(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_eventos", {"fecha_desde": "2026-10-10", "fecha_hasta": "2026-10-14"})]))

        _, respuesta = self.turno("Estaré 5 días en Huánuco desde el 10 de octubre, ¿hay algún evento?")

        nombres = [i["nombre"] for i in respuesta.presentacion["items"]]
        self.assertEqual(nombres, ["Concierto"])  # Festival del Café (mes aprox.) y Expo (por confirmar) fuera

    def test_misma_busqueda_vacia_no_se_ejecuta_dos_veces(self):
        # Ronda 1 con dos tools (Complex Path); ronda 2 repite la misma búsqueda
        # vacía con otra capitalización y limit distinto → misma huella.
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"q": "alquiler de bicicletas"}), ("buscar_ubicaciones", {"q": "Kotosh"})]),
            interaccion_falsa(llamadas=[("buscar_lugares", {"q": "Alquiler de Bicicletas", "limit": 5})]),
            interaccion_falsa("No encontré eso registrado."),
        )

        with patch.object(tool_catalog, "ejecutar_herramienta", wraps=tool_catalog.ejecutar_herramienta) as ejecutar:
            _, respuesta = self.turno("¿Hay alquiler de bicicletas cerca de Kotosh?")

        self.assertEqual(ejecutar.call_count, 2)  # solo la ronda 1; la repetición no se ejecuta
        self.assertEqual(self.crear.call_count, 3)
        repetido = json.loads(self.crear.call_args_list[2].kwargs["input"][0]["result"])
        self.assertEqual(repetido["error"], "consulta_ya_realizada_sin_resultados")
        self.assertTrue(self.crear.call_args_list[2].kwargs["input"][0]["is_error"])
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)

    def test_evidencia_parcial_no_termina_en_502(self):
        variantes = [
            [("buscar_lugares", {"distrito": "amarilis"}), ("consultar_clima", {"ciudad": "tingo-maria"})],
            [("buscar_lugares", {"provincia": "huanuco", "q": "Tingo"})],
            [("buscar_lugares", {"q": "Tingo María"})],
            [("buscar_lugares", {"categoria": "natural", "q": "tingo"})],
            [("buscar_lugares", {"q": "selva"})],
            [("buscar_lugares", {"q": "cascada"})],
        ]
        self.crear.side_effect = [interaccion_falsa(llamadas=v, id=f"i{n}") for n, v in enumerate(variantes)]

        with patch.object(prov_servicios, "obtener_clima_actual", return_value={
            "disponible": True, "ciudad_slug": "tingo-maria", "temperatura_c": 25.0, "estado_texto": "Nublado",
        }):
            _, respuesta = self.turno("¿Qué puedo visitar en Tingo María y cómo está el clima?")

        self.assertEqual(self.crear.call_count, chatbot_service.MAX_TOOL_ROUNDS + 1)
        self.assertIn("Clima actual en", respuesta.contenido)
        self.assertIn("Nublado", respuesta.contenido)
        self.assertIn("No encontré lugares turísticos registrados", respuesta.contenido)
        self.assertNotIn("Open-Meteo", respuesta.contenido)
        self.assertEqual(respuesta.tipo_fuente, "external_trusted")
        self.assertEqual(Mensaje.objects.filter(conversacion=self.conversacion).count(), 2)


class SanitizacionPublicaTests(GeminiSimuladoMixin, TestCase):
    """C6.3.1: nombres técnicos de proveedores nunca llegan al turista."""

    def sanitizar(self, texto):
        return chatbot_service._sanitizar_respuesta_publica(texto)

    def test_a_parentesis(self):
        self.assertEqual(self.sanitizar("El clima actual es 23 °C (Open-Meteo)."), "El clima actual es 23 °C.")
        self.assertEqual(self.sanitizar("Está nublado (fuente: Open-Meteo) y hay 19 °C."), "Está nublado y hay 19 °C.")

    def test_b_proveedor_dentro_de_frase(self):
        casos = [
            "Según Open-Meteo, la temperatura es de 22 °C.",
            "La temperatura es de 22 °C según Open Meteo.",
            "Fuente: Open-Meteo. La temperatura es de 22 °C.",
            "La temperatura es de 22 °C — Open-Meteo",
        ]
        for texto in casos:
            limpio = self.sanitizar(texto)
            self.assertNotIn("meteo", limpio.lower(), texto)
            self.assertIn("22 °C", limpio, texto)
            self.assertNotIn("()", limpio)
            self.assertNotIn(" .", limpio)
            self.assertTrue(limpio[0].isupper(), limpio)

    def test_c_deepseek_gemini_tool_registry(self):
        limpio = self.sanitizar("DeepSeek encontró 2 opciones vía Gemini; TOOL_REGISTRY ejecutó buscar_lugares (deepseek).")
        for tecnico in ("DeepSeek", "deepseek", "Gemini", "TOOL_REGISTRY"):
            self.assertNotIn(tecnico, limpio)
        self.assertIn("2 opciones", limpio)

    def test_d_fuentes_oficiales_c5_intactas(self):
        textos = [
            "Según fuentes oficiales consultadas, hay alojamientos registrados.\n\nFuentes oficiales:\n- MINCETUR — https://www.gob.pe/mincetur\n- Perú Travel — https://www.peru.travel/es",
            "Fuente oficial: gob.pe",
            "Municipalidad Provincial de Huánuco — Y tú qué planes",
        ]
        for texto in textos:
            self.assertEqual(self.sanitizar(texto), texto)

    def test_e_contenido_turistico_intacto(self):
        texto = (
            "Pollería Carlos (Pollería / Parrillas) — S/ 19.00 a S/ 80.00 — Jirón 28 de Julio 861.\n"
            "Hotel Real, Municipalidad Provincial de Huánuco, tel. 062-512345, 2026-10-10.\n"
            "Ver restaurante: /restaurantes/polleria-carlos/"
        )
        self.assertEqual(self.sanitizar(texto), texto)
        self.assertIsNone(self.sanitizar(None))
        self.assertEqual(self.sanitizar(""), "")

    def test_f_se_sanitiza_antes_de_persistir_y_devolver(self):
        self.responder(interaccion_falsa("El clima actual es 23 °C (Open-Meteo). Lo indicó DeepSeek."))

        http = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "¿Cómo está el clima?"}, content_type="application/json"
        )

        self.assertEqual(http.status_code, 200)
        contenido = http.json()["respuesta"]["contenido"]
        self.assertEqual(contenido, "El clima actual es 23 °C. Lo indicó.")
        persistido = Mensaje.objects.get(rol=Mensaje.Rol.ASISTENTE)
        self.assertEqual(persistido.contenido, contenido)
        for tecnico in ("Open-Meteo", "DeepSeek"):
            self.assertNotIn(tecnico, http.content.decode())
            self.assertNotIn(tecnico, persistido.contenido)

    def test_prompt_prohibe_nombres_tecnicos_pero_permite_fuentes_oficiales(self):
        prompt = system_prompt.construir_system_prompt()
        self.assertIn("Nunca muestres al turista nombres técnicos de proveedores", prompt)
        self.assertIn("Google Search", prompt)
        self.assertIn("gob.pe", prompt)


class ContenidoSeguroTests(GeminiSimuladoMixin, TestCase):
    """C7: una respuesta del modelo con HTML se devuelve/persiste como texto
    plano sin alterar (JSON, nunca ejecutado; el frontend usa textContent)."""

    def test_html_del_modelo_se_devuelve_como_texto_plano_sin_alterar(self):
        payload_malicioso = "Ten cuidado: <script>alert(1)</script> no es un lugar registrado."
        self.responder(interaccion_falsa(payload_malicioso))

        http = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "hola"}, content_type="application/json"
        )

        contenido = http.json()["respuesta"]["contenido"]
        self.assertEqual(contenido, payload_malicioso)
        self.assertEqual(Mensaje.objects.get(rol=Mensaje.Rol.ASISTENTE).contenido, payload_malicioso)


class RenderersTests(ProvidersDataMixin, TestCase):
    def test_lugares_y_lugar(self):
        texto = response_renderers.renderizar("buscar_lugares", prov_turismo.buscar_lugares())
        self.assertIn("- Kotosh (Arqueológico, HUANUCO) — entrada pagada, S/ 5.00 a S/ 10.00 — Horario registrado: 8:00 a 17:00 — Ver lugar: /lugares-turisticos/kotosh/", texto)
        self.assertIn("Cueva de las Lechuzas", texto)

        detalle = response_renderers.renderizar("obtener_lugar", prov_turismo.obtener_lugar("kotosh"))
        self.assertIn("Servicios: Guía", detalle)
        self.assertIn("Ver lugar: /lugares-turisticos/kotosh/", detalle)

    def test_eventos_respetan_tipo_fecha_y_estado(self):
        texto = response_renderers.renderizar("buscar_eventos", prov_eventos.buscar_eventos(limit=10))
        self.assertIn("Expo Huánuco — fecha por confirmar — CANCELADO", texto)
        self.assertIn("Festival del Café — aproximadamente en octubre de 2026", texto)
        self.assertIn("Feria — del 2026-10-20 al 2026-10-25", texto)
        self.assertIn("Concierto — 2026-10-10, desde las 19:00", texto)

    def test_clima_tipo_cambio_y_vacios(self):
        clima = {"ok": True, "tool": "consultar_clima", "tipo_fuente": "external_trusted",
                 "item": {"disponible": True, "ubicacion": "Huánuco (Ciudad)", "temperatura_c": 20.0,
                          "sensacion_c": 19.0, "humedad_pct": 50, "viento_kph": 5.0,
                          "probabilidad_lluvia_pct": 10, "estado_texto": "Nublado", "es_respaldo": True,
                          "fuente": "Open-Meteo", "url": "/planifica/clima-temporadas/?ciudad=huanuco"}}
        texto = response_renderers.renderizar("consultar_clima", clima)
        self.assertEqual(texto, (
            "Clima actual en Huánuco (Ciudad)\n\n"
            "Nublado · 20.0 °C\n"
            "Sensación térmica: 19.0 °C\n"
            "Humedad: 50%\n"
            "Viento: 5.0 km/h\n"
            "Probabilidad de lluvia: 10%\n\n"
            "(dato de respaldo, puede no estar actualizado)"
        ))
        self.assertNotIn("Open-Meteo", texto)
        self.assertNotIn("/planifica/clima-temporadas/", texto)
        self.assertNotIn("Fuente", texto)

        self.assertEqual(response_renderers.renderizar("consultar_tipo_cambio", {"ok": True, "item": None}), response_renderers.SIN_RESULTADOS)
        self.assertIsNone(response_renderers.renderizar("consultar_tipo_cambio", {"ok": False, "error": "x"}))
        self.assertIsNone(response_renderers.renderizar("buscar_ubicaciones", {"ok": True, "count": 1, "items": [{}]}))
        self.assertNotIn("buscar_ubicaciones", response_renderers.DIRECT_RENDER_TOOLS)
        self.assertEqual(len(response_renderers.DIRECT_RENDER_TOOLS), 18)

    def test_movilidad_servicios_y_emergencias(self):
        tarifas = response_renderers.renderizar("consultar_tarifas_movilidad", prov_movilidad.consultar_tarifas_movilidad())
        self.assertIn("Mototaxi: desde S/ 3.00 — aprox. USD 0.85", tarifas)
        self.assertIn("- Negocia la tarifa", tarifas)

        rutas = response_renderers.renderizar("consultar_como_llegar", prov_movilidad.consultar_como_llegar())
        self.assertIn("[Vía terrestre] Lima - Huánuco en bus — Lima → HUANUCO — en bus: 10 horas", rutas)

        servicios = response_renderers.renderizar("consultar_servicios_utiles", prov_servicios.consultar_servicios_utiles())
        self.assertIn("Botica Central (Farmacias) — Huánuco — 24 horas — Horario registrado: 24 horas — whatsapp: 999111222", servicios)

        emergencias = response_renderers.renderizar("consultar_emergencias", prov_servicios.consultar_emergencias())
        self.assertIn("PNP (Policía): 105 — Atención 24/7", emergencias)
        self.assertIn("Serenazgo Huánuco (Serenazgo): (062) 111 — Móvil 999 000 — 6:00 a 22:00 — zonas: HUANUCO", emergencias)


class TipoFuenteHibridoTests(TestCase):
    def test_item_no_disponible_es_no_evidence(self):
        resultado = {"ok": True, "tipo_fuente": "external_trusted", "item": {"disponible": False}}
        self.assertEqual(chatbot_service.calcular_tipo_fuente([resultado]), "no_evidence")

        disponible = {"ok": True, "tipo_fuente": "external_trusted", "item": {"disponible": True}}
        self.assertEqual(chatbot_service.calcular_tipo_fuente([disponible]), "external_trusted")


# ---------------------------------------------------------------------------
# C5 — fallback a fuentes externas confiables (Gemini Google Search grounding)
# ---------------------------------------------------------------------------

URL_GOB = "https://www.gob.pe/institucion/mincetur/noticias/1"
URL_GORE = "https://regionhuanuco.gob.pe/eventos/fiesta"
URL_PROMPERU = "https://www.peru.travel/es/destinos/huanuco"
GOOGLE_SEARCH_TOOL = [{"type": "google_search"}]


def interaccion_grounded(texto, citas=(), id="ext-1", status="completed"):
    anotaciones = [SimpleNamespace(type="url_citation", url=url, title=titulo) for titulo, url in citas]
    contenido = SimpleNamespace(type="text", text=texto, annotations=anotaciones)
    pasos = [
        SimpleNamespace(type="google_search_call", id="gs-1"),
        SimpleNamespace(type="google_search_result", call_id="gs-1",
                        result=[SimpleNamespace(search_suggestions="<div class='sugerencias'>HTML</div>")]),
        SimpleNamespace(type="model_output", content=[contenido]),
    ]
    return SimpleNamespace(id=id, status=status, output_text=texto, steps=pasos, usage=None)


class TrustedSourcesTests(TestCase):
    def test_matriz_de_urls(self):
        confiables = [
            "https://www.gob.pe/institucion/mincetur",
            "https://regionhuanuco.gob.pe/eventos",
            "https://www.peru.travel/es/destinos/huanuco",
            "https://www.ytuqueplanes.com/destinos/huanuco",
            "https://SENAMHI.GOB.PE./pronostico",
        ]
        rechazadas = [
            "https://evilgob.pe/x",
            "https://gob.pe.evil.com/x",
            "https://gob.pe@evil.com/x",
            "http://www.gob.pe/x",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "https://es.wikipedia.org/wiki/Huanuco",
            "https://www.tripadvisor.com.pe/x",
            "", None, 42, "https://",
        ]
        for url in confiables:
            self.assertTrue(trusted_sources.es_url_confiable(url), url)
        for url in rechazadas:
            self.assertFalse(trusted_sources.es_url_confiable(url), url)
        self.assertEqual(trusted_sources.dominio("https://SENAMHI.GOB.PE./x"), "senamhi.gob.pe")
        self.assertIn("gob.pe", trusted_sources.DOMINIOS_CONFIABLES)


class GroundingParserTests(TestCase):
    def test_extrae_texto_y_citas_trusted_deduplicadas(self):
        citas = [("MINCETUR", URL_GOB), (None, URL_PROMPERU), ("MINCETUR", URL_GOB)]

        resultado = external_search.normalizar_grounding(interaccion_grounded("Según fuentes oficiales consultadas, X.", citas))

        self.assertEqual(resultado["tipo_fuente"], "external_trusted")
        self.assertEqual(resultado["texto"], "Según fuentes oficiales consultadas, X.")
        self.assertEqual(resultado["fuentes"], [
            {"titulo": "MINCETUR", "url": URL_GOB, "dominio": "www.gob.pe"},
            {"titulo": "www.peru.travel", "url": URL_PROMPERU, "dominio": "www.peru.travel"},
        ])
        self.assertNotIn("HTML", resultado["texto"])

    def test_maximo_tres_fuentes(self):
        citas = [(f"F{i}", f"https://www.gob.pe/{i}") for i in range(5)]

        resultado = external_search.normalizar_grounding(interaccion_grounded("texto", citas))

        self.assertEqual(len(resultado["fuentes"]), 3)
        self.assertEqual(external_search.formatear_respuesta(resultado).count("\n- "), 3)
        self.assertIn("\n\nFuentes oficiales:\n- F0 — https://www.gob.pe/0", external_search.formatear_respuesta(resultado))

    def test_sin_citas_sentinela_o_no_trusted_es_no_evidence(self):
        casos = [
            interaccion_grounded("Texto sin citas"),
            interaccion_grounded("SIN_EVIDENCIA", [("MINCETUR", URL_GOB)]),
            interaccion_grounded("Texto", [("Wikipedia", "https://es.wikipedia.org/wiki/Huanuco")]),
            interaccion_grounded("Texto", [("MINCETUR", URL_GOB), ("TripAdvisor", "https://www.tripadvisor.com/x")]),
            interaccion_grounded("", [("MINCETUR", URL_GOB)]),
        ]
        for interaccion in casos:
            self.assertEqual(
                external_search.normalizar_grounding(interaccion),
                {"ok": True, "tipo_fuente": "no_evidence", "texto": None, "fuentes": []},
            )

    def test_interaccion_fallida(self):
        with self.assertRaises(llm_client.ProveedorIAError):
            external_search.normalizar_grounding(interaccion_grounded("x", status="failed"))


class ExternalSearchConfigTests(TestCase):
    def setUp(self):
        patcher = patch.object(llm_client, "crear_interaccion", return_value=interaccion_grounded("Según fuentes oficiales consultadas, X.", [("GORE", URL_GORE)]))
        self.crear = patcher.start()
        self.addCleanup(patcher.stop)

    @override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=False)
    def test_deshabilitada_no_llama(self):
        with self.assertRaises(external_search.BusquedaExternaNoDisponible):
            external_search.buscar("¿Hay feria?")
        self.crear.assert_not_called()

    @override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=True, CHATBOT_EXTERNAL_SEARCH_PROVIDER="deepseek")
    def test_deepseek_no_soportado_como_busqueda_confiable(self):
        with self.assertRaises(external_search.BusquedaExternaNoDisponible):
            external_search.buscar("¿Hay feria?")
        self.crear.assert_not_called()

    @override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=True, CHATBOT_EXTERNAL_SEARCH_PROVIDER="gemini", CHATBOT_AI_THINKING_LEVEL="low", CHATBOT_AI_PROVIDER="deepseek")
    def test_llamada_compacta_con_google_search_desacoplada_del_provider_conversacional(self):
        resultado = external_search.buscar("¿Qué eventos hay en Huánuco?", tool="consultar_clima", resumen_interno="buscar_lugares (1 resultado(s))")

        self.crear.assert_called_once()
        kwargs = self.crear.call_args.kwargs
        self.assertEqual(kwargs["tools"], GOOGLE_SEARCH_TOOL)  # sin las 17 declaraciones
        self.assertNotIn("previous_interaction_id", kwargs)
        self.assertEqual(kwargs["generation_config"], {"tool_choice": "auto", "thinking_level": "low"})
        self.assertIn("fuentes oficiales", kwargs["system_instruction"])
        self.assertIn(timezone.localdate().isoformat(), kwargs["system_instruction"])
        self.assertIn("senamhi.gob.pe", kwargs["system_instruction"])
        self.assertIn("Wikipedia", kwargs["system_instruction"])
        self.assertIn("Ya confirmado con datos internos", kwargs["input"])
        self.assertIn("¿Qué eventos hay en Huánuco?", kwargs["input"])
        self.assertEqual(resultado["provider"], "gemini")
        self.assertEqual(resultado["tipo_fuente"], "external_trusted")

    def test_una_busqueda_por_turno(self):
        conversacion = Conversacion.objects.create(session_key="s-max")
        with patch.object(external_search, "buscar") as buscar:
            estado, resultado = chatbot_service._buscar_externo(conversacion, {"busquedas": 1}, "x")
        buscar.assert_not_called()
        self.assertEqual((estado, resultado), ("no_disponible", None))
        self.assertEqual(external_search.MAX_EXTERNAL_SEARCHES_PER_TURN, 1)


class FallbackExternoTests(GeminiSimuladoMixin, TestCase):
    def habilitar(self):
        ajustes = override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=True, CHATBOT_EXTERNAL_SEARCH_PROVIDER="gemini")
        ajustes.enable()
        self.addCleanup(ajustes.disable)

    def test_simple_con_evidencia_interna_no_busca(self):
        self.habilitar()
        self.responder(interaccion_falsa(llamadas=[("buscar_lugares", {"tipo_costo": "gratis"})]))

        with patch.object(external_search, "buscar", wraps=external_search.buscar) as buscar:
            _, respuesta = self.turno("¿Qué lugares gratuitos hay?")

        buscar.assert_not_called()
        self.assertEqual(self.crear.call_count, 1)
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_simple_sin_evidencia_una_busqueda_grounded_sin_tercera_llamada(self):
        self.habilitar()
        self.responder(
            interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "ceviche"})], id="int-1"),
            interaccion_grounded("Según fuentes oficiales consultadas, en Huánuco hay ferias gastronómicas.", [("PROMPERÚ", URL_PROMPERU)]),
        )

        _, respuesta = self.turno("¿Dónde como ceviche en Huánuco?")

        self.assertEqual(self.crear.call_count, 2)
        externa = self.crear.call_args_list[1].kwargs
        self.assertEqual(externa["tools"], GOOGLE_SEARCH_TOOL)
        self.assertNotIn("previous_interaction_id", externa)
        self.assertEqual(externa["input"], "¿Dónde como ceviche en Huánuco?")
        self.assertEqual(
            respuesta.contenido,
            "Según fuentes oficiales consultadas, en Huánuco hay ferias gastronómicas.\n\nFuentes oficiales:\n- PROMPERÚ — " + URL_PROMPERU,
        )
        self.assertEqual(respuesta.tipo_fuente, "external_trusted")
        self.assertEqual(Mensaje.objects.count(), 2)

    def test_simple_sin_evidencia_externa_sin_citas_termina_determinista(self):
        self.habilitar()
        self.responder(
            interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "ceviche"})]),
            interaccion_grounded("Creo que hay cevicherías en el centro."),
            interaccion_falsa("(no debería usarse)"),
        )

        _, respuesta = self.turno("¿Dónde como ceviche?")

        self.assertEqual(self.crear.call_count, 2)
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_simple_sin_evidencia_deshabilitado_no_busca(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "ceviche"})]))

        _, respuesta = self.turno("¿Dónde como ceviche?")

        self.assertEqual(self.crear.call_count, 1)
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_externo_429_o_timeout_degrada_sin_huerfanos(self):
        self.habilitar()
        for excepcion in (llm_client.ProveedorIARateLimit("429"), llm_client.ProveedorIATimeout("timeout")):
            Mensaje.objects.all().delete()
            self.crear.side_effect = [
                interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "ceviche"})]),
                excepcion,
            ]

            _, respuesta = self.turno("¿Dónde como ceviche?")

            self.assertEqual(respuesta.contenido, external_search.TEXTO_NO_VERIFICADO)
            self.assertEqual(respuesta.tipo_fuente, "no_evidence")
            self.assertEqual(Mensaje.objects.count(), 2)

    def test_complejo_parcial_con_externo_es_mixed(self):
        self.habilitar()
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"distrito": "rupa-rupa"}), ("buscar_eventos", {"q": "inexistente"})]),
            interaccion_falsa("Puedes visitar la Cueva de las Lechuzas."),
            interaccion_grounded("Según fuentes oficiales consultadas, la feria es en octubre.", [("GORE Huánuco", URL_GORE)]),
        )

        with patch.object(external_search, "buscar", wraps=external_search.buscar) as buscar:
            _, respuesta = self.turno("¿Qué visito en Tingo María y qué ferias hay?")

        buscar.assert_called_once()
        self.assertEqual(self.crear.call_count, 3)
        externa = self.crear.call_args_list[2].kwargs
        self.assertEqual(externa["tools"], GOOGLE_SEARCH_TOOL)
        self.assertIn("Ya confirmado con datos internos de Viaje Informado: buscar_lugares (1 resultado(s))", externa["input"])
        self.assertEqual(
            respuesta.contenido,
            "Puedes visitar la Cueva de las Lechuzas.\n\nSegún fuentes oficiales consultadas, la feria es en octubre.\n\nFuentes oficiales:\n- GORE Huánuco — " + URL_GORE,
        )
        self.assertEqual(respuesta.tipo_fuente, "mixed")

    def test_complejo_parcial_externo_falla_conserva_lo_interno(self):
        self.habilitar()
        self.crear.side_effect = [
            interaccion_falsa(llamadas=[("buscar_lugares", {"distrito": "rupa-rupa"}), ("buscar_eventos", {"q": "inexistente"})]),
            interaccion_falsa("Puedes visitar la Cueva de las Lechuzas."),
            llm_client.ProveedorIATimeout("timeout"),
        ]

        _, respuesta = self.turno("¿Qué visito y qué ferias hay?")

        self.assertEqual(respuesta.contenido, "Puedes visitar la Cueva de las Lechuzas.\n\n" + external_search.TEXTO_NO_VERIFICADO)
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_complejo_todo_interno_con_evidencia_no_busca(self):
        self.habilitar()
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"distrito": "rupa-rupa"}), ("consultar_tipo_cambio", {})]),
            interaccion_falsa("Cueva y tipo de cambio."),
        )
        with patch.object(external_search, "buscar", wraps=external_search.buscar) as buscar:
            _, respuesta = self.turno("¿Qué visito y a cuánto está el dólar?")

        buscar.assert_not_called()
        self.assertEqual(self.crear.call_count, 2)
        self.assertEqual(respuesta.tipo_fuente, "mixed")

    def test_complejo_todo_vacio_termina_determinista_sin_llamada_extra(self):
        self.habilitar()
        self.responder(
            interaccion_falsa(llamadas=[("buscar_lugares", {"q": "nada"}), ("buscar_eventos", {"q": "nada"})]),
            interaccion_falsa("Podría haber algo, según recuerdo."),
            interaccion_grounded("Sin citas útiles."),
            interaccion_falsa("(no debería usarse)"),
        )

        _, respuesta = self.turno("¿Hay parques temáticos?")

        self.assertEqual(self.crear.call_count, 3)
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_tool_desconocida_o_argumentos_invalidos_no_disparan_busqueda(self):
        self.habilitar()
        self.responder(
            interaccion_falsa(llamadas=[("buscar_hoteles_secretos", {})]),
            interaccion_falsa("No dispongo de esa herramienta."),
        )
        with patch.object(external_search, "buscar", wraps=external_search.buscar) as buscar:
            _, respuesta = self.turno("Busca hoteles secretos")

        buscar.assert_not_called()
        self.assertEqual(respuesta.contenido, "No dispongo de esa herramienta.")
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_bug_propio_en_busqueda_se_propaga(self):
        self.habilitar()
        self.responder(interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "ceviche"})]))

        with patch.object(external_search, "buscar", side_effect=RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                self.turno("¿Dónde como ceviche?")

        self.assertEqual(Mensaje.objects.count(), 0)


@override_settings(CHATBOT_AI_API_KEY="", CHATBOT_DEEPSEEK_API_KEY="", CHATBOT_EXTERNAL_SEARCH_PROVIDER="gemini")
class FallbackQuickActionTests(ProvidersDataMixin, TestCase):
    def setUp(self):
        self.url = reverse("chatbot:enviar_mensaje")
        self.crear = patch.object(llm_client, "crear_interaccion").start()
        self.addCleanup(patch.stopall)

    def accion(self, accion_id):
        return self.client.post(self.url, data={"accion": accion_id}, content_type="application/json")

    @override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=True)
    def test_con_evidencia_cero_llamadas(self):
        datos = self.accion("restaurantes_destacados").json()["respuesta"]

        self.crear.assert_not_called()
        self.assertEqual(datos["tipo_fuente"], "internal")
        self.assertIn("Restaurante Huanuqueño", datos["contenido"])

    @override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=True)
    def test_vacia_con_fallback_una_busqueda_grounded(self):
        self.crear.return_value = interaccion_grounded("Según fuentes oficiales consultadas, hay alojamientos registrados en MINCETUR.", [("MINCETUR", URL_GOB)])

        datos = self.accion("alojamientos_destacados").json()["respuesta"]

        self.crear.assert_called_once()
        self.assertEqual(self.crear.call_args.kwargs["tools"], GOOGLE_SEARCH_TOOL)
        self.assertEqual(self.crear.call_args.kwargs["input"], "Alojamientos destacados")
        self.assertEqual(datos["tipo_fuente"], "external_trusted")
        self.assertIn("Fuentes oficiales:\n- MINCETUR — " + URL_GOB, datos["contenido"])
        self.assertEqual(Mensaje.objects.filter(rol=Mensaje.Rol.USUARIO).get().contenido, "Alojamientos destacados")

    @override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=False)
    def test_vacia_deshabilitado_no_evidence_sin_llamadas(self):
        datos = self.accion("alojamientos_destacados").json()["respuesta"]

        self.crear.assert_not_called()
        self.assertEqual(datos["tipo_fuente"], "no_evidence")
        self.assertEqual(datos["contenido"], external_search.TEXTO_SIN_EVIDENCIA)

    @override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=True)
    def test_vacia_externo_429_responde_200_no_verificado(self):
        self.crear.side_effect = llm_client.ProveedorIARateLimit("429")

        respuesta = self.accion("alojamientos_destacados")

        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()["respuesta"]
        self.assertEqual(datos["tipo_fuente"], "no_evidence")
        self.assertEqual(datos["contenido"], external_search.TEXTO_NO_VERIFICADO)
        self.assertEqual(Mensaje.objects.count(), 2)


# ---------------------------------------------------------------------------
# C6.1 — CTAs semánticas, clima limpio y Natural Fast Path
# ---------------------------------------------------------------------------

class CtaSemanticaTests(ProvidersDataMixin, TestCase):
    def test_etiquetas_por_tipo_de_contenido(self):
        restaurantes = response_renderers.renderizar("buscar_restaurantes", prov_establecimientos.buscar_restaurantes())
        self.assertIn("Ver restaurante: ", restaurantes)
        self.assertNotIn("Ver más: ", restaurantes)

        alojamientos = response_renderers.renderizar("buscar_alojamientos", prov_establecimientos.buscar_alojamientos())
        self.assertIn("Ver alojamiento: ", alojamientos)

        por_plato = response_renderers.renderizar(
            "buscar_restaurantes_por_plato", prov_establecimientos.buscar_restaurantes_por_plato("pachamanca")
        )
        self.assertIn("Ver dónde comer: ", por_plato)

        plato = response_renderers.renderizar("buscar_platos", prov_gastronomia.buscar_platos())
        self.assertIn("Ver dónde comer: ", plato)
        self.assertNotIn("/restaurantes/?plato=", plato.split("Ver dónde comer: ")[0])

        evento = response_renderers.renderizar("obtener_evento", prov_eventos.obtener_evento("concierto"))
        self.assertIn("Ver evento: ", evento)

        lugar = response_renderers.renderizar("obtener_lugar", prov_turismo.obtener_lugar("kotosh"))
        self.assertIn("Ver lugar: ", lugar)

    def test_establecimiento_detalle_usa_tipo_real(self):
        restaurante = response_renderers.renderizar(
            "obtener_establecimiento", prov_establecimientos.obtener_establecimiento("restaurante-huanuqueno")
        )
        self.assertIn("Ver restaurante: ", restaurante)

        alojamiento = response_renderers.renderizar(
            "obtener_establecimiento", prov_establecimientos.obtener_establecimiento("hotel-real")
        )
        self.assertIn("Ver alojamiento: ", alojamiento)

    def test_ninguna_ruta_interna_aparece_sin_etiqueta_ver(self):
        """Toda ruta interna ('/algo/') debe ir precedida de 'Ver <algo>: '."""
        resultados = [
            response_renderers.renderizar("buscar_lugares", prov_turismo.buscar_lugares()),
            response_renderers.renderizar("buscar_restaurantes", prov_establecimientos.buscar_restaurantes()),
            response_renderers.renderizar("buscar_eventos", prov_eventos.buscar_eventos(limit=10)),
            response_renderers.renderizar("buscar_platos", prov_gastronomia.buscar_platos()),
        ]
        for texto in resultados:
            for linea in texto.split("\n"):
                for segmento in linea.split(" — "):
                    valor = segmento.split(": ", 1)[-1]
                    if valor.startswith("/") or valor.startswith("http"):
                        self.assertRegex(segmento, r"^Ver [^:]+: ", segmento)


class ClimaSinProveedorTecnicoTests(TestCase):
    def _clima(self, **overrides):
        item = {
            "disponible": True, "ubicacion": "Tingo María (Ciudad)", "temperatura_c": 21.9,
            "sensacion_c": 26.2, "humedad_pct": 95, "viento_kph": 0.3, "probabilidad_lluvia_pct": 28,
            "estado_texto": "Parcialmente nublado", "es_respaldo": False, "fuente": "Open-Meteo",
        }
        item.update(overrides)
        return {"ok": True, "tool": "consultar_clima", "tipo_fuente": "external_trusted", "item": item}

    def test_no_menciona_proveedor_ni_ruta(self):
        texto = response_renderers.renderizar("consultar_clima", self._clima())

        self.assertTrue(texto.startswith("Clima actual en Tingo María (Ciudad)"))
        self.assertIn("Parcialmente nublado · 21.9 °C", texto)
        self.assertIn("Sensación térmica: 26.2 °C", texto)
        self.assertNotIn("Open-Meteo", texto)
        self.assertNotIn("Fuente", texto)
        self.assertNotIn("/planifica/clima-temporadas/", texto)
        self.assertNotIn("Ver más", texto)  # sin CTA inline: la sugerencia la añade el frontend

    def test_no_disponible_sigue_sin_proveedor(self):
        texto = response_renderers.renderizar("consultar_clima", self._clima(disponible=False))

        self.assertIn("No pude obtener el clima actual", texto)
        self.assertNotIn("Open-Meteo", texto)


class NaturalQuickActionsTests(TestCase):
    def test_frases_inequivocas(self):
        casos = {
            "¿Cuál es la temperatura en Tingo María?": "clima_tingo_maria",
            "cual es la temperatura en tingo maria": "clima_tingo_maria",
            "¿Cómo está el clima en Huánuco?": "clima_huanuco",
            "temperatura en Huánuco": "clima_huanuco",
            "¿Tipo de cambio?": "tipo_cambio",
            "cuanto esta el dolar": "tipo_cambio",
            "Emergencias": "emergencias",
            "¿Qué eventos hay?": "eventos_proximos",
            "Platos típicos": "platos_tipicos",
            "Lugares destacados": "lugares_destacados",
            "tarifas de movilidad": "tarifas_movilidad",
        }
        for mensaje, esperado in casos.items():
            self.assertEqual(natural_quick_actions.detectar(mensaje), esperado, mensaje)

    def test_no_intercepta_consultas_complejas_ni_ambiguas(self):
        complejas = [
            "¿Dónde puedo comer pachamanca?",
            "¿Qué me recomiendas hacer mañana si llueve y quiero comer algo típico?",
            "¿Qué puedo visitar en Tingo María y cómo está el clima?",
            "Hola",
            "¿Qué eventos hay este fin de semana?",
            "clima en Lima",
        ]
        for mensaje in complejas:
            self.assertIsNone(natural_quick_actions.detectar(mensaje), mensaje)

    def test_ids_reconocidos_existen_en_quick_actions(self):
        ids_reconocidos = set(natural_quick_actions._FRASES)
        self.assertTrue(ids_reconocidos <= set(quick_actions.QUICK_ACTIONS))


class NaturalFastPathTests(GeminiSimuladoMixin, TestCase):
    def test_temperatura_tingo_maria_sin_llamadas_llm(self):
        mensaje = "¿Cuál es la temperatura en Tingo María?"

        with patch.object(tool_catalog, "ejecutar_herramienta", wraps=tool_catalog.ejecutar_herramienta) as ejecutar, \
             patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": True, "temperatura_c": 20.0, "ubicacion": "Tingo María"}):
            _, respuesta = self.turno(mensaje)

        self.crear.assert_not_called()
        ejecutar.assert_called_once_with("consultar_clima", {"ciudad": "tingo-maria"})
        self.assertTrue(respuesta.contenido.startswith("Clima actual en Tingo María"))
        self.assertEqual(respuesta.tipo_fuente, "external_trusted")

    def test_persiste_el_mensaje_original_no_el_label(self):
        mensaje = "¿Cuál es la temperatura en Tingo María?"

        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": True, "temperatura_c": 20.0}):
            self.turno(mensaje)

        usuario = Mensaje.objects.get(rol=Mensaje.Rol.USUARIO)
        self.assertEqual(usuario.contenido, mensaje)
        self.assertNotEqual(usuario.contenido, "Clima en Tingo María")

    def test_funciona_sin_ninguna_api_key(self):
        with override_settings(CHATBOT_AI_API_KEY="", CHATBOT_DEEPSEEK_API_KEY=""):
            _, respuesta = self.turno("Emergencias")

        self.crear.assert_not_called()
        self.assertIn("PNP", respuesta.contenido)

    def test_consulta_compleja_sigue_usando_el_llm(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "pachamanca"})]))

        self.turno("¿Dónde puedo comer pachamanca?")

        self.crear.assert_called_once()

    def test_c5_fallback_si_no_hay_evidencia(self):
        self.habilitar_external_search = override_settings(
            CHATBOT_EXTERNAL_SEARCH_ENABLED=True, CHATBOT_EXTERNAL_SEARCH_PROVIDER="gemini"
        )
        self.habilitar_external_search.enable()
        self.addCleanup(self.habilitar_external_search.disable)
        self.crear.return_value = interaccion_grounded(
            "Según fuentes oficiales consultadas, hay servicios registrados.", [("MINCETUR", URL_GOB)]
        )

        with patch.object(prov_servicios, "obtener_clima_actual", return_value={"disponible": False}):
            _, respuesta = self.turno("clima en huanuco")

        self.crear.assert_called_once()  # solo la búsqueda externa de C5, nunca interpretación
        self.assertEqual(respuesta.tipo_fuente, "external_trusted")


class ExclusionAuthTemplateTests(TestCase):
    def test_login_no_incluye_el_widget(self):
        respuesta = self.client.get(reverse("accounts:login"))

        self.assertNotContains(respuesta, 'id="pcbot-root"')

    def test_home_si_incluye_el_widget(self):
        respuesta = self.client.get(reverse("base:home"))

        self.assertContains(respuesta, 'id="pcbot-root"')

    def test_favoritos_no_se_excluye(self):
        usuario = User.objects.create_user(username="turista-fav", password="clave-123")
        self.client.force_login(usuario)

        respuesta = self.client.get(reverse("interacciones:favoritos"))

        self.assertContains(respuesta, 'id="pcbot-root"')


# ---------------------------------------------------------------------------
# C6.2 — presentación estructurada, emergencias de 2 niveles, eventos
# confirmados, y limpieza de platos/lugares/movilidad
# ---------------------------------------------------------------------------

class ContratoPresentacionTests(GeminiSimuladoMixin, TestCase):
    def test_presentacion_ausente_por_defecto_backward_compatible(self):
        self.responder(interaccion_falsa("Hola, soy Pillco Bot."))

        respuesta = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "Hola"}, content_type="application/json"
        )

        datos = respuesta.json()
        self.assertEqual(set(datos["respuesta"]), {"id", "rol", "contenido", "tipo_fuente", "creado"})
        self.assertNotIn("presentacion", datos["respuesta"])

    def test_presentacion_se_agrega_para_tipos_conocidos_sin_perder_contenido(self):
        self.responder(interaccion_falsa(llamadas=[("buscar_lugares", {"destacado": True})]))

        respuesta = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "lugares destacados por favor"}, content_type="application/json"
        )

        datos = respuesta.json()["respuesta"]
        self.assertIn("contenido", datos)
        self.assertTrue(datos["contenido"])
        self.assertEqual(datos["presentacion"]["tipo"], "lugares")
        self.assertEqual(datos["tipo_fuente"], "internal")


class PresentarClimaTests(TestCase):
    def _resultado(self, **overrides):
        item = {
            "ciudad_slug": "tingo-maria", "ubicacion": "Tingo María (Ciudad)", "disponible": True,
            "temperatura_c": 20.4, "estado_texto": "Mayormente despejado", "sensacion_c": 24.3,
            "humedad_pct": 99, "viento_kph": 0.2, "probabilidad_lluvia_pct": 16, "es_respaldo": False,
            "fuente": "Open-Meteo",
        }
        item.update(overrides)
        return {"ok": True, "tipo_fuente": "external_trusted", "item": item}

    def test_payload_completo(self):
        texto, p = presenters.presentar_clima(self._resultado())

        self.assertEqual(p, {
            "tipo": "clima", "ciudad": "Tingo María", "temperatura": 20.4, "estado": "Mayormente despejado",
            "sensacion": 24.3, "humedad": 99, "viento": 0.2, "lluvia": 16, "respaldo": False,
            "cta": {
                "titulo": "También te puede interesar", "texto": "Conoce las temporadas de Tingo María",
                "label": "Ver más", "url": "/planifica/clima-temporadas/?ciudad=tingo-maria",
            },
        })
        self.assertNotIn("Open-Meteo", texto)
        self.assertNotIn("/planifica/clima-temporadas/", texto)

    def test_no_disponible_sin_presentacion(self):
        texto, p = presenters.presentar_clima(self._resultado(disponible=False))

        self.assertIsNone(p)
        self.assertIn("No pude obtener el clima actual", texto)


class EmergenciasNivelesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pnp = ContactoEmergencia.objects.create(
            ambito="nacional", categoria="policia", nombre="Policía Nacional del Perú",
            numero_visible="105", numero_tel="105", es_24_horas=True, orden=1,
        )
        cls.bomberos = ContactoEmergencia.objects.create(
            ambito="nacional", categoria="bomberos", nombre="Bomberos Voluntarios del Perú",
            numero_visible="116", numero_tel="116", es_24_horas=True, orden=2,
        )
        cls.samu = ContactoEmergencia.objects.create(
            ambito="nacional", categoria="salud", nombre="SAMU",
            numero_visible="106", numero_tel="106", es_24_horas=True, orden=3,
        )

        departamento = Departamento.objects.create(nombre_oficial="HUANUCO", slug="huanuco")
        provincia_hu = Provincia.objects.create(departamento=departamento, nombre_oficial="HUANUCO", slug="huanuco")
        provincia_lp = Provincia.objects.create(departamento=departamento, nombre_oficial="LEONCIO PRADO", slug="leoncio-prado")
        cls.dist_tingo = Distrito.objects.create(provincia=provincia_lp, nombre_oficial="RUPA-RUPA", slug="rupa-rupa", codigo_inei="100601")
        cls.dist_ambo = Distrito.objects.create(provincia=provincia_hu, nombre_oficial="AMBO", slug="ambo", codigo_inei="100201")

        cls.zona_tingo = ZonaAtencionEmergencia.objects.create(distrito=cls.dist_tingo, slug="tingo-maria")
        cls.zona_ambo = ZonaAtencionEmergencia.objects.create(distrito=cls.dist_ambo, slug="ambo")  # sin contactos locales

        cls.comisaria = ContactoEmergencia.objects.create(
            ambito="local", categoria="policia", nombre="Comisaría Sectorial Tingo María",
            numero_visible="062-561000", numero_tel="062561000", orden=1,
        )
        cls.comisaria.zonas.set([cls.zona_tingo])

    def test_quick_action_emergencias_solo_3_nacionales(self):
        _, tool, argumentos = quick_actions.resolver("emergencias")
        self.assertEqual(tool, "consultar_emergencias")

        resultado = tool_catalog.ejecutar_herramienta(tool, argumentos)
        texto, p = presenters.presentar_emergencias(resultado)

        self.assertEqual(p["tipo"], "emergencias_nacionales")
        self.assertEqual([(i["nombre"], i["numero"]) for i in p["items"]], [
            ("Policía Nacional del Perú", "105"),
            ("Bomberos Voluntarios del Perú", "116"),
            ("SAMU", "106"),
        ])
        self.assertIsNotNone(p["zona_prompt"])
        self.assertEqual([z["slug"] for z in p["zonas"]], ["rupa-rupa"])  # ambo no tiene contactos locales

    def test_natural_fast_path_emergencias_cero_llamadas_llm(self):
        conversacion = Conversacion.objects.create(session_key="s-emg")
        with patch.object(llm_client, "crear_interaccion") as crear:
            mensaje_usuario, respuesta = chatbot_service.procesar_turno(conversacion, "Números de emergencia")

        crear.assert_not_called()
        self.assertEqual(respuesta.presentacion["tipo"], "emergencias_nacionales")
        self.assertEqual(mensaje_usuario.contenido, "Números de emergencia")

    def test_zona_con_contactos_locales(self):
        zona = presenters.resolver_zona_emergencia("Tingo María")
        self.assertEqual(zona, {"slug": "rupa-rupa", "nombre": "Tingo María", "mensaje": "Emergencias en Tingo María"})

        conversacion = Conversacion.objects.create(session_key="s-emg-zona")
        with patch.object(llm_client, "crear_interaccion") as crear:
            _, respuesta = chatbot_service.procesar_turno(conversacion, "Emergencias en Tingo María")

        crear.assert_not_called()
        self.assertEqual(respuesta.presentacion["tipo"], "emergencias_locales")
        self.assertEqual(respuesta.presentacion["titulo"], "Contactos en Tingo María")
        self.assertEqual([i["nombre"] for i in respuesta.presentacion["items"]], ["Comisaría Sectorial Tingo María"])

    def test_zona_sin_contactos_locales_conserva_nacionales(self):
        resultado = tool_catalog.ejecutar_herramienta("consultar_emergencias", {"distrito": "ambo", "ambito": "local", "limit": 10})
        texto, p = presenters.presentar_emergencias(resultado, zona_nombre="Ambo")

        self.assertEqual(texto, "No encontré contactos locales registrados para Ambo.")
        self.assertEqual(p["tipo"], "emergencias_nacionales")
        self.assertEqual({i["numero"] for i in p["items"]}, {"105", "116", "106"})
        self.assertIsNone(p["zona_prompt"])

    def test_zona_no_registrada_no_intercepta(self):
        self.assertIsNone(natural_quick_actions.detectar_emergencia_zona("Emergencias en Marte"))
        self.assertIsNone(presenters.resolver_zona_emergencia("Amarilis"))  # sin contactos locales registrados


class EventosProximosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categoria = CategoriaEvento.objects.create(nombre="Festividad C6.2", slug="festividad-c62")
        cls.hoy = timezone.localdate()

        cls.ev_dentro = Evento.objects.create(
            categoria_principal=cls.categoria, nombre="Feria Confirmada", slug="feria-confirmada-c62",
            tipo_fecha="exacta", fecha_inicio=cls.hoy + timedelta(days=3), tipo_costo="gratis",
        )
        cls.ev_fuera = Evento.objects.create(
            categoria_principal=cls.categoria, nombre="Feria Lejana", slug="feria-lejana-c62",
            tipo_fecha="exacta", fecha_inicio=cls.hoy + timedelta(days=10),
            tipo_costo="pagado", precio_desde=Decimal("15.00"),
        )
        cls.ev_por_confirmar = Evento.objects.create(
            categoria_principal=cls.categoria, nombre="Semana Santa", slug="semana-santa-c62",
            tipo_fecha="por_confirmar", tipo_costo="consultar",
        )
        cls.ev_mes_aprox = Evento.objects.create(
            categoria_principal=cls.categoria, nombre="Festival Aproximado", slug="festival-aprox-c62",
            tipo_fecha="mes_aproximado", mes_aproximado=cls.hoy.month, anio_aproximado=cls.hoy.year,
            tipo_costo="no_aplica",
        )
        ancla = cls.hoy + timedelta(days=2)
        cls.ev_anual = Evento.objects.create(
            categoria_principal=cls.categoria, nombre="Aniversario Anual", slug="aniversario-anual-c62",
            tipo_fecha="anual_fija", dia_inicio_anual=ancla.day, mes_inicio_anual=ancla.month,
            tipo_costo="no_aplica",
        )

    def _proximos(self):
        _, tool, argumentos = quick_actions.resolver("eventos_proximos")
        return tool_catalog.ejecutar_herramienta(tool, argumentos)

    def test_solo_fechas_confirmadas_dentro_de_7_dias(self):
        resultado = self._proximos()
        nombres = {i["nombre"] for i in resultado["items"]}

        self.assertIn("Feria Confirmada", nombres)
        self.assertIn("Aniversario Anual", nombres)
        self.assertNotIn("Feria Lejana", nombres)
        self.assertNotIn("Semana Santa", nombres)
        self.assertNotIn("Festival Aproximado", nombres)

    def test_presentacion_eventos_costo_humano(self):
        resultado = self._proximos()
        texto, p = presenters.presentar_eventos(resultado)

        por_nombre = {i["nombre"]: i for i in p["items"]}
        self.assertEqual(por_nombre["Feria Confirmada"]["costo"], "Gratis")
        self.assertIsNone(por_nombre["Aniversario Anual"]["costo"])  # no_requiere: se omite
        for costo in (i["costo"] for i in p["items"]):
            self.assertNotIn("sin costo aplicable", (costo or "").lower())
            self.assertNotIn("no requiere", (costo or "").lower())

    def test_sin_eventos_confirmados_empty_state(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_eventos", {
            "fecha_desde": (self.hoy + timedelta(days=300)).isoformat(),
            "fecha_hasta": (self.hoy + timedelta(days=307)).isoformat(),
            "incluir_aproximados": False,
        })
        texto, p = presenters.presentar_eventos(resultado)

        self.assertIsNone(p)
        self.assertIn("No hay eventos con fecha confirmada", texto)
        self.assertIn("Ver agenda de eventos: ", texto)

    def test_natural_fast_path_eventos_proximos_cero_llm(self):
        conversacion = Conversacion.objects.create(session_key="s-eventos")
        with patch.object(llm_client, "crear_interaccion") as crear:
            _, respuesta = chatbot_service.procesar_turno(conversacion, "eventos proximos")

        crear.assert_not_called()
        if respuesta.presentacion:
            nombres = {i["nombre"] for i in respuesta.presentacion["items"]}
            self.assertNotIn("Semana Santa", nombres)

    def test_quick_action_sin_eventos_no_es_no_evidence(self):
        # Una Quick Action usa argumentos fijos (nunca una búsqueda libre de
        # usuario): un catálogo vacío es una respuesta interna completa y
        # confiable, no "evidencia insuficiente" (bug real encontrado en
        # verificación manual — antes caía a external_search.TEXTO_SIN_EVIDENCIA).
        Evento.objects.all().delete()
        conversacion = Conversacion.objects.create(session_key="s-eventos-vacio")
        with patch.object(llm_client, "crear_interaccion") as crear:
            _, respuesta = chatbot_service.procesar_turno(conversacion, "eventos proximos")

        crear.assert_not_called()
        self.assertIsNone(respuesta.presentacion)
        self.assertEqual(respuesta.tipo_fuente, "internal")
        self.assertIn("No hay eventos con fecha confirmada", respuesta.contenido)
        self.assertNotEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)


class PlatosYLugaresLimpiosTests(ProvidersDataMixin, TestCase):
    def test_nombre_legible_solo_transforma_todo_mayusculas(self):
        self.assertEqual(presenters._nombre_legible("PARQUE NACIONAL DE TINGO MARIA"), "Parque Nacional de Tingo Maria")
        self.assertEqual(presenters._nombre_legible("Cueva de las Lechuzas"), "Cueva de las Lechuzas")
        self.assertEqual(presenters._nombre_legible("MUSEO IPSS"), "Museo Ipss")
        self.assertEqual(presenters._nombre_legible(""), "")

    def test_platos_tipicos_sin_plato_bandera_ni_descripcion(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_platos", {"limit": 10})
        texto, p = presenters.presentar_platos_tipicos(resultado)

        nombres = [i["nombre"] for i in p["items"]]
        self.assertIn("Pachamanca", nombres)
        self.assertIn("Locro de gallina", nombres)
        for i in p["items"]:
            self.assertNotIn("plato bandera", i["nombre"].lower())
            self.assertEqual(set(i), {"nombre", "cta_label", "url"})
        self.assertNotIn("plato bandera", texto.lower())
        self.assertEqual(p["items"][0]["cta_label"], "Ver dónde comer")

    def test_lugares_entrada_libre_sin_cero_soles(self):
        lugar_no_requiere = LugarTuristico.objects.create(
            categoria_principal=self.cat_arqueo, nombre="Templo Libre", slug="templo-libre",
            distrito=self.dist_huanuco, tipo_costo="no_requiere",
            precio_desde=Decimal("0.00"), precio_hasta=Decimal("0.00"),
        )
        resultado = tool_catalog.ejecutar_herramienta("buscar_lugares", {"q": "Templo Libre"})
        _, p = presenters.presentar_lugares(resultado)

        # La tarjeta estructurada es lo que ve el turista (el texto plano es
        # solo un fallback legado para clientes sin `presentacion`).
        item = p["items"][0]
        self.assertEqual(item["entrada"], "Entrada libre")
        self.assertNotIn("S/ 0.00", item["entrada"])
        self.assertNotIn("no requiere entrada", item["entrada"].lower())

    def test_lugar_pagado_y_horario_y_cta(self):
        resultado = tool_catalog.ejecutar_herramienta("buscar_lugares", {"q": "Kotosh"})
        texto, p = presenters.presentar_lugares(resultado)

        item = p["items"][0]
        self.assertEqual(item["entrada"], "S/ 5.00 – S/ 10.00")
        self.assertEqual(item["horario"], "8:00 a 17:00")
        self.assertEqual(item["cta_label"], "Ver lugar")
        self.assertTrue(item["url"].startswith("/lugares-turisticos/"))


class MovilidadTests(ProvidersDataMixin, TestCase):
    def test_presentacion_movilidad_pen_usd_y_recomendaciones_separadas(self):
        resultado = tool_catalog.ejecutar_herramienta("consultar_tarifas_movilidad", {})
        texto, p = presenters.presentar_movilidad(resultado)

        self.assertEqual(p["tipo"], "movilidad")
        item = p["items"][0]
        self.assertEqual(item["tipo"], "Mototaxi")
        self.assertEqual(item["pen"], "3.00")
        self.assertIsNotNone(item["usd"])
        self.assertNotIn("recomendaciones", item)
        self.assertEqual(p["recomendaciones"], [{"icono": "💡", "texto": "Negocia la tarifa"}])

    def test_movilidad_general_es_fast_path(self):
        conversacion = Conversacion.objects.create(session_key="s-mov")
        with patch.object(llm_client, "crear_interaccion") as crear:
            _, respuesta = chatbot_service.procesar_turno(conversacion, "¿Cómo me movilizo en Huánuco?")

        crear.assert_not_called()
        self.assertEqual(respuesta.presentacion["tipo"], "movilidad")

    def test_consulta_con_origen_destino_no_se_intercepta(self):
        casos = [
            "¿Qué tomo para ir de la Plaza de Armas a Kotosh?",
            "¿Cómo llego de la Plaza de Armas a Kotosh?",
        ]
        for mensaje in casos:
            self.assertIsNone(natural_quick_actions.detectar(mensaje), mensaje)


# =============================================================================
# C8 — Favoritos, recomendaciones contextualizadas e itinerarios
# =============================================================================

_NOMBRES_TECNICOS_C8 = ("DeepSeek", "Gemini", "Open-Meteo", "TOOL_REGISTRY", "reasoning", "consultar_favoritos", "planificar_itinerario")
_CLAVES_PROHIBIDAS_C8 = {"id", "slug", "usuario", "user_id", "session_key", "reasoning", "call_id"}


def _assert_presentacion_limpia(test, presentacion):
    """Sin IDs internos, sin reasoning, sin nombres técnicos y solo URLs internas."""
    def recorrer(valor):
        if isinstance(valor, dict):
            test.assertFalse(_CLAVES_PROHIBIDAS_C8 & set(valor), set(valor))
            for clave, v in valor.items():
                if clave == "url" and v:
                    test.assertTrue(v.startswith("/") and not v.startswith("//"), v)
                recorrer(v)
        elif isinstance(valor, list):
            for v in valor:
                recorrer(v)
    recorrer(presentacion)
    volcado = json.dumps(presentacion, ensure_ascii=False)
    for nombre in _NOMBRES_TECNICOS_C8:
        test.assertNotIn(nombre, volcado)


class FavoritosDataMixin(ProvidersDataMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.usuario_a = User.objects.create_user(username="turista-a", password="clave-123")
        cls.usuario_b = User.objects.create_user(username="turista-b", password="clave-123")
        cls.usuario_sin = User.objects.create_user(username="turista-sin", password="clave-123")
        Favorito.objects.create(usuario=cls.usuario_a, lugar_turistico=cls.kotosh)
        Favorito.objects.create(usuario=cls.usuario_a, establecimiento=cls.rest_huanuqueno)
        Favorito.objects.create(usuario=cls.usuario_b, lugar_turistico=cls.lechuzas)
        # Candidatos para sugerencias afines/diversas (no favoritos de nadie)
        cls.templo = LugarTuristico.objects.create(
            categoria_principal=cls.cat_arqueo, nombre="Templo Nuevo", slug="templo-nuevo",
            distrito=cls.dist_huanuco, tipo_costo="gratis",
        )
        cls.laguna = LugarTuristico.objects.create(
            categoria_principal=cls.cat_natural, nombre="Laguna Destacada", slug="laguna-destacada",
            distrito=cls.dist_huanuco, tipo_costo="gratis", destacado=True,
        )


class FavoritosProviderTests(FavoritosDataMixin, TestCase):
    def favoritos(self, usuario, **args):
        return tool_catalog.ejecutar_herramienta("consultar_favoritos", args, usuario=usuario)

    def test_anonimo_no_obtiene_favoritos(self):
        for anonimo in (None, AnonymousUser()):
            resultado = self.favoritos(anonimo)
            self.assertEqual((resultado["ok"], resultado["count"], resultado["autenticado"]), (True, 0, False))
            self.assertEqual(resultado["tipo_fuente"], "internal")

    def test_usuario_con_favoritos_y_tipo(self):
        resultado = self.favoritos(self.usuario_a)

        self.assertEqual(resultado["autenticado"], True)
        self.assertEqual(
            [(i["tipo"], i["nombre"]) for i in resultado["items"]],
            [("lugar", "Kotosh"), ("restaurante", "Restaurante Huanuqueño")],
        )

    def test_usuario_sin_favoritos(self):
        resultado = self.favoritos(self.usuario_sin)
        self.assertEqual((resultado["count"], resultado["autenticado"]), (0, True))

    def test_aislamiento_entre_usuarios(self):
        nombres_a = {i["nombre"] for i in self.favoritos(self.usuario_a)["items"]}
        nombres_b = {i["nombre"] for i in self.favoritos(self.usuario_b)["items"]}

        self.assertEqual(nombres_b, {"Cueva de las Lechuzas"})
        self.assertFalse(nombres_a & nombres_b)

    def test_filtro_por_tipo(self):
        self.assertEqual([i["nombre"] for i in self.favoritos(self.usuario_a, tipo="restaurante")["items"]], ["Restaurante Huanuqueño"])
        self.assertEqual([i["nombre"] for i in self.favoritos(self.usuario_a, tipo="lugar")["items"]], ["Kotosh"])
        self.assertEqual(self.favoritos(self.usuario_a, tipo="alojamiento")["count"], 0)
        self.assertEqual(self.favoritos(self.usuario_a, tipo="otro")["error"], "argumento_invalido")

    def test_favorito_inactivo_no_aparece(self):
        oculto = LugarTuristico.objects.get(slug="lugar-oculto")
        Favorito.objects.create(usuario=self.usuario_b, lugar_turistico=oculto)

        self.assertEqual([i["nombre"] for i in self.favoritos(self.usuario_b)["items"]], ["Cueva de las Lechuzas"])

    def test_identidad_nunca_es_argumento(self):
        for argumentos in ({"user_id": self.usuario_b.pk}, {"usuario": self.usuario_b.pk}, {"username": "turista-b"}, {"session_key": "x"}):
            resultado = tool_catalog.ejecutar_herramienta("consultar_favoritos", argumentos)
            self.assertEqual(resultado["error"], "argumentos_invalidos", argumentos)
        # También con contexto legítimo de A: el argumento del modelo no lo sobrescribe.
        resultado = self.favoritos(self.usuario_a, user_id=self.usuario_b.pk)
        self.assertEqual(resultado["error"], "argumentos_invalidos")
        # El contexto solo llega a las tools que lo declaran.
        self.assertTrue(tool_catalog.ejecutar_herramienta("buscar_lugares", {"q": "Kotosh"}, usuario=self.usuario_a)["ok"])
        self.assertEqual(tool_catalog.TOOLS_CON_USUARIO, {"consultar_favoritos", "planificar_itinerario"})

    def test_sugerencias_explicadas_y_diversas(self):
        resultado = self.favoritos(self.usuario_a, sugerencias=True)

        sugerencias = resultado["sugerencias"]
        nombres = [s["nombre"] for s in sugerencias]
        self.assertIn("Templo Nuevo", nombres)
        self.assertNotIn("Kotosh", nombres)
        templo = next(s for s in sugerencias if s["nombre"] == "Templo Nuevo")
        self.assertEqual(templo["motivo"], "Porque tienes guardados lugares de la categoría Arqueológico")
        # Opción diversa: destacada y de otra categoría, para no encerrar al turista.
        laguna = next(s for s in sugerencias if s["nombre"] == "Laguna Destacada")
        self.assertIn("distinta a tus lugares guardados", laguna["motivo"])
        self.assertNotIn("sugerencias", self.favoritos(self.usuario_a))


class FavoritosChatTests(FavoritosDataMixin, TestCase):
    def setUp(self):
        ajustes = override_settings(
            CHATBOT_AI_PROVIDER="gemini", CHATBOT_AI_THINKING_LEVEL="low", CHATBOT_EXTERNAL_SEARCH_ENABLED=False
        )
        ajustes.enable()
        self.addCleanup(ajustes.disable)
        self.crear = patch.object(llm_client, "crear_interaccion").start()
        self.addCleanup(patch.stopall)

    def turno(self, mensaje, usuario=None):
        conversacion = Conversacion.objects.create(usuario=usuario, session_key="" if usuario else "s-fav")
        return chatbot_service.procesar_turno(conversacion, mensaje)[1]

    def test_fast_path_anonimo_controlado(self):
        respuesta = self.turno("¿Cuáles son mis favoritos?")

        self.crear.assert_not_called()
        self.assertIn(presenters.TEXTO_FAVORITOS_LOGIN, respuesta.contenido)
        self.assertIn(f"Iniciar sesión: {reverse('accounts:login')}", respuesta.contenido)
        self.assertEqual(respuesta.tipo_fuente, "internal")
        self.assertIsNone(respuesta.presentacion)
        self.assertNotIn("Kotosh", respuesta.contenido)

    def test_fast_path_autenticado_con_favoritos(self):
        respuesta = self.turno("Muéstrame mis favoritos.", self.usuario_a)

        self.crear.assert_not_called()
        self.assertEqual(respuesta.tipo_fuente, "internal")
        p = respuesta.presentacion
        self.assertEqual(p["tipo"], "favoritos")
        self.assertEqual([(i["tipo"], i["nombre"]) for i in p["items"]], [("Lugar turístico", "Kotosh"), ("Restaurante", "Restaurante Huanuqueño")])
        self.assertEqual(p["items"][0]["cta_label"], "Ver lugar")
        self.assertEqual(set(p["items"][0]), {"tipo", "nombre", "categoria", "ubicacion", "precio", "motivo", "cta_label", "url"})
        _assert_presentacion_limpia(self, p)

    def test_autenticado_sin_favoritos(self):
        respuesta = self.turno("mis favoritos", self.usuario_sin)

        self.crear.assert_not_called()
        self.assertEqual(respuesta.contenido, presenters.TEXTO_SIN_FAVORITOS)
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_simple_path_con_tipo(self):
        self.crear.side_effect = [interaccion_falsa(llamadas=[("consultar_favoritos", {"tipo": "restaurante"})])]

        respuesta = self.turno("¿Tengo restaurantes guardados?", self.usuario_a)

        self.crear.assert_called_once()
        self.assertEqual(respuesta.presentacion["titulo"], "Tus favoritos · Restaurantes")
        self.assertEqual([i["nombre"] for i in respuesta.presentacion["items"]], ["Restaurante Huanuqueño"])

    def test_simple_path_tipo_sin_favoritos_es_internal(self):
        self.crear.side_effect = [interaccion_falsa(llamadas=[("consultar_favoritos", {"tipo": "alojamiento"})])]

        respuesta = self.turno("¿Tengo alojamientos guardados?", self.usuario_a)

        self.assertEqual(respuesta.contenido, "No tienes alojamientos guardados en favoritos.")
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_llm_no_puede_seleccionar_usuario(self):
        self.crear.side_effect = [
            interaccion_falsa(llamadas=[("consultar_favoritos", {"user_id": self.usuario_b.pk})]),
            interaccion_falsa("No pude consultar tus favoritos."),
        ]
        with patch.object(tool_catalog, "ejecutar_herramienta", wraps=tool_catalog.ejecutar_herramienta) as ejecutar:
            respuesta = self.turno("mis favoritos por favor", self.usuario_a)

        self.assertEqual(ejecutar.call_args.kwargs, {"usuario": self.usuario_a})
        pasos = self.crear.call_args_list[1].kwargs["input"]
        self.assertTrue(all("Lechuzas" not in json.dumps(p, default=str) for p in pasos))
        self.assertNotIn("Lechuzas", respuesta.contenido)

    def test_recomendacion_desde_favoritos_explicada(self):
        self.crear.side_effect = [interaccion_falsa(llamadas=[("consultar_favoritos", {"sugerencias": True})])]

        respuesta = self.turno("Usa mis favoritos para recomendarme qué visitar.", self.usuario_a)

        p = respuesta.presentacion
        self.assertEqual(p["titulo_sugerencias"], presenters.TITULO_SUGERENCIAS)
        motivos = [s["motivo"] for s in p["sugerencias"]]
        self.assertIn("Porque tienes guardados lugares de la categoría Arqueológico", motivos)
        self.assertIn("Templo Nuevo", respuesta.contenido)
        for palabra in ("mejor", "ideal"):
            self.assertNotIn(palabra, respuesta.contenido.lower())
        self.assertEqual(respuesta.tipo_fuente, "internal")
        _assert_presentacion_limpia(self, p)

    def test_endpoint_anonimo_con_conversation_id_ajeno(self):
        conversacion_a = Conversacion.objects.create(usuario=self.usuario_a)

        respuesta = self.client.post(
            reverse("chatbot:enviar_mensaje"),
            data={"mensaje": "mis favoritos", "conversation_id": conversacion_a.pk, "user_id": self.usuario_a.pk},
            content_type="application/json",
        )

        datos = respuesta.json()
        self.assertNotEqual(datos["conversation_id"], conversacion_a.pk)
        self.assertIn(presenters.TEXTO_FAVORITOS_LOGIN, datos["respuesta"]["contenido"])
        self.assertNotIn("Kotosh", datos["respuesta"]["contenido"])
        self.assertEqual(conversacion_a.mensajes.count(), 0)

    def test_endpoint_autenticado_usa_su_identidad(self):
        self.client.force_login(self.usuario_b)

        respuesta = self.client.post(
            reverse("chatbot:enviar_mensaje"), data={"mensaje": "ver mis favoritos"}, content_type="application/json"
        )

        datos = respuesta.json()["respuesta"]
        self.assertEqual([i["nombre"] for i in datos["presentacion"]["items"]], ["Cueva de las Lechuzas"])
        self.assertEqual(datos["tipo_fuente"], "internal")


class RecomendacionesTests(GeminiSimuladoMixin, TestCase):
    def test_recomendacion_sin_favoritos_respeta_presupuesto_y_ubicacion(self):
        Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=self.cat_hotel, nombre="Hostal Centro",
            slug="hostal-centro", rango_precio="economico",
            precio_desde=Decimal("60.00"), precio_hasta=Decimal("120.00"),
        ).sucursales.create(nombre="Sede", slug="sede-centro", distrito=self.dist_huanuco, es_principal=True)
        self.responder(interaccion_falsa(llamadas=[("buscar_alojamientos", {"precio_max": 30, "moneda": "USD", "distrito": "huanuco"})]))

        _, respuesta = self.turno("Recomiéndame un hospedaje en Huánuco por menos de US$30 la noche")

        self.crear.assert_called_once()
        p = respuesta.presentacion
        self.assertEqual(p["tipo"], "alojamientos")
        self.assertEqual([i["nombre"] for i in p["items"]], ["Hostal Centro"])
        self.assertIn("US$ 30.00 ≈ S/ 105.60", p["nota"])
        self.assertTrue(p["items"][0]["excede_presupuesto"])
        self.assertNotIn("mejor", respuesta.contenido.lower())
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_prompt_incluye_reglas_c8_sin_duplicar(self):
        prompt = system_prompt.construir_system_prompt()

        for fragmento in ("consultar_favoritos", "planificar_itinerario", "no una reserva", "nunca infieras gustos", "próxima ocurrencia futura"):
            self.assertIn(fragmento, prompt)
        self.assertEqual(prompt.count("REGLA FUNDAMENTAL SOBRE HECHOS"), 1)
        self.assertLess(len(prompt), 9000)


class ItinerarioDataMixin(FavoritosDataMixin):
    HOY = date(2026, 9, 15)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hostal = Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=cls.cat_hotel, nombre="Hostal Económico",
            slug="hostal-economico", rango_precio="economico",
            precio_desde=Decimal("60.00"), precio_hasta=Decimal("90.00"),
        )
        cls.hostal.sucursales.create(nombre="Sede", slug="sede-hostal", distrito=cls.dist_huanuco, es_principal=True)
        cls.ev_navidad = Evento.objects.create(
            categoria_principal=cls.cat_fest, nombre="Navidad Huanuqueña", slug="navidad-huanuquena",
            tipo_fecha="exacta", fecha_inicio=date(2026, 12, 26), distrito=cls.dist_huanuco,
            tipo_costo="gratis", tipo_horario="todo_el_dia",
        )
        cls.dist_vacio = Distrito.objects.create(
            provincia=cls.prov_huanuco, nombre_oficial="PILLCO MARCA", slug="pillco-marca", codigo_inei="100111"
        )

    def planificar(self, usuario=None, **args):
        args.setdefault("fecha_inicio", "2026-12-25")
        args.setdefault("fecha_fin", "2026-12-30")
        with patch.object(prov_itinerario.timezone, "localdate", return_value=self.HOY):
            return tool_catalog.ejecutar_herramienta("planificar_itinerario", args, usuario=usuario)


class ItinerarioPlannerTests(ItinerarioDataMixin, TestCase):
    def test_caso_a_usd_con_tipo_cambio_mockeado(self):
        resultado = self.planificar(presupuesto=500, moneda="USD")

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["tipo_fuente"], "internal")
        it = resultado["item"]
        self.assertEqual((it["dias"], it["noches"]), (6, 5))
        self.assertEqual(len(it["dias_plan"]), 6)
        self.assertEqual([d["fecha"] for d in it["dias_plan"]][::5], ["2026-12-25", "2026-12-30"])
        self.assertEqual(it["presupuesto"]["monto_pen"], "1760.00")
        self.assertEqual(it["presupuesto"]["conversion"]["tipo_cambio_venta"], "3.5200")
        # Alojamiento base único y el más barato que cabe (precio_desde * noches).
        self.assertEqual(it["alojamiento"]["nombre"], "Hostal Económico")
        self.assertTrue(it["alojamiento"]["cabe_en_presupuesto"])
        costos = it["costos"]
        self.assertEqual((costos["conocido_minimo"], costos["conocido_maximo"]), ("320.00", "500.00"))
        self.assertEqual(costos["margen"], "1440.00")
        self.assertTrue(costos["suficiente"])
        self.assertLessEqual(Decimal(costos["conocido_minimo"]), Decimal(it["presupuesto"]["monto_pen"]))
        self.assertIn("traslado hacia/desde Huánuco", costos["no_incluidos"])
        self.assertIn("movilidad local", costos["no_incluidos"])
        # Día 1: 2 lugares + 1 comida; el evento confirmado cae en su fecha.
        dia1 = it["dias_plan"][0]
        self.assertEqual([a["tipo"] for a in dia1["actividades"]], ["lugar", "lugar", "restaurante"])
        self.assertEqual([a["momento"] for a in dia1["actividades"]], ["mañana", "tarde", "comida"])
        dia2 = it["dias_plan"][1]
        self.assertEqual(dia2["fecha"], "2026-12-26")
        self.assertIn(("evento", "Navidad Huanuqueña"), [(a["tipo"], a["item"]["nombre"]) for a in dia2["actividades"]])
        self.assertEqual([p["nombre"] for p in it["platos_tipicos"]], ["Pachamanca"])
        self.assertEqual(it["ajustes_por_presupuesto"], [])

    def test_caso_b_sin_presupuesto_no_inventa_costo_total(self):
        resultado = self.planificar()

        it = resultado["item"]
        self.assertIsNone(it["presupuesto"])
        self.assertIsNone(it["costos"]["margen"])
        self.assertIsNone(it["costos"]["suficiente"])
        self.assertIsNotNone(it["alojamiento"])
        texto, presentacion = presenters.presentar_itinerario(resultado)
        self.assertIsNone(presentacion["resumen"]["presupuesto"])
        self.assertIsNone(presentacion["resumen"]["margen"])
        self.assertNotIn("Margen", texto)

    def test_caso_c_presupuesto_insuficiente_sin_descuentos(self):
        resultado = self.planificar(presupuesto=100, moneda="PEN")

        it = resultado["item"]
        self.assertFalse(it["alojamiento"]["cabe_en_presupuesto"])
        self.assertEqual(it["alojamiento"]["nombre"], "Hostal Económico")
        self.assertFalse(it["costos"]["suficiente"])
        self.assertEqual(it["ajustes_por_presupuesto"], ["Kotosh"])
        nombres = [a["item"]["nombre"] for d in it["dias_plan"] for a in d["actividades"]]
        self.assertNotIn("Kotosh", nombres)
        texto, presentacion = presenters.presentar_itinerario(resultado)
        self.assertIn("el presupuesto no alcanza para esta combinación", presentacion["resumen"]["margen"])
        self.assertIn("retiré: Kotosh", presentacion["resumen"]["nota_presupuesto"])
        self.assertNotIn("descuento", texto.lower())
        self.assertNotIn("garantiz", texto.lower())

    def test_caso_d_sin_eventos_sigue_generando(self):
        resultado = self.planificar(fecha_inicio="2027-01-05", fecha_fin="2027-01-07")

        it = resultado["item"]
        self.assertTrue(it["disponible"])
        self.assertEqual((it["dias"], it["noches"]), (3, 2))
        self.assertIn("eventos confirmados", it["sin_datos"])
        self.assertFalse([a for d in it["dias_plan"] for a in d["actividades"] if a["tipo"] == "evento"])

    def test_caso_e_datos_insuficientes(self):
        resultado = self.planificar(distrito="pillco-marca")

        it = resultado["item"]
        self.assertFalse(it["disponible"])
        self.assertEqual(it["destino"], "Pillco Marca")
        self.assertEqual(set(it["sin_datos"]), {"lugares turísticos", "restaurantes", "alojamientos", "eventos confirmados"})
        texto, presentacion = presenters.presentar_itinerario(resultado)
        self.assertIsNone(presentacion)
        self.assertIn("No tengo suficiente información registrada sobre Pillco Marca", texto)
        self.assertEqual(self.planificar(distrito="no-existe")["error"], "argumento_invalido")

    def test_caso_f_usd_sin_tipo_cambio_no_convierte(self):
        TipoCambio.objects.update(activo=False)

        resultado = self.planificar(presupuesto=500, moneda="USD")

        it = resultado["item"]
        self.assertEqual(it["presupuesto"]["monto"], "500.00")
        self.assertIsNone(it["presupuesto"]["monto_pen"])
        self.assertIsNone(it["presupuesto"]["conversion"])
        self.assertIn("No hay tipo de cambio vigente", it["aviso_presupuesto"])
        self.assertIsNone(it["costos"]["suficiente"])
        _, presentacion = presenters.presentar_itinerario(resultado)
        self.assertEqual(presentacion["resumen"]["presupuesto"], "US$ 500.00 (sin conversión verificable)")
        self.assertNotIn("≈", presentacion["resumen"]["presupuesto"])

    def test_caso_g_eventos_inciertos_excluidos(self):
        resultado = self.planificar(fecha_inicio="2026-10-09", fecha_fin="2026-10-12")

        eventos = [a["item"]["nombre"] for d in resultado["item"]["dias_plan"] for a in d["actividades"] if a["tipo"] == "evento"]
        self.assertEqual(eventos, ["Concierto"])  # exacta y confirmada
        self.assertNotIn("Expo Huánuco", eventos)  # por_confirmar
        self.assertNotIn("Festival del Café", eventos)  # mes_aproximado (octubre)

    def test_caso_h_favorito_compatible_se_prioriza(self):
        resultado = self.planificar(usuario=self.usuario_b)

        primera = resultado["item"]["dias_plan"][0]["actividades"][0]
        self.assertEqual(primera["item"]["nombre"], "Cueva de las Lechuzas")
        self.assertEqual(primera["motivo"], "Guardado en tus favoritos")
        self.assertEqual(resultado["item"]["favoritos_usados"], ["Cueva de las Lechuzas"])
        otros = [a["motivo"] for d in resultado["item"]["dias_plan"] for a in d["actividades"]][1:]
        self.assertEqual(set(otros), {None})

    def test_caso_i_favorito_incompatible_no_se_fuerza(self):
        Favorito.objects.create(usuario=self.usuario_b, establecimiento=self.hotel)  # sin precio registrado

        por_destino = self.planificar(usuario=self.usuario_b, distrito="huanuco")
        nombres = [a["item"]["nombre"] for d in por_destino["item"]["dias_plan"] for a in d["actividades"]]
        self.assertNotIn("Cueva de las Lechuzas", nombres)  # está en Rupa-Rupa

        por_presupuesto = self.planificar(usuario=self.usuario_b, presupuesto=800, moneda="PEN")
        self.assertEqual(por_presupuesto["item"]["alojamiento"]["nombre"], "Hostal Económico")
        self.assertNotIn("Hotel Real", por_presupuesto["item"]["favoritos_usados"])

        sin_presupuesto = self.planificar(usuario=self.usuario_b)
        self.assertEqual(sin_presupuesto["item"]["alojamiento"]["nombre"], "Hotel Real")
        self.assertEqual(sin_presupuesto["item"]["alojamiento"]["motivo"], "Guardado en tus favoritos")

    def test_validaciones_de_fechas(self):
        self.assertEqual(self.planificar(fecha_inicio="2026-01-01", fecha_fin="2026-01-05")["error"], "argumento_invalido")
        self.assertEqual(self.planificar(fecha_inicio="2026-12-30", fecha_fin="2026-12-25")["error"], "argumento_invalido")
        self.assertEqual(self.planificar(fecha_inicio="2026-12-01", fecha_fin="2026-12-31")["error"], "argumento_invalido")
        self.assertEqual(self.planificar(fecha_inicio="25/12/2026")["error"], "argumento_invalido")
        self.assertEqual(tool_catalog.ejecutar_herramienta("planificar_itinerario", {"fecha_inicio": "2026-12-25"})["error"], "argumentos_invalidos")
        self.assertEqual(self.planificar(fecha_inicio="2026-12-25", fecha_fin="2026-12-25")["item"]["noches"], 0)

    def test_planificar_es_json_serializable_y_anonimo(self):
        resultado = self.planificar(presupuesto=1000)
        json.dumps(resultado)
        self.assertEqual(resultado["item"]["favoritos_usados"], [])


class ItinerarioChatTests(ItinerarioDataMixin, TestCase):
    def setUp(self):
        ajustes = override_settings(
            CHATBOT_AI_PROVIDER="gemini", CHATBOT_AI_THINKING_LEVEL="low", CHATBOT_EXTERNAL_SEARCH_ENABLED=False
        )
        ajustes.enable()
        self.addCleanup(ajustes.disable)
        self.crear = patch.object(llm_client, "crear_interaccion").start()
        patch.object(prov_itinerario.timezone, "localdate", return_value=self.HOY).start()
        self.addCleanup(patch.stopall)

    def turno(self, mensaje, usuario=None):
        conversacion = Conversacion.objects.create(usuario=usuario, session_key="" if usuario else "s-itin")
        return chatbot_service.procesar_turno(conversacion, mensaje)[1]

    def test_simple_path_una_llamada_y_presentacion(self):
        self.crear.side_effect = [interaccion_falsa(llamadas=[(
            "planificar_itinerario", {"fecha_inicio": "2026-12-25", "fecha_fin": "2026-12-30", "presupuesto": 500, "moneda": "USD"},
        )])]

        respuesta = self.turno("Quiero viajar a Huánuco del 25 al 30 de diciembre con US$500. Elabórame un itinerario.")

        self.crear.assert_called_once()
        self.assertEqual(respuesta.tipo_fuente, "internal")
        p = respuesta.presentacion
        self.assertEqual(p["tipo"], "itinerario")
        resumen = p["resumen"]
        self.assertEqual((resumen["destino"], resumen["dias"], resumen["noches"]), ("Huánuco", 6, 5))
        self.assertEqual((resumen["fecha_inicio"], resumen["fecha_fin"]), ("2026-12-25", "2026-12-30"))
        self.assertIn("US$ 500.00 ≈ S/ 1760.00", resumen["presupuesto"])
        self.assertEqual(resumen["estimado"], "Costos registrados: desde S/ 320.00 hasta S/ 500.00")
        self.assertIn("Margen aproximado", resumen["margen"])
        self.assertIn("No incluye: ", resumen["nota_presupuesto"])
        self.assertIn("traslado hacia/desde Huánuco", resumen["nota_presupuesto"])
        self.assertEqual(p["alojamiento"]["nombre"], "Hostal Económico")
        self.assertEqual(p["alojamiento"]["precio"], "S/ 60.00 – S/ 90.00 por noche")
        self.assertEqual(len(p["dias_plan"]), 6)
        actividad = p["dias_plan"][0]["actividades"][0]
        self.assertEqual(set(actividad), {"momento", "tipo", "nombre", "detalle", "motivo", "cta_label", "url"})
        self.assertEqual((actividad["momento"], actividad["nombre"], actividad["cta_label"]), ("Mañana", "Kotosh", "Ver lugar"))
        self.assertEqual(actividad["detalle"], "Arqueológico · HUANUCO · S/ 5.00 – S/ 10.00")
        evento = next(a for d in p["dias_plan"] for a in d["actividades"] if a["tipo"] == "evento")
        self.assertEqual(evento["nombre"], "Navidad Huanuqueña")
        self.assertEqual(p["platos"], [{"nombre": "Pachamanca", "url": f"{reverse('establecimientos:listado_restaurantes')}?plato=pachamanca"}])
        _assert_presentacion_limpia(self, p)
        self.assertIn("Itinerario propuesto para Huánuco", respuesta.contenido)
        self.assertIn("Presupuesto: US$ 500.00", respuesta.contenido)
        for palabra in ("garantiz", "mejor hotel", "reserva confirmada"):
            self.assertNotIn(palabra, respuesta.contenido.lower())

    def test_datos_insuficientes_no_evidence_sin_fuentes_externas(self):
        self.crear.side_effect = [interaccion_falsa(llamadas=[(
            "planificar_itinerario", {"fecha_inicio": "2026-12-25", "fecha_fin": "2026-12-27", "distrito": "pillco-marca"},
        )])]
        with patch.object(external_search, "buscar") as buscar:
            respuesta = self.turno("Itinerario para Pillco Marca del 25 al 27 de diciembre")

        buscar.assert_not_called()
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")
        self.assertIsNone(respuesta.presentacion)
        self.assertIn("No tengo suficiente información registrada sobre Pillco Marca", respuesta.contenido)

    def test_favoritos_influyen_via_contexto_seguro(self):
        self.crear.side_effect = [interaccion_falsa(llamadas=[(
            "planificar_itinerario", {"fecha_inicio": "2026-12-25", "fecha_fin": "2026-12-26"},
        )])]

        respuesta = self.turno("Itinerario del 25 al 26 de diciembre", self.usuario_b)

        p = respuesta.presentacion
        self.assertEqual(p["resumen"]["favoritos"], ["Cueva de las Lechuzas"])
        self.assertEqual(p["dias_plan"][0]["actividades"][0]["motivo"], "Guardado en tus favoritos")
        self.assertIn("Prioricé tus favoritos: Cueva de las Lechuzas", respuesta.contenido)

    def test_llm_no_inyecta_identidad_en_itinerario(self):
        self.crear.side_effect = [
            interaccion_falsa(llamadas=[("planificar_itinerario", {"fecha_inicio": "2026-12-25", "fecha_fin": "2026-12-26", "usuario": self.usuario_b.pk})]),
            interaccion_falsa("No pude armar el itinerario."),
        ]
        respuesta = self.turno("Itinerario del 25 al 26 de diciembre")

        paso = self.crear.call_args_list[1].kwargs["input"][-1]
        self.assertIn("argumentos_invalidos", json.dumps(paso, default=str))
        self.assertNotIn("Lechuzas", respuesta.contenido)

    def test_quick_action_favoritos_registrada_sin_boton(self):
        label, tool, argumentos = quick_actions.resolver("mis_favoritos")
        self.assertEqual((label, tool, argumentos), ("Mis favoritos", "consultar_favoritos", {"limit": 10}))
        self.assertEqual(natural_quick_actions.detectar("¿Cuáles son mis favoritos?"), "mis_favoritos")
        self.assertIsNone(natural_quick_actions.detectar("recomiéndame lugares parecidos a mis favoritos"))


# =============================================================================
# Correcciones finales — suficiencia de evidencia (C5) y scope médico
# =============================================================================

class SuficienciaEvidenciaTests(GeminiSimuladoMixin, TestCase):
    def habilitar_c5(self):
        ajustes = override_settings(CHATBOT_EXTERNAL_SEARCH_ENABLED=True, CHATBOT_EXTERNAL_SEARCH_PROVIDER="gemini")
        ajustes.enable()
        self.addCleanup(ajustes.disable)

    def sin_ingredientes(self):
        IngredienteClavePlato.objects.filter(plato=self.pachamanca).delete()

    def llamada_ingredientes(self, q="pachamanca", aspecto="ingredientes"):
        return interaccion_falsa(llamadas=[("buscar_platos", {"q": q, "aspecto": aspecto})], id="int-1")

    def test_provider_declara_evidencia_por_aspecto(self):
        con = tool_catalog.ejecutar_herramienta("buscar_platos", {"q": "pachamanca", "aspecto": "ingredientes"})
        self.assertEqual((con["count"], con["aspecto"], con["evidencia_suficiente"]), (1, "ingredientes", True))
        sin = tool_catalog.ejecutar_herramienta("buscar_platos", {"q": "locro", "aspecto": "ingredientes"})
        self.assertEqual((sin["count"], sin["evidencia_suficiente"]), (1, False))
        for aspecto in ("preparacion", "origen"):
            self.assertFalse(tool_catalog.ejecutar_herramienta("buscar_platos", {"q": "pachamanca", "aspecto": aspecto})["evidencia_suficiente"])
        ficha = tool_catalog.ejecutar_herramienta("obtener_plato", {"slug": "pachamanca", "aspecto": "ingredientes"})
        self.assertTrue(ficha["evidencia_suficiente"])
        self.assertNotIn("evidencia_suficiente", tool_catalog.ejecutar_herramienta("buscar_platos", {"q": "pachamanca"}))
        self.assertEqual(tool_catalog.ejecutar_herramienta("buscar_platos", {"aspecto": "receta"})["error"], "argumento_invalido")
        self.assertFalse(chatbot_service._tiene_datos(sin))
        self.assertTrue(chatbot_service._tiene_datos(con))

    def test_caso_1_plato_sin_ingredientes_usa_c5_con_fuente_oficial(self):
        self.habilitar_c5()
        self.sin_ingredientes()
        self.responder(
            self.llamada_ingredientes(),
            interaccion_grounded(
                "Según fuentes oficiales consultadas, la pachamanca lleva carne, papa, camote y hierbas como el chincho.",
                [("MINCETUR", URL_GOB)],
            ),
        )

        _, respuesta = self.turno("¿Qué ingredientes tiene la pachamanca?")

        self.assertEqual(self.crear.call_count, 2)
        externa = self.crear.call_args_list[1].kwargs
        self.assertEqual(externa["tools"], GOOGLE_SEARCH_TOOL)
        self.assertEqual(externa["input"], "¿Qué ingredientes tiene la pachamanca?")
        self.assertIn("ytuqueplanes.com", externa["system_instruction"])
        self.assertTrue(respuesta.contenido.startswith("Según fuentes oficiales consultadas, la pachamanca lleva carne"))
        self.assertIn(f"Fuentes oficiales:\n- MINCETUR — {URL_GOB}", respuesta.contenido)
        self.assertEqual(respuesta.tipo_fuente, "external_trusted")
        self.assertIsNone(respuesta.presentacion)

    def test_caso_2_dato_interno_disponible_no_usa_c5(self):
        self.habilitar_c5()
        self.responder(self.llamada_ingredientes())

        with patch.object(external_search, "buscar", wraps=external_search.buscar) as buscar:
            _, respuesta = self.turno("¿Qué ingredientes tiene la pachamanca?")

        buscar.assert_not_called()
        self.assertEqual(self.crear.call_count, 1)
        self.assertIn("Según la información registrada en Viaje Informado, Pachamanca lleva como ingredientes clave: Carne de cerdo.", respuesta.contenido)
        self.assertIn("Ver dónde comer: /restaurantes/?plato=pachamanca", respuesta.contenido)
        self.assertEqual(respuesta.tipo_fuente, "internal")
        self.assertIsNone(respuesta.presentacion)

    def test_caso_3_c5_deshabilitado_respuesta_honesta(self):
        self.sin_ingredientes()
        self.responder(self.llamada_ingredientes())

        _, respuesta = self.turno("¿Qué ingredientes tiene la pachamanca?")

        self.assertEqual(self.crear.call_count, 1)
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")
        self.assertNotIn("Pachamanca", respuesta.contenido)

    def test_caso_4_c5_sin_citas_confiables_no_evidence(self):
        self.habilitar_c5()
        self.sin_ingredientes()
        self.responder(
            self.llamada_ingredientes(),
            interaccion_grounded("Creo que lleva carne de cerdo y papas.", [("Blog", "https://blog-recetas.example/pachamanca")]),
        )

        _, respuesta = self.turno("¿Qué ingredientes tiene la pachamanca?")

        self.assertEqual(self.crear.call_count, 2)
        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_caso_5_donde_comer_sigue_interno(self):
        self.habilitar_c5()
        self.responder(interaccion_falsa(llamadas=[("buscar_restaurantes_por_plato", {"plato": "pachamanca"})]))

        with patch.object(external_search, "buscar") as buscar:
            _, respuesta = self.turno("¿Dónde puedo comer pachamanca?")

        buscar.assert_not_called()
        self.assertEqual(respuesta.tipo_fuente, "internal")
        self.assertEqual(respuesta.presentacion["tipo"], "restaurantes")

    def test_caso_6_pregunta_de_ingrediente_concreto_es_gastronomica(self):
        mensaje = "¿La pachamanca lleva maní?"
        self.assertFalse(chatbot_service.detectar_consulta_medica(mensaje))
        self.responder(self.llamada_ingredientes())

        _, respuesta = self.turno(mensaje)

        self.assertEqual(self.crear.call_count, 1)
        self.assertIn("Carne de cerdo", respuesta.contenido)
        self.assertEqual(respuesta.tipo_fuente, "internal")

    def test_casos_7_y_8_consulta_medica_fuera_de_alcance_sin_ia_ni_c5(self):
        self.habilitar_c5()
        for mensaje in (
            "Soy alérgico al maní, ¿la pachamanca es segura para mí?",
            "Tengo diabetes, ¿qué comida me recomiendas?",
            "¿Qué debo tomar si este plato me cayó mal?",
            "¿Este alimento es seguro para mi enfermedad?",
        ):
            with patch.object(external_search, "buscar") as buscar:
                _, respuesta = self.turno(mensaje)
            buscar.assert_not_called()
            self.crear.assert_not_called()
            self.assertEqual(respuesta.contenido, chatbot_service.TEXTO_FUERA_ALCANCE_MEDICO, mensaje)
            self.assertEqual(respuesta.tipo_fuente, "", mensaje)
        self.assertEqual(Mensaje.objects.filter(rol=Mensaje.Rol.ASISTENTE).count(), 4)

    def test_guard_medico_no_bloquea_por_exceso(self):
        for mensaje in (
            "¿Qué ingredientes tiene la pachamanca?",
            "¿Cómo se prepara el locro de gallina?",
            "¿Qué es el chincho?",
            "¿Es seguro visitar Kotosh de noche?",
            "¿Qué restaurante me recomiendas en Huánuco?",
            "¿Cuál es el origen de la pachamanca?",
        ):
            self.assertFalse(chatbot_service.detectar_consulta_medica(mensaje), mensaje)

    def test_caso_9_origen_y_descripcion_internal_first(self):
        self.habilitar_c5()
        PlatoTipico.objects.filter(pk=self.pachamanca.pk).update(descripcion_corta="Plato cocido bajo tierra con piedras calientes.")
        self.responder(self.llamada_ingredientes(aspecto="descripcion"))
        with patch.object(external_search, "buscar") as buscar:
            _, descripcion = self.turno("¿Qué es la pachamanca?")
        buscar.assert_not_called()
        self.assertEqual(descripcion.contenido.split("\n")[0], "Pachamanca: Plato cocido bajo tierra con piedras calientes.")
        self.assertEqual(descripcion.tipo_fuente, "internal")

        self.responder(
            self.llamada_ingredientes(aspecto="origen"),
            interaccion_grounded("Según fuentes oficiales consultadas, la pachamanca tiene origen prehispánico.", [("PROMPERÚ", URL_PROMPERU)]),
        )
        _, origen = self.turno("¿Cuál es el origen de la pachamanca?")
        self.assertEqual(origen.tipo_fuente, "external_trusted")
        self.assertIn("origen prehispánico", origen.contenido)

    def test_complex_path_no_conserva_redaccion_sin_evidencia(self):
        self.sin_ingredientes()
        self.responder(
            interaccion_falsa(llamadas=[("buscar_platos", {"q": "pachamanca", "aspecto": "ingredientes"}), ("consultar_tipo_cambio", {})]),
            interaccion_falsa("La pachamanca lleva cerdo, papa y camote (de memoria)."),
        )
        TipoCambio.objects.update(activo=False)

        _, respuesta = self.turno("¿Qué ingredientes tiene la pachamanca y cuánto está el dólar?")

        self.assertEqual(respuesta.contenido, external_search.TEXTO_SIN_EVIDENCIA)
        self.assertEqual(respuesta.tipo_fuente, "no_evidence")

    def test_prompt_y_schemas_incluyen_aspecto_y_scope(self):
        prompt = system_prompt.construir_system_prompt()
        self.assertIn("aspecto=ingredientes|preparacion|origen|descripcion", prompt)
        self.assertIn("No das asesoramiento médico", prompt)
        esquemas = {d["name"]: d["parameters"]["properties"] for d in tool_schemas.declaraciones_funcion()}
        self.assertEqual(esquemas["buscar_platos"]["aspecto"]["enum"], ["ingredientes", "descripcion", "preparacion", "origen"])
        self.assertIn("aspecto", esquemas["obtener_plato"])
