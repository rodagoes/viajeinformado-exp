from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.metricas.choices import OrigenDato
from apps.metricas.models import PeriodoEvaluacion
from apps.metricas.test_servicios import D, diaria, periodo_corto

from .models import ConfiguracionPublica, Sponsor


def configurar(**campos):
    ConfiguracionPublica.objects.update_or_create(pk=1, defaults=campos)


def crear_sponsors(n, activo=True):
    return [
        Sponsor.objects.create(nombre=f"Sponsor {i}", logo=f"sponsors/s{i}.png", orden=i, activo=activo)
        for i in range(1, n + 1)
    ]


def franja_footer(html):
    return html.split('<footer class="vi-footer')[1].split("</footer>")[0]


class ConfiguracionPublicaTests(TestCase):
    def test_singleton_una_sola_fila_y_apagada_por_defecto(self):
        a = ConfiguracionPublica.cargar()
        b = ConfiguracionPublica(mostrar_metricas_home=True)
        b.save()  # intenta crear otra: se guarda sobre la misma fila
        self.assertEqual(ConfiguracionPublica.objects.count(), 1)
        self.assertEqual(a.pk, b.pk)
        ConfiguracionPublica.objects.get().delete()  # no borra
        self.assertEqual(ConfiguracionPublica.objects.count(), 1)
        self.assertFalse(a.mostrar_metricas_home or a.mostrar_sponsors_footer or ConfiguracionPublica.cargar().mostrar_sponsors_footer)

    def test_admin_abre_directo_la_configuracion_y_no_permite_alta_ni_borrado(self):
        self.client.force_login(get_user_model().objects.create_superuser("cfg", "c@example.com", "x-pass-123"))
        r = self.client.get(reverse("admin:base_configuracionpublica_changelist"))
        self.assertRedirects(r, reverse("admin:base_configuracionpublica_change", args=[1]), fetch_redirect_response=False)
        pagina = self.client.get(reverse("admin:base_configuracionpublica_change", args=[1]))
        self.assertContains(pagina, "Mostrar estadísticas en Home")
        self.assertContains(pagina, "Mostrar sponsors en Footer")
        self.assertEqual(self.client.get(reverse("admin:base_configuracionpublica_add")).status_code, 403)


class HomeCifrasToggleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = periodo_corto()
        diaria(cls.periodo, D(2026, 6, 1), nuevos=5, sesiones=10)

    def test_off_no_renderiza_la_seccion(self):
        configurar(mostrar_metricas_home=False)
        html = self.client.get("/").content.decode()
        self.assertNotIn("home-metricas", html)
        self.assertNotIn("VIAJE INFORMADO EN CIFRAS", html)

    def test_on_muestra_las_cuatro_cards(self):
        configurar(mostrar_metricas_home=True)
        html = self.client.get("/").content.decode()
        self.assertIn("home-metricas", html)
        self.assertEqual(html.count("home-metricas__card"), 4)

    @override_settings(METRICAS_HOME_ORIGEN=OrigenDato.REAL)
    def test_on_con_origen_real_sin_datos_reales_no_muestra_ceros(self):
        configurar(mostrar_metricas_home=True)
        self.assertNotIn("home-metricas", self.client.get("/").content.decode())  # hay datos SIMULADOS, no REAL


class SponsorsFooterTests(TestCase):
    def footer(self):
        return franja_footer(self.client.get("/").content.decode())

    def test_toggle_off_no_muestra_sponsors(self):
        crear_sponsors(2)
        configurar(mostrar_sponsors_footer=False)
        self.assertNotIn("vi-sponsors", self.footer())

    def test_toggle_on_sin_sponsors_activos_no_deja_franja(self):
        configurar(mostrar_sponsors_footer=True)
        self.assertNotIn("vi-sponsors", self.footer())
        crear_sponsors(2, activo=False)
        self.assertNotIn("vi-sponsors", self.footer())

    def test_toggle_on_con_activo_lo_muestra_con_y_sin_enlace(self):
        configurar(mostrar_sponsors_footer=True)
        Sponsor.objects.create(nombre="Con enlace", logo="sponsors/a.png", url="https://ejemplo.com/", orden=1)
        Sponsor.objects.create(nombre="Sin enlace", logo="sponsors/b.png", orden=2)
        Sponsor.objects.create(nombre="Inactivo", logo="sponsors/c.png", orden=3, activo=False)
        footer = self.footer()
        self.assertIn('alt="Con enlace"', footer)
        self.assertIn('href="https://ejemplo.com/" target="_blank" rel="noopener noreferrer"', footer)
        self.assertIn('alt="Sin enlace"', footer)
        self.assertNotIn("Inactivo", footer)
        self.assertEqual(footer.count('class="vi-sponsor__link"'), 1)
        self.assertLess(footer.index("Con enlace"), footer.index("Sin enlace"))  # respeta el orden

    def test_cantidad_visible_segun_total(self):
        configurar(mostrar_sponsors_footer=True)
        esperado = {1: (1, 1), 3: (3, 3), 5: (5, 3), 6: (5, 3)}
        creados = 0
        for total in (1, 3, 5, 6):
            while creados < total:
                creados += 1
                Sponsor.objects.create(nombre=f"S{creados}", logo=f"sponsors/{creados}.png", orden=creados)
            footer = self.footer()
            desktop, movil = esperado[total]
            self.assertIn(f"--sp-n-d: {desktop}; --sp-n-m: {movil};", footer, total)
            self.assertEqual(footer.count('class="vi-sponsor"'), total)
            self.assertIn('data-max-desktop="5" data-max-movil="3"', footer)

    def test_una_sola_consulta_de_configuracion_por_peticion(self):
        configurar(mostrar_sponsors_footer=True, mostrar_metricas_home=True)  # Home y footer comparten la configuración
        crear_sponsors(2)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get("/")
        consultas = [q for q in ctx.captured_queries if "base_configuracionpublica" in q["sql"].lower()]
        self.assertEqual(len(consultas), 1)


class AdminPruebasLocalVsProduccionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("pruebas", "p@example.com", "x-pass-123")
        cls.periodo = periodo_corto()

    def setUp(self):
        self.client.force_login(self.admin)

    def urls(self):
        return (
            reverse("admin:metricas_periodoevaluacion_changelist"),
            reverse("admin:metricas_generacionsimulada_changelist"),
        )

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=True)
    def test_local_muestra_generaciones_y_periodos(self):
        indice = self.client.get(reverse("admin:index")).content.decode()
        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertIn(f'href="{url}"', indice)  # sidebar

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_los_oculta_sin_borrar_datos(self):
        indice = self.client.get(reverse("admin:index")).content.decode()
        for url in self.urls():
            self.assertNotIn(f'href="{url}"', indice)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertTrue(PeriodoEvaluacion.objects.filter(pk=self.periodo.pk).exists())  # los datos siguen ahí

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_conserva_las_metricas_reales(self):
        indice = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn(reverse("admin:metricas_metricadiaria_changelist"), indice)
        self.assertEqual(self.client.get(reverse("admin:metricas_metricadiaria_changelist")).status_code, 200)
