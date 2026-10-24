"""Humo global del Admin: el tema (sidebar, filtros como <select>) no rompe ninguna pantalla registrada."""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


def _url(modelo, accion):
    meta = modelo._meta
    return reverse(f"admin:{meta.app_label}_{meta.model_name}_{accion}")


class AdminGlobalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser("humo-admin", "h@example.com", "x-pass-123")

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_todas_las_listas_y_altas_cargan_con_sidebar_y_filtros_select(self):
        revisados = 0
        for modelo, model_admin in admin.site._registry.items():
            with self.subTest(modelo=modelo.__name__):
                lista = self.client.get(_url(modelo, "changelist"), follow=True)  # Configuración pública redirige a su única fila
                self.assertEqual(lista.status_code, 200)
                self.assertContains(lista, 'id="vi-nav-scroll"')  # cabecera fija + lista con scroll propio
                if model_admin.list_filter:
                    self.assertContains(lista, 'class="vi-filter"')
                    self.assertNotContains(lista, "<details data-filter-title")  # ya no hay filtros en lista vertical
                if model_admin.has_add_permission(lista.wsgi_request):
                    self.assertEqual(self.client.get(_url(modelo, "add")).status_code, 200)
                revisados += 1
        self.assertGreater(revisados, 50)

    def test_selects_de_filtro_conservan_busqueda_orden_y_otros_filtros(self):
        from apps.establecimientos.models import Establecimiento

        lista = self.client.get(_url(Establecimiento, "changelist"), {"q": "fogon", "o": "1", "tipo__exact": "restaurante"})
        html = lista.content.decode()
        # una opción del filtro "activo" arrastra búsqueda, orden y el otro filtro activo
        opcion = [l for l in html.splitlines() if "activo__exact=1" in l and "<option" in l]
        self.assertTrue(opcion)
        for fragmento in ("q=fogon", "o=1", "tipo__exact=restaurante"):
            self.assertIn(fragmento, opcion[0])
