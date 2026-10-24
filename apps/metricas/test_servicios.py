from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from .choices import (
    AlcancePeriodo,
    DispositivoAcceso,
    FuenteTrafico,
    GranularidadUnicos,
    OrigenDato,
    TipoInteraccion,
)
from .models import (
    InteraccionDiaria,
    MetaMuestraMensual,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    PeriodoEvaluacion,
    UnicosPeriodo,
)
from .services import validacion
from .services.datos import cargar_datos
from .services.intervalos import Intervalo, intervalos_mensuales, intervalos_semanales
from .services.resumenes import resumen_mensual, resumen_semanal, resumen_total
from .services.unicos import asegurar_intervalos_unicos, evaluar_cotas_unicos, evaluar_fila_unicos
from .tests import crear_periodo

SIM, REAL = OrigenDato.SIMULADO, OrigenDato.REAL
D = date


def diaria(periodo, fecha, nuevos=0, recurrentes=0, origen=SIM, sesiones=None, rebote=0, paginas=None, duracion=0,
           desglose=True):
    """Fila diaria coherente (sesiones >= únicos, páginas suficientes) con desglose que suma las sesiones."""
    sesiones = nuevos + recurrentes + 1 if sesiones is None else sesiones
    paginas = 2 * sesiones - rebote if paginas is None else paginas
    m = MetricaDiaria.objects.create(
        periodo=periodo, origen=origen, fecha=fecha, sesiones=sesiones, paginas_vistas=paginas,
        duracion_total_seg=duracion, sesiones_rebote=rebote, usuarios_nuevos=nuevos, usuarios_recurrentes=recurrentes,
    )
    if desglose:
        MetricaDiariaFuente.objects.create(metrica_diaria=m, fuente=FuenteTrafico.DIRECTO, sesiones=sesiones)
        MetricaDiariaDispositivo.objects.create(metrica_diaria=m, dispositivo=DispositivoAcceso.MOVIL, sesiones=sesiones)
    return m


def unicos(periodo, granularidad, inicio, fin, recurrentes=0, origen=SIM):
    return UnicosPeriodo.objects.create(
        periodo=periodo, origen=origen, granularidad=granularidad, inicio=inicio, fin=fin, usuarios_recurrentes=recurrentes,
    )


def periodo_corto(**extra):
    """01/06/2026 (lunes) a 14/06/2026: dos semanas completas dentro de junio."""
    datos = dict(nombre="Corto", fecha_inicio=D(2026, 6, 1), fecha_fin=D(2026, 6, 14), tamano_muestra=None,
                 alcance=AlcancePeriodo.TODOS_VISITANTES)
    datos.update(extra)
    return crear_periodo(**datos)


class FormatosTests(SimpleTestCase):
    def test_redondea_en_lugar_de_truncar(self):
        from . import formatos
        self.assertEqual(formatos.pct(8 / 42 * 100), "19,05 %")  # 19,0476…
        self.assertEqual(formatos.pct(2 / 3 * 100), "66,67 %")
        self.assertEqual(formatos.num(3.1), "3,10")
        self.assertEqual(formatos.pct(None), "—")
        self.assertEqual(formatos.pct(0), "0,00 %")  # un 0 real no es "sin dato"


class IntervalosTests(SimpleTestCase):
    def test_periodo_de_tesis_tiene_18_semanas_y_4_meses(self):
        semanas = intervalos_semanales(D(2026, 6, 1), D(2026, 9, 30))
        self.assertEqual(len(semanas), 18)
        self.assertEqual(semanas[0], Intervalo(D(2026, 6, 1), D(2026, 6, 7)))
        self.assertEqual(semanas[-1], Intervalo(D(2026, 9, 28), D(2026, 9, 30)))
        self.assertTrue(all(s.inicio.weekday() == 0 for s in semanas))
        self.assertTrue(all(s.dias == 7 for s in semanas[:-1]))
        self.assertEqual(semanas[-1].dias, 3)
        meses = intervalos_mensuales(D(2026, 6, 1), D(2026, 9, 30))
        self.assertEqual(
            meses,
            [Intervalo(D(2026, 6, 1), D(2026, 6, 30)), Intervalo(D(2026, 7, 1), D(2026, 7, 31)),
             Intervalo(D(2026, 8, 1), D(2026, 8, 31)), Intervalo(D(2026, 9, 1), D(2026, 9, 30))],
        )

    def test_semanas_cubren_el_rango_sin_huecos_ni_solapes(self):
        semanas = intervalos_semanales(D(2026, 6, 1), D(2026, 9, 30))
        for anterior, siguiente in zip(semanas, semanas[1:]):
            self.assertEqual(anterior.fin + timedelta(days=1), siguiente.inicio)
        self.assertEqual(sum(s.dias for s in semanas), 122)

    def test_semana_parcial_al_inicio(self):
        semanas = intervalos_semanales(D(2026, 6, 3), D(2026, 6, 16))  # miércoles a martes
        self.assertEqual(semanas[0], Intervalo(D(2026, 6, 3), D(2026, 6, 7)))
        self.assertEqual(semanas[1], Intervalo(D(2026, 6, 8), D(2026, 6, 14)))
        self.assertEqual(semanas[2], Intervalo(D(2026, 6, 15), D(2026, 6, 16)))

    def test_un_solo_dia_y_rango_invertido(self):
        self.assertEqual(intervalos_semanales(D(2026, 6, 3), D(2026, 6, 3)), [Intervalo(D(2026, 6, 3), D(2026, 6, 3))])
        self.assertEqual(intervalos_mensuales(D(2026, 6, 3), D(2026, 6, 3)), [Intervalo(D(2026, 6, 3), D(2026, 6, 3))])
        self.assertEqual(intervalos_semanales(D(2026, 6, 3), D(2026, 6, 2)), [])
        self.assertEqual(intervalos_mensuales(D(2026, 6, 3), D(2026, 6, 2)), [])

    def test_meses_parciales(self):
        self.assertEqual(
            intervalos_mensuales(D(2026, 6, 15), D(2026, 7, 10)),
            [Intervalo(D(2026, 6, 15), D(2026, 6, 30)), Intervalo(D(2026, 7, 1), D(2026, 7, 10))],
        )

    def test_meses_cruzando_de_anio_y_bisiesto(self):
        meses = intervalos_mensuales(D(2026, 11, 20), D(2027, 2, 5))
        self.assertEqual([(m.inicio.year, m.inicio.month) for m in meses], [(2026, 11), (2026, 12), (2027, 1), (2027, 2)])
        self.assertEqual(meses[-1], Intervalo(D(2027, 2, 1), D(2027, 2, 5)))
        self.assertEqual(intervalos_mensuales(D(2028, 2, 1), D(2028, 2, 29))[0].fin, D(2028, 2, 29))


class EstructuraUnicosTests(TestCase):
    def test_crea_semanas_y_meses_con_recurrentes_cero(self):
        p = crear_periodo()
        r = asegurar_intervalos_unicos(p)
        self.assertEqual((r.creados, r.existentes), (22, 0))
        filas = UnicosPeriodo.objects.filter(periodo=p)
        self.assertEqual(filas.filter(granularidad=GranularidadUnicos.SEMANA).count(), 18)
        self.assertEqual(filas.filter(granularidad=GranularidadUnicos.MES).count(), 4)
        self.assertEqual(set(filas.values_list("origen", flat=True)), {SIM})
        self.assertEqual(set(filas.values_list("usuarios_recurrentes", flat=True)), {0})
        ultima = filas.get(granularidad=GranularidadUnicos.SEMANA, inicio=D(2026, 9, 28))
        self.assertEqual(ultima.fin, D(2026, 9, 30))

    def test_es_idempotente_y_no_pisa_valores(self):
        p = crear_periodo()
        asegurar_intervalos_unicos(p)
        fila = UnicosPeriodo.objects.get(periodo=p, granularidad=GranularidadUnicos.SEMANA, inicio=D(2026, 6, 8))
        fila.usuarios_recurrentes = 7
        fila.save()
        r = asegurar_intervalos_unicos(p)
        self.assertEqual((r.creados, r.existentes), (0, 22))
        self.assertEqual(UnicosPeriodo.objects.filter(periodo=p).count(), 22)
        fila.refresh_from_db()
        self.assertEqual(fila.usuarios_recurrentes, 7)

    def test_completa_solo_lo_que_falta(self):
        p = crear_periodo()
        unicos(p, GranularidadUnicos.MES, D(2026, 6, 1), D(2026, 6, 30), recurrentes=4)
        r = asegurar_intervalos_unicos(p)
        self.assertEqual((r.creados, r.existentes), (21, 1))
        self.assertEqual(UnicosPeriodo.objects.get(periodo=p, granularidad="MES", inicio=D(2026, 6, 1)).usuarios_recurrentes, 4)

    def test_fila_con_fin_distinto_se_informa_y_no_se_toca(self):
        p = crear_periodo()
        mala = unicos(p, GranularidadUnicos.SEMANA, D(2026, 6, 1), D(2026, 6, 5), recurrentes=2)
        r = asegurar_intervalos_unicos(p)
        self.assertEqual(r.inconsistentes, [mala])
        mala.refresh_from_db()
        self.assertEqual((mala.fin, mala.usuarios_recurrentes), (D(2026, 6, 5), 2))

    def test_solo_simulado_y_no_toca_otros_origenes(self):
        p = crear_periodo()
        with self.assertRaises(ValueError):
            asegurar_intervalos_unicos(p, REAL)
        unicos(p, GranularidadUnicos.MES, D(2026, 6, 1), D(2026, 6, 30), origen=REAL, recurrentes=9)
        r = asegurar_intervalos_unicos(p)
        self.assertEqual(r.creados, 22)  # la fila REAL no cuenta como existente SIMULADA
        self.assertEqual(UnicosPeriodo.objects.filter(origen=REAL).count(), 1)

    def test_comando(self):
        p = periodo_corto()
        salida = StringIO()
        call_command("asegurar_unicos_periodo", periodo=p.pk, stdout=salida)
        self.assertIn("3 creados, 0 ya existían", salida.getvalue())  # 2 semanas + 1 mes
        salida = StringIO()
        call_command("asegurar_unicos_periodo", periodo=p.pk, stdout=salida)
        self.assertIn("0 creados, 3 ya existían", salida.getvalue())


class CotasUnicosTests(TestCase):
    """Periodo 01–14/06: semana 1 (1–7) y semana 2 (8–14), todos los días cargados."""

    @classmethod
    def setUpTestData(cls):
        cls.p = periodo_corto()
        for dia in range(1, 8):  # semana 1: 3 nuevos por día; recurrentes 1 desde el día 2
            diaria(cls.p, D(2026, 6, dia), nuevos=3, recurrentes=0 if dia == 1 else 1)
        for dia in range(8, 15):  # semana 2: 1 nuevo y 2 recurrentes por día
            diaria(cls.p, D(2026, 6, dia), nuevos=1, recurrentes=2)

    def cotas(self, inicio, fin, recurrentes):
        return evaluar_cotas_unicos(cargar_datos(self.p, SIM), "Semana", inicio, fin, recurrentes)

    def test_valores_dentro_de_cotas(self):
        # semana 2: nuevos 7, recurrentes diarios Σ14, previos 21, únicos diarios 3 (máx) y Σ21
        for r in (0, 1, 14):
            errores, avisos = self.cotas(D(2026, 6, 8), D(2026, 6, 14), r)
            self.assertEqual((errores, avisos), ([], []), f"recurrentes={r}")
        self.assertEqual(self.cotas(D(2026, 6, 1), D(2026, 6, 7), 0), ([], []))

    def test_excede_recurrentes_diarios_y_suma_de_unicos(self):
        errores, _ = self.cotas(D(2026, 6, 8), D(2026, 6, 14), 15)
        self.assertEqual(len(errores), 2)
        self.assertTrue(any("suma de recurrentes diarios del intervalo (14)" in e for e in errores))
        self.assertTrue(any("suma de únicos diarios (21)" in e for e in errores))

    def test_primera_semana_no_admite_recurrentes(self):
        errores, _ = self.cotas(D(2026, 6, 1), D(2026, 6, 7), 1)
        self.assertEqual(len(errores), 1)
        self.assertIn("usuarios nuevos anteriores al intervalo (0)", errores[0])

    def test_recurrentes_no_pueden_superar_nuevos_anteriores(self):
        p = periodo_corto(nombre="Previos")
        diaria(p, D(2026, 6, 1), nuevos=1)
        for dia in range(2, 8):
            diaria(p, D(2026, 6, dia))
        for dia in range(8, 15):
            diaria(p, D(2026, 6, dia), recurrentes=1)
        errores, _ = evaluar_cotas_unicos(cargar_datos(p, SIM), "S2", D(2026, 6, 8), D(2026, 6, 14), 5)
        self.assertEqual(len(errores), 1)
        self.assertIn("anteriores al intervalo (1)", errores[0])

    def test_unicos_menores_que_el_maximo_diario(self):
        p = periodo_corto(nombre="Maximo")
        diaria(p, D(2026, 6, 1), nuevos=10)
        for dia in range(2, 8):
            diaria(p, D(2026, 6, dia))
        for dia in range(8, 15):
            diaria(p, D(2026, 6, dia), recurrentes=4 if dia == 8 else 0)
        errores, _ = evaluar_cotas_unicos(cargar_datos(p, SIM), "S2", D(2026, 6, 8), D(2026, 6, 14), 2)
        self.assertEqual(len(errores), 1)
        self.assertIn("máximo de únicos de un día (4)", errores[0])
        self.assertEqual(evaluar_cotas_unicos(cargar_datos(p, SIM), "S2", D(2026, 6, 8), D(2026, 6, 14), 4), ([], []))

    def test_sin_metricas_en_el_intervalo_solo_advierte(self):
        p = periodo_corto(nombre="Vacio")
        errores, avisos = evaluar_cotas_unicos(cargar_datos(p, SIM), "S1", D(2026, 6, 1), D(2026, 6, 7), 50)
        self.assertEqual(errores, [])
        self.assertIn("sin métricas diarias", avisos[0])

    def test_cobertura_incompleta_no_inventa_errores(self):
        p = periodo_corto(nombre="Parcial")
        diaria(p, D(2026, 6, 8), nuevos=1)
        diaria(p, D(2026, 6, 9), nuevos=0, recurrentes=3)  # semana 2 con 2 de 7 días y sin datos de la semana 1
        datos = cargar_datos(p, SIM)
        errores, avisos = evaluar_cotas_unicos(datos, "S2", D(2026, 6, 8), D(2026, 6, 14), 5)
        # Las cotas basadas en sumas no son concluyentes sin todos los días: advertencias, no errores.
        self.assertEqual(errores, [])
        self.assertEqual(len(avisos), 3)
        self.assertTrue(all("no concluyente" in a for a in avisos))
        # El máximo diario sí es concluyente aunque falten días.
        errores, _ = evaluar_cotas_unicos(datos, "S2", D(2026, 6, 8), D(2026, 6, 14), 0)
        self.assertEqual(len(errores), 1)
        self.assertIn("máximo de únicos de un día (3)", errores[0])

    def test_evaluar_fila_con_valor_aun_no_guardado(self):
        fila = unicos(self.p, GranularidadUnicos.SEMANA, D(2026, 6, 8), D(2026, 6, 14), recurrentes=0)
        self.assertEqual(evaluar_fila_unicos(fila), ([], []))
        errores, _ = evaluar_fila_unicos(fila, recurrentes=15)
        self.assertTrue(errores)
        fila.refresh_from_db()
        self.assertEqual(fila.usuarios_recurrentes, 0)


class AgregacionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.p = periodo_corto(nombre="Agregacion")

    def test_ratios_desde_bases_agregadas_no_promedios(self):
        diaria(self.p, D(2026, 6, 1), nuevos=1, sesiones=10, rebote=5, paginas=40, duracion=100)  # rebote 50 %
        diaria(self.p, D(2026, 6, 2), nuevos=1, sesiones=90, rebote=0, paginas=270, duracion=1800)  # rebote 0 %
        semana = resumen_semanal(self.p, SIM)[0]
        self.assertEqual(semana.sesiones, 100)
        self.assertEqual(semana.tasa_rebote, 5)  # no (50 + 0) / 2 = 25
        self.assertEqual(semana.paginas_por_sesion, 3.1)  # 310 / 100, no el promedio de 4 y 3
        self.assertEqual(semana.duracion_media, 19)  # 1900 / 100, no el promedio de 10 y 20

    def test_unicos_no_se_suman_se_calculan_desde_nuevos_y_recurrentes_guardados(self):
        diaria(self.p, D(2026, 6, 1), nuevos=5)
        diaria(self.p, D(2026, 6, 2), nuevos=0, recurrentes=5)
        diaria(self.p, D(2026, 6, 3), nuevos=0, recurrentes=5)
        unicos(self.p, GranularidadUnicos.SEMANA, D(2026, 6, 1), D(2026, 6, 7), recurrentes=0)
        semana = resumen_semanal(self.p, SIM)[0]
        # Σ únicos diarios = 5 + 5 + 5 = 15, pero los únicos de la semana son 5 + 0
        self.assertEqual((semana.usuarios_nuevos, semana.usuarios_recurrentes, semana.usuarios_unicos), (5, 0, 5))
        self.assertEqual((semana.porcentaje_nuevos, semana.porcentaje_recurrentes), (100, 0))

    def test_porcentajes_nuevos_y_recurrentes_suman_100(self):
        diaria(self.p, D(2026, 6, 1), nuevos=6)
        diaria(self.p, D(2026, 6, 9), nuevos=2, recurrentes=3)
        unicos(self.p, GranularidadUnicos.SEMANA, D(2026, 6, 8), D(2026, 6, 14), recurrentes=3)
        s2 = resumen_semanal(self.p, SIM)[1]
        self.assertEqual((s2.usuarios_nuevos, s2.usuarios_unicos), (2, 5))
        self.assertAlmostEqual(s2.porcentaje_nuevos + s2.porcentaje_recurrentes, 100)

    def test_sin_fila_de_unicos_no_hay_dato(self):
        diaria(self.p, D(2026, 6, 1), nuevos=4)
        semana = resumen_semanal(self.p, SIM)[0]
        self.assertEqual(semana.usuarios_nuevos, 4)
        self.assertIsNone(semana.usuarios_recurrentes)
        self.assertIsNone(semana.usuarios_unicos)
        self.assertIsNone(semana.porcentaje_nuevos)

    def test_sin_sesiones_los_ratios_son_none(self):
        semana = resumen_semanal(self.p, SIM)[0]
        for atributo in ("paginas_por_sesion", "duracion_media", "tasa_rebote"):
            self.assertIsNone(getattr(semana, atributo), atributo)
        self.assertEqual(semana.dias_con_datos, 0)

    def test_fuentes_dispositivos_e_interacciones_se_suman(self):
        for dia, directo, social in ((1, 4, 1), (2, 2, 3)):
            m = diaria(self.p, D(2026, 6, dia), nuevos=0, sesiones=directo + social, desglose=False)
            MetricaDiariaFuente.objects.create(metrica_diaria=m, fuente=FuenteTrafico.DIRECTO, sesiones=directo)
            MetricaDiariaFuente.objects.create(metrica_diaria=m, fuente=FuenteTrafico.SOCIAL, sesiones=social)
            MetricaDiariaDispositivo.objects.create(metrica_diaria=m, dispositivo=DispositivoAcceso.TABLET, sesiones=directo + social)
        for dia, tipo, n in ((1, TipoInteraccion.CHATBOT_CONSULTA, 3), (2, TipoInteraccion.CHATBOT_CONSULTA, 4),
                             (2, TipoInteraccion.UBICACION_CLICK, 2), (9, TipoInteraccion.IDIOMA_CAMBIADO, 5)):
            InteraccionDiaria.objects.create(periodo=self.p, origen=SIM, fecha=D(2026, 6, dia), tipo=tipo, cantidad=n)
        s1, s2 = resumen_semanal(self.p, SIM)[:2]
        self.assertEqual((s1.fuentes["DIRECTO"], s1.fuentes["SOCIAL"], s1.fuentes["OTROS"]), (6, 4, 0))
        self.assertEqual(sum(s1.fuentes.values()), s1.sesiones)
        self.assertEqual(s1.dispositivos["TABLET"], s1.sesiones)
        self.assertEqual(s1.interacciones["chatbot_consulta"], 7)
        self.assertEqual(s1.interacciones["ubicacion_click"], 2)
        self.assertEqual(s2.interacciones["idioma_cambiado"], 5)
        self.assertEqual(len(s1.interacciones), 9)  # los 9 tipos, aunque sean 0
        self.assertEqual(resumen_total(self.p, SIM).total_interacciones, 14)

    def test_interaccion_sin_fila_diaria_tambien_cuenta(self):
        InteraccionDiaria.objects.create(
            periodo=self.p, origen=SIM, fecha=D(2026, 6, 3), tipo=TipoInteraccion.FAVORITO_AGREGADO, cantidad=2,
        )
        self.assertEqual(resumen_semanal(self.p, SIM)[0].interacciones["favorito_agregado"], 2)

    def test_origenes_no_se_mezclan(self):
        diaria(self.p, D(2026, 6, 1), nuevos=2)
        diaria(self.p, D(2026, 6, 1), nuevos=50, origen=REAL, desglose=False)
        InteraccionDiaria.objects.create(
            periodo=self.p, origen=REAL, fecha=D(2026, 6, 1), tipo=TipoInteraccion.CHATBOT_CONSULTA, cantidad=99,
        )
        sim = resumen_total(self.p, SIM)
        self.assertEqual((sim.usuarios_nuevos, sim.total_interacciones), (2, 0))
        self.assertEqual(resumen_total(self.p, REAL).usuarios_nuevos, 50)

    def test_resumen_mensual_con_meta_y_avance(self):
        p = crear_periodo(nombre="Tesis")
        for mes, n in ((6, 42), (7, 76), (8, 110), (9, 132)):
            MetaMuestraMensual.objects.create(periodo=p, anio=2026, mes=mes, nuevos_objetivo=n)
        diaria(p, D(2026, 6, 1), nuevos=6)
        diaria(p, D(2026, 6, 2), nuevos=15)
        meses = resumen_mensual(p, SIM)
        self.assertEqual(len(meses), 4)
        junio = meses[0]
        self.assertEqual((junio.usuarios_nuevos, junio.meta_objetivo), (21, 42))
        self.assertEqual(junio.avance_meta, 50)
        self.assertEqual(meses[3].meta_objetivo, 132)
        self.assertEqual(len(resumen_semanal(p, SIM)), 18)

    def test_total_de_muestra_registrada(self):
        p = crear_periodo(nombre="Total")
        diaria(p, D(2026, 6, 1), nuevos=6)
        diaria(p, D(2026, 6, 2), nuevos=2, recurrentes=3)
        total = resumen_total(p, SIM)
        self.assertEqual((total.usuarios_nuevos, total.usuarios_unicos, total.avance_muestra), (8, 8, 8 / 360 * 100))
        self.assertIsNone(total.porcentaje_nuevos)  # sin % nuevo/recurrente del periodo completo
        self.assertIsNone(total.porcentaje_recurrentes)
        self.assertEqual(total.dias_con_datos, 2)

    def test_total_de_todos_los_visitantes_no_deduce_unicos(self):
        diaria(self.p, D(2026, 6, 1), nuevos=3)
        total = resumen_total(self.p, SIM)
        self.assertIsNone(total.usuarios_unicos)  # no aditivo y sin fila TOTAL: no se inventa
        self.assertIsNone(total.avance_muestra)

    def test_numero_de_consultas_constante(self):
        for dia in range(1, 15):
            diaria(self.p, D(2026, 6, dia), nuevos=1)
        with self.assertNumQueries(6):
            resumen_semanal(self.p, SIM)
        with self.assertNumQueries(6):
            resumen_mensual(self.p, SIM)
        with self.assertNumQueries(6):
            validacion.validar_periodo_metricas(self.p, SIM)
        datos = cargar_datos(self.p, SIM)
        with self.assertNumQueries(0):
            resumen_semanal(self.p, SIM, datos=datos)
            resumen_total(self.p, SIM, datos=datos)
            validacion.validar_periodo_metricas(self.p, SIM, datos=datos)


class ValidacionGlobalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.p = crear_periodo(nombre="Tesis")

    def metas(self, p=None, valores=((6, 42), (7, 76), (8, 110), (9, 132))):
        for mes, n in valores:
            MetaMuestraMensual.objects.create(periodo=p or self.p, anio=2026, mes=mes, nuevos_objetivo=n)

    def validar(self, p=None, origen=SIM):
        return validacion.validar_periodo_metricas(p or self.p, origen)

    def test_sin_datos(self):
        r = self.validar()
        self.assertEqual(r.estado, validacion.SIN_DATOS)
        self.assertTrue(r.valido)
        self.assertEqual(r.resumen["dias_faltantes"], 122)

    def test_periodo_parcial_esta_en_progreso(self):
        self.metas()
        diaria(self.p, D(2026, 6, 1), nuevos=6)
        diaria(self.p, D(2026, 6, 2), nuevos=2, recurrentes=3)
        r = self.validar()
        self.assertEqual(r.estado, validacion.EN_PROGRESO)
        self.assertEqual(r.mensaje_estado, "El periodo está en progreso.")
        self.assertTrue(r.valido)
        self.assertIn("Faltan métricas diarias para 120 días (03/06–30/09).", r.advertencias)
        self.assertIn("Junio: 8 / 42 usuarios nuevos.", r.advertencias)
        self.assertIn("Julio: 0 / 76 usuarios nuevos.", r.advertencias)
        self.assertIn("Muestra: 8 / 360 usuarios nuevos.", r.advertencias)
        self.assertIn("Los intervalos de únicos todavía están incompletos: faltan 22 de 22.", r.advertencias)
        self.assertIn("Metas completas: 360 / 360.", r.correctos)
        self.assertEqual(r.resumen["usuarios_nuevos"], 8)

    def test_metas_incompletas_y_excedidas(self):
        self.metas(valores=((6, 42), (7, 76), (8, 110)))
        self.assertIn("Metas incompletas: 228 / 360.", self.validar().advertencias)
        MetaMuestraMensual.objects.create(periodo=self.p, anio=2026, mes=9, nuevos_objetivo=133)
        r = self.validar()
        self.assertEqual(r.estado, validacion.CON_ERRORES)
        self.assertIn("Las metas mensuales suman 361, más que el tamaño de la muestra (360).", r.errores)

    def test_sin_metas(self):
        self.assertIn("No hay metas mensuales definidas.", self.validar().advertencias)

    def test_meta_mensual_excedida_es_error(self):
        self.metas()
        diaria(self.p, D(2026, 6, 1), nuevos=43, sesiones=50)
        r = self.validar()
        self.assertEqual(r.estado, validacion.CON_ERRORES)
        self.assertFalse(r.valido)
        self.assertIn("Junio: 43 / 42 usuarios nuevos exceden la meta mensual.", r.errores)

    def test_mes_sin_meta_advierte(self):
        self.metas(valores=((6, 42),))
        diaria(self.p, D(2026, 7, 1), nuevos=3)
        self.assertIn("Julio: sin meta mensual definida (3 usuarios nuevos).", self.validar().advertencias)

    def test_falta_de_dias_con_rangos(self):
        p = periodo_corto(nombre="Huecos")
        for dia in (1, 2, 3, 6, 9, 10, 11, 12, 13, 14):
            diaria(p, D(2026, 6, dia), nuevos=0)
        r = validacion.validar_periodo_metricas(p, SIM)
        self.assertIn("Faltan métricas diarias para 4 días (04/06–05/06, 07/06–08/06).", r.advertencias)

    def test_total_exacto_y_estado_completo(self):
        p = crear_periodo(nombre="Chico", fecha_inicio=D(2026, 6, 1), fecha_fin=D(2026, 6, 2), tamano_muestra=5)
        MetaMuestraMensual.objects.create(periodo=p, anio=2026, mes=6, nuevos_objetivo=5)
        diaria(p, D(2026, 6, 1), nuevos=3)
        diaria(p, D(2026, 6, 2), nuevos=2)
        self.assertEqual(validacion.validar_periodo_metricas(p, SIM).estado, validacion.EN_PROGRESO)  # faltan únicos
        asegurar_intervalos_unicos(p)
        r = validacion.validar_periodo_metricas(p, SIM)
        self.assertEqual((r.estado, r.errores, r.advertencias), (validacion.COMPLETO, [], []))
        self.assertIn("Muestra completa: 5 / 5 usuarios nuevos.", r.correctos)
        self.assertIn("Junio: 5 / 5 usuarios nuevos (meta alcanzada).", r.correctos)

    def test_total_excedido_y_por_debajo(self):
        p = crear_periodo(nombre="Chico", fecha_inicio=D(2026, 6, 1), fecha_fin=D(2026, 6, 2), tamano_muestra=5)
        diaria(p, D(2026, 6, 1), nuevos=4)
        self.assertIn("Muestra: 4 / 5 usuarios nuevos.", validacion.validar_periodo_metricas(p, SIM).advertencias)
        diaria(p, D(2026, 6, 2), nuevos=2)
        self.assertIn("Los usuarios nuevos (6) exceden el tamaño de la muestra (5).", validacion.validar_periodo_metricas(p, SIM).errores)

    def test_desglose_inconsistente(self):
        m = diaria(self.p, D(2026, 6, 1), nuevos=2, sesiones=10, desglose=False)
        MetricaDiariaFuente.objects.create(metrica_diaria=m, fuente=FuenteTrafico.DIRECTO, sesiones=7)
        MetricaDiariaDispositivo.objects.create(metrica_diaria=m, dispositivo=DispositivoAcceso.MOVIL, sesiones=11)
        r = self.validar()
        self.assertEqual(r.estado, validacion.CON_ERRORES)
        self.assertIn("01/06/2026: la suma por fuente de tráfico (7) no coincide con las sesiones (10).", r.errores)
        self.assertIn("01/06/2026: la suma por dispositivo (11) no coincide con las sesiones (10).", r.errores)

    def test_dia_sin_desglose_con_sesiones_es_inconsistente(self):
        diaria(self.p, D(2026, 6, 1), nuevos=2, desglose=False)
        self.assertTrue(any("fuente de tráfico (0)" in e for e in self.validar().errores))

    def test_recurrentes_diarios_imposibles(self):
        diaria(self.p, D(2026, 6, 1), nuevos=1, recurrentes=2)
        r = self.validar()
        self.assertTrue(any("deben ser 0" in e for e in r.errores))

    def test_unicos_faltantes_invalidos_inesperados_e_inconsistentes(self):
        p = periodo_corto(nombre="Cortito")
        for dia in range(1, 15):
            diaria(p, D(2026, 6, dia), nuevos=1)
        r = validacion.validar_periodo_metricas(p, SIM)
        self.assertIn("Los intervalos de únicos todavía están incompletos: faltan 3 de 3.", r.advertencias)
        asegurar_intervalos_unicos(p)
        self.assertEqual(validacion.validar_periodo_metricas(p, SIM).estado, validacion.COMPLETO)
        semana1 = UnicosPeriodo.objects.get(periodo=p, granularidad="SEMANA", inicio=D(2026, 6, 1))
        semana1.usuarios_recurrentes = 3
        semana1.save()
        r = validacion.validar_periodo_metricas(p, SIM)
        self.assertEqual(r.estado, validacion.CON_ERRORES)
        self.assertTrue(any("anteriores al intervalo (0)" in e for e in r.errores))
        semana1.usuarios_recurrentes = 0
        semana1.save()
        unicos(p, GranularidadUnicos.SEMANA, D(2026, 6, 3), D(2026, 6, 4))
        self.assertTrue(any("inesperado" in e for e in validacion.validar_periodo_metricas(p, SIM).errores))
        UnicosPeriodo.objects.filter(inicio=D(2026, 6, 3)).delete()
        UnicosPeriodo.objects.filter(pk=semana1.pk).update(fin=D(2026, 6, 5))
        self.assertTrue(any("se esperaba 07/06/2026" in e for e in validacion.validar_periodo_metricas(p, SIM).errores))

    def test_no_cruza_origenes(self):
        diaria(self.p, D(2026, 6, 1), nuevos=999, origen=REAL, desglose=False, sesiones=1000)
        self.metas()
        sim = self.validar()
        self.assertEqual(sim.estado, validacion.SIN_DATOS)
        self.assertEqual(sim.resumen["usuarios_nuevos"], 0)
        real = self.validar(origen=REAL)
        self.assertEqual(real.estado, validacion.CON_ERRORES)  # 999 > meta de junio, solo en REAL

    def test_solo_consulta_no_modifica_datos(self):
        self.metas()
        diaria(self.p, D(2026, 6, 1), nuevos=2)
        modelos = (MetricaDiaria, UnicosPeriodo, InteraccionDiaria, MetaMuestraMensual, PeriodoEvaluacion)
        antes = [(m, list(m.objects.values())) for m in modelos]
        self.validar()
        resumen_total(self.p, SIM)
        for modelo, filas in antes:
            self.assertEqual(list(modelo.objects.values()), filas, modelo.__name__)

    def test_estado_no_se_guarda_en_bd(self):
        self.assertNotIn("estado", {f.name for f in PeriodoEvaluacion._meta.get_fields()})
