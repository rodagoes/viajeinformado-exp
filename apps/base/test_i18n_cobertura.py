"""Cobertura ES/EN de la auditoría completa: textos que antes quedaban en español, renderers
deterministas de PillcoBot, contenido dinámico de movilidad / servicios / emergencias, correos,
UX móvil del calendario de Eventos (ganchos HTML/JS/CSS) y sincronía de claves JS.
"""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import translation

from apps.accounts.views import _enviar_otp
from apps.base.context_processors import js_i18n
from apps.chatbot.services import natural_quick_actions, presenters, quick_actions, response_renderers
from apps.clima.ubicaciones import obtener_ciudad
from apps.emergencias.models import ContactoEmergencia
from apps.eventos.models import Evento
from apps.eventos.tests import EventosTestDataMixin
from apps.movilidad.models import ConsejoMovilidad, TransportePublico
from apps.servicios_turista.models import CategoriaServicioTurista

STATIC_JS = Path(settings.BASE_DIR) / "static" / "assets" / "js"
STATIC_CSS = Path(settings.BASE_DIR) / "static" / "assets" / "css"


class RestauraIdiomaMixin:
    """El cliente de pruebas deja activo el idioma de la última petición en el hilo: se restaura
    para no contaminar a los demás tests (que crean modelos en español)."""

    def setUp(self):
        super().setUp()
        self.addCleanup(translation.activate, "es")


def en(func, *args, **kwargs):
    with translation.override("en"):
        return func(*args, **kwargs)


class PillcoBotRenderersEnInglesTests(TestCase):
    """Los textos deterministas (títulos, CTA, vacíos, fechas) salen en el idioma activo;
    los nombres propios que vienen de la BD no se tocan."""

    EVENTOS = {
        "ok": True, "tool": "buscar_eventos", "count": 1,
        "items": [{
            "nombre": "Festividad de la Danza de los Negritos de Huánuco", "tipo_fecha": "exacta",
            "fecha_inicio": "2026-12-24", "fecha_fin": "2027-01-19", "tipo_costo": "gratis",
            "lugar": "Plaza de Armas de Huánuco", "distrito": "Huánuco", "url_listado": "/eventos/",
        }],
    }

    def test_eventos_en_ingles_conserva_el_nombre_propio(self):
        texto, pres = en(presenters.texto_y_presentacion, "buscar_eventos", self.EVENTOS)
        self.assertEqual(pres["titulo"], "Upcoming events")
        tarjeta = pres["items"][0]
        self.assertEqual(tarjeta["cta_label"], "View event")
        self.assertEqual(tarjeta["nombre"], "Festividad de la Danza de los Negritos de Huánuco")
        self.assertEqual(tarjeta["ubicacion"], "Plaza de Armas de Huánuco")
        self.assertEqual(tarjeta["costo"], "Free")
        self.assertEqual(tarjeta["fecha"], "24 DEC – 19 JAN")
        self.assertIn("Registered events:", texto)
        self.assertIn("See more: /eventos/", texto)

    def test_eventos_en_espanol_no_cambia(self):
        with translation.override("es"):
            texto, pres = presenters.texto_y_presentacion("buscar_eventos", self.EVENTOS)
        self.assertEqual(pres["titulo"], "Eventos próximos")
        self.assertEqual(pres["items"][0]["cta_label"], "Ver evento")
        self.assertEqual(pres["items"][0]["fecha"], "24 DIC – 19 ENE")
        self.assertEqual(pres["items"][0]["costo"], "Gratis")
        self.assertIn("Eventos registrados:", texto)

    def test_eventos_sin_resultados_en_ingles(self):
        texto, pres = en(presenters.presentar_eventos, {"ok": True, "items": []})
        self.assertTrue(texto.startswith("There are no events with a confirmed date in the coming days."))
        self.assertIn("View events calendar: /eventos/", texto)
        self.assertIsNone(pres)

    def test_platos_en_ingles(self):
        resultado = {"ok": True, "tool": "buscar_platos", "count": 1, "items": [
            {"nombre": "Pachamanca huanuqueña", "url_donde_comer": "/restaurantes/?plato=pachamanca"}]}
        _texto, pres = en(presenters.presentar_platos_tipicos, resultado)
        self.assertEqual(pres["titulo"], "Traditional dishes of Huánuco")
        self.assertEqual(pres["items"][0]["cta_label"], "See where to eat")
        self.assertEqual(pres["items"][0]["nombre"], "Pachamanca huanuqueña")

    def test_lugares_y_entrada_en_ingles(self):
        resultado = {"ok": True, "tool": "buscar_lugares", "count": 1, "items": [{
            "nombre": "Kotosh", "categoria": "Sitios arqueológicos", "distrito": "Amarilis",
            "tipo_costo": "gratis", "url": "/lugares/kotosh/", "horario_visita": ""}]}
        texto, pres = en(presenters.presentar_lugares, resultado)
        self.assertEqual(pres["items"][0]["cta_label"], "View place")
        self.assertEqual(pres["items"][0]["entrada"], "Free entry")
        self.assertEqual(pres["items"][0]["nombre"], "Kotosh")
        self.assertTrue(texto.startswith("Registered tourist attractions:"))
        self.assertIn("free admission", texto)

    def test_sin_resultados_y_clima_en_ingles(self):
        self.assertEqual(
            en(response_renderers.renderizar, "buscar_lugares", {"ok": True, "items": [], "count": 0}),
            "I couldn't find any registered information that confirms that.",
        )
        clima = {"ok": True, "item": {
            "disponible": True, "ubicacion": "Huánuco (City)", "estado_texto": "Clear", "temperatura_c": 22,
            "sensacion_c": 21, "humedad_pct": 50, "viento_kph": 5, "probabilidad_lluvia_pct": 10}}
        texto = en(response_renderers.renderizar_clima, clima)
        self.assertTrue(texto.startswith("Current weather in Huánuco (City)"))
        self.assertIn("Feels like: 21 °C", texto)
        self.assertIn("Chance of rain: 10%", texto)

    def test_meses_abreviados_siguen_el_idioma(self):
        self.assertEqual(en(presenters._fecha_corta, "2026-09-05"), "5 SEP")
        self.assertEqual(en(presenters._fecha_corta, "2026-12-05"), "5 DEC")
        with translation.override("es"):
            self.assertEqual(presenters._fecha_corta("2026-01-05"), "5 ENE")
            self.assertEqual(presenters._fecha_corta("2026-08-05"), "5 AGO")

    def test_fecha_larga_del_itinerario(self):
        self.assertEqual(en(presenters._fecha_larga, "2026-09-20"), "September 20, 2026")
        with translation.override("es"):
            self.assertEqual(presenters._fecha_larga("2026-09-20"), "20 de septiembre de 2026")

    def test_favoritos_anonimo_y_vacio_en_ingles(self):
        texto, _ = en(presenters.presentar_favoritos, {"autenticado": False})
        self.assertIn("You need to sign in to view your favorites.", texto)
        texto, _ = en(presenters.presentar_favoritos, {"autenticado": True, "items": [], "tipo": "lugar"})
        self.assertEqual(texto, "You don't have any places saved in favorites.")

    def test_duracion_del_itinerario_usa_plural(self):
        self.assertEqual(en(response_renderers.texto_duracion, 3, 2), "3 days, 2 nights")
        self.assertEqual(en(response_renderers.texto_duracion, 1, 0), "1 day, 0 nights")
        with translation.override("es"):
            self.assertEqual(response_renderers.texto_duracion(3, 2), "3 días, 2 noches")

    def test_etiquetas_de_choices_se_traducen(self):
        item = {"nombre": "Comisaría X", "categoria": "turismo", "numero": "105", "zonas": []}
        self.assertIn("(Tourist Police)", en(response_renderers._emergencia, item))
        with translation.override("es"):
            self.assertIn("(Policía de Turismo)", response_renderers._emergencia(item))

    def test_acciones_rapidas_en_ingles(self):
        etiquetas = {i: en(quick_actions.resolver, i)[0] for i in quick_actions.QUICK_ACTIONS}
        self.assertEqual(etiquetas["eventos_proximos"], "Upcoming events")
        self.assertEqual(etiquetas["tipo_cambio"], "Exchange rate")
        with translation.override("es"):
            self.assertEqual(quick_actions.resolver("eventos_proximos")[0], "Eventos próximos")

    def test_frases_naturales_en_ingles_y_espanol(self):
        self.assertEqual(natural_quick_actions.detectar("What's the weather in Huánuco?"), "clima_huanuco")
        self.assertEqual(natural_quick_actions.detectar("upcoming events"), "eventos_proximos")
        self.assertEqual(natural_quick_actions.detectar("Traditional dishes"), "platos_tipicos")
        self.assertEqual(natural_quick_actions.detectar("eventos próximos"), "eventos_proximos")
        self.assertIsNone(natural_quick_actions.detectar("tell me a long story about Huánuco"))

    def test_bienvenida_del_bot_en_ingles(self):
        with translation.override("en"):
            claves = js_i18n(RequestFactory().get("/"))["vi_i18n"]
        self.assertTrue(claves["pcb_bienvenida"].startswith("Hi! I'm PillcoBot"))
        self.assertEqual(claves["pcb_ver_comer"], "See where to eat")


class ClavesJsSincronizadasTests(RestauraIdiomaMixin, TestCase):
    """Toda clave `ViI18n('clave', ...)` de un .js debe existir en el canal vi-i18n."""

    def test_todas_las_claves_de_js_existen(self):
        claves = js_i18n(RequestFactory().get("/"))["vi_i18n"]
        usadas = set()
        for ruta in STATIC_JS.glob("*.js"):
            usadas |= set(re.findall(r"ViI18n\(\s*['\"](\w+)['\"]", ruta.read_text(encoding="utf-8")))
        self.assertTrue(usadas)
        self.assertEqual(sorted(usadas - set(claves)), [])

    def test_vi_i18n_se_carga_antes_que_los_scripts_de_pagina(self):
        html = self.client.get(reverse("base:home")).content.decode()
        self.assertLess(html.index('id="vi-i18n"'), html.index("vi-i18n.js"))
        self.assertLess(html.index("vi-i18n.js"), html.index("main.js"))


class TextosEstaticosAntesEnEspanolTests(RestauraIdiomaMixin, TestCase):
    def get_en(self, nombre):
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        return self.client.get(reverse(nombre)).content.decode()

    def test_historia_en_ingles_conserva_letra_del_himno_y_provincias(self):
        html = self.get_en("base:historia")
        self.assertIn("History of Huánuco", html)
        self.assertIn("Founding of Huánuco", html)
        self.assertIn("Keep discovering Huánuco", html)
        self.assertIn("Salve oh Huánuco tierra bravía", html)  # letra oficial: no se traduce
        self.assertIn("Dos de Mayo", html)  # topónimo
        self.assertNotIn("Fundación de Huánuco", html)

    def test_historia_en_espanol_no_cambia(self):
        html = self.client.get(reverse("base:historia")).content.decode()
        self.assertIn("Fundación de Huánuco", html)
        self.assertIn("Nuestros símbolos", html)

    def test_paginas_legales_en_ingles_y_correo_intacto(self):
        html = self.get_en("base:privacidad")
        self.assertIn("Privacy Policy", html)
        self.assertIn("mailto:viajeinformadohuanuco@gmail.com", html)
        self.assertIn("Terms and Conditions", self.get_en("base:terminos"))

    def test_filtros_de_lugares_en_ingles(self):
        html = self.get_en("turismo:listado_lugares")
        for texto in ("Difficulty", "Easy", "Difficult", "Cost", "Paid", "Name A–Z"):
            self.assertIn(texto, html)
        self.assertNotIn(">Dificultad<", html)

    def test_clima_atribucion_y_consejos(self):
        html = self.get_en("clima:clima_temporadas")
        self.assertIn("Powered by:", html)
        self.assertIn("Tips", html)
        self.assertNotIn("Con datos de:", html)

    def test_emergencias_qr_y_aria_traducidos(self):
        html = self.get_en("emergencias:emergencias")
        self.assertNotIn("Escanea el código QR", html)
        self.assertNotIn("Copiar el número de", html)
        self.assertIn("For foreign tourists", html)  # bloque bilingüe intencional

    def test_nombres_de_atractivos_del_home_conservan_el_espanol_en_ingles(self):
        html = self.get_en("base:home")
        self.assertIn("La Catedral de Huánuco", html)
        self.assertIn("El templo de las manos cruzadas de Kotosh", html)
        self.assertIn("I recommend visiting", html)  # la oración que los rodea sí se traduce

    def test_nombre_de_ciudad_del_clima_se_traduce_al_leer(self):
        self.assertEqual(en(obtener_ciudad, "huanuco")["nombre_completo"], "Huánuco (City)")
        with translation.override("es"):
            self.assertEqual(obtener_ciudad("huanuco")["nombre_completo"], "Huánuco (Ciudad)")


class CorreosEnElIdiomaActivoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("viajero", "viajero@example.com", "Clave-segura-123", first_name="Ana")

    def test_correo_otp_en_ingles(self):
        with translation.override("en"):
            _enviar_otp(self.user)
        correo = mail.outbox[-1]
        self.assertEqual(correo.subject, "Your verification code - Viaje Informado")
        self.assertIn("Hello Ana,", correo.body)
        self.assertIn("Your verification code is:", correo.body)

    def test_correo_otp_en_espanol(self):
        with translation.override("es"):
            _enviar_otp(self.user)
        correo = mail.outbox[-1]
        self.assertEqual(correo.subject, "Tu código de verificación - Viaje Informado")
        self.assertIn("Hola Ana,", correo.body)


class ContenidoDinamicoAmpliadoTests(EventosTestDataMixin, TestCase):
    """Campos añadidos a modeltranslation: `_en` lleno se muestra en inglés y `_en` vacío cae al ES."""

    def test_consejo_de_movilidad(self):
        c = ConsejoMovilidad.objects.create(texto="Lleva efectivo.", seccion="tarifas_taxi")
        c.texto_en = "Bring cash."
        c.save()
        self.assertEqual(en(lambda: ConsejoMovilidad.objects.get(pk=c.pk).texto), "Bring cash.")
        with translation.override("es"):
            self.assertEqual(ConsejoMovilidad.objects.get(pk=c.pk).texto, "Lleva efectivo.")

    def test_transporte_publico_cae_al_espanol_sin_traduccion(self):
        t = TransportePublico.objects.create(
            nombre="Bicitaxi de prueba", slug="bicitaxi-x", descripcion="Rápido y económico.", tarifa_minima=Decimal("3.00"))
        with translation.override("en"):
            t = TransportePublico.objects.get(pk=t.pk)
            self.assertEqual(t.descripcion, "Rápido y económico.")
            self.assertEqual(t.nombre, "Bicitaxi de prueba")
        t.descripcion_en = "Fast and affordable."
        t.save()
        self.assertEqual(en(lambda: TransportePublico.objects.get(pk=t.pk).descripcion), "Fast and affordable.")

    def test_categoria_de_servicio_y_contacto_de_emergencia(self):
        cat = CategoriaServicioTurista.objects.create(nombre="Hospitales", slug="hospitales-x")
        cat.nombre_en = "Hospitals"
        cat.save()
        self.assertEqual(en(lambda: CategoriaServicioTurista.objects.get(pk=cat.pk).nombre), "Hospitals")
        contacto = ContactoEmergencia.objects.create(
            ambito="nacional", categoria="policia", nombre="Policía Nacional del Perú",
            descripcion="Emergencias de seguridad.", numero_visible="105", numero_tel="105")
        with translation.override("en"):
            contacto = ContactoEmergencia.objects.get(pk=contacto.pk)
            self.assertEqual(contacto.descripcion, "Emergencias de seguridad.")  # fallback ES
            self.assertEqual(contacto.nombre, "Policía Nacional del Perú")  # nombre oficial: no se traduce
        self.assertFalse(hasattr(ContactoEmergencia, "nombre_en"))

    def test_lugar_del_evento_se_traduce_pero_no_el_nombre(self):
        evento = self.evento_base(nombre="Aniversario de Huánuco", lugar="Diversos puntos de la ciudad")
        evento.save()
        Evento.objects.filter(pk=evento.pk).update(lugar_en="Various locations across the city")
        with translation.override("en"):
            evento = Evento.objects.get(pk=evento.pk)
            self.assertEqual(evento.lugar, "Various locations across the city")
            self.assertEqual(evento.nombre, "Aniversario de Huánuco")
        self.assertFalse(hasattr(Evento, "nombre_en"))


class CalendarioMovilEventosTests(RestauraIdiomaMixin, EventosTestDataMixin, TestCase):
    """Ganchos HTML / JS / CSS del calendario (hoja inferior móvil, scroll lock, año, pie)."""

    def html(self, idioma="es", query=""):
        self.client.post(reverse("set_language"), {"language": idioma, "next": "/"})
        return self.client.get(reverse("eventos:listado_eventos") + query).content.decode()

    def test_tres_capas_sin_nombres_duplicados_habilitados(self):
        html = self.html(query="?desde=2026-10-20&hasta=2026-10-31")
        control = re.search(r'<input[^>]*id="ev-rango-input"[^>]*>', html).group(0)
        self.assertNotIn("name=", control)  # capa A: solo visual, no se envía
        ocultos = re.findall(r'<input type="hidden" name="(desde|hasta)"[^>]*data-rango-hidden[^>]*disabled>', html)
        self.assertEqual(sorted(ocultos), ["desde", "hasta"])  # capa B: deshabilitada hasta que Flatpickr esté listo
        nativos = re.findall(r'<input type="date" name="(desde|hasta)"[^>]*>', html)
        self.assertEqual(sorted(nativos), ["desde", "hasta"])  # capa C: fallback nativo activo
        for tag in re.findall(r'<input type="date"[^>]*>', html):
            self.assertNotIn("disabled", tag)

    def test_locale_de_flatpickr_solo_en_espanol(self):
        self.assertIn("l10n/es.js", self.html("es"))
        self.assertNotIn("l10n/es.js", self.html("en"))

    def test_textos_del_calendario_en_ambos_idiomas(self):
        for idioma, esperados in (("es", ("Limpiar", "Listo", "Año")), ("en", ("Clear", "Done", "Year"))):
            self.client.post(reverse("set_language"), {"language": idioma, "next": "/"})
            respuesta = self.client.get(reverse("eventos:listado_eventos"))
            claves = respuesta.context["vi_i18n"]
            self.assertEqual((claves["cal_limpiar"], claves["cal_listo"], claves["cal_anio"]), esperados)
            self.assertIn(claves["cal_titulo"], ("Elegir fechas", "Choose dates"))
            self.assertIn(claves["cal_fin"], ("Elige la fecha de fin", "Choose the end date"))
            nuevos = {
                "es": ("Elegir año", "Año actual", "Década anterior", "Década siguiente"),
                "en": ("Choose year", "Current year", "Previous decade", "Next decade"),
            }[idioma]
            self.assertEqual(
                (claves["cal_elegir_anio"], claves["cal_anio_actual"], claves["cal_decada_ant"], claves["cal_decada_sig"]),
                nuevos,
            )

    def test_javascript_del_calendario(self):
        js = (STATIC_JS / "agenda-eventos.js").read_text(encoding="utf-8")
        inicio = js.index("const inicializarRangoFechas")
        bloque = js[inicio: js.index('CTA "Promociona tu evento"')]
        self.assertNotIn("setTimeout", bloque)  # sin temporizadores para "arreglar" el layout
        for esperado in (
            "closeOnSelect: false", "changeYear(", "ev-cal-anio", "bloquearScroll", "desbloquearScroll",
            "window.scrollTo(0, scrollGuardado)", 'position = "fixed"', "pageshow", "cal_limpiar", "cal_listo",
            "instancia.clear(true, false)", "disableMobile: true",
        ):
            self.assertIn(esperado, bloque)
        self.assertIn('hiddenDesde.value = instancia.formatDate(fechas[0], "Y-m-d")', bloque)

    def test_limpiar_conserva_el_mes_y_anio_visibles(self):
        bloque = self.bloque_calendario()
        limpiar = bloque[bloque.index("limpiar.addEventListener"): bloque.index("const listo = document.createElement")]
        # `clear(true, false)`: sin volver al mes inicial. Ningún salto de vista al limpiar.
        self.assertIn("instancia.clear(true, false)", limpiar)
        self.assertNotRegex(limpiar, r"instancia\.clear\(\s*\)")
        for salto in ("jumpToDate", "changeMonth", "changeYear", "setDate"):
            self.assertNotIn(salto, limpiar)

    def reglas_css(self):
        css = re.sub(r"/\*.*?\*/", "", (STATIC_CSS / "agenda-eventos.css").read_text(encoding="utf-8"), flags=re.S)
        reglas = {}
        for selectores, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            for selector in selectores.split(","):
                reglas.setdefault(" ".join(selector.split()), []).append(cuerpo)
        return reglas

    def test_el_chip_de_fechas_no_impone_ancho(self):
        """El ancho lo dicta el contenido (icono + texto): ninguna regla del chip fija width / min-width /
        flex-basis, y el <input> de Flatpickr sale del flujo (su ancho intrínseco de ~212 px lo estiraba)."""
        reglas = self.reglas_css()
        for selector in (".ev-rango", ".ev-rango__picker", ".ev-fecha-picker", ".ev-fecha-picker__visual",
                         ".ev-rango__picker.is-active .ev-fecha-picker__visual",
                         ".ev-filtros-rapidos__fecha-form"):
            for cuerpo in reglas.get(selector, []):
                self.assertNotRegex(cuerpo, r"(?<![-\w])(min-|max-)?width\s*:", selector)
                self.assertNotRegex(cuerpo, r"flex-basis\s*:", selector)
                self.assertNotRegex(cuerpo, r"flex\s*:\s*[^;]*\d+(px|%|rem)", selector)
        self.assertIn("flex: 0 0 auto", "".join(reglas[".ev-filtros-rapidos__fecha-form"]))
        self.assertIn("white-space: nowrap", "".join(reglas[".ev-fecha-picker__visual"]))
        self.assertIn("position: absolute", "".join(reglas[".ev-rango__control"]))
        self.assertIn("min-height: 44px", "".join(reglas[".ev-fecha-picker__visual"]))  # target táctil

    def test_x_del_chip_dentro_del_chip_y_sin_segunda_x_circular(self):
        reglas = self.reglas_css()
        x = "".join(reglas[".ev-rango__quitar"])
        self.assertIn("position: absolute", x)  # dentro del chip, sobre el input
        self.assertRegex(x, r"z-index:\s*1")
        self.assertRegex(x, r"width:\s*36px")
        self.assertIn(".ev-rango__quitar:focus-visible", reglas)  # foco visible
        self.assertIn(".ev-rango__quitar:hover", reglas)
        self.assertNotIn(".ev-btn-limpiar-rapido", reglas)  # la X circular genérica ya no existe
        self.assertIn(".ev-acciones-rapidas__limpiar", reglas)

    def test_css_de_la_hoja_movil(self):
        css = (STATIC_CSS / "agenda-eventos.css").read_text(encoding="utf-8")
        self.assertIn("max-width: 767.98px", css)
        self.assertIn("position: fixed !important", css)
        self.assertIn("env(safe-area-inset-bottom", css)
        self.assertIn("@keyframes ev-cal-entrada", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("html.ev-cal-bloqueo", css)
        hoja = css[css.index("hoja inferior FIJA"): css.index("Móvil: la fila de filtros rápidos")]
        sin_comentarios = re.sub(r"/\*.*?\*/", "", hoja, flags=re.S)
        self.assertNotRegex(sin_comentarios, r"transform:\s*translate\(-50%")  # causaba el parpadeo en iPhone

    def bloque_calendario(self):
        js = (STATIC_JS / "agenda-eventos.js").read_text(encoding="utf-8")
        return js[js.index("const inicializarRangoFechas"): js.index('CTA "Promociona tu evento"')]

    def test_calendario_sin_minDate_ni_maxDate(self):
        codigo = re.sub(r"//.*", "", self.bloque_calendario())  # sin comentarios
        self.assertNotRegex(codigo, r"(minDate|maxDate)\s*:")  # no se impide ninguna fecha

    def test_selector_de_anio_ya_no_es_un_select_con_lista_fija(self):
        bloque = self.bloque_calendario()
        self.assertNotIn('createElement("select")', bloque)
        for viejo in ("anioMin", "anioMax", "dataset.anioMin", "dataset.anioMax", "insertBefore(nueva", "menulist"):
            self.assertNotIn(viejo, bloque)
        css = (STATIC_CSS / "agenda-eventos.css").read_text(encoding="utf-8")
        self.assertNotIn("menulist-button", css)

    def test_selector_de_anio_por_decadas_sin_tope_y_con_changeyear(self):
        bloque = self.bloque_calendario()
        for esperado in (
            "const DECADA = 10", "Math.floor(anio / DECADA) * DECADA",  # década del año en curso, sin rango fijo
            "Number(panel.dataset.inicio) + delta * DECADA",  # ‹ › avanzan/retroceden 10 años sin límite
            "instancia.changeYear(anio)", "sincronizarAnio(instancia)", "alternarVistaAnios(instancia, false, true)",
            "aria-current", "aria-expanded", 'ViI18n("cal_decada_ant"', 'ViI18n("cal_decada_sig"',
            'ViI18n("cal_anio_actual"', 'ViI18n("cal_elegir_anio"', "anterior.addEventListener", "siguiente.addEventListener",
        ):
            self.assertIn(esperado, bloque)
        self.assertNotRegex(bloque, r"type\s*=\s*[\"']number")  # sin input numérico (teclado)
        # Los años son <button> reales, no divs clicables.
        self.assertIn('document.createElement("button")', bloque[bloque.index("Los 10 botones"):])

    def test_data_anio_de_eventos_se_emite_pero_no_limita(self):
        self.evento_base(nombre="Evento 2031", slug="evento-2031", fecha_inicio=date(2031, 3, 1)).save()
        html = self.html("es")
        self.assertRegex(html, r'id="ev-rango-form"[^>]*data-anio-min="\d{4}" data-anio-max="2031"')

    def test_cierre_por_scroll_solo_en_popover_desktop(self):
        bloque = self.bloque_calendario()
        for esperado in (
            "instalarCierrePorScroll", "quitarCierrePorScroll", "if (cierrePorScroll) return;",  # sin duplicados
            'window.addEventListener("scroll"', 'window.removeEventListener("scroll"',
            'window.addEventListener("resize"', 'window.removeEventListener("resize"',
            "{ passive: true }", "onDestroy: quitarCierrePorScroll", "instancia.close()",
        ):
            self.assertIn(esperado, bloque)
        # Se instala únicamente en la rama de popover (no en la hoja móvil) y se quita al cerrar.
        self.assertEqual(bloque.count("instalarCierrePorScroll(instancia);"), 1)
        self.assertRegex(bloque, r"if \(esHoja\(\)\) bloquearScroll\(\);\s*else \{[^}]*instalarCierrePorScroll\(instancia\)")
        onclose = bloque[bloque.index("onClose:"): bloque.index("onDestroy:")]
        self.assertIn("quitarCierrePorScroll()", onclose)

    def test_jerarquia_de_capas_del_calendario(self):
        css = (STATIC_CSS / "agenda-eventos.css").read_text(encoding="utf-8")
        header = int(re.search(r"z-index:\s*(\d+)", (STATIC_CSS / "header.css").read_text(encoding="utf-8")).group(1))
        sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertNotIn("99999", sin_comentarios)
        self.assertNotIn("99998", sin_comentarios)
        popover = int(re.search(r"\.flatpickr-calendar\.open \{\s*z-index:\s*(\d+)", sin_comentarios).group(1))
        fondo = int(re.search(r"\.ev-cal-fondo \{[^}]*z-index:\s*(\d+)", sin_comentarios).group(1))
        bloque_hoja = re.sub(r"/\*.*?\*/", "", css[css.index("hoja inferior FIJA"):], flags=re.S)
        hoja = int(re.search(r"z-index:\s*(\d+)", bloque_hoja).group(1))
        self.assertLess(popover, header)  # el popover desktop nunca tapa la cabecera fija
        self.assertLess(header, fondo)
        self.assertLess(fondo, hoja)  # la hoja móvil sí queda sobre la cabecera

    def test_sin_eventos_no_se_emiten_limites_de_anio(self):
        Evento.objects.all().delete()
        self.assertNotIn("data-anio-min", self.html("es"))

    def test_rango_y_query_se_conservan_al_cambiar_idioma(self):
        query = "?desde=2026-10-20&hasta=2026-10-31&categoria=x"
        respuesta = self.client.get(reverse("eventos:listado_eventos") + query)
        self.assertContains(respuesta, 'name="next" value="/eventos/?desde=2026-10-20&amp;hasta=2026-10-31&amp;categoria=x"')
        redir = self.client.post(reverse("set_language"), {"language": "en", "next": "/eventos/" + query})
        self.assertEqual(redir["Location"], "/eventos/" + query)

    def test_rango_muestra_la_cabecera_en_ingles(self):
        self.evento_base(nombre="Evento de octubre", fecha_inicio=date(2026, 10, 25)).save()
        html = self.html("en", "?desde=2026-10-20&hasta=2026-10-31")
        self.assertIn("during your trip", html)
        self.assertIn("Change dates", html)


class ImportadorAlcanceAmpliadoTests(TestCase):
    """El importador offline cubre movilidad / servicios / emergencias / Evento.lugar con locators
    estables (sin depender de PK) y un registro ausente en el entorno no es un error."""

    def correr(self, label, registros):
        from apps.base.test_importar_traducciones_en import archivo, correr
        return correr(archivo(*registros, label=label))

    def test_consejo_por_texto_es_y_transporte_por_slug(self):
        c = ConsejoMovilidad.objects.create(texto="Lleva efectivo.", seccion="tarifas_taxi")
        salida = self.correr("movilidad.ConsejoMovilidad", [
            {"locator": {"texto_es": "Lleva efectivo."}, "pk": 999999, "_ref": "x",
             "campos": {"texto": {"es": "Lleva efectivo.", "en": "Bring cash."}}}])
        self.assertIn("Campos cargados: 1", salida)
        self.assertEqual(ConsejoMovilidad.objects.filter(pk=c.pk).values_list("texto_en", flat=True).first(), "Bring cash.")

    def test_contacto_de_emergencia_por_ambito_categoria_nombre(self):
        contacto = ContactoEmergencia.objects.create(
            ambito="nacional", categoria="salud", nombre="SAMU", descripcion="Urgencias médicas.",
            numero_visible="106", numero_tel="106")
        salida = self.correr("emergencias.ContactoEmergencia", [
            {"locator": {"ambito": "nacional", "categoria": "salud", "nombre": "SAMU"}, "pk": 1, "_ref": "SAMU",
             "campos": {"descripcion": {"es": "Urgencias médicas.", "en": "Medical emergencies."}}}])
        self.assertIn("Campos cargados: 1", salida)
        self.assertEqual(
            ContactoEmergencia.objects.filter(pk=contacto.pk).values_list("descripcion_en", flat=True).first(),
            "Medical emergencies.")

    def test_registro_de_produccion_ausente_no_es_error(self):
        salida = self.correr("servicios_turista.ServicioTurista", [
            {"locator": {"slug": "no-existe-aqui"}, "pk": 7, "_ref": "x",
             "campos": {"descripcion_corta": {"es": "Texto", "en": "Text"}}}])
        self.assertIn("[no_encontrado]", salida)
        self.assertIn("Errores: 0", salida)

    def test_modelo_fuera_de_alcance_se_rechaza(self):
        from django.core.management.base import CommandError
        from apps.base.test_importar_traducciones_en import archivo
        with self.assertRaises(CommandError):
            self.correr("ubicaciones.Distrito", [{"locator": {"slug": "x"}, "campos": {"nombre": {"es": "a", "en": "b"}}}])


class AdminDeModelosAmpliadosTests(TestCase):
    def setUp(self):
        self.addCleanup(translation.activate, "es")
        User.objects.create_superuser("admin", "admin@example.com", "Clave-admin-123")
        self.client.login(username="admin", password="Clave-admin-123")

    def test_changelists_y_formularios_con_pestanas_es_en(self):
        for ruta in (
            "movilidad/categoriamovilidad", "movilidad/rutamovilidad", "movilidad/transportepublico",
            "movilidad/consejomovilidad", "servicios_turista/categoriaservicioturista",
            "servicios_turista/servicioturista", "servicios_turista/contactoservicioturista",
            "emergencias/contactoemergencia",
        ):
            self.assertEqual(self.client.get(f"/admin/{ruta}/").status_code, 200, ruta)
            self.assertEqual(self.client.get(f"/admin/{ruta}/add/").status_code, 200, ruta)
        respuesta = self.client.get("/admin/movilidad/consejomovilidad/add/")
        self.assertContains(respuesta, 'name="texto_es"')
        self.assertContains(respuesta, 'name="texto_en"')
