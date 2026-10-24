"""Admin de Métricas: diferencias LOCAL / PRODUCCIÓN, filtros Año/Mes, sin date_hierarchy ni "Mostrar recuentos"."""
from datetime import date, datetime, timezone

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .admin import (
    EventoMetricaAdmin, InteraccionDiariaAdmin, MetricaDiariaAdmin, SesionMetricaAdmin, UnicosPeriodoAdmin,
    VisitanteMetricaAdmin,
)
from .choices import DispositivoAcceso, FuenteTrafico, GranularidadUnicos, OrigenDato, TipoInteraccion
from .models import EventoMetrica, InteraccionDiaria, MetricaDiaria, SesionMetrica, UnicosPeriodo, VisitanteMetrica
from .test_servicios import diaria, periodo_corto

SIM, REAL, GA4 = OrigenDato.SIMULADO, OrigenDato.REAL, OrigenDato.GA4
ADMINS = (
    MetricaDiariaAdmin, InteraccionDiariaAdmin, UnicosPeriodoAdmin, VisitanteMetricaAdmin, SesionMetricaAdmin,
    EventoMetricaAdmin,
)


def url(modelo):
    return reverse(f"admin:metricas_{modelo}_changelist")


class BaseAdminEntorno(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("met-env", "m@example.com", "x-pass-123")
        cls.periodo = periodo_corto()
        for origen, fecha in (
            (SIM, date(2026, 6, 10)), (REAL, date(2026, 10, 12)), (REAL, date(2025, 10, 5)), (GA4, date(2026, 6, 20)),
        ):
            diaria(cls.periodo, fecha, nuevos=2, origen=origen)
            InteraccionDiaria.objects.create(
                periodo=cls.periodo, origen=origen, fecha=fecha, tipo=TipoInteraccion.CHATBOT_CONSULTA, cantidad=3)
        UnicosPeriodo.objects.create(
            periodo=cls.periodo, origen=SIM, granularidad=GranularidadUnicos.SEMANA, inicio=date(2026, 6, 1),
            fin=date(2026, 6, 7), usuarios_recurrentes=0)
        UnicosPeriodo.objects.create(
            periodo=cls.periodo, origen=REAL, granularidad=GranularidadUnicos.MES, inicio=date(2026, 6, 1),
            fin=date(2026, 6, 30), usuarios_recurrentes=0)
        cls.visitante = VisitanteMetrica.objects.create(origen=REAL, primera_visita=date(2026, 10, 12))
        VisitanteMetrica.objects.create(origen=REAL, primera_visita=date(2025, 3, 1))
        sesion = SesionMetrica.objects.create(
            visitante=cls.visitante, origen=REAL, fecha=date(2026, 10, 12),
            inicio=datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc), paginas_vistas=2,
            fuente=FuenteTrafico.DIRECTO, dispositivo=DispositivoAcceso.MOVIL, idioma="es")
        EventoMetrica.objects.create(
            visitante=cls.visitante, sesion=sesion, origen=REAL, tipo=TipoInteraccion.UBICACION_CLICK,
            fecha=date(2026, 10, 12), entidad_tipo="lugar", entidad_id=3)

    def setUp(self):
        self.client.force_login(self.usuario)

    def filas(self, modelo, **params):
        r = self.client.get(url(modelo), params)
        self.assertEqual(r.status_code, 200)
        return r.context["cl"].result_count

    def cabeceras_y_filtros(self, modelo):
        cl = self.client.get(url(modelo)).context["cl"]
        return list(cl.list_display), [f if isinstance(f, str) else f.parameter_name for f in cl.list_filter]


class LocalVsProduccionTests(BaseAdminEntorno):
    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=True)
    def test_local_conserva_columnas_filtros_y_todos_los_origenes(self):
        columnas, filtros = self.cabeceras_y_filtros("metricadiaria")
        for esperado in ("periodo", "origen", "editado_manual"):
            self.assertIn(esperado, columnas)
        self.assertTrue({"periodo", "origen", "editado_manual", "anio", "mes"} <= set(filtros))
        self.assertEqual(self.filas("metricadiaria"), 4)  # SIMULADO + REAL + GA4
        _, filtros_i = self.cabeceras_y_filtros("interacciondiaria")
        self.assertTrue({"periodo", "origen", "tipo", "anio", "mes"} <= set(filtros_i))
        columnas_u, filtros_u = self.cabeceras_y_filtros("unicosperiodo")
        self.assertIn("agrupar_por", columnas_u)
        self.assertTrue({"periodo", "origen", "agrupar_por"} <= set(filtros_u))
        self.assertEqual(self.filas("unicosperiodo"), 2)

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_oculta_periodo_origen_y_editado_manual(self):
        columnas, filtros = self.cabeceras_y_filtros("metricadiaria")
        for oculto in ("periodo", "origen", "editado_manual"):
            self.assertNotIn(oculto, columnas)
            self.assertNotIn(oculto, filtros)
        self.assertEqual(set(filtros), {"anio", "mes"})
        columnas_i, filtros_i = self.cabeceras_y_filtros("interacciondiaria")
        self.assertEqual(columnas_i, ["fecha", "tipo", "cantidad"])
        self.assertEqual(set(filtros_i), {"tipo", "anio", "mes"})
        columnas_u, filtros_u = self.cabeceras_y_filtros("unicosperiodo")
        for oculto in ("periodo", "origen"):
            self.assertNotIn(oculto, columnas_u + filtros_u)

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_excluye_simulado_pero_conserva_real_y_ga4(self):
        self.assertEqual(self.filas("metricadiaria"), 3)  # sin la SIMULADO; REAL y GA4 permanecen
        self.assertEqual(self.filas("interacciondiaria"), 3)
        self.assertEqual(self.filas("unicosperiodo"), 1)
        self.assertEqual(self.filas("visitantemetrica"), 2)
        r = self.client.get(url("metricadiaria"))
        self.assertEqual({m.origen for m in r.context["cl"].result_list}, {REAL, GA4})

    @override_settings(METRICAS_ADMIN_PRUEBAS_VISIBLE=False)
    def test_produccion_no_borra_datos_ni_deja_abrir_filas_simuladas(self):
        simulada = MetricaDiaria.objects.get(origen=SIM)
        respuesta = self.client.get(reverse("admin:metricas_metricadiaria_change", args=[simulada.pk]))
        self.assertEqual(respuesta.status_code, 302)  # el Admin responde "no existe" (redirige al listado)
        self.assertTrue(MetricaDiaria.objects.filter(pk=simulada.pk).exists())


class SinDateHierarchyNiRecuentosTests(BaseAdminEntorno):
    def test_ningun_admin_de_metricas_usa_date_hierarchy_ni_recuentos(self):
        for clase in ADMINS:
            with self.subTest(admin=clase.__name__):
                self.assertIsNone(clase.date_hierarchy)
                self.assertEqual(clase.show_facets, admin.ShowFacets.NEVER)

    def test_paginas_sin_barra_de_fechas_ni_mostrar_recuentos(self):
        for modelo in (
            "metricadiaria", "interacciondiaria", "unicosperiodo", "visitantemetrica", "sesionmetrica", "eventometrica",
        ):
            with self.subTest(modelo=modelo):
                html = self.client.get(url(modelo)).content.decode()
                self.assertNotIn("dateline", html)
                self.assertNotIn("Mostrar recuentos", html)

    def test_titulos_simplificados(self):
        for modelo, titulo in (
            ("interacciondiaria", "Interacciones diarias"), ("eventometrica", "Eventos de interacción"),
            ("sesionmetrica", "Sesiones"), ("visitantemetrica", "Visitantes"),
        ):
            self.assertContains(self.client.get(url(modelo)), f"<h1>{titulo}</h1>", html=True)

    def test_agrupar_por_reemplaza_a_granularidad(self):
        html = self.client.get(url("unicosperiodo")).content.decode()
        self.assertIn("Agrupar por", html)
        self.assertNotIn("Granularidad", html)


class FiltrosAnioMesTests(BaseAdminEntorno):
    def test_combinaciones_en_metricas_diarias(self):
        # filas: 2026-06 (SIM), 2026-10 (REAL), 2025-10 (REAL), 2026-06 (GA4)
        self.assertEqual(self.filas("metricadiaria"), 4)
        self.assertEqual(self.filas("metricadiaria", anio=2026), 3)
        self.assertEqual(self.filas("metricadiaria", mes=10), 2)
        self.assertEqual(self.filas("metricadiaria", anio=2026, mes=10), 1)
        self.assertEqual(self.filas("metricadiaria", anio=2026, mes=10, origen__exact=REAL), 1)
        self.assertEqual(self.filas("metricadiaria", anio=2025, mes=6), 0)

    def test_anios_dinamicos_mas_reciente_primero_y_meses_traducibles(self):
        filtros = {
            f.parameter_name: f for f in self.client.get(url("metricadiaria")).context["cl"].filter_specs
            if hasattr(f, "parameter_name")
        }
        self.assertEqual([v for v, _ in filtros["anio"].lookup_choices], ["2026", "2025"])
        meses = [n for _, n in filtros["mes"].lookup_choices]
        self.assertEqual(len(meses), 12)
        self.assertEqual(meses[0], "Enero")
        self.assertEqual(meses[9], "Octubre")

    def test_parametros_invalidos_se_ignoran(self):
        self.assertEqual(self.filas("metricadiaria", anio="abc", mes="99"), 4)

    def test_cada_admin_filtra_por_su_campo_de_fecha_real(self):
        self.assertEqual(self.filas("interacciondiaria", anio=2026, mes=10), 1)
        self.assertEqual(self.filas("eventometrica", anio=2026, mes=10), 1)
        self.assertEqual(self.filas("eventometrica", anio=2025), 0)
        self.assertEqual(self.filas("sesionmetrica", mes=10), 1)
        self.assertEqual(self.filas("visitantemetrica", anio=2026), 1)  # primera_visita
        self.assertEqual(self.filas("visitantemetrica", anio=2025, mes=3), 1)
        self.assertEqual(self.filas("visitantemetrica", mes=10), 1)

    def test_las_opciones_conservan_otros_filtros_y_orden(self):
        r = self.client.get(
            url("interacciondiaria"), {"tipo__exact": TipoInteraccion.CHATBOT_CONSULTA, "o": "1", "anio": "2026"},
        )
        opcion_mes = [linea for linea in r.content.decode().splitlines() if "<option" in linea and "mes=10" in linea]
        self.assertTrue(opcion_mes)
        for fragmento in ("tipo__exact=chatbot_consulta", "o=1", "anio=2026"):
            self.assertIn(fragmento, opcion_mes[0])
