"""Periodo operativo anual de producción y comando actualizar_metricas_reales (solo datos REAL)."""
from datetime import date, datetime, timezone as tz
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from .choices import AlcancePeriodo, OrigenDato, TipoInteraccion
from .models import EventoMetrica, MetricaDiaria, PeriodoEvaluacion, SesionMetrica, VisitanteMetrica
from .services import consolidacion_real as cr
from .services.periodo_operativo import asegurar_periodo_operativo, buscar_periodo_operativo
from .test_servicios import diaria, periodo_corto

D = date
REAL, SIM = OrigenDato.REAL, OrigenDato.SIMULADO


def sesion_real(fecha, paginas=2, duracion=30):
    v = VisitanteMetrica.objects.create(origen=REAL, primera_visita=fecha)
    inicio = datetime(fecha.year, fecha.month, fecha.day, 15, 0, tzinfo=tz.utc)
    s = SesionMetrica.objects.create(
        visitante=v, origen=REAL, fecha=fecha, inicio=inicio, fin=inicio, paginas_vistas=paginas, duracion_seg=duracion,
        fuente="DIRECTO", dispositivo="MOVIL",
    )
    EventoMetrica.objects.create(
        visitante=v, sesion=s, origen=REAL, tipo=TipoInteraccion.LUGAR_DETALLE_CLICK, fecha=fecha)
    return v


def actualizar(hoy, *args):
    salida = StringIO()
    with mock.patch.object(cr, "hoy", return_value=hoy):
        call_command("actualizar_metricas_reales", *args, stdout=salida, stderr=StringIO())
    return salida.getvalue()


def estado(periodo):
    return {
        "diarias": list(MetricaDiaria.objects.filter(periodo=periodo, origen=REAL).order_by("fecha").values_list(
            "fecha", "sesiones", "paginas_vistas", "duracion_total_seg", "sesiones_rebote", "usuarios_nuevos",
            "usuarios_recurrentes")),
        "n_interacciones": periodo.interacciones_diarias.count(),
        "n_unicos": periodo.unicos.count(),
    }


class PeriodoOperativoTests(TestCase):
    def test_crea_el_periodo_del_anio_con_fechas_y_alcance_correctos(self):
        periodo, creado = asegurar_periodo_operativo(D(2026, 10, 24))
        self.assertTrue(creado)
        self.assertEqual(periodo.nombre, "Producción 2026")
        self.assertEqual((periodo.fecha_inicio, periodo.fecha_fin), (D(2026, 1, 1), D(2026, 12, 31)))
        self.assertEqual(periodo.alcance, AlcancePeriodo.TODOS_VISITANTES)
        self.assertIsNone(periodo.tamano_muestra)
        self.assertFalse(periodo.activo)

    def test_reutiliza_y_no_duplica(self):
        primero, _ = asegurar_periodo_operativo(D(2026, 3, 1))
        segundo, creado = asegurar_periodo_operativo(D(2026, 12, 31))
        self.assertFalse(creado)
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(PeriodoEvaluacion.objects.filter(nombre="Producción 2026").count(), 1)

    def test_cambio_de_anio_crea_el_nuevo_sin_tocar_el_anterior(self):
        p26, _ = asegurar_periodo_operativo(D(2026, 12, 31))
        self.assertIsNone(buscar_periodo_operativo(D(2027, 1, 1)))  # no se crean periodos futuros por adelantado
        p27, creado = asegurar_periodo_operativo(D(2027, 1, 1))
        self.assertTrue(creado)
        self.assertNotEqual(p26.pk, p27.pk)
        self.assertEqual((p27.nombre, p27.fecha_inicio, p27.fecha_fin), ("Producción 2027", D(2027, 1, 1), D(2027, 12, 31)))
        p26.refresh_from_db()
        self.assertEqual(p26.fecha_fin, D(2026, 12, 31))

    def test_no_toca_ni_reutiliza_periodos_de_tesis(self):
        tesis = periodo_corto()
        antes = (tesis.nombre, tesis.fecha_inicio, tesis.fecha_fin, tesis.alcance, tesis.activo)
        operativo, creado = asegurar_periodo_operativo(D(2026, 6, 15))
        self.assertTrue(creado)
        self.assertNotEqual(operativo.pk, tesis.pk)
        tesis.refresh_from_db()
        self.assertEqual((tesis.nombre, tesis.fecha_inicio, tesis.fecha_fin, tesis.alcance, tesis.activo), antes)

    def test_convive_con_un_periodo_de_tesis_activo(self):
        PeriodoEvaluacion.objects.create(
            nombre="Tesis", fecha_inicio=D(2026, 6, 1), fecha_fin=D(2026, 9, 30), tamano_muestra=10, activo=True)
        periodo, creado = asegurar_periodo_operativo(D(2026, 10, 1))  # "solo uno activo": el operativo no es activo
        self.assertTrue(creado)
        self.assertFalse(periodo.activo)


class ActualizarMetricasRealesTests(TestCase):
    HOY = D(2026, 10, 24)

    @classmethod
    def setUpTestData(cls):
        sesion_real(D(2026, 10, 20))
        sesion_real(D(2026, 10, 22), paginas=1)

    def test_crea_periodo_y_consolida_los_hechos_reales(self):
        salida = actualizar(self.HOY)
        periodo = PeriodoEvaluacion.objects.get(nombre="Producción 2026")
        self.assertIn("creado ahora", salida)
        e = estado(periodo)
        self.assertEqual(sum(f[1] for f in e["diarias"]), 2)  # sesiones
        self.assertEqual(e["diarias"][0][0], D(2026, 1, 1))   # cubre desde el inicio del periodo hasta hoy
        self.assertEqual(e["diarias"][-1][0], self.HOY)
        self.assertEqual(e["n_interacciones"], 2)

    def test_segunda_ejecucion_es_idempotente(self):
        actualizar(self.HOY)
        periodo = PeriodoEvaluacion.objects.get(nombre="Producción 2026")
        primera = estado(periodo)
        salida = actualizar(self.HOY)
        self.assertIn("ya existía", salida)
        self.assertEqual(estado(periodo), primera)
        self.assertEqual(PeriodoEvaluacion.objects.filter(nombre="Producción 2026").count(), 1)

    def test_una_sesion_activa_se_corrige_en_la_siguiente_ejecucion(self):
        actualizar(self.HOY)
        periodo = PeriodoEvaluacion.objects.get(nombre="Producción 2026")
        s = SesionMetrica.objects.get(fecha=D(2026, 10, 22))
        s.duracion_seg, s.paginas_vistas = 600, 5  # el navegador siguió informando después de la consolidación
        s.save()
        actualizar(self.HOY)
        fila = MetricaDiaria.objects.get(periodo=periodo, origen=REAL, fecha=D(2026, 10, 22))
        self.assertEqual((fila.duracion_total_seg, fila.paginas_vistas), (600, 5))

    def test_no_modifica_datos_simulados(self):
        tesis = periodo_corto()
        sim = diaria(tesis, D(2026, 6, 3), nuevos=4, origen=SIM)
        antes = (sim.sesiones, sim.usuarios_nuevos)
        actualizar(self.HOY)
        actualizar(self.HOY)
        sim.refresh_from_db()
        self.assertEqual((sim.sesiones, sim.usuarios_nuevos), antes)
        self.assertEqual(MetricaDiaria.objects.filter(periodo=tesis, origen=SIM).count(), 1)
        self.assertFalse(MetricaDiaria.objects.filter(origen=SIM).exclude(periodo=tesis).exists())

    def test_dry_run_no_escribe_ni_crea_periodo(self):
        salida = actualizar(self.HOY, "--dry-run")
        self.assertIn("se crearía", salida)
        self.assertFalse(PeriodoEvaluacion.objects.filter(nombre="Producción 2026").exists())
        asegurar_periodo_operativo(self.HOY)
        salida = actualizar(self.HOY, "--dry-run")
        self.assertIn("DRY-RUN", salida)
        self.assertFalse(MetricaDiaria.objects.filter(origen=REAL).exists())

    def test_cambio_de_anio_usa_el_periodo_nuevo(self):
        actualizar(D(2026, 12, 31))
        actualizar(D(2027, 1, 1))
        self.assertEqual(
            sorted(PeriodoEvaluacion.objects.filter(nombre__startswith="Producción").values_list("nombre", flat=True)),
            ["Producción 2026", "Producción 2027"],
        )
        p27 = PeriodoEvaluacion.objects.get(nombre="Producción 2027")
        self.assertEqual(MetricaDiaria.objects.filter(periodo=p27, origen=REAL).count(), 1)  # solo el 01/01/2027

    @override_settings(METRICAS_REAL_HABILITADAS=False)
    def test_avisa_si_el_tracking_esta_apagado_pero_consolida(self):
        salida = actualizar(self.HOY)
        self.assertIn("METRICAS_REAL_HABILITADAS está apagado", salida)
        self.assertTrue(MetricaDiaria.objects.filter(origen=REAL).exists())
