from datetime import date, time

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from apps.eventos.models import CategoriaEvento, Evento
from apps.eventos.tests import EventosTestDataMixin


class ContenidoDinamicoFallbackTests(TestCase):
    """django-modeltranslation: `_en` vacío cae al español, `_en` lleno se muestra."""

    def setUp(self):
        self.cat = CategoriaEvento.objects.create(
            nombre="Festividades", slug="festividades", descripcion="Fiestas tradicionales"
        )

    def test_es_es_el_idioma_por_defecto(self):
        with translation.override("es"):
            self.assertEqual(CategoriaEvento.objects.get(pk=self.cat.pk).descripcion, "Fiestas tradicionales")

    def test_en_vacio_cae_al_espanol(self):
        with translation.override("en"):
            cat = CategoriaEvento.objects.get(pk=self.cat.pk)
            self.assertEqual(cat.descripcion, "Fiestas tradicionales")
            self.assertEqual(cat.nombre, "Festividades")

    def test_en_lleno_se_muestra_en_ingles(self):
        self.cat.descripcion_en = "Traditional festivities"
        self.cat.nombre_en = "Festivities"
        self.cat.save()
        with translation.override("en"):
            cat = CategoriaEvento.objects.get(pk=self.cat.pk)
            self.assertEqual(cat.descripcion, "Traditional festivities")
            self.assertEqual(cat.nombre, "Festivities")
        with translation.override("es"):
            self.assertEqual(CategoriaEvento.objects.get(pk=self.cat.pk).nombre, "Festividades")

    def test_columna_original_conserva_el_espanol(self):
        # El código anterior al cambio (rollback) sigue leyendo la columna original.
        with connection.cursor() as cursor:
            cursor.execute("SELECT nombre FROM eventos_categoriaevento WHERE id = %s", [self.cat.pk])
            self.assertEqual(cursor.fetchone()[0], "Festividades")

    def test_nombre_de_evento_no_se_traduce(self):
        self.assertFalse(hasattr(Evento, "nombre_en"))


class SelectorDeIdiomaTests(TestCase):
    """Infraestructura Django i18n: cookie, idioma por defecto y `next`."""

    def test_espanol_es_el_idioma_por_defecto(self):
        response = self.client.get(reverse("base:home"))
        self.assertContains(response, '<html lang="es">')

    def test_accept_language_del_navegador_se_ignora(self):
        response = self.client.get(reverse("base:home"), headers={"accept-language": "en-US,en;q=0.9"})
        self.assertContains(response, '<html lang="es">')

    def test_cambiar_a_ingles_fija_cookie_y_lang(self):
        response = self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.cookies["django_language"].value, "en")
        self.assertContains(self.client.get(reverse("base:home")), '<html lang="en">')

    def test_el_idioma_persiste_al_navegar(self):
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        for nombre in ("base:home", "base:historia", "eventos:listado_eventos"):
            self.assertContains(self.client.get(reverse(nombre)), '<html lang="en">')

    def test_idioma_invalido_se_ignora(self):
        self.client.post(reverse("set_language"), {"language": "pt", "next": "/"})
        self.assertContains(self.client.get(reverse("base:home")), '<html lang="es">')

    def test_next_externo_se_rechaza(self):
        response = self.client.post(reverse("set_language"), {"language": "en", "next": "https://evil.example/"})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example", response["Location"])

    def test_header_incluye_selector_con_next_de_la_url_completa(self):
        response = self.client.get("/eventos/?categoria=festividades&page=2")
        self.assertContains(response, 'name="next" value="/eventos/?categoria=festividades&amp;page=2"')
        self.assertContains(response, 'name="language" value="en"')
        self.assertContains(response, 'name="language" value="es"')


class PillcoBotIdiomaTests(TestCase):
    def test_el_prompt_en_espanol_no_cambia_y_en_ingles_pide_responder_en_ingles(self):
        from apps.chatbot.services.system_prompt import construir_system_prompt

        with translation.override("es"):
            es = construir_system_prompt()
        with translation.override("en"):
            en = construir_system_prompt()
        self.assertNotIn("IDIOMA DE LA INTERFAZ", es)
        self.assertIn("IDIOMA DE LA INTERFAZ", en)
        self.assertTrue(en.startswith(es))


class ContenidoDinamicoP1Tests(TestCase):
    """Lugares, establecimientos, platos y hero: `_en` lleno se muestra en inglés,
    `_en` vacío cae al español (nunca error ni vacío) y los nombres propios no se traducen."""

    def test_lugar_turistico_descripcion_en_y_fallback(self):
        from apps.turismo.models import CategoriaLugarTuristico, LugarTuristico
        from apps.ubicaciones.models import Departamento, Distrito, Provincia

        dep = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        prov = Provincia.objects.create(departamento=dep, nombre_oficial="Huánuco", slug="huanuco")
        dist = Distrito.objects.create(provincia=prov, nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101")
        cat = CategoriaLugarTuristico.objects.create(nombre="Arqueológico", slug="arqueologico")
        lugar = LugarTuristico.objects.create(
            categoria_principal=cat, distrito=dist, nombre="Kotosh", slug="kotosh",
            descripcion="Templo antiguo", historia="Historia en español",
        )
        lugar.descripcion_en = "Ancient temple"
        lugar.save()
        with translation.override("en"):
            lugar = LugarTuristico.objects.get(pk=lugar.pk)
            self.assertEqual(lugar.descripcion, "Ancient temple")
            self.assertEqual(lugar.historia, "Historia en español")  # sin _en: fallback ES
            self.assertEqual(lugar.nombre, "Kotosh")  # nombre propio: no se traduce
        with translation.override("es"):
            self.assertEqual(LugarTuristico.objects.get(pk=lugar.pk).descripcion, "Templo antiguo")
        self.assertFalse(hasattr(LugarTuristico, "nombre_en"))

    def test_establecimiento_y_plato_no_traducen_el_nombre(self):
        from apps.establecimientos.models import CategoriaEstablecimiento, Establecimiento
        from apps.gastronomia.models import CategoriaPlatoTipico, PlatoTipico
        from apps.ubicaciones.models import Departamento, Distrito, Provincia

        dep = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        prov = Provincia.objects.create(departamento=dep, nombre_oficial="Huánuco", slug="huanuco")
        dist = Distrito.objects.create(provincia=prov, nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101")
        cat_est = CategoriaEstablecimiento.objects.create(nombre="Criolla", slug="criolla")
        est = Establecimiento.objects.create(
            categoria_principal=cat_est, tipo="restaurante", nombre="La Casona", slug="la-casona", descripcion_corta="Comida local"
        )
        est.descripcion_corta_en = "Local food"
        est.save()
        cat = CategoriaPlatoTipico.objects.create(nombre="Postres típicos", slug="postres-tipicos")
        plato = PlatoTipico.objects.create(categoria=cat, nombre="Patachi", slug="patachi", descripcion_corta="Sopa")
        with translation.override("en"):
            self.assertEqual(Establecimiento.objects.get(pk=est.pk).descripcion_corta, "Local food")
            self.assertEqual(PlatoTipico.objects.get(pk=plato.pk).descripcion_corta, "Sopa")  # fallback
            self.assertEqual(PlatoTipico.objects.get(pk=plato.pk).nombre, "Patachi")
        self.assertFalse(hasattr(Establecimiento, "nombre_en"))
        self.assertFalse(hasattr(PlatoTipico, "nombre_en"))

    def test_hero_slide_titulo_en_y_fallback(self):
        from apps.base.models import HomeHeroSlide

        slide = HomeHeroSlide.objects.create(
            etiqueta="Historia", titulo_principal="Descubre lugares", titulo_resaltado="con identidad",
            descripcion="Tu guía", archivo="home/hero/x.jpg",
        )
        slide.titulo_principal_en = "Discover places"
        slide.save()
        with translation.override("en"):
            slide = HomeHeroSlide.objects.get(pk=slide.pk)
            self.assertEqual(slide.titulo_principal, "Discover places")
            self.assertEqual(slide.titulo_resaltado, "con identidad")  # fallback ES

    def test_pagina_publica_en_ingles_muestra_el_campo_traducido(self):
        cat = CategoriaEvento.objects.create(nombre="Festividades", slug="festividades", descripcion="Fiestas")
        cat.nombre_en = "Festivities"
        cat.save()
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, "Festivities")
        self.client.post(reverse("set_language"), {"language": "es", "next": "/"})
        self.assertContains(self.client.get(reverse("eventos:listado_eventos")), "Festividades")


class AdminTraducidoTests(TestCase):
    """Los admin con TranslationAdmin siguen cargando (changelist y formulario)."""

    def setUp(self):
        from django.contrib.auth.models import User

        self.admin = User.objects.create_superuser("admin", "a@example.com", "pass12345")
        self.client.force_login(self.admin)

    def test_changelists_y_formularios_cargan(self):
        for ruta in (
            "eventos/evento", "eventos/categoriaevento", "turismo/lugarturistico",
            "establecimientos/establecimiento", "gastronomia/platotipico", "base/homeheroslide",
        ):
            self.assertEqual(self.client.get(f"/admin/{ruta}/").status_code, 200, ruta)
            self.assertEqual(self.client.get(f"/admin/{ruta}/add/").status_code, 200, ruta)

    def test_formulario_de_categoria_ofrece_campos_es_y_en(self):
        response = self.client.get("/admin/eventos/categoriaevento/add/")
        self.assertContains(response, 'name="nombre_es"')
        self.assertContains(response, 'name="nombre_en"')


class TextosEstaticosEnInglesTests(TestCase):
    """Con la cookie en `en` los textos estáticos cambian (catálogo locale/en);
    en español (por defecto) siguen igual."""

    def setUp(self):
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})

    def test_navegacion_principal_en_ingles(self):
        response = self.client.get(reverse("base:home"))
        for texto in (">Home</a>", ">Events</a>", "Explore", "Plan", "Sign in"):
            self.assertContains(response, texto)
        self.assertNotContains(response, ">Inicio</a>")
        self.assertNotContains(response, ">Eventos</a>")

    def test_navegacion_en_espanol_por_defecto(self):
        cliente = self.client_class()
        response = cliente.get(reverse("base:home"))
        self.assertContains(response, ">Inicio</a>")
        self.assertContains(response, ">Eventos</a>")
        self.assertContains(response, "Iniciar sesión")

    def test_eventos_textos_del_selector_de_fechas(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        for texto in ("Choose dates", "Tomorrow", "This weekend", "Filters", "Apply filters", "Promote your event"):
            self.assertContains(response, texto)
        self.assertNotContains(response, "Elegir fechas")

    def test_pagina_de_login_en_ingles(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, "Welcome")
        self.assertContains(response, "Enter your password")
        self.assertNotContains(response, "Ingrese su contraseña")

    def test_errores_de_formulario_en_ingles(self):
        from apps.accounts.forms import RegistroForm

        with translation.override("en"):
            form = RegistroForm(data={"password1": "Abcdef1!", "password2": "distinta"})
            form.is_valid()
            errores = str(form.errors)
        self.assertIn("Both passwords must match.", errores)

    def test_mensaje_del_cta_de_eventos_en_ingles(self):
        response = self.client.post(
            reverse("eventos:reportar_problema_evento"), {"nombre_problema": ""}, follow=True
        )
        self.assertContains(response, "We could not send your report")

    def test_bloque_bilingue_de_emergencias_no_se_toca(self):
        # Tiene su propio selector ES/ENG con ambos textos literales.
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertContains(response, "For foreign tourists")

    def test_cadenas_para_js_en_ingles(self):
        response = self.client.get(reverse("base:home"))
        self.assertContains(response, r"Sending\u2026")  # json_script escapa la elipsis
        self.assertContains(response, '"MON"')
        self.assertContains(response, "Calendar - %(anio)s")

    def test_texto_sin_traduccion_cae_al_original_sin_error(self):
        sin_catalogo = "Texto que no existe en el " + "catálogo"  # variable: makemessages no la extrae
        with translation.override("en"):
            self.assertEqual(translation.gettext(sin_catalogo), sin_catalogo)


class RangoDeFechasEnInglesTests(EventosTestDataMixin, TestCase):
    DESDE = "2026-10-20"
    HASTA = "2026-10-31"

    def setUp(self):
        self.url = reverse("eventos:listado_eventos")
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})

    def crear_dia(self, dia, **kw):
        evento = self.evento_base(tipo_fecha="exacta", fecha_inicio=dia, **kw)
        evento.full_clean()
        evento.save()
        return evento

    def consultar(self, desde=DESDE, hasta=HASTA, **extra):
        return self.client.get(self.url, {"desde": desde, "hasta": hasta, **extra})

    def test_titulos_del_fallback_y_distancias(self):
        self.crear_dia(date(2026, 10, 15))
        self.crear_dia(date(2026, 11, 7))
        response = self.consultar()
        self.assertContains(response, "Events during your selected dates")
        self.assertContains(response, "Just before your visit")
        self.assertContains(response, "Shortly after your visit")
        self.assertContains(response, "5 days before your arrival")
        self.assertContains(response, "7 days after your trip")
        self.assertContains(response, "We found some celebrations very close to your dates.")
        self.assertContains(
            response, "There are no events scheduled exactly between October 20 and October 31."
        )

    def test_distancias_en_singular(self):
        self.crear_dia(date(2026, 10, 19))
        self.crear_dia(date(2026, 11, 1))
        response = self.consultar()
        self.assertContains(response, "1 day before your arrival")
        self.assertContains(response, "1 day after your trip")

    def test_sin_cercanos_en_ingles(self):
        response = self.consultar()
        self.assertContains(response, "We have no events registered near those dates.")
        self.assertContains(response, "While you are in Huánuco, you can also discover:")
        self.assertContains(response, "Tourist attractions")
        self.assertContains(response, "Change dates")

    def test_titulo_con_resultados_singular_y_plural(self):
        self.crear_dia(date(2026, 10, 25))
        self.assertContains(self.consultar(), "1 event during your trip")
        self.crear_dia(date(2026, 10, 26))
        self.assertContains(self.consultar(), "2 events during your trip")

    def test_resumen_de_fechas_y_formato_de_dia(self):
        self.crear_dia(date(2026, 10, 25))
        response = self.consultar()
        self.assertContains(response, "Oct. 20 – Oct. 31")
        self.assertContains(response, "October 25")  # fecha de la card sin año, orden inglés

    def test_errores_de_validacion_en_ingles(self):
        self.assertContains(self.consultar("2026-01-01", "2027-01-03"), "Select a range of up to 366 days.")
        self.assertContains(
            self.consultar("2026-10-31", "2026-10-20"), "The end date cannot be earlier than the start date."
        )
        self.assertContains(
            self.consultar(hasta=""), "Select a valid start date and end date."
        )

    def test_estado_y_horario_en_ingles(self):
        hoy = timezone.localdate()
        evento = self.evento_base(tipo_fecha="exacta", fecha_inicio=hoy, tipo_horario="todo_el_dia", hora_inicio=None)
        evento.full_clean()
        evento.save()
        response = self.client.get(self.url)
        tarjeta = response.context["tarjetas"][0]
        self.assertEqual(tarjeta["estado"], "Today")
        self.assertEqual(tarjeta["horario"], "All day")
        self.assertEqual(tarjeta["estado_slug"], "hoy")  # el CSS depende de la clave estable

    def test_reglas_de_fecha_relativa_en_ingles(self):
        from apps.eventos.views import celebracion_resumen

        evento = self.evento_base(
            tipo_fecha="anual_relativa", fecha_inicio=None, orden_semana_relativa=2,
            dia_semana_relativa=5, mes_relativa=9,
        )
        with translation.override("en"):
            self.assertEqual(celebracion_resumen(evento), "Every second Saturday of September")
        with translation.override("es"):
            self.assertEqual(celebracion_resumen(evento), "Cada segundo sábado de septiembre")

    def test_horas_am_pm(self):
        from apps.eventos.views import horario_card_texto

        evento = self.evento_base(hora_inicio=time(15, 30))
        with translation.override("en"):
            self.assertEqual(horario_card_texto(evento), "3:30 PM")
        with translation.override("es"):
            self.assertEqual(horario_card_texto(evento), "3:30 p. m.")


class ClimaIdiomaTests(TestCase):
    def test_etiqueta_del_clima_se_traduce_al_leer_y_la_cache_no_se_contamina(self):
        from unittest.mock import patch as _patch

        from apps.clima.services import clima_actual

        cacheado = {"disponible": True, "estado_texto": "Despejado"}
        with _patch.object(clima_actual, "_obtener_clima_actual", return_value=cacheado):
            with translation.override("en"):
                self.assertEqual(clima_actual.obtener_clima_actual()["estado_texto"], "Clear")
            with translation.override("es"):
                self.assertEqual(clima_actual.obtener_clima_actual()["estado_texto"], "Despejado")
        self.assertEqual(cacheado["estado_texto"], "Despejado")  # no se muta el dato cacheado


class EtiquetasDeChoicesTests(TestCase):
    """Las etiquetas de `choices` visibles (dificultad, rango de precio) se traducen en el template."""

    def test_catalogo_en_ingles(self):
        from django.utils.translation import gettext

        with translation.override("en"):
            self.assertEqual(gettext("Fácil"), "Easy")
            self.assertEqual(gettext("Difícil"), "Difficult")
            self.assertEqual(gettext("Económico"), "Budget")
        with translation.override("es"):
            self.assertEqual(gettext("Difícil"), "Difícil")

    def test_las_etiquetas_extraidas_no_incluyen_datos_tecnicos(self):
        # El catálogo no debe contener correos, URLs ni clases CSS como msgid.
        import re

        from django.conf import settings

        po = (settings.BASE_DIR / "locale" / "en" / "LC_MESSAGES" / "django.po").read_text(encoding="utf-8")
        ids = re.findall(r'^msgid "(.+)"$', po, re.M)
        for msgid in ids:
            self.assertNotRegex(msgid, r"\w@\w", msgid)
            self.assertNotRegex(msgid, r"https?://", msgid)
            self.assertNotRegex(msgid, r"^vi-[a-z-]+$", msgid)
        self.assertNotIn("fuzzy", po)
