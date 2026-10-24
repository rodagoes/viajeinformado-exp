from datetime import date, datetime, timezone as tz
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import PerfilUsuario

from .choices import AlcancePeriodo, OrigenDato
from .models import (
    EventoMetrica,
    InteraccionDiaria,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    SesionMetrica,
    UnicosPeriodo,
    VisitanteMetrica,
)
from .services import consolidacion_real as cr
from .services.resumenes import resumen_mensual, resumen_semanal, resumen_total
from .services.validacion import COMPLETO, EN_PROGRESO, SIN_DATOS, validar_periodo_metricas
from .tests import crear_periodo

D = date
REAL, SIM, GA4 = OrigenDato.REAL, OrigenDato.SIMULADO, OrigenDato.GA4
HOY = D(2026, 10, 31)  # posterior al periodo de prueba (01–14/10)


def visitante(primera, **extra):
    return VisitanteMetrica.objects.create(origen=REAL, primera_visita=primera, **extra)


def sesion(v, fecha, paginas=1, duracion=0, fuente="DIRECTO", dispositivo="MOVIL"):
    inicio = datetime(fecha.year, fecha.month, fecha.day, 15, 0, tzinfo=tz.utc)
    return SesionMetrica.objects.create(
        visitante=v, origen=REAL, fecha=fecha, inicio=inicio, fin=inicio, paginas_vistas=paginas, duracion_seg=duracion,
        fuente=fuente, dispositivo=dispositivo,
    )


def evento(v, fecha, tipo):
    return EventoMetrica.objects.create(visitante=v, origen=REAL, tipo=tipo, fecha=fecha)


def periodo_real(**extra):
    datos = dict(
        nombre="Octubre REAL", fecha_inicio=D(2026, 10, 1), fecha_fin=D(2026, 10, 14),
        alcance=AlcancePeriodo.TODOS_VISITANTES, tamano_muestra=None,
    )
    datos.update(extra)
    return crear_periodo(**datos)


def instantanea(periodo, origen=REAL):
    """Valores de todos los agregados (sin pks) para comparar ejecuciones."""
    return {
        "diarias": list(MetricaDiaria.objects.filter(periodo=periodo, origen=origen).order_by("fecha").values_list(
            "fecha", "sesiones", "paginas_vistas", "duracion_total_seg", "sesiones_rebote", "usuarios_nuevos", "usuarios_recurrentes",
            "editado_manual")),
        "fuentes": list(MetricaDiariaFuente.objects.filter(metrica_diaria__periodo=periodo, metrica_diaria__origen=origen)
                        .order_by("metrica_diaria__fecha", "fuente").values_list("metrica_diaria__fecha", "fuente", "sesiones")),
        "dispositivos": list(MetricaDiariaDispositivo.objects.filter(metrica_diaria__periodo=periodo, metrica_diaria__origen=origen)
                             .order_by("metrica_diaria__fecha", "dispositivo").values_list("metrica_diaria__fecha", "dispositivo", "sesiones")),
        "interacciones": list(InteraccionDiaria.objects.filter(periodo=periodo, origen=origen).order_by("fecha", "tipo")
                              .values_list("fecha", "tipo", "cantidad")),
        "unicos": list(UnicosPeriodo.objects.filter(periodo=periodo, origen=origen).order_by("granularidad", "inicio")
                       .values_list("granularidad", "inicio", "fin", "usuarios_recurrentes")),
    }


class BaseReal(TestCase):
    """Escenario del 01 al 14/10/2026 (jueves a miércoles): tres semanas lunes-domingo recortadas y un mes."""

    @classmethod
    def setUpTestData(cls):
        cls.periodo = periodo_real()
        cls.a = visitante(D(2026, 10, 1))
        cls.b = visitante(D(2026, 10, 1))
        cls.c = visitante(D(2026, 10, 2))
        cls.d = visitante(D(2026, 10, 6))
        sesion(cls.a, D(2026, 10, 1), paginas=3, duracion=100, fuente="DIRECTO", dispositivo="MOVIL")
        sesion(cls.a, D(2026, 10, 2), paginas=1, duracion=0, fuente="SOCIAL", dispositivo="ESCRITORIO")
        sesion(cls.a, D(2026, 10, 6), paginas=2, duracion=50, fuente="ORGANICO", dispositivo="MOVIL")
        sesion(cls.b, D(2026, 10, 1), paginas=1, duracion=10, fuente="DIRECTO", dispositivo="ESCRITORIO")
        sesion(cls.c, D(2026, 10, 2), paginas=2, duracion=30, fuente="DIRECTO", dispositivo="MOVIL")
        sesion(cls.c, D(2026, 10, 2), paginas=1, duracion=5, fuente="DIRECTO", dispositivo="MOVIL")  # 2.ª sesión del mismo día
        sesion(cls.d, D(2026, 10, 6), paginas=4, duracion=200, fuente="REFERIDO", dispositivo="TABLET")
        evento(cls.a, D(2026, 10, 1), "lugar_detalle_click")
        evento(cls.a, D(2026, 10, 1), "lugar_detalle_click")
        evento(cls.c, D(2026, 10, 2), "ubicacion_click")
        evento(cls.d, D(2026, 10, 6), "chatbot_consulta")
        EventoMetrica.objects.create(visitante=None, origen=REAL, tipo="idioma_cambiado", fecha=D(2026, 10, 6))

    def setUp(self):
        parche = mock.patch.object(cr, "hoy", return_value=HOY)
        parche.start()
        self.addCleanup(parche.stop)

    def reconstruir(self, **kw):
        kw.setdefault("dry_run", False)
        return cr.reconstruir_metricas_reales(self.periodo, **kw)


class DiariaRealTests(BaseReal):
    def test_metricas_diarias_derivadas_de_los_hechos(self):
        self.reconstruir()
        filas = {m.fecha: m for m in MetricaDiaria.objects.filter(periodo=self.periodo, origen=REAL)}
        self.assertEqual(len(filas), 14)  # cobertura completa: también los días sin sesiones
        d1, d2, d6, d3 = filas[D(2026, 10, 1)], filas[D(2026, 10, 2)], filas[D(2026, 10, 6)], filas[D(2026, 10, 3)]
        self.assertEqual((d1.sesiones, d1.paginas_vistas, d1.duracion_total_seg, d1.sesiones_rebote), (2, 4, 110, 1))
        self.assertEqual((d1.usuarios_nuevos, d1.usuarios_recurrentes), (2, 0))
        # dos sesiones de C el mismo día cuentan 2 sesiones pero un solo usuario
        self.assertEqual((d2.sesiones, d2.paginas_vistas, d2.sesiones_rebote), (3, 4, 2))
        self.assertEqual((d2.usuarios_nuevos, d2.usuarios_recurrentes), (1, 1))
        self.assertEqual((d6.sesiones, d6.paginas_vistas, d6.duracion_total_seg, d6.sesiones_rebote), (2, 6, 250, 0))
        self.assertEqual((d6.usuarios_nuevos, d6.usuarios_recurrentes), (1, 1))
        self.assertEqual((d3.sesiones, d3.paginas_vistas, d3.usuarios_nuevos, d3.usuarios_recurrentes), (0, 0, 0, 0))
        for m in filas.values():
            self.assertEqual(m.usuarios_unicos, m.usuarios_nuevos + m.usuarios_recurrentes)
            self.assertGreaterEqual(m.sesiones, m.usuarios_unicos)
            self.assertFalse(m.editado_manual)
            self.assertEqual(m.origen, REAL)

    def test_rebote_es_una_sola_pagina_y_se_calcula_sobre_bases_sumadas(self):
        self.reconstruir()
        total = resumen_total(self.periodo, REAL)
        self.assertEqual((total.sesiones, total.sesiones_rebote), (7, 3))
        self.assertAlmostEqual(total.tasa_rebote, 3 / 7 * 100)
        self.assertEqual(total.duracion_total_seg, 395)

    def test_fuentes_y_dispositivos_suman_las_sesiones_de_cada_dia(self):
        self.reconstruir()
        for m in MetricaDiaria.objects.filter(periodo=self.periodo, origen=REAL):
            self.assertEqual(sum(m.fuentes.values_list("sesiones", flat=True)), m.sesiones, m.fecha)
            self.assertEqual(sum(m.dispositivos.values_list("sesiones", flat=True)), m.sesiones, m.fecha)
        d2 = MetricaDiaria.objects.get(periodo=self.periodo, origen=REAL, fecha=D(2026, 10, 2))
        self.assertEqual(dict(d2.fuentes.values_list("fuente", "sesiones")), {"DIRECTO": 2, "SOCIAL": 1})
        self.assertEqual(dict(d2.dispositivos.values_list("dispositivo", "sesiones")), {"MOVIL": 2, "ESCRITORIO": 1})
        # política: solo se guardan categorías con valor; la ausencia equivale a 0
        self.assertFalse(MetricaDiariaFuente.objects.filter(sesiones=0).exists())
        self.assertEqual(MetricaDiaria.objects.get(periodo=self.periodo, origen=REAL, fecha=D(2026, 10, 3)).fuentes.count(), 0)

    def test_interacciones_agrupadas_por_fecha_y_tipo(self):
        self.reconstruir()
        self.assertEqual(instantanea(self.periodo)["interacciones"], [
            (D(2026, 10, 1), "lugar_detalle_click", 2), (D(2026, 10, 2), "ubicacion_click", 1),
            (D(2026, 10, 6), "chatbot_consulta", 1), (D(2026, 10, 6), "idioma_cambiado", 1),
        ])
        total = resumen_total(self.periodo, REAL)
        self.assertEqual(total.total_interacciones, 5)
        self.assertEqual(total.interacciones["lugar_detalle_click"], 2)
        self.assertEqual(total.interacciones["favorito_agregado"], 0)  # ausencia = 0 en los resúmenes


class UnicosRealTests(BaseReal):
    def test_semanas_y_mes_cuentan_visitantes_distintos_sin_sumar_unicos_diarios(self):
        self.reconstruir()
        filas = {(u.granularidad, u.inicio): u for u in UnicosPeriodo.objects.filter(periodo=self.periodo, origen=REAL)}
        self.assertEqual(sorted(filas), [
            ("MES", D(2026, 10, 1)), ("SEMANA", D(2026, 10, 1)), ("SEMANA", D(2026, 10, 5)), ("SEMANA", D(2026, 10, 12)),
        ])
        semanas = resumen_semanal(self.periodo, REAL)
        # semana 1 (01–04/10): A, B y C. Los únicos diarios suman 2 + 2 = 4, pero hay 3 personas distintas.
        s1 = semanas[0]
        self.assertEqual((s1.usuarios_nuevos, s1.usuarios_recurrentes, s1.usuarios_unicos), (3, 0, 3))
        # semana 2 (05–11/10): A (ya conocida) y D (nueva)
        s2 = semanas[1]
        self.assertEqual((s2.usuarios_nuevos, s2.usuarios_recurrentes, s2.usuarios_unicos), (1, 1, 2))
        self.assertEqual((semanas[2].usuarios_nuevos, semanas[2].usuarios_recurrentes, semanas[2].usuarios_unicos), (0, 0, 0))
        mes = resumen_mensual(self.periodo, REAL)[0]
        self.assertEqual((mes.usuarios_nuevos, mes.usuarios_recurrentes, mes.usuarios_unicos), (4, 0, 4))

    def test_un_visitante_repetido_en_varios_dias_cuenta_una_sola_vez_en_el_intervalo(self):
        self.reconstruir()
        s1 = resumen_semanal(self.periodo, REAL)[0]
        suma_diaria = sum(
            m.usuarios_nuevos + m.usuarios_recurrentes for m in MetricaDiaria.objects.filter(
                periodo=self.periodo, origen=REAL, fecha__range=(D(2026, 10, 1), D(2026, 10, 4)),
            )
        )
        self.assertEqual(suma_diaria, 4)
        self.assertEqual(s1.usuarios_unicos, 3)  # A estuvo activo dos días

    def test_solo_se_persisten_los_recurrentes(self):
        self.reconstruir()
        self.assertEqual({f.name for f in UnicosPeriodo._meta.get_fields()} & {"usuarios_nuevos", "usuarios_unicos"}, set())
        self.assertEqual(
            list(UnicosPeriodo.objects.filter(periodo=self.periodo, granularidad="SEMANA").order_by("inicio").values_list("usuarios_recurrentes", flat=True)),
            [0, 1, 0],
        )

    def test_la_validacion_de_la_fase_c_da_completo_para_un_periodo_real_transcurrido(self):
        resultado = self.reconstruir()
        v = validar_periodo_metricas(self.periodo, REAL)
        self.assertEqual((v.estado, v.errores, v.advertencias), (COMPLETO, [], []))
        self.assertEqual(resultado.validacion.estado, COMPLETO)

    def test_semana_con_visitante_recurrente_de_semanas_previas(self):
        extra = visitante(D(2026, 10, 1))
        sesion(extra, D(2026, 10, 13), paginas=2)
        self.reconstruir()
        s3 = resumen_semanal(self.periodo, REAL)[2]
        self.assertEqual((s3.usuarios_nuevos, s3.usuarios_recurrentes, s3.usuarios_unicos), (0, 1, 1))
        v = validar_periodo_metricas(self.periodo, REAL)
        self.assertEqual(v.errores, [])


class AlcanceYPeriodoTests(TestCase):
    def setUp(self):
        parche = mock.patch.object(cr, "hoy", return_value=HOY)
        parche.start()
        self.addCleanup(parche.stop)

    def test_muestra_registrada_solo_cuenta_cuentas_verificadas(self):
        periodo = periodo_real(nombre="Muestra", alcance=AlcancePeriodo.MUESTRA_REGISTRADA, tamano_muestra=10)
        ok = User.objects.create_user(username="ok", password="x")
        PerfilUsuario.objects.create(user=ok, nombres_apellidos="Ok", verificado=True)
        sin_verificar = User.objects.create_user(username="nov", password="x")
        PerfilUsuario.objects.create(user=sin_verificar, nombres_apellidos="NoV", verificado=False)
        verificado = visitante(D(2026, 10, 1), es_registrado=True, usuario=ok)
        no_verificado = visitante(D(2026, 10, 1), es_registrado=True, usuario=sin_verificar)
        anonimo = visitante(D(2026, 10, 1))
        for v in (verificado, no_verificado, anonimo):
            sesion(v, D(2026, 10, 1), paginas=2)
            evento(v, D(2026, 10, 1), "ubicacion_click")
        cr.reconstruir_metricas_reales(periodo, dry_run=False)
        d1 = MetricaDiaria.objects.get(periodo=periodo, origen=REAL, fecha=D(2026, 10, 1))
        self.assertEqual((d1.sesiones, d1.usuarios_nuevos), (1, 1))
        self.assertEqual(InteraccionDiaria.objects.get(periodo=periodo, origen=REAL).cantidad, 1)

    def test_todos_los_visitantes_incluye_anonimos_y_registrados(self):
        periodo = periodo_real(nombre="Todos")
        u = User.objects.create_user(username="u", password="x")
        PerfilUsuario.objects.create(user=u, nombres_apellidos="U", verificado=True)
        sesion(visitante(D(2026, 10, 1), es_registrado=True, usuario=u), D(2026, 10, 1))
        sesion(visitante(D(2026, 10, 1)), D(2026, 10, 1))
        cr.reconstruir_metricas_reales(periodo, dry_run=False)
        self.assertEqual(MetricaDiaria.objects.get(periodo=periodo, origen=REAL, fecha=D(2026, 10, 1)).sesiones, 2)

    def test_periodo_en_curso_cubre_hasta_hoy_y_queda_en_progreso_sin_exigir_metas(self):
        periodo = periodo_real(nombre="En curso")
        sesion(visitante(D(2026, 10, 1)), D(2026, 10, 1), paginas=2)
        with mock.patch.object(cr, "hoy", return_value=D(2026, 10, 5)):
            resultado = cr.reconstruir_metricas_reales(periodo, dry_run=False)
        self.assertEqual(resultado.agregados.hasta, D(2026, 10, 5))
        self.assertEqual(MetricaDiaria.objects.filter(periodo=periodo, origen=REAL).count(), 5)  # no hay filas futuras
        self.assertEqual(resultado.validacion.estado, EN_PROGRESO)
        self.assertEqual(resultado.validacion.errores, [])
        self.assertFalse(any("meta" in a.lower() or "muestra" in a.lower() for a in resultado.validacion.advertencias))
        # los intervalos que ya empezaron existen (con datos hasta hoy); los futuros no
        self.assertEqual(
            list(UnicosPeriodo.objects.filter(periodo=periodo, origen=REAL).order_by("granularidad", "inicio").values_list("granularidad", "inicio")),
            [("MES", D(2026, 10, 1)), ("SEMANA", D(2026, 10, 1)), ("SEMANA", D(2026, 10, 5))],
        )

    def test_sin_hechos_el_periodo_real_esta_sin_datos_o_en_progreso(self):
        periodo = periodo_real(nombre="Vacío")
        self.assertEqual(validar_periodo_metricas(periodo, REAL).estado, SIN_DATOS)
        resultado = cr.reconstruir_metricas_reales(periodo, dry_run=False)
        self.assertEqual(resultado.agregados.totales["sesiones"], 0)
        self.assertEqual(MetricaDiaria.objects.filter(periodo=periodo, origen=REAL).count(), 14)  # días vividos con 0 sesiones
        self.assertEqual(resultado.validacion.estado, COMPLETO)  # cobertura total, sin metas que exigir

    def test_rango_fuera_del_periodo_o_invertido_se_rechaza(self):
        periodo = periodo_real(nombre="Rangos")
        for desde, hasta in ((D(2026, 9, 30), D(2026, 10, 3)), (D(2026, 10, 1), D(2026, 10, 15)), (D(2026, 10, 5), D(2026, 10, 2))):
            with self.subTest(desde=desde, hasta=hasta), self.assertRaises(ValueError):
                cr.reconstruir_metricas_reales(periodo, desde, hasta, dry_run=False)
        self.assertEqual(MetricaDiaria.objects.count(), 0)

    def test_periodo_de_tesis_simulado_no_se_toca(self):
        tesis = crear_periodo(nombre="Tesis")  # 01/06–30/09, muestra registrada
        MetricaDiaria.objects.create(
            periodo=tesis, origen=SIM, fecha=D(2026, 6, 1), sesiones=5, paginas_vistas=12, duracion_total_seg=100,
            sesiones_rebote=1, usuarios_nuevos=3, usuarios_recurrentes=0,
        )
        sesion(visitante(D(2026, 10, 1)), D(2026, 10, 1))
        antes = instantanea(tesis, SIM)
        with self.assertRaises(ValueError):  # las fechas de octubre no pertenecen al periodo de tesis
            cr.reconstruir_metricas_reales(tesis, D(2026, 10, 1), D(2026, 10, 5), dry_run=False)
        self.assertEqual(instantanea(tesis, SIM), antes)
        self.assertEqual(MetricaDiaria.objects.filter(origen=REAL).count(), 0)


class IdempotenciaYAislamientoTests(BaseReal):
    def test_reconstruir_dos_veces_da_exactamente_lo_mismo(self):
        self.reconstruir()
        primera = instantanea(self.periodo)
        ids_primera = set(MetricaDiaria.objects.values_list("pk", flat=True))
        self.reconstruir()
        self.assertEqual(instantanea(self.periodo), primera)
        self.assertEqual(MetricaDiaria.objects.filter(origen=REAL).count(), 14)  # sin duplicados
        self.assertEqual(UnicosPeriodo.objects.filter(origen=REAL).count(), 4)
        self.assertEqual(len(ids_primera), 14)

    def test_refleja_cambios_en_los_hechos_y_elimina_lo_obsoleto(self):
        self.reconstruir()
        antes = instantanea(self.periodo)
        SesionMetrica.objects.filter(visitante=self.d).delete()  # D ya no tiene sesiones
        EventoMetrica.objects.filter(visitante=self.d).delete()
        self.reconstruir()
        despues = instantanea(self.periodo)
        self.assertNotEqual(despues, antes)
        d6 = MetricaDiaria.objects.get(periodo=self.periodo, origen=REAL, fecha=D(2026, 10, 6))
        self.assertEqual((d6.sesiones, d6.usuarios_nuevos), (1, 0))
        self.assertNotIn((D(2026, 10, 6), "chatbot_consulta", 1), despues["interacciones"])
        self.assertEqual(sum(1 for f, t, _ in despues["interacciones"] if t == "chatbot_consulta"), 0)

    def test_nunca_toca_simulado_ga4_otros_periodos_ni_fechas_fuera_del_rango(self):
        otro = periodo_real(nombre="Otro periodo")

        def fila(periodo, origen, fecha, nuevos=1):
            return MetricaDiaria.objects.create(
                periodo=periodo, origen=origen, fecha=fecha, sesiones=nuevos + 1, paginas_vistas=2 * (nuevos + 1),
                duracion_total_seg=10, sesiones_rebote=0, usuarios_nuevos=nuevos, usuarios_recurrentes=0,
            )

        fila(self.periodo, SIM, D(2026, 10, 1))
        fila(self.periodo, GA4, D(2026, 10, 2))
        fila(otro, REAL, D(2026, 10, 3))
        InteraccionDiaria.objects.create(periodo=self.periodo, origen=SIM, fecha=D(2026, 10, 1), tipo="ubicacion_click", cantidad=9)
        UnicosPeriodo.objects.create(periodo=self.periodo, origen=GA4, granularidad="MES", inicio=D(2026, 10, 1), fin=D(2026, 10, 14), usuarios_recurrentes=3)
        protegidos = (instantanea(self.periodo, SIM), instantanea(self.periodo, GA4), instantanea(otro, REAL))
        self.reconstruir()
        self.assertEqual((instantanea(self.periodo, SIM), instantanea(self.periodo, GA4), instantanea(otro, REAL)), protegidos)

    def test_un_rango_parcial_solo_reemplaza_ese_rango(self):
        self.reconstruir()
        completo = instantanea(self.periodo)
        MetricaDiaria.objects.filter(periodo=self.periodo, origen=REAL, fecha=D(2026, 10, 12)).update(sesiones=0)  # marca fuera del rango
        resultado = self.reconstruir(fecha_inicio=D(2026, 10, 1), fecha_fin=D(2026, 10, 4))
        self.assertEqual((resultado.agregados.desde, resultado.agregados.hasta), (D(2026, 10, 1), D(2026, 10, 4)))
        self.assertEqual(MetricaDiaria.objects.get(periodo=self.periodo, origen=REAL, fecha=D(2026, 10, 12)).sesiones, 0)  # intacta
        self.assertEqual(MetricaDiaria.objects.filter(origen=REAL).count(), 14)
        # solo la semana 1 estaba completa dentro del rango: la semana 2 y el mes no se tocan
        self.assertEqual(
            instantanea(self.periodo)["unicos"], completo["unicos"],
        )
        self.assertEqual([(u.granularidad, u.inicio) for u in resultado.agregados.unicos], [("SEMANA", D(2026, 10, 1))])

    def test_es_atomico_si_falla_a_mitad(self):
        self.reconstruir()
        antes = instantanea(self.periodo)
        sesion(self.d, D(2026, 10, 7), paginas=2)  # un hecho nuevo que cambiaría el resultado
        with mock.patch.object(cr.UnicosPeriodo.objects, "bulk_create", side_effect=RuntimeError("falla simulada")):
            with self.assertRaises(RuntimeError):
                self.reconstruir()
        self.assertEqual(instantanea(self.periodo), antes)  # ni el borrado ni lo insertado quedaron a medias
        self.reconstruir()
        self.assertNotEqual(instantanea(self.periodo), antes)

    def test_dry_run_no_escribe_y_describe_el_plan(self):
        r = cr.reconstruir_metricas_reales(self.periodo)  # dry_run por defecto
        self.assertFalse(r.escribio)
        self.assertEqual(MetricaDiaria.objects.count() + InteraccionDiaria.objects.count() + UnicosPeriodo.objects.count(), 0)
        self.assertEqual(r.filas["metricas_diarias"], 14)
        self.assertEqual(r.filas["unicos"], 4)
        self.assertEqual(r.existentes, {"metricas_diarias": 0, "interacciones": 0, "unicos": 0})
        self.assertEqual(r.agregados.totales["sesiones"], 7)
        self.reconstruir()
        otra = cr.reconstruir_metricas_reales(self.periodo)
        self.assertEqual(otra.existentes, {"metricas_diarias": 14, "interacciones": 4, "unicos": 4})

    def test_no_depende_de_valores_simulados(self):
        MetricaDiaria.objects.create(
            periodo=self.periodo, origen=SIM, fecha=D(2026, 10, 1), sesiones=999, paginas_vistas=2000, duracion_total_seg=1,
            sesiones_rebote=0, usuarios_nuevos=1, usuarios_recurrentes=0,
        )
        self.reconstruir()
        self.assertEqual(MetricaDiaria.objects.get(periodo=self.periodo, origen=REAL, fecha=D(2026, 10, 1)).sesiones, 2)

    def test_numero_de_consultas_fijo_no_crece_con_los_datos(self):
        def consultas():
            with CaptureQueriesContext(connection) as ctx:
                cr.calcular_agregados_reales(self.periodo)
            return len(ctx)

        base = consultas()
        for i in range(30):
            v = visitante(D(2026, 10, 3))
            sesion(v, D(2026, 10, 3 + i % 8), paginas=2)
            evento(v, D(2026, 10, 3), "lugar_detalle_click")
        self.assertEqual(consultas(), base)
        self.assertEqual(base, 5)  # sesiones, fuente, dispositivo, visitantes-día y eventos


class ComandoTests(BaseReal):
    def ejecutar(self, *args):
        salida = StringIO()
        call_command("reconstruir_metricas_reales", *args, stdout=salida)
        return salida.getvalue()

    def test_por_defecto_es_dry_run(self):
        texto = self.ejecutar("--periodo", str(self.periodo.pk))
        self.assertEqual(MetricaDiaria.objects.count(), 0)
        for esperado in ("Agregados REAL", "Sesiones:       7", "DRY-RUN: no se escribió nada", "Filas a escribir: 14 diarias",
                         "recurrentes semanales [0, 1, 0]", "Tasa de rebote: 42,86 %"):
            self.assertIn(esperado, texto)

    def test_aplicar_escribe_y_valida(self):
        texto = self.ejecutar("--periodo", self.periodo.nombre, "--aplicar")
        self.assertEqual(MetricaDiaria.objects.filter(origen=REAL).count(), 14)
        self.assertIn("Agregados REAL guardados", texto)
        self.assertIn("Completo", texto)
        self.assertNotIn("DRY-RUN", texto)

    def test_rango_y_errores_de_uso(self):
        self.ejecutar("--periodo", str(self.periodo.pk), "--desde", "2026-10-01", "--hasta", "2026-10-04", "--aplicar")
        self.assertEqual(MetricaDiaria.objects.filter(origen=REAL).count(), 4)
        with self.assertRaisesMessage(CommandError, "fuera del periodo"):
            self.ejecutar("--periodo", str(self.periodo.pk), "--desde", "2026-09-01")
        with self.assertRaisesMessage(CommandError, "AAAA-MM-DD"):
            self.ejecutar("--periodo", str(self.periodo.pk), "--desde", "1/10")
        with self.assertRaisesMessage(CommandError, "no existe"):
            self.ejecutar("--periodo", "999999")


class AdminYResumenesRealTests(BaseReal):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser("admin", "a@x.com", "clave12345"))
        self.reconstruir()

    def test_los_resumenes_de_la_fase_c_funcionan_con_origen_real(self):
        for vista in ("semanal", "mensual", "total"):
            r = self.client.get(reverse(f"admin:metricas_periodoevaluacion_resumen_{vista}"), {"periodo": self.periodo.pk, "origen": "REAL"})
            self.assertEqual(r.status_code, 200, vista)
        r = self.client.get(reverse("admin:metricas_periodoevaluacion_resumen_total"), {"periodo": self.periodo.pk, "origen": "REAL", "validar": "1"})
        self.assertContains(r, "Completo")
        indicadores = dict(map(tuple, r.context["tablas"][0]["filas"]))
        self.assertEqual(indicadores["Sesiones totales"], "7")
        self.assertEqual(indicadores["Tasa de rebote"], "42,86 %")
        mensual = self.client.get(reverse("admin:metricas_periodoevaluacion_resumen_mensual"), {"periodo": self.periodo.pk, "origen": "REAL"})
        self.assertEqual(mensual.context["tablas"][0]["filas"][0][3], "4")  # nuevos del mes

    def test_los_agregados_real_son_de_solo_lectura(self):
        m = MetricaDiaria.objects.filter(origen=REAL).first()
        self.assertEqual(self.client.post(reverse("admin:metricas_metricadiaria_change", args=[m.pk]), {"_save": "g", "sesiones": 1}).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:metricas_metricadiaria_delete", args=[m.pk]), {"post": "yes"}).status_code, 403)
        i = InteraccionDiaria.objects.filter(origen=REAL).first()
        self.assertEqual(self.client.post(reverse("admin:metricas_interacciondiaria_change", args=[i.pk]), {"_save": "g", "cantidad": 99}).status_code, 403)
        u = UnicosPeriodo.objects.filter(origen=REAL).first()
        self.assertEqual(self.client.post(reverse("admin:metricas_unicosperiodo_change", args=[u.pk]), {"_save": "g", "usuarios_recurrentes": 99}).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:metricas_metricadiaria_change", args=[m.pk])).status_code, 200)  # consultable
        self.assertEqual(self.client.get(reverse("admin:metricas_unicosperiodo_add")).status_code, 403)

    def test_el_listado_filtra_por_origen_real(self):
        r = self.client.get(reverse("admin:metricas_metricadiaria_changelist"), {"origen__exact": "REAL"})
        self.assertEqual(r.context["cl"].result_count, 14)
