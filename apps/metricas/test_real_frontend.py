import re
import shutil
import subprocess
import unittest
import uuid
from datetime import date, time, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.establecimientos.models import CategoriaEstablecimiento, Establecimiento
from apps.eventos.models import CategoriaEvento, Evento
from apps.gastronomia.models import CategoriaPlatoTipico, PlatoTipico
from apps.interacciones.models import Favorito
from apps.interacciones.tests import InteraccionesTestBase
from apps.servicios_turista.models import CategoriaServicioTurista, ServicioTurista

from .choices import OrigenDato
from .models import EventoMetrica, MetricaDiaria, SesionMetrica, VisitanteMetrica
from .services import entidades, real

ACTIVO = override_settings(METRICAS_REAL_HABILITADAS=True)
URL = "/metricas/evento/"
PAGINA = "/historia/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"
SERVER_SIDE = ("chatbot_consulta", "favorito_agregado", "idioma_cambiado")


class FrontendBase(InteraccionesTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        categoria = CategoriaEstablecimiento.objects.get(slug="restaurantes")
        cls.alojamiento = Establecimiento.objects.create(
            tipo="alojamiento", categoria_principal=categoria, nombre="Hotel Kotosh", slug="hotel-kotosh",
        )
        cls.evento = Evento(
            categoria_principal=CategoriaEvento.objects.create(nombre="Festividades", slug="festividades"),
            nombre="Evento de prueba", slug="evento-frontend", tipo_fecha="exacta", fecha_inicio=date(2026, 8, 15),
            tipo_horario="exacta", hora_inicio=time(10, 0), tipo_costo="gratis", tipo_ubicacion="lugar_exacto",
            distrito=cls.lugar.distrito,
        )
        cls.evento.full_clean()
        cls.evento.save()
        cls.categoria_plato = CategoriaPlatoTipico.objects.create(nombre="Fondos", slug="fondos")
        cls.plato = PlatoTipico.objects.create(categoria=cls.categoria_plato, nombre="Pachamanca", slug="pachamanca")
        cls.servicio = ServicioTurista.objects.create(
            categoria_principal=CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud"),
            nombre="Hospital Regional", slug="hospital-regional",
        )

    # ---- helpers
    def cliente(self, ua=UA, enforce_csrf=False):
        return Client(enforce_csrf_checks=enforce_csrf, HTTP_USER_AGENT=ua)

    def abrir_pagina(self, cliente):
        return cliente.get(PAGINA)

    def enviar(self, cliente, tipo, via="listado", **extra):
        datos = {"tipo": tipo, "via": via, "click_id": str(uuid.uuid4()), **extra}
        token = cliente.cookies.get("csrftoken")
        if token and "csrfmiddlewaretoken" not in datos:
            datos["csrfmiddlewaretoken"] = token.value
        return cliente.post(URL, datos)

    def eventos(self):
        return list(EventoMetrica.objects.order_by("id"))


@ACTIVO
class EndpointTests(FrontendBase):
    def setUp(self):
        self.c = self.cliente()
        self.abrir_pagina(self.c)

    def casos_validos(self):
        return [
            ("lugar_detalle_click", "listado", dict(entidad_id=self.lugar.pk), ("lugar", self.lugar.pk)),
            ("restaurante_detalle_click", "listado", dict(entidad_id=self.establecimiento.pk), ("establecimiento", self.establecimiento.pk)),
            ("alojamiento_detalle_click", "listado", dict(entidad_id=self.alojamiento.pk), ("establecimiento", self.alojamiento.pk)),
            ("evento_detalle_click", "agenda", dict(entidad_id=self.evento.pk), ("evento", self.evento.pk)),
            ("gastronomia_donde_comer_click", "platos_tipicos", dict(entidad_id=self.plato.pk), ("plato", self.plato.pk)),
            ("ubicacion_click", "como_llegar", dict(entidad_tipo="lugar", entidad_id=self.lugar.pk), ("lugar", self.lugar.pk)),
            ("ubicacion_click", "iniciar_ruta", dict(entidad_tipo="establecimiento", entidad_id=self.alojamiento.pk), ("establecimiento", self.alojamiento.pk)),
            ("ubicacion_click", "servicios_utiles", dict(entidad_tipo="servicio", entidad_id=self.servicio.pk), ("servicio", self.servicio.pk)),
        ]

    def test_cada_tipo_valido_se_registra_con_entidad_canonica_y_via(self):
        for tipo, via, extra, (entidad_tipo, entidad_id) in self.casos_validos():
            with self.subTest(tipo=tipo, via=via):
                EventoMetrica.objects.all().delete()
                r = self.enviar(self.c, tipo, via, **extra)
                self.assertEqual((r.status_code, r.content), (204, b""))
                (e,) = self.eventos()
                self.assertEqual((e.tipo, e.entidad_tipo, e.entidad_id, e.meta, e.origen), (tipo, entidad_tipo, entidad_id, {"via": via}, "REAL"))

    def test_el_tipo_de_entidad_enviado_por_el_cliente_no_se_usa_salvo_en_ubicacion(self):
        self.enviar(self.c, "lugar_detalle_click", entidad_id=self.lugar.pk, entidad_tipo="plato")
        (e,) = self.eventos()
        self.assertEqual(e.entidad_tipo, "lugar")

    def test_identificacion_por_slug(self):
        self.enviar(self.c, "lugar_detalle_click", "chatbot", entidad_slug=self.lugar.slug)
        self.enviar(self.c, "restaurante_detalle_click", "chatbot", entidad_slug=self.establecimiento.slug)
        self.enviar(self.c, "alojamiento_detalle_click", "chatbot", entidad_slug=self.alojamiento.slug)
        self.assertEqual([(e.tipo, e.entidad_id) for e in self.eventos()], [
            ("lugar_detalle_click", self.lugar.pk), ("restaurante_detalle_click", self.establecimiento.pk),
            ("alojamiento_detalle_click", self.alojamiento.pk),
        ])
        self.assertEqual(self.enviar(self.c, "lugar_detalle_click", entidad_slug="../etc/passwd").status_code, 400)

    def test_vias_de_controles_equivalentes(self):
        for via in ("listado", "favoritos", "chatbot"):
            self.assertEqual(self.enviar(self.c, "lugar_detalle_click", via, entidad_id=self.lugar.pk).status_code, 204)
        self.assertEqual([e.meta["via"] for e in self.eventos()], ["listado", "favoritos", "chatbot"])
        self.assertEqual(self.enviar(self.c, "lugar_detalle_click", "agenda", entidad_id=self.lugar.pk).status_code, 400)

    def test_solo_post(self):
        for metodo in (self.c.get, self.c.put, self.c.delete):
            self.assertEqual(metodo(URL).status_code, 405)
        self.assertEqual(self.eventos(), [])

    def test_eventos_server_side_no_se_pueden_falsificar(self):
        for tipo in SERVER_SIDE + ("scroll", "", "Lugar_Detalle_Click"):
            with self.subTest(tipo=tipo):
                self.assertEqual(self.enviar(self.c, tipo, "listado", entidad_id=self.lugar.pk).status_code, 400)
        self.assertEqual(self.eventos(), [])
        self.assertTrue(set(SERVER_SIDE).isdisjoint(entidades.TIPOS_FRONTEND))
        self.assertEqual(len(entidades.TIPOS_FRONTEND), 6)

    def test_click_id_duplicado_cuenta_una_vez_e_invalido_se_rechaza(self):
        clic = str(uuid.uuid4())
        for _ in range(3):
            self.assertEqual(self.enviar(self.c, "lugar_detalle_click", entidad_id=self.lugar.pk, click_id=clic).status_code, 204)
        self.assertEqual(len(self.eventos()), 1)
        self.assertEqual(self.enviar(self.c, "lugar_detalle_click", entidad_id=self.lugar.pk, click_id="no-uuid").status_code, 400)

    def test_dos_clics_legitimos_con_distinto_click_id_cuentan_ambos(self):
        for _ in range(2):
            self.enviar(self.c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        self.assertEqual(len(self.eventos()), 2)

    def test_entidades_inexistentes_inactivas_o_invalidas(self):
        malos = [
            ("lugar_detalle_click", dict(entidad_id=99999)),
            ("lugar_detalle_click", dict(entidad_id="abc")),
            ("lugar_detalle_click", dict(entidad_id=-4)),
            ("lugar_detalle_click", dict()),
            ("evento_detalle_click", dict(entidad_id=99999)),
            ("evento_detalle_click", dict(entidad_slug=self.evento.slug)),  # el evento solo se identifica por id
            ("gastronomia_donde_comer_click", dict(entidad_id=99999)),
            ("ubicacion_click", dict(entidad_tipo="servicio", entidad_id=99999)),
            ("ubicacion_click", dict(entidad_tipo="plato", entidad_id=self.plato.pk)),
            ("ubicacion_click", dict(entidad_id=self.lugar.pk)),
        ]
        vias = {"evento_detalle_click": "agenda", "gastronomia_donde_comer_click": "platos_tipicos", "ubicacion_click": "como_llegar"}
        for tipo, extra in malos:
            with self.subTest(tipo=tipo, extra=extra):
                self.assertEqual(self.enviar(self.c, tipo, vias.get(tipo, "listado"), **extra).status_code, 400)
        self.assertEqual(self.eventos(), [])

    def test_restaurante_y_alojamiento_se_validan_contra_el_tipo_real(self):
        self.assertEqual(self.enviar(self.c, "restaurante_detalle_click", entidad_id=self.alojamiento.pk).status_code, 400)
        self.assertEqual(self.enviar(self.c, "alojamiento_detalle_click", entidad_id=self.establecimiento.pk).status_code, 400)
        self.assertEqual(self.enviar(self.c, "restaurante_detalle_click", entidad_slug=self.alojamiento.slug).status_code, 400)
        self.assertEqual(self.eventos(), [])

    def test_entidades_desactivadas_no_cuentan(self):
        self.lugar.activo = False
        self.lugar.save()
        self.evento.activo = False
        self.evento.save()
        self.plato.activo = False
        self.plato.save()
        self.servicio.activo = False
        self.servicio.save()
        for tipo, via, extra in (
            ("lugar_detalle_click", "listado", dict(entidad_id=self.lugar.pk)),
            ("evento_detalle_click", "agenda", dict(entidad_id=self.evento.pk)),
            ("gastronomia_donde_comer_click", "platos_tipicos", dict(entidad_id=self.plato.pk)),
            ("ubicacion_click", "servicios_utiles", dict(entidad_tipo="servicio", entidad_id=self.servicio.pk)),
        ):
            self.assertEqual(self.enviar(self.c, tipo, via, **extra).status_code, 400, tipo)
        self.assertEqual(self.eventos(), [])

    def test_vias_invalidas_o_ausentes(self):
        for via in ("", "otra", "LISTADO", "x" * 500):
            self.assertEqual(self.enviar(self.c, "lugar_detalle_click", via, entidad_id=self.lugar.pk).status_code, 400)
        self.assertEqual(self.eventos(), [])

    def test_los_errores_no_revelan_detalles_internos(self):
        r = self.enviar(self.c, "lugar_detalle_click", entidad_id=99999)
        self.assertEqual((r.status_code, r.json()), (400, {"ok": False}))

    def test_privacidad_solo_se_guarda_via_y_entidad(self):
        self.enviar(
            self.c, "ubicacion_click", "iniciar_ruta", entidad_tipo="lugar", entidad_id=self.lugar.pk,
            url="https://www.google.com/maps/dir/?api=1&destination=-9.9,-76.2", nombre="Juan Pérez", email="a@b.pe",
            titulo=self.lugar.nombre, texto_chat="secreto",
        )
        (e,) = self.eventos()
        self.assertEqual(e.meta, {"via": "iniciar_ruta"})
        guardado = repr(list(EventoMetrica.objects.values())) + repr(list(VisitanteMetrica.objects.values())) + repr(list(SesionMetrica.objects.values()))
        for dato in ("google.com/maps", "Juan", "a@b.pe", "secreto", "Chrome", "127.0.0.1"):
            self.assertNotIn(dato, guardado)


@ACTIVO
class EndpointCsrfYControlesTests(FrontendBase):
    def test_sin_token_csrf_se_rechaza_y_con_token_en_el_cuerpo_se_acepta(self):
        c = self.cliente(enforce_csrf_checks=True) if False else Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA)
        self.abrir_pagina(c)
        datos = {"tipo": "lugar_detalle_click", "via": "listado", "entidad_id": self.lugar.pk}
        self.assertEqual(c.post(URL, datos).status_code, 403)
        self.assertEqual(c.post(URL, {**datos, "csrfmiddlewaretoken": "token-falso"}).status_code, 403)
        self.assertEqual(EventoMetrica.objects.count(), 0)
        token = c.cookies["csrftoken"].value  # lo mismo que hace metricas.js (token en el cuerpo, compatible con sendBeacon)
        self.assertEqual(c.post(URL, {**datos, "csrfmiddlewaretoken": token}).status_code, 204)
        self.assertEqual(EventoMetrica.objects.count(), 1)

    def test_token_enviado_como_cabecera_tambien_vale_para_el_fallback_fetch(self):
        c = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA)
        self.abrir_pagina(c)
        r = c.post(URL, {"tipo": "lugar_detalle_click", "via": "listado", "entidad_id": self.lugar.pk},
                   HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
        self.assertEqual(r.status_code, 204)

    def test_flag_apagado_no_persiste_nada(self):
        c = self.cliente()
        self.abrir_pagina(c)
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            r = self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        self.assertEqual((r.status_code, EventoMetrica.objects.count()), (204, 0))

    def test_staff_y_bots_se_ignoran(self):
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        c = self.cliente()
        self.abrir_pagina(c)
        c.force_login(staff)
        self.assertEqual(self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk).status_code, 204)
        bot = self.cliente()
        self.abrir_pagina(bot)
        bot.defaults["HTTP_USER_AGENT"] = "Googlebot/2.1"
        self.assertEqual(self.enviar(bot, "lugar_detalle_click", entidad_id=self.lugar.pk).status_code, 204)
        self.assertEqual(EventoMetrica.objects.count(), 0)

    def test_sin_visitante_previo_se_ignora_y_no_crea_visitantes(self):
        sin_cookies = self.cliente()
        sin_cookies.cookies["csrftoken"] = "x" * 32
        r = sin_cookies.post(URL, {"tipo": "lugar_detalle_click", "via": "listado", "entidad_id": self.lugar.pk,
                                   "csrfmiddlewaretoken": "x" * 32})
        self.assertEqual(r.status_code, 204)
        self.assertEqual((VisitanteMetrica.objects.count(), EventoMetrica.objects.count()), (0, 0))
        desconocido = self.cliente()
        desconocido.cookies["vi_vid"] = str(uuid.uuid4())
        self.enviar(desconocido, "lugar_detalle_click", entidad_id=self.lugar.pk)
        self.assertEqual((VisitanteMetrica.objects.count(), EventoMetrica.objects.count()), (0, 0))

    def test_staff_no_carga_metricas_js_y_el_resto_si_solo_con_el_flag(self):
        anonimo = self.client.get(PAGINA).content.decode()
        self.assertIn("assets/js/metricas.js", anonimo)
        self.assertIn('data-endpoint="/metricas/evento/"', anonimo)
        self.assertRegex(anonimo, r'data-csrf="[^"]+"')
        with override_settings(METRICAS_REAL_HABILITADAS=False):
            self.assertNotIn("metricas.js", self.client.get(PAGINA).content.decode())
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        c = Client()
        c.force_login(staff)
        self.assertNotIn("metricas.js", c.get(PAGINA).content.decode())

    def test_dataset_simulado_intacto(self):
        c = self.cliente()
        self.abrir_pagina(c)
        self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        self.assertEqual(MetricaDiaria.objects.filter(origen=OrigenDato.SIMULADO).count(), 0)


@ACTIVO
class EndpointSesionTests(FrontendBase):
    def test_el_evento_se_asocia_a_la_sesion_vigente_sin_sumar_paginas(self):
        c = self.cliente()
        self.abrir_pagina(c)
        self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        s = SesionMetrica.objects.get()
        (e,) = self.eventos()
        self.assertEqual((e.sesion, s.paginas_vistas, SesionMetrica.objects.count()), (s, 1, 1))
        self.assertEqual((e.visitante, VisitanteMetrica.objects.count()), (VisitanteMetrica.objects.get(), 1))

    def test_sin_sesion_vigente_queda_nula_y_no_se_crea_ninguna(self):
        c = self.cliente()
        self.abrir_pagina(c)
        del c.cookies["vi_sid"]
        self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        (e,) = self.eventos()
        self.assertIsNone(e.sesion)
        self.assertEqual(SesionMetrica.objects.count(), 1)

    def test_sesion_expirada_no_se_reutiliza(self):
        c = self.cliente()
        self.abrir_pagina(c)
        hace = timezone.now() - timedelta(minutes=45)
        SesionMetrica.objects.update(inicio=hace - timedelta(seconds=5), fin=hace)
        self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        self.assertIsNone(self.eventos()[0].sesion)
        self.assertEqual(SesionMetrica.objects.count(), 1)

    def test_el_evento_extiende_la_sesion_y_renueva_su_cookie(self):
        c = self.cliente()
        self.abrir_pagina(c)
        hace = timezone.now() - timedelta(minutes=20)
        SesionMetrica.objects.update(inicio=hace - timedelta(seconds=5), fin=hace)
        r = self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        self.assertEqual(r.cookies["vi_sid"]["max-age"], 1800)
        self.assertGreater(SesionMetrica.objects.get().fin, timezone.now() - timedelta(minutes=1))


@ACTIVO
class RateLimitTests(FrontendBase):
    @override_settings(METRICAS_LIMITE_EVENTOS_POR_MINUTO=3)
    def test_exceso_se_rechaza_de_forma_segura_y_luego_se_recupera(self):
        c = self.cliente()
        self.abrir_pagina(c)
        for _ in range(3):
            self.assertEqual(self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk).status_code, 204)
        r = self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk)
        self.assertEqual((r.status_code, r.json()), (429, {"ok": False}))
        self.assertEqual(EventoMetrica.objects.count(), 3)
        # minutos después una interacción real vuelve a contar (sin deduplicación agresiva)
        with mock.patch.object(real, "ahora", return_value=timezone.now() + timedelta(seconds=120)):
            self.assertEqual(self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk).status_code, 204)
        self.assertEqual(EventoMetrica.objects.count(), 4)

    def test_el_limite_es_por_visitante(self):
        with override_settings(METRICAS_LIMITE_EVENTOS_POR_MINUTO=2):
            a, b = self.cliente(), self.cliente()
            self.abrir_pagina(a)
            self.abrir_pagina(b)
            for _ in range(2):
                self.enviar(a, "lugar_detalle_click", entidad_id=self.lugar.pk)
            self.assertEqual(self.enviar(a, "lugar_detalle_click", entidad_id=self.lugar.pk).status_code, 429)
            self.assertEqual(self.enviar(b, "lugar_detalle_click", entidad_id=self.lugar.pk).status_code, 204)

    def test_uso_normal_queda_muy_por_debajo_del_limite_por_defecto(self):
        self.assertEqual(real.limite_eventos_por_minuto(), 30)
        c = self.cliente()
        self.abrir_pagina(c)
        for _ in range(10):  # diez acciones en un minuto ya es mucho para una persona
            self.assertEqual(self.enviar(c, "lugar_detalle_click", entidad_id=self.lugar.pk).status_code, 204)

    def test_clics_no_consumen_el_cupo_de_otros_visitantes_ni_usan_ip(self):
        self.assertNotIn("ip", {f.name for f in EventoMetrica._meta.get_fields()})


# ---------------------------------------------------------------- plantillas renderizadas

@ACTIVO
class AtributosEnPlantillasTests(FrontendBase):
    def test_listado_de_lugares(self):
        html = self.client.get(reverse("turismo:listado_lugares")).content.decode()
        self.assertIn('data-metrica-evento="lugar_detalle_click" data-metrica-via="listado"', html)
        self.assertIn(f'data-metrica-entidad-id="{self.lugar.pk}"', html)

    def test_listado_de_restaurantes_y_alojamientos(self):
        r = self.client.get(reverse("establecimientos:listado_restaurantes")).content.decode()
        self.assertIn('data-metrica-evento="restaurante_detalle_click" data-metrica-via="listado"', r)
        self.assertIn(f'data-metrica-entidad-id="{self.establecimiento.pk}"', r)
        self.assertNotIn("alojamiento_detalle_click", r)
        a = self.client.get(reverse("establecimientos:listado_alojamientos")).content.decode()
        self.assertIn('data-metrica-evento="alojamiento_detalle_click" data-metrica-via="listado"', a)
        self.assertIn(f'data-metrica-entidad-id="{self.alojamiento.pk}"', a)
        self.assertNotIn("restaurante_detalle_click", a)

    def test_gastronomia_solo_en_donde_comer(self):
        html = self.client.get(reverse("gastronomia:platos_tipicos")).content.decode()
        self.assertIn('data-metrica-evento="gastronomia_donde_comer_click" data-metrica-via="platos_tipicos"', html)
        self.assertIn(f'data-metrica-entidad-id="{self.plato.pk}"', html)
        self.assertEqual(html.count("data-metrica-evento="), 1)  # ni paginación ni categorías ni otros enlaces

    def test_favoritos_ver_mas_reutiliza_el_tipo_de_contenido(self):
        for recurso, campo in ((self.lugar, "lugar_turistico"), (self.establecimiento, "establecimiento"), (self.alojamiento, "establecimiento")):
            Favorito.objects.create(usuario=self.usuario, **{campo: recurso})
        self.client.login(username="turista1", password="clave12345")
        html = self.client.get(reverse("interacciones:favoritos")).content.decode()
        for tipo, recurso in (("lugar_detalle_click", self.lugar), ("restaurante_detalle_click", self.establecimiento),
                              ("alojamiento_detalle_click", self.alojamiento)):
            self.assertRegex(html, rf'data-metrica-evento="{tipo}"\s+data-metrica-via="favoritos" data-metrica-entidad-id="{recurso.pk}"')

    def test_las_tarjetas_sin_accion_del_usuario_no_llevan_atributos_de_otros_tipos(self):
        html = self.client.get(reverse("turismo:listado_lugares")).content.decode()
        for ajeno in ("ubicacion_click", "evento_detalle_click", "gastronomia_donde_comer_click"):
            self.assertNotIn(ajeno, html)


# ---------------------------------------------------------------- plantillas y JS (comprobaciones estáticas)

def leer(ruta):
    return (settings.BASE_DIR / ruta).read_text(encoding="utf-8")


def etiquetas_con(texto, evento):
    return re.findall(rf'<[^<>]*data-metrica-evento="{evento}"[^<>]*>', texto)


def vias(etiquetas):
    return sorted(re.search(r'data-metrica-via="(\w+)"', e).group(1) for e in etiquetas)


class ControlesDeUbicacionTests(TestCase):
    def test_detalle_de_lugar(self):
        t = leer("templates/turismo/detalle-lugar-turistico.html")
        self.assertEqual(vias(etiquetas_con(t, "ubicacion_click")), ["abrir_mapa", "como_llegar", "iniciar_ruta"])
        envoltorio = re.search(r'<div class="como-llegar-wrap"[^<>]*>', t).group(0)
        self.assertIn('data-metrica-entidad-tipo="lugar"', envoltorio)
        self.assertIn('data-metrica-entidad-id="{{ lugar.pk }}"', envoltorio)
        for etiqueta, marca in ((etiquetas_con(t, "ubicacion_click")[0], "data-show-dir"),):
            self.assertIn(marca, etiqueta)

    def test_detalle_de_establecimiento_incluye_los_enlaces_sueltos(self):
        t = leer("templates/establecimientos/detalle_establecimiento.html")
        etiquetas = etiquetas_con(t, "ubicacion_click")
        self.assertEqual(vias(etiquetas), ["abrir_mapa", "como_llegar", "como_llegar", "como_llegar", "iniciar_ruta"])
        sueltos = [e for e in etiquetas if "data-show-dir" not in e and "data-open-link" not in e and "data-enlace-ruta" not in e]
        self.assertEqual(len(sueltos), 2)  # los dos "Cómo llegar" fuera del componente
        for suelto in sueltos:
            self.assertIn('data-metrica-entidad-tipo="establecimiento"', suelto)
            self.assertIn('data-metrica-entidad-id="{{ establecimiento.pk }}"', suelto)
        envoltorio = re.search(r'<section[^<>]*id="detalle-ubicacion"[^<>]*>', t).group(0)
        self.assertIn('data-metrica-entidad-id="{{ establecimiento.pk }}"', envoltorio)

    def test_servicios_utiles(self):
        t = leer("templates/servicios_turista/servicios_utiles.html")
        etiquetas = etiquetas_con(t, "ubicacion_click")
        self.assertEqual(vias(etiquetas), ["abrir_mapa", "como_llegar", "iniciar_ruta", "servicios_utiles"])
        tarjeta = next(e for e in etiquetas if "data-abrir-como-llegar" in e)
        self.assertIn('data-metrica-entidad-tipo="servicio"', tarjeta)
        self.assertIn('data-metrica-entidad-id="{{ tarjeta.id }}"', tarjeta)
        self.assertIn('data-metrica-entidad-tipo="servicio">', re.search(r'<div class="como-llegar-wrap su-como-llegar"[^<>]*>', t).group(0))
        self.assertEqual(etiquetas_con(t, "evento_detalle_click"), [])  # "Ver información" de servicios no es de eventos
        boton_info = re.search(r"<button[^<>]*data-abrir-info[^<>]*>", t).group(0)
        self.assertNotIn("data-metrica", boton_info)

    def test_el_js_de_servicios_fija_el_servicio_abierto_en_el_modal(self):
        js = leer("static/assets/js/servicios-utiles.js")
        self.assertIn("envoltorio.dataset.metricaEntidadId = servicioId", js)


class JavaScriptTests(TestCase):
    def test_evento_se_registra_solo_si_existe_y_el_modal_se_abre(self):
        js = leer("static/assets/js/agenda-eventos.js")
        existe = js.index("if (!evento) return;")
        registro = js.index('window.ViMetricas.registrar("evento_detalle_click"')
        abre = js.index("modal.show();", registro)
        self.assertLess(existe, registro)
        self.assertLess(registro, abre)
        self.assertEqual(js.count('registrar("evento_detalle_click"'), 1)
        self.assertIn('via: "agenda"', js)
        # el botón de la tarjeta no lleva atributos propios: el conteo sale de abrirEvento (sin duplicar)
        self.assertNotIn("data-metrica", leer("templates/eventos/partials/_card.html"))

    def test_metricas_js_cumple_el_contrato(self):
        js = leer("static/assets/js/metricas.js")
        for requerido in ("sendBeacon", "keepalive", "csrfmiddlewaretoken", "randomUUID", "VENTANA_DEDUP_MS", "window.ViMetricas",
                          "data-metrica-evento".replace("data-", "") and "metricaEvento", "#pcbot-root a[href]", "/lugares-turisticos/",
                          "/restaurantes/", "/alojamientos/", "click_id"):
            self.assertIn(requerido, js)
        self.assertNotIn("preventDefault", js)  # nunca altera el comportamiento del enlace o botón
        self.assertNotIn("stopPropagation", js)

    def test_se_carga_desde_base_html_con_endpoint_y_csrf(self):
        base = leer("templates/base.html")
        self.assertIn("{% if METRICAS_ACTIVAS %}", base)
        self.assertIn("metricas.js", base)
        self.assertIn("data-csrf=\"{{ csrf_token }}\"", base)

    def test_el_flag_en_produccion_sigue_apagado(self):
        self.assertIn("METRICAS_REAL_HABILITADAS', default=False)", leer("config/settings/production.py"))

    def test_los_controles_de_contenido_declaran_tipo_via_y_entidad(self):
        for ruta, tipos in (
            ("templates/turismo/listado-lugares-turisticos.html", ["lugar_detalle_click"]),
            ("templates/establecimientos/listado_establecimientos.html", ["restaurante_detalle_click", "alojamiento_detalle_click"]),
            ("templates/gastronomia/platos_tipicos.html", ["gastronomia_donde_comer_click"]),
        ):
            t = leer(ruta)
            for tipo in tipos:
                (etiqueta,) = etiquetas_con(t, tipo)
                self.assertRegex(etiqueta, r'data-metrica-via="\w+"')
                self.assertRegex(etiqueta, r'data-metrica-entidad-id="\{\{ \w+\.pk \}\}"')


# ---------------------------------------------------------------- F.1: modo de ruta en ubicacion_click

@ACTIVO
class ModoRutaEndpointTests(FrontendBase):
    """`modo` (a_pie | auto) solo se guarda en ubicacion_click con via=iniciar_ruta; el tipo del evento no cambia."""

    def setUp(self):
        self.c = self.cliente()
        self.abrir_pagina(self.c)

    def ruta(self, **extra):
        return self.enviar(self.c, "ubicacion_click", "iniciar_ruta", entidad_tipo="lugar", entidad_id=self.lugar.pk, **extra)

    def test_a_pie_y_auto_se_guardan_en_meta(self):
        for modo in ("a_pie", "auto"):
            with self.subTest(modo=modo):
                EventoMetrica.objects.all().delete()
                self.assertEqual(self.ruta(modo=modo).status_code, 204)
                (e,) = self.eventos()
                self.assertEqual((e.tipo, e.meta), ("ubicacion_click", {"via": "iniciar_ruta", "modo": modo}))

    def test_a_pie_y_auto_seguidos_son_dos_interacciones_separadas(self):
        self.ruta(modo="a_pie")
        self.ruta(modo="auto")
        self.assertEqual([e.meta["modo"] for e in self.eventos()], ["a_pie", "auto"])
        self.assertEqual({e.tipo for e in self.eventos()}, {"ubicacion_click"})

    def test_modo_invalido_se_rechaza_y_no_se_registra(self):
        for modo in ("bicicleta", "A_PIE", "walking", "driving", "a pie", "<script>", "x" * 500, "a_pie ", "auto;"):
            with self.subTest(modo=modo):
                self.assertEqual(self.ruta(modo=modo).status_code, 400)
        self.assertEqual(self.eventos(), [])

    def test_sin_modo_sigue_siendo_valido_para_clientes_antiguos(self):
        self.assertEqual(self.ruta().status_code, 204)
        self.assertEqual(self.ruta(modo="").status_code, 204)
        self.assertEqual([e.meta for e in self.eventos()], [{"via": "iniciar_ruta"}] * 2)

    def test_modo_no_aplica_a_otras_vias_ni_tipos_y_se_ignora_sin_guardarlo(self):
        for via in ("como_llegar", "abrir_mapa", "servicios_utiles"):
            for modo in ("auto", "bicicleta"):
                self.assertEqual(
                    self.enviar(self.c, "ubicacion_click", via, entidad_tipo="lugar", entidad_id=self.lugar.pk, modo=modo).status_code, 204,
                )
        self.assertEqual(self.enviar(self.c, "lugar_detalle_click", "listado", entidad_id=self.lugar.pk, modo="auto").status_code, 204)
        self.assertEqual(self.enviar(self.c, "evento_detalle_click", "agenda", entidad_id=self.evento.pk, modo="auto").status_code, 204)
        for e in self.eventos():
            self.assertEqual(set(e.meta), {"via"}, e.meta)
        self.assertEqual(len(self.eventos()), 8)

    def test_nunca_se_guarda_un_modo_arbitrario_ni_texto_libre(self):
        self.ruta(modo="auto", destino="https://www.google.com/maps/dir/x", texto="libre")
        (e,) = self.eventos()
        self.assertEqual(e.meta, {"via": "iniciar_ruta", "modo": "auto"})
        self.assertNotIn("google", repr(EventoMetrica.objects.values()))

    def test_modos_permitidos_son_una_lista_cerrada_ampliable_en_un_solo_lugar(self):
        self.assertEqual(entidades.MODOS_RUTA, {"a_pie", "auto"})
        with mock.patch.object(entidades, "MODOS_RUTA", {"a_pie", "auto", "transporte"}):
            self.assertEqual(self.ruta(modo="transporte").status_code, 204)
        self.assertEqual(self.eventos()[-1].meta["modo"], "transporte")
        self.assertEqual(self.ruta(modo="transporte").status_code, 400)  # fuera del parche vuelve a rechazarse

    def test_regresion_los_demas_tipos_frontend_siguen_funcionando(self):
        casos = [
            ("lugar_detalle_click", "listado", dict(entidad_id=self.lugar.pk)),
            ("restaurante_detalle_click", "favoritos", dict(entidad_id=self.establecimiento.pk)),
            ("alojamiento_detalle_click", "chatbot", dict(entidad_slug=self.alojamiento.slug)),
            ("evento_detalle_click", "agenda", dict(entidad_id=self.evento.pk)),
            ("gastronomia_donde_comer_click", "platos_tipicos", dict(entidad_id=self.plato.pk)),
            ("ubicacion_click", "como_llegar", dict(entidad_tipo="servicio", entidad_id=self.servicio.pk)),
            ("ubicacion_click", "abrir_mapa", dict(entidad_tipo="establecimiento", entidad_id=self.alojamiento.pk)),
        ]
        for tipo, via, extra in casos:
            self.assertEqual(self.enviar(self.c, tipo, via, **extra).status_code, 204, (tipo, via))
        self.assertEqual(len(self.eventos()), len(casos))
        for tipo in SERVER_SIDE:  # siguen sin poder enviarse desde el navegador
            self.assertEqual(self.enviar(self.c, tipo, "listado", entidad_id=self.lugar.pk).status_code, 400)


class ModoRutaFrontendEstaticoTests(TestCase):
    """Comprobaciones de las plantillas y los archivos JS. El comportamiento real está en JsNodeTests."""

    PLANTILLAS = (
        "templates/turismo/detalle-lugar-turistico.html",
        "templates/establecimientos/detalle_establecimiento.html",
        "templates/servicios_turista/servicios_utiles.html",
    )

    def test_iniciar_ruta_declara_que_el_modo_se_lee_del_travelmode_del_href(self):
        for ruta in self.PLANTILLAS:
            (etiqueta,) = [e for e in etiquetas_con(leer(ruta), "ubicacion_click") if 'data-metrica-via="iniciar_ruta"' in e]
            self.assertIn("data-enlace-ruta", etiqueta, ruta)
            self.assertIn('data-metrica-modo-desde="travelmode"', etiqueta, ruta)

    def test_ya_no_hay_modo_fijo_en_las_plantillas_que_pueda_quedar_obsoleto(self):
        for ruta in self.PLANTILLAS:
            self.assertNotIn('data-metrica-modo="', leer(ruta), ruta)  # el valor fijo a_pie causaba el bug de F.1

    def test_como_llegar_abrir_mapa_y_servicios_no_declaran_modo(self):
        for ruta in self.PLANTILLAS:
            for etiqueta in etiquetas_con(leer(ruta), "ubicacion_click"):
                if 'data-metrica-via="iniciar_ruta"' not in etiqueta:
                    self.assertNotIn("data-metrica-modo", etiqueta, (ruta, etiqueta))

    def test_el_componente_de_mapa_no_mantiene_un_segundo_estado(self):
        js = leer("static/assets/js/desplazable-como-llegar.js")
        self.assertNotIn("metrica", js.lower())

    def test_metricas_js_lee_el_modo_del_href_al_momento_del_clic(self):
        js = leer("static/assets/js/metricas.js")
        self.assertIn("searchParams.get('travelmode')", js)
        self.assertIn("modo: control.dataset.metricaModoDesde === 'travelmode' ? modoDeRuta(control) : undefined", js)
        self.assertNotIn("metricaModo,", js)  # no se lee un atributo con el modo guardado
        self.assertIn("opciones.modo || ''", js)  # el modo forma parte de la clave anti doble clic


@unittest.skipUnless(shutil.which("node"), "Node no está instalado: se omiten las pruebas de comportamiento de JavaScript")
class JsNodeTests(TestCase):
    """Ejecuta apps/metricas/tests_js con Node (sin dependencias ni paquetes): código real de metricas.js y del componente
    de mapa sobre un DOM simulado, incluido el flujo seleccionar auto -> iniciar ruta -> payload con modo=auto."""

    def test_modo_de_ruta(self):
        resultado = subprocess.run(
            ["node", "apps/metricas/tests_js/modo_ruta.test.js"], cwd=settings.BASE_DIR, capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("OK 8 pruebas", resultado.stdout)
