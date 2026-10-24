import math
import random
from copy import deepcopy
from dataclasses import replace
from datetime import date

from django.test import SimpleTestCase, TestCase

from .choices import GranularidadUnicos
from .services import simulacion as sim
from .services.diagnostico import RangosDiagnostico, diagnosticar_dataset
from .services.previsualizacion import lineas_previsualizacion
from .services.resumenes import resumen_mensual
from .services.validacion import COMPLETO, validar_periodo_metricas
from .test_servicios import SIM
from .test_simulacion import CUOTAS, SEMILLA, periodo_tesis

SEMILLAS = [SEMILLA, *range(1, 25)]
R = RangosDiagnostico()
EPS = 1e-9


class CalibracionDiariaTests(SimpleTestCase):
    """Sanity checks de simulación (no son datos empíricos ni constraints de BD)."""

    def test_conteo_de_rebotes_acotado_con_suficientes_sesiones(self):
        rng = random.Random(11)
        p = sim.ParametrosSimulacion()
        for _ in range(3000):
            sesiones = rng.randint(p.sesiones_dia_estable, 80)
            tasa = rng.uniform(p.rebote_min, p.rebote_max)
            rebotes = sim._contar_rebotes(rng, sesiones, tasa, p)
            self.assertGreaterEqual(rebotes / sesiones, R.rebote[0] - EPS)
            self.assertLessEqual(rebotes / sesiones, R.rebote[1] + EPS)

    def test_con_pocas_sesiones_el_ruido_binomial_sigue_existiendo(self):
        rng = random.Random(5)
        p = sim.ParametrosSimulacion()
        tasas = {sim._contar_rebotes(rng, 5, 0.4, p) / 5 for _ in range(400)}
        self.assertIn(0.0, tasas)
        self.assertIn(1.0, tasas)

    def test_navegacion_conserva_invariantes_y_rangos(self):
        rng = random.Random(21)
        p = sim.ParametrosSimulacion()
        for _ in range(1500):
            sesiones = rng.randint(1, 70)
            rebotes, paginas, segundos = sim._navegacion(rng, sesiones, p)
            self.assertLessEqual(rebotes, sesiones)
            self.assertGreaterEqual(paginas, rebotes + 2 * (sesiones - rebotes))
            self.assertGreaterEqual(segundos, 0)
            if sesiones >= p.sesiones_dia_estable:
                self.assertTrue(R.rebote[0] - EPS <= rebotes / sesiones <= R.rebote[1] + EPS)
                self.assertTrue(R.paginas_por_sesion[0] - EPS <= paginas / sesiones <= R.paginas_por_sesion[1] + EPS)
                self.assertTrue(R.duracion_media_seg[0] - 1 <= segundos / sesiones <= R.duracion_media_seg[1] + 1)

    def test_duracion_correlaciona_con_paginas_y_rebote(self):
        rng = random.Random(3)
        p = sim.ParametrosSimulacion()
        dias = [sim._navegacion(rng, 40, p) for _ in range(300)]
        # más páginas por sesión -> más segundos por sesión (correlación positiva)
        xs = [d[1] / 40 for d in dias]
        ys = [d[2] / 40 for d in dias]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        covarianza = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        self.assertGreater(covarianza, 0)
        # más rebote -> menos segundos por sesión (correlación negativa)
        rb = [d[0] / 40 for d in dias]
        mr = sum(rb) / len(rb)
        self.assertLess(sum((x - mr) * (y - my) for x, y in zip(rb, ys)), 0)


class CalibracionDatasetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = periodo_tesis()
        cls.datasets = {s: sim.simular_periodo(cls.periodo, s) for s in SEMILLAS}

    def test_cuotas_y_validez_para_varias_semillas(self):
        for semilla, ds in self.datasets.items():
            with self.subTest(semilla=semilla):
                por_mes = {}
                for f in ds.diarias:
                    por_mes[f.fecha.month] = por_mes.get(f.fecha.month, 0) + f.usuarios_nuevos
                self.assertEqual(por_mes, {6: 42, 7: 76, 8: 110, 9: 132})
                self.assertEqual(sum(por_mes.values()), 360)
                self.assertEqual(sim.validar_dataset(ds), [])
                r = validar_periodo_metricas(self.periodo, SIM, datos=ds.a_datos())
                self.assertEqual((r.estado, r.errores, r.advertencias), (COMPLETO, [], []))

    def test_misma_semilla_misma_huella_y_semillas_distintas_huellas_distintas(self):
        self.assertEqual(sim.simular_periodo(self.periodo, SEMILLA).checksum, self.datasets[SEMILLA].checksum)
        huellas = {ds.checksum for ds in self.datasets.values()}
        self.assertEqual(len(huellas), len(SEMILLAS))

    def test_rebote_duracion_y_paginas_dentro_de_rango_en_dias_estables(self):
        for semilla, ds in self.datasets.items():
            for f in ds.diarias:
                if f.sesiones < R.sesiones_dia_estable:
                    continue
                with self.subTest(semilla=semilla, fecha=f.fecha):
                    self.assertTrue(R.rebote[0] - EPS <= f.sesiones_rebote / f.sesiones <= R.rebote[1] + EPS)
                    media = f.duracion_total_seg / f.sesiones
                    self.assertTrue(R.duracion_media_seg[0] - 1 <= media <= R.duracion_media_seg[1] + 1, media)
                    self.assertTrue(R.paginas_por_sesion[0] - EPS <= f.paginas_vistas / f.sesiones <= R.paginas_por_sesion[1] + EPS)
                    self.assertGreaterEqual(f.paginas_vistas, f.sesiones_rebote + 2 * (f.sesiones - f.sesiones_rebote))

    def test_la_tasa_de_rebote_sigue_variando_entre_dias(self):
        for semilla in (SEMILLA, 3, 9):
            tasas = {round(f.sesiones_rebote / f.sesiones, 3) for f in self.datasets[semilla].diarias if f.sesiones >= 10}
            self.assertGreater(len(tasas), 20, semilla)
            self.assertGreater(len({f.paginas_vistas / f.sesiones for f in self.datasets[semilla].diarias if f.sesiones >= 10}), 20)

    def test_sin_dias_vacios_con_la_base_consolidada_ni_desde_agosto(self):
        for semilla, ds in self.datasets.items():
            with self.subTest(semilla=semilla):
                d = diagnosticar_dataset(ds)
                vacios = [f for f in d.dias_sin_sesiones if f >= date(2026, 8, 1)]
                self.assertEqual(vacios, [])
                self.assertEqual([f for f in d.dias_sin_sesiones if f >= d.inicio_base_consolidada], [])
                self.assertLessEqual(d.inicio_base_consolidada, date(2026, 8, 1))

    def test_los_dias_vacios_iniciales_siguen_siendo_posibles(self):
        con_vacios = [s for s, ds in self.datasets.items() if diagnosticar_dataset(ds).dias_sin_sesiones]
        self.assertGreater(len(con_vacios), len(SEMILLAS) // 2)

    def test_nuevos_y_recurrentes_mensuales_coherentes(self):
        for semilla in (SEMILLA, 4, 17):
            ds = self.datasets[semilla]
            meses = resumen_mensual(self.periodo, SIM, datos=ds.a_datos())
            filas = [u for u in ds.unicos if u.granularidad == GranularidadUnicos.MES]
            self.assertEqual([m.usuarios_recurrentes for m in meses], [u.usuarios_recurrentes for u in filas])
            self.assertEqual([m.usuarios_nuevos for m in meses], [42, 76, 110, 132])
            self.assertEqual(meses[0].usuarios_recurrentes, 0)
            for m in meses:
                self.assertEqual(m.usuarios_unicos, m.usuarios_nuevos + m.usuarios_recurrentes)
                self.assertAlmostEqual(m.porcentaje_nuevos + m.porcentaje_recurrentes, 100)
                previos = sum(n for mes, n in CUOTAS if mes < m.inicio.month)
                self.assertLessEqual(m.usuarios_recurrentes, previos)
            # la proporción de recurrentes crece con el periodo
            porcentajes = [m.porcentaje_recurrentes for m in meses]
            self.assertEqual(porcentajes, sorted(porcentajes))


class DiagnosticoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = periodo_tesis()
        cls.ds = sim.simular_periodo(cls.periodo, SEMILLA)

    def test_no_modifica_el_dataset(self):
        antes = deepcopy(self.ds)
        diagnosticar_dataset(self.ds)
        lineas_previsualizacion(self.ds, con_dias=True)
        self.assertEqual(self.ds.diarias, antes.diarias)
        self.assertEqual(self.ds.unicos, antes.unicos)
        self.assertEqual(sim.calcular_huella(self.ds), self.ds.checksum)

    def test_extremos_coinciden_con_un_recalculo_independiente(self):
        d = diagnosticar_dataset(self.ds)
        estables = [f for f in self.ds.diarias if f.sesiones >= 10]
        self.assertEqual(d.dias_estables, len(estables))
        self.assertAlmostEqual(d.rebote_max.valor, max(f.sesiones_rebote / f.sesiones for f in estables))
        self.assertAlmostEqual(d.duracion_min.valor, min(f.duracion_total_seg / f.sesiones for f in estables))
        self.assertAlmostEqual(d.paginas_max.valor, max(f.paginas_vistas / f.sesiones for f in estables))
        self.assertEqual(d.dias_sin_sesiones, [f.fecha for f in self.ds.diarias if f.sesiones == 0])
        self.assertEqual(d.max_recurrentes.valor, max(f.usuarios_recurrentes for f in self.ds.diarias))
        self.assertEqual(d.mayor_actividad[0][1], max(f.sesiones for f in self.ds.diarias))
        self.assertEqual(d.menor_actividad[0][1], min(f.sesiones for f in self.ds.diarias))
        self.assertEqual([n for _, n in d.mayor_actividad], sorted((n for _, n in d.mayor_actividad), reverse=True))
        sesiones = sum(f.sesiones for f in self.ds.diarias)
        chatbot = sum(f.interacciones["chatbot_consulta"] for f in self.ds.diarias)
        self.assertAlmostEqual(d.chatbot_por_sesion, chatbot / sesiones)
        self.assertAlmostEqual(d.chatbot_por_participante, chatbot / 360)
        self.assertLessEqual(d.max_sesiones_por_unico.valor, 4)  # tope por usuario del perfil por defecto
        self.assertEqual(d.advertencias, [])

    def copia(self):
        return replace(self.ds, diarias=[replace(f, fuentes=dict(f.fuentes), dispositivos=dict(f.dispositivos),
                                                  interacciones=dict(f.interacciones)) for f in self.ds.diarias])

    def test_detecta_extremos_dias_vacios_e_interacciones_huerfanas(self):
        ds = self.copia()
        estable = next(f for f in ds.diarias if f.sesiones >= 10)
        estable.sesiones_rebote = int(estable.sesiones * 0.85)
        estable.duracion_total_seg = estable.sesiones * 420
        agosto = next(f for f in ds.diarias if f.fecha == date(2026, 8, 12))
        agosto.sesiones = agosto.paginas_vistas = agosto.duracion_total_seg = agosto.sesiones_rebote = 0
        agosto.interacciones["ubicacion_click"] = 2
        texto = "\n".join(diagnosticar_dataset(ds).advertencias)
        self.assertIn("Rebote diario 80.0 % el", texto)
        self.assertIn("fuera de [20.0 %, 60.0 %]", texto)
        self.assertIn("Duración media diaria 07:00", texto)
        self.assertIn("sin sesiones con la base ya consolidada", texto)
        self.assertIn("12/08/2026: hay interacciones sin sesiones", texto)

    def test_idioma_frecuente_advierte(self):
        ds = self.copia()
        for f in ds.diarias:
            f.interacciones["idioma_cambiado"] = f.sesiones
        self.assertTrue(any("cambio de idioma es frecuente" in a for a in diagnosticar_dataset(ds).advertencias))

    def test_rangos_configurables(self):
        estricto = RangosDiagnostico(rebote=(0.39, 0.40))
        self.assertTrue(any("Rebote diario" in a for a in diagnosticar_dataset(self.ds, estricto).advertencias))


class PrevisualizacionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = periodo_tesis()
        cls.texto = "\n".join(lineas_previsualizacion(sim.simular_periodo(cls.periodo, SEMILLA)))

    def test_incluye_nuevos_y_recurrentes_con_porcentajes(self):
        for esperado in ("Nuevos", "Recurr.", "Únicos", "% nuevos", "% recur.", "Ses/únic", "Sesiones/usuario de la muestra"):
            self.assertIn(esperado, self.texto)
        junio = next(l for l in self.texto.splitlines() if "Junio 2026" in l)
        self.assertIn("100,00 %", junio)
        self.assertIn("0,00 %", junio)
        self.assertIn("exacta", junio)

    def test_incluye_diagnostico_y_cocientes_de_interacciones(self):
        for esperado in ("DIAGNÓSTICO DE SIMULACIÓN", "Rebote diario", "Duración media diaria", "Días sin sesiones",
                         "Mayor actividad", "Menor actividad", "Interacciones/sesión", "Consultas al chatbot/sesión",
                         "Consultas al chatbot/usuario de la muestra"):
            self.assertIn(esperado, self.texto)
        self.assertEqual(sum(1 for l in self.texto.splitlines() if l.strip().endswith("%") and "detalle" in l), 4)

    def test_no_imprime_los_122_dias_por_defecto(self):
        self.assertNotIn("Detalle diario", self.texto)
        self.assertLess(len(self.texto.splitlines()), 90)
