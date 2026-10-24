from django.test import TestCase
from django.urls import reverse


class HeaderMovilTests(TestCase):
    def get(self, url, idioma="es"):
        self.client.cookies["django_language"] = idioma
        return self.client.get(url)

    def test_selector_desktop_y_selector_movil_en_el_menu(self):
        html = self.get(reverse("base:home")).content.decode()
        self.assertEqual(html.count('class="vi-dropdown vi-lang"'), 1)  # desktop: dentro de .vi-actions
        menu_movil = html.split('id="viMobileMenu"')[1]
        self.assertIn("vi-mobile-lang__switch", menu_movil)  # móvil: al final del menú hamburguesa
        self.assertIn(reverse("set_language"), menu_movil)
        self.assertIn('aria-label="Cambiar a español"', menu_movil)
        self.assertIn('aria-label="Switch to English"', menu_movil)
        self.assertIn('name="next"', menu_movil)  # conserva la página actual como el selector desktop

    def test_idioma_activo_marcado_en_el_selector_movil(self):
        for idioma, etiqueta in (("es", "Cambiar a español"), ("en", "Switch to English")):
            with self.subTest(idioma=idioma):
                menu = self.get(reverse("base:home"), idioma).content.decode().split('id="viMobileMenu"')[1]
                activo = [l for l in menu.split("<button") if "is-current" in l and "vi-mobile-lang__btn" in l]
                self.assertEqual(len(activo), 1)
                self.assertIn(etiqueta, activo[0])

    def test_grupos_del_menu_movil_exponen_aria_expanded(self):
        menu = self.get(reverse("base:home")).content.decode().split('id="viMobileMenu"')[1]
        self.assertGreaterEqual(menu.count('class="vi-mobile-group__summary" aria-expanded="'), 3)
        self.assertLessEqual(menu.count("<details class=\"vi-mobile-group active\" open"), 1)  # solo la sección actual
