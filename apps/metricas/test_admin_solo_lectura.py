"""Métricas diarias e Interacciones diarias: CRUD completo en local, solo consulta en producción (solo desde el Admin)."""
from datetime import date

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .admin import InteraccionDiariaAdmin, MetricaDiariaAdmin
from .choices import OrigenDato, TipoInteraccion
from .models import InteraccionDiaria, MetricaDiaria
from .test_servicios import diaria, periodo_corto

REAL, SIM = OrigenDato.REAL, OrigenDato.SIMULADO
MODELOS = (("metricadiaria", MetricaDiaria, MetricaDiariaAdmin), ("interacciondiaria", InteraccionDiaria, InteraccionDiariaAdmin))


def u(modelo, accion, *args):
    return reverse(f"admin:metricas_{modelo}_{accion}", args=args)


class SoloLecturaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("ro-met", "r@example.com", "x-pass-123")
        cls.periodo = periodo_corto()
        cls.m_real = diaria(cls.periodo, date(2026, 10, 12), nuevos=2, origen=REAL)
        cls.m_sim = diaria(cls.periodo, date(2026, 6, 10), nuevos=2, origen=SIM)
        cls.i_real = InteraccionDiaria.objects.create(
            periodo=cls.periodo, origen=REAL, fecha=date(2026, 10, 12), tipo=TipoInteraccion.CHATBOT_CONSULTA, cantidad=3)
        cls.i_sim = InteraccionDiaria.objects.create(
            periodo=cls.periodo, origen=SIM, fecha=date(2026, 6, 10), tipo=TipoInteraccion.CHATBOT_CONSULTA, cantidad=3)

    def setUp(self):
        self.client.force_login(self.usuario)

    def permisos(self, clase, modelo, obj=None):
        request = RequestFactory().get("/")
        request.user = self.usuario
        ma = clase(modelo, admin.site)
        return ma.has_add_permission(request), ma.has_change_permission(request, obj), ma.has_delete_permission(request, obj)

    # ------------------------------------------------------------------ local
    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=True)
    def test_local_conserva_alta_edicion_y_borrado(self):
        for _, modelo, clase in MODELOS:
            with self.subTest(modelo=modelo.__name__):
                self.assertEqual(self.permisos(clase, modelo), (True, True, True))
        # y las pantallas siguen ofreciendo el flujo de siempre
        self.assertEqual(self.client.get(u("metricadiaria", "add")).status_code, 200)
        self.assertEqual(self.client.get(u("interacciondiaria", "add")).status_code, 200)
        self.assertContains(self.client.get(u("metricadiaria", "changelist")), u("metricadiaria", "add"))
        ficha = self.client.get(u("metricadiaria", "change", self.m_sim.pk))
        self.assertContains(ficha, "_save")

    # ------------------------------------------------------------- producción
    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_sin_permisos_de_escritura(self):
        for _, modelo, clase in MODELOS:
            with self.subTest(modelo=modelo.__name__):
                self.assertEqual(self.permisos(clase, modelo), (False, False, False))

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_sin_anadir_ni_en_listado_ni_en_sidebar(self):
        for nombre, _, _ in MODELOS:
            with self.subTest(modelo=nombre):
                self.assertEqual(self.client.get(u(nombre, "add")).status_code, 403)
                listado = self.client.get(u(nombre, "changelist"))
                self.assertEqual(listado.status_code, 200)
                self.assertNotContains(listado, u(nombre, "add"))  # ni el botón superior ni el "+ Añadir" del sidebar
                self.assertNotContains(listado, "delete_selected")
                self.assertContains(listado, f'href="{u(nombre, "changelist")}"')  # el modelo sigue navegable
        indice = self.client.get(reverse("admin:index")).content.decode()
        self.assertNotIn(u("metricadiaria", "add"), indice)
        self.assertNotIn(u("interacciondiaria", "add"), indice)
        self.assertIn(u("metricadiaria", "changelist"), indice)

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_la_ficha_se_consulta_en_solo_lectura(self):
        for nombre, obj in (("metricadiaria", self.m_real), ("interacciondiaria", self.i_real)):
            with self.subTest(modelo=nombre):
                ficha = self.client.get(u(nombre, "change", obj.pk))
                self.assertEqual(ficha.status_code, 200)
                html = ficha.content.decode()
                for boton in ("_save", "_continue", "_addanother", "deletelink"):
                    self.assertNotIn(boton, html)
                self.assertNotIn("<input type=\"text\"", html.split("<form")[1] if "<form" in html else html)  # campos como texto
                self.assertTrue(ficha.context["adminform"].form.fields == {} or all(
                    f in ficha.context["adminform"].readonly_fields for f in ficha.context["adminform"].form.fields))

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_bloquea_edicion_y_borrado_por_url_y_no_toca_datos(self):
        for nombre, modelo, obj in (("metricadiaria", MetricaDiaria, self.m_real), ("interacciondiaria", InteraccionDiaria, self.i_real)):
            with self.subTest(modelo=nombre):
                self.assertEqual(self.client.post(u(nombre, "change", obj.pk), {"_save": "x"}).status_code, 403)
                self.assertEqual(self.client.get(u(nombre, "delete", obj.pk)).status_code, 403)
                self.assertEqual(self.client.post(u(nombre, "delete", obj.pk), {"post": "yes"}).status_code, 403)
                self.assertTrue(modelo.objects.filter(pk=obj.pk).exists())

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_sigue_pudiendo_filtrar_y_el_orm_sigue_escribiendo(self):
        r = self.client.get(u("metricadiaria", "changelist"), {"anio": 2026, "mes": 10})
        self.assertEqual(r.context["cl"].result_count, 1)
        # el tracking REAL, las consolidaciones y los comandos usan el ORM: los permisos del Admin no los afectan
        nueva = diaria(self.periodo, date(2026, 10, 13), nuevos=1, origen=REAL)
        nueva.duracion_total_seg += 10
        nueva.save()
        InteraccionDiaria.objects.create(
            periodo=self.periodo, origen=REAL, fecha=date(2026, 10, 13), tipo=TipoInteraccion.CHATBOT_CONSULTA, cantidad=1)
        self.assertEqual(MetricaDiaria.objects.filter(origen=REAL).count(), 2)
