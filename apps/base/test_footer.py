from datetime import date

from django.test import TestCase
from django.urls import reverse


class FooterTests(TestCase):
    def html(self, idioma="es"):
        self.client.cookies["django_language"] = idioma
        pagina = self.client.get(reverse("base:home")).content.decode()
        return pagina.split('<footer class="vi-footer')[1].split("</footer>")[0]

    def test_logo_unico_sin_texto_duplicado_de_marca(self):
        footer = self.html()
        self.assertEqual(footer.count('class="vi-footer__logo"'), 1)  # un solo logo (el resto de <img> son los iconos SVG de sección)
        self.assertIn("logo-footer.webp", footer)
        self.assertNotIn("<h3>VIAJE INFORMADO</h3>", footer)  # el nombre va dentro de la imagen, no como texto

    def test_navegacion_reutiliza_las_rutas_reales_del_header(self):
        footer = self.html()
        for nombre in (
            "turismo:listado_lugares", "base:historia", "establecimientos:listado_restaurantes",
            "gastronomia:platos_tipicos", "establecimientos:listado_alojamientos", "eventos:listado_eventos",
            "movilidad:tarifas_taxi", "movilidad:como_llegar", "clima:clima_temporadas", "monedas:tipo_cambio",
            "servicios_turista:servicios_utiles", "emergencias:emergencias", "base:privacidad", "base:terminos",
        ):
            self.assertIn(f'href="{reverse(nombre)}"', footer, nombre)
        self.assertNotIn('href="#"', footer)

    def test_redes_sociales_originales_gmail_facebook_instagram(self):
        footer = self.html()
        for red, icono in (("google", "bi-google"), ("facebook", "bi-facebook"), ("instagram", "bi-instagram")):
            self.assertIn(f'data-social="{red}"', footer)
            self.assertIn(icono, footer)
        self.assertEqual(footer.count('<div class="filled">'), 3)  # relleno animado original
        self.assertIn('href="mailto:viajeinformadohuanuco@gmail.com"', footer)
        self.assertIn('aria-label="Enviar correo electrónico"', footer)
        self.assertIn('href="https://www.facebook.com/viajeinformadohco/"', footer)
        self.assertIn('href="https://www.instagram.com/viajeinformadohco/"', footer)
        self.assertEqual(footer.count('rel="noopener noreferrer"'), 2)
        self.assertNotIn('href="#"', footer)

    def test_acordeon_movil_solo_en_categorias_con_subopciones(self):
        footer = self.html()
        self.assertEqual(footer.count('<details class="vi-footer__group"'), 3)  # Explorar, Gastronomía, Planifica
        self.assertIn("vi-footer__col--single", footer)  # Eventos: enlace directo
        self.assertNotIn("onerror=", footer)  # el logo .webp ya existe: sin fallback provisional

    def test_iconos_de_seccion_son_svg_editables_desde_el_template(self):
        footer = self.html()
        for archivo, clase in (
            ("explorar.svg", "explorar"), ("gastronomia-alojamiento.svg", "gastronomia"), ("eventos.svg", "eventos"),
            ("planifica.svg", "planifica"), ("contacto.svg", "contacto"),
        ):
            self.assertIn(f"/static/assets/img/footer/icons/{archivo}", footer)
            self.assertIn(f"vi-footer__icon--{clase}", footer)
        self.assertEqual(footer.count("vi-footer__section-icon-img"), 5)
        self.assertIn("bi-google", footer)  # los iconos sociales no se tocan

    def test_copyright_con_anio_dinamico_en_es_y_en(self):
        anio = date.today().year
        self.assertIn(f"© {anio} Viaje Informado Huánuco. Todos los derechos reservados.", self.html("es"))
        self.assertIn(f"© {anio} Viaje Informado Huánuco. All rights reserved.", self.html("en"))

    def test_titulos_traducidos_en_ingles(self):
        footer = self.html("en")
        for texto in ("Explore", "Food and lodging", "Plan", "CONTACT", "Privacy policy", "Terms and conditions"):
            self.assertIn(texto, footer)
