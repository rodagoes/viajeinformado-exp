from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


def _leer(ruta_relativa):
    return (settings.BASE_DIR / "static" / "assets" / ruta_relativa).read_text(encoding="utf-8")


class SkeletonEstaticoTests(SimpleTestCase):
    """El skeleton representa una carga real: nunca hay retrasos artificiales."""

    def test_skeleton_js_no_usa_temporizadores(self):
        js = _leer("js/skeleton.js")
        for prohibido in ("setTimeout", "setInterval", "requestAnimationFrame"):
            self.assertNotIn(prohibido, js)

    def test_skeleton_js_se_retira_con_eventos_reales(self):
        js = _leer("js/skeleton.js")
        for evento in ("'load'", "'error'", "'pageshow'"):
            self.assertIn(evento, js)

    def test_historia_usa_finally_para_retirar_el_skeleton(self):
        js = _leer("js/historia.js")
        self.assertIn(".finally(", js)
        self.assertNotIn("setTimeout", js)

    def test_skeleton_css_respeta_prefers_reduced_motion(self):
        css = _leer("css/componentes/skeleton.css")
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("#EEF3FB", css)
        self.assertIn("#DFE7F3", css)


class SkeletonEnLasPaginasTests(TestCase):
    def test_base_enlaza_css_y_js_del_skeleton(self):
        response = self.client.get(reverse("base:home"))
        self.assertContains(response, "assets/css/componentes/skeleton.css")
        self.assertContains(response, "assets/js/skeleton.js")

    def test_base_emite_el_json_de_cadenas_para_js(self):
        response = self.client.get(reverse("base:home"))
        self.assertContains(response, 'id="vi-i18n"')
