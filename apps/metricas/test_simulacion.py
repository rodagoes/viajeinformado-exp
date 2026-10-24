import random
from dataclasses import replace
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .choices import AlcancePeriodo, DispositivoAcceso, EstadoGeneracion, FuenteTrafico, GranularidadUnicos, OrigenDato, TipoInteraccion
from .models import (
    GeneracionSimulada,
    InteraccionDiaria,
    MetaMuestraMensual,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    PeriodoEvaluacion,
    UnicosPeriodo,
    VisitanteMetrica,
)
from .services import simulacion as sim
from .services.resumenes import resumen_mensual, resumen_total
from .services.unicos import evaluar_cotas_unicos
from .services.validacion import COMPLETO, validar_periodo_metricas
from .test_servicios import D, REAL, SIM, diaria, unicos
from .tests import crear_periodo

CUOTAS = ((6, 42), (7, 76), (8, 110), (9, 132))
SEMILLA = 20260601


def periodo_tesis(nombre="Tesis", cuotas=CUOTAS, **extra):
    p = crear_periodo(nombre=nombre, **extra)
    for mes, n in cuotas:
        MetaMuestraMensual.objects.create(periodo=p, anio=2026, mes=mes, nuevos_objetivo=n)
    return p


def conteos(periodo=None, origen=SIM):
    filtro = {"periodo": periodo, "origen": origen} if periodo else {"origen": origen}
    hijos = {f"metrica_diaria__{k}": v for k, v in filtro.items()}
    return {
        "diarias": MetricaDiaria.objects.filter(**filtro).count(),
        "interacciones": InteraccionDiaria.objects.filter(**filtro).count(),
        "unicos": UnicosPeriodo.objects.filter(**filtro).count(),
        "fuentes": MetricaDiariaFuente.objects.filter(**hijos).count(),
        "dispositivos": MetricaDiariaDispositivo.objects.filter(**hijos).count(),
    }


class SimuladorBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = periodo_tesis()
        cls.dataset = sim.simular_periodo(cls.periodo, SEMILLA)


class UtilidadesTests(SimpleTestCase):
    def test_reparto_entero_suma_exacta(self):
        rng = random.Random(7)
        for _ in range(500):
            total = rng.randint(0, 300)
            pesos = [rng.random() + 0.01 for _ in range(rng.randint(1, 6))]
            reparto = sim.reparto_entero(total, pesos)
            self.assertEqual(sum(reparto), total)
            self.assertTrue(all(x >= 0 for x in reparto))

    def test_reparto_es_proporcional_y_determinista(self):
        self.assertEqual(sim.reparto_entero(10, [1, 1, 1]), [4, 3, 3])  # empate: gana el primer índice
        self.assertEqual(sim.reparto_entero(0, [1, 2]), [0, 0])
        self.assertEqual(sim.reparto_entero(100, [38, 27, 18, 12, 5]), [38, 27, 18, 12, 5])
        with self.assertRaises(ValueError):
            sim.reparto_entero(5, [0, 0])

    def test_poisson_determinista_y_no_negativo(self):
        a = [sim._poisson(random.Random(3), lam) for lam in (0, 0.5, 5, 50, 200)]
        b = [sim._poisson(random.Random(3), lam) for lam in (0, 0.5, 5, 50, 200)]
        self.assertEqual(a, b)
        self.assertEqual(a[0], 0)
        self.assertTrue(all(x >= 0 for x in a))


class ReproducibilidadTests(SimuladorBase):
    def test_misma_semilla_mismo_dataset_y_huella(self):
        otro = sim.simular_periodo(self.periodo, SEMILLA)
        self.assertEqual(otro.checksum, self.dataset.checksum)
        self.assertEqual(otro.diarias, self.dataset.diarias)
        self.assertEqual(otro.unicos, self.dataset.unicos)
        self.assertRegex(self.dataset.checksum, r"^[0-9a-f]{64}$")

    def test_la_huella_no_depende_de_ids_ni_de_cuando_se_genera(self):
        gemelo = periodo_tesis(nombre="Otro nombre")  # otro pk, mismas fechas y metas
        self.assertEqual(sim.simular_periodo(gemelo, SEMILLA).checksum, self.dataset.checksum)

    def test_otra_semilla_otro_dataset_con_metas_exactas(self):
        otro = sim.simular_periodo(self.periodo, SEMILLA + 1)
        self.assertNotEqual(otro.checksum, self.dataset.checksum)
        self.assertNotEqual(otro.diarias, self.dataset.diarias)
        self.assertEqual(sim.validar_dataset(otro), [])
        self.assertEqual(sum(f.usuarios_nuevos for f in otro.diarias), 360)

    def test_otros_parametros_cambian_la_huella(self):
        otro = sim.simular_periodo(self.periodo, SEMILLA, replace(sim.ParametrosSimulacion(), prob_retorno_base=0.08))
        self.assertNotEqual(otro.checksum, self.dataset.checksum)
        self.assertEqual(sim.validar_dataset(otro), [])

    def test_no_usa_el_random_global(self):
        random.seed(1)
        a = sim.simular_periodo(self.periodo, SEMILLA).checksum
        random.seed(999)
        random.random()
        self.assertEqual(sim.simular_periodo(self.periodo, SEMILLA).checksum, a)

    def test_varias_semillas_siempre_validas(self):
        for semilla in range(1, 13):
            self.assertEqual(sim.validar_dataset(sim.simular_periodo(self.periodo, semilla)), [], f"semilla {semilla}")


class CuotasYCoberturaTests(SimuladorBase):
    def test_cuotas_mensuales_exactas_y_total_360(self):
        por_mes = {}
        for f in self.dataset.diarias:
            por_mes[f.fecha.month] = por_mes.get(f.fecha.month, 0) + f.usuarios_nuevos
        self.assertEqual(por_mes, {6: 42, 7: 76, 8: 110, 9: 132})
        self.assertEqual(sum(por_mes.values()), 360)
        self.assertEqual(self.dataset.participantes, 360)

    def test_122_dias_sin_huecos(self):
        fechas = [f.fecha for f in self.dataset.diarias]
        self.assertEqual(len(fechas), 122)
        self.assertEqual(fechas[0], D(2026, 6, 1))
        self.assertEqual(fechas[-1], D(2026, 9, 30))
        self.assertTrue(all(b - a == timedelta(days=1) for a, b in zip(fechas, fechas[1:])))

    def test_hay_variedad_de_nuevos_por_dia(self):
        nuevos = [f.usuarios_nuevos for f in self.dataset.diarias]
        self.assertIn(0, nuevos)
        self.assertGreater(max(nuevos), 3)
        self.assertGreater(len(set(nuevos)), 5)

    def test_funciona_con_otro_periodo_y_metas(self):
        p = crear_periodo(nombre="Parcial", fecha_inicio=D(2026, 6, 17), fecha_fin=D(2026, 8, 12), tamano_muestra=50)
        for mes, n in ((6, 10), (7, 30), (8, 10)):
            MetaMuestraMensual.objects.create(periodo=p, anio=2026, mes=mes, nuevos_objetivo=n)
        ds = sim.simular_periodo(p, 5)
        self.assertEqual(len(ds.diarias), 57)
        self.assertEqual([m.usuarios_nuevos for m in resumen_mensual(p, SIM, datos=ds.a_datos())], [10, 30, 10])
        self.assertEqual(sim.validar_dataset(ds), [])

    def test_no_simula_si_las_metas_no_cuadran_o_el_alcance_no_corresponde(self):
        incompleto = periodo_tesis(nombre="Incompleto", cuotas=CUOTAS[:3])
        with self.assertRaises(sim.SimulacionError):
            sim.simular_periodo(incompleto, 1)
        todos = crear_periodo(nombre="Todos", alcance=AlcancePeriodo.TODOS_VISITANTES, tamano_muestra=None)
        with self.assertRaises(sim.SimulacionError):
            sim.simular_periodo(todos, 1)


class ParticipantesEnMemoriaTests(SimuladorBase):
    def test_no_se_crean_cuentas_ni_visitantes(self):
        usuarios, visitantes = User.objects.count(), VisitanteMetrica.objects.count()
        sim.persistir_dataset(self.dataset)
        self.assertEqual(User.objects.count(), usuarios)
        self.assertEqual(VisitanteMetrica.objects.count(), visitantes)

    def test_visitas_posteriores_a_la_primera_y_sin_repetir(self):
        rng = random.Random(1)
        p = sim.ParametrosSimulacion()
        dias = [D(2026, 6, 1) + timedelta(days=n) for n in range(30)]
        nuevos = [3] * 30
        primeras, visitas = sim._simular_visitas(rng, dias, nuevos, [1.0] * 30, p)
        self.assertEqual(len(primeras), 90)
        for primera, lista in zip(primeras, visitas):
            self.assertTrue(all(d > primera for d in lista))
            self.assertEqual(lista, sorted(set(lista)))

    def test_primer_dia_sin_recurrentes_y_recurrentes_posibles(self):
        self.assertEqual(self.dataset.diarias[0].usuarios_recurrentes, 0)
        incorporados = 0
        for f in self.dataset.diarias:
            self.assertLessEqual(f.usuarios_recurrentes, incorporados)
            incorporados += f.usuarios_nuevos

    def test_recurrentes_crecen_con_la_base(self):
        por_mes = {}
        for f in self.dataset.diarias:
            por_mes.setdefault(f.fecha.month, []).append(f.usuarios_recurrentes)
        medias = [sum(v) / len(v) for _, v in sorted(por_mes.items())]
        self.assertEqual(medias, sorted(medias))
        self.assertLess(medias[0], 3)
        self.assertGreater(medias[-1], 8)
        self.assertFalse(all(b > a for a, b in zip(
            [f.usuarios_recurrentes for f in self.dataset.diarias],
            [f.usuarios_recurrentes for f in self.dataset.diarias][1:],
        )))  # no es una serie perfectamente creciente


class MetricasDiariasTests(SimuladorBase):
    def test_invariantes_por_dia(self):
        for f in self.dataset.diarias:
            unicos_dia = f.usuarios_nuevos + f.usuarios_recurrentes
            self.assertGreaterEqual(f.sesiones, unicos_dia)
            self.assertLessEqual(f.sesiones_rebote, f.sesiones)
            self.assertGreaterEqual(f.paginas_vistas, f.sesiones_rebote + 2 * (f.sesiones - f.sesiones_rebote))
            self.assertGreaterEqual(f.duracion_total_seg, 0)
            self.assertEqual(sum(f.fuentes.values()), f.sesiones)
            self.assertEqual(sum(f.dispositivos.values()), f.sesiones)
            self.assertEqual(set(f.fuentes), {c for c, _ in FuenteTrafico.choices})
            self.assertEqual(set(f.dispositivos), {c for c, _ in DispositivoAcceso.choices})
            if unicos_dia == 0:
                self.assertEqual((f.sesiones, f.paginas_vistas, f.duracion_total_seg), (0, 0, 0))

    def test_cada_usuario_genera_al_menos_una_sesion_y_algunos_mas(self):
        unicos_total = sum(f.usuarios_nuevos + f.usuarios_recurrentes for f in self.dataset.diarias)
        sesiones = sum(f.sesiones for f in self.dataset.diarias)
        self.assertGreater(sesiones, unicos_total)
        self.assertLess(sesiones / unicos_total, 1.6)

    def test_indicadores_plausibles_y_con_variacion(self):
        total = resumen_total(self.periodo, SIM, datos=self.dataset.a_datos())
        self.assertTrue(2.0 <= total.paginas_por_sesion <= 4.0, total.paginas_por_sesion)
        self.assertTrue(60 <= total.duracion_media <= 240, total.duracion_media)
        self.assertTrue(28 <= total.tasa_rebote <= 48, total.tasa_rebote)
        tasas = {round(f.sesiones_rebote / f.sesiones, 3) for f in self.dataset.diarias if f.sesiones >= 10}
        medias = {round(f.duracion_total_seg / f.sesiones) for f in self.dataset.diarias if f.sesiones >= 10}
        self.assertGreater(len(tasas), 20)  # no el mismo porcentaje todos los días
        self.assertGreater(len(medias), 20)
        self.assertTrue(all(f.duracion_total_seg / f.sesiones < 600 for f in self.dataset.diarias if f.sesiones))

    def test_fuentes_y_dispositivos_siguen_los_pesos_base(self):
        total = resumen_total(self.periodo, SIM, datos=self.dataset.a_datos())
        for codigo, peso in sim.ParametrosSimulacion().pesos_fuente.items():
            self.assertAlmostEqual(total.fuentes[codigo] / total.sesiones, peso, delta=0.05, msg=codigo)
        self.assertGreater(total.dispositivos["MOVIL"], total.dispositivos["ESCRITORIO"])
        self.assertGreater(total.dispositivos["ESCRITORIO"], total.dispositivos["TABLET"])


class InteraccionesSimuladasTests(SimuladorBase):
    def test_nueve_tipos_por_dia_no_negativos(self):
        for f in self.dataset.diarias:
            self.assertEqual(set(f.interacciones), {c for c, _ in TipoInteraccion.choices})
            self.assertTrue(all(v >= 0 for v in f.interacciones.values()))

    def test_relaciones_basicas(self):
        for f in self.dataset.diarias:
            i = f.interacciones
            aperturas = i["lugar_detalle_click"] + i["restaurante_detalle_click"] + i["alojamiento_detalle_click"]
            self.assertLessEqual(i["favorito_agregado"], aperturas)
            if f.sesiones == 0:
                self.assertEqual(sum(i.values()), 0)
        total = resumen_total(self.periodo, SIM, datos=self.dataset.a_datos()).interacciones
        self.assertLess(total["favorito_agregado"], total["lugar_detalle_click"])
        self.assertLess(total["idioma_cambiado"], total["favorito_agregado"])
        self.assertTrue(all(v > 0 for v in total.values()))

    def test_correlacionan_con_la_actividad(self):
        dias = sorted(self.dataset.diarias, key=lambda f: f.paginas_vistas)
        mitad = len(dias) // 2
        bajos = sum(sum(f.interacciones.values()) for f in dias[:mitad])
        altos = sum(sum(f.interacciones.values()) for f in dias[mitad:])
        self.assertGreater(altos, bajos * 2)


class UnicosSimuladosTests(SimuladorBase):
    def test_18_semanas_y_4_meses(self):
        semanas = [u for u in self.dataset.unicos if u.granularidad == GranularidadUnicos.SEMANA]
        meses = [u for u in self.dataset.unicos if u.granularidad == GranularidadUnicos.MES]
        self.assertEqual((len(semanas), len(meses)), (18, 4))
        self.assertEqual(semanas[-1].inicio, D(2026, 9, 28))

    def test_primer_intervalo_sin_recurrentes_y_cotas_cumplidas(self):
        datos = self.dataset.a_datos()
        self.assertEqual(self.dataset.unicos[0].usuarios_recurrentes, 0)
        junio = next(u for u in self.dataset.unicos if u.granularidad == "MES" and u.inicio == D(2026, 6, 1))
        self.assertEqual(junio.usuarios_recurrentes, 0)
        for u in self.dataset.unicos:
            errores, avisos = evaluar_cotas_unicos(datos, "intervalo", u.inicio, u.fin, u.usuarios_recurrentes)
            self.assertEqual((errores, avisos), ([], []), f"{u.granularidad} {u.inicio}")

    def test_recurrentes_se_derivan_de_los_participantes_no_de_sumas_diarias(self):
        datos = self.dataset.a_datos()
        distintos = 0
        for u in self.dataset.unicos:
            suma_diaria = sum(f.usuarios_recurrentes for f in self.dataset.diarias if u.inicio <= f.fecha <= u.fin)
            self.assertLessEqual(u.usuarios_recurrentes, suma_diaria)
            distintos += u.usuarios_recurrentes < suma_diaria
        self.assertGreater(distintos, 10)  # los no aditivos realmente difieren de la suma
        mensual = resumen_mensual(self.periodo, SIM, datos=datos)
        self.assertEqual([m.usuarios_nuevos for m in mensual], [42, 76, 110, 132])

    def test_dataset_completo_pasa_la_validacion_global(self):
        r = validar_periodo_metricas(self.periodo, SIM, datos=self.dataset.a_datos())
        self.assertEqual((r.estado, r.errores, r.advertencias), (COMPLETO, [], []))
        self.assertEqual(sim.validar_dataset(self.dataset), [])


class ValidacionDatasetTests(SimuladorBase):
    def copia(self):
        return replace(self.dataset, diarias=[replace(f, fuentes=dict(f.fuentes), dispositivos=dict(f.dispositivos),
                                                       interacciones=dict(f.interacciones)) for f in self.dataset.diarias])

    def test_detecta_desgloses_y_coberturas_rotas(self):
        ds = self.copia()
        ds.diarias[3].fuentes["DIRECTO"] += 1
        ds.diarias[4].dispositivos["MOVIL"] -= 1 if ds.diarias[4].dispositivos["MOVIL"] else 0
        ds.diarias[5].paginas_vistas = 0
        ds.diarias[6].interacciones.pop("idioma_cambiado")
        errores = sim.validar_dataset(ds)
        self.assertTrue(any("fuentes no suman" in e for e in errores))
        self.assertTrue(any("páginas vistas insuficientes" in e or "no suman" in e for e in errores))
        self.assertTrue(any("9 tipos" in e for e in errores))
        incompleto = replace(self.dataset, diarias=self.dataset.diarias[:-1])
        self.assertTrue(any("cobertura diaria" in e for e in sim.validar_dataset(incompleto)))

    def test_detecta_cuota_mensual_rota(self):
        ds = self.copia()
        dia = next(f for f in ds.diarias if f.fecha.month == 6 and f.usuarios_nuevos)
        dia.usuarios_nuevos += 1
        dia.sesiones += 1
        dia.paginas_vistas += 2
        dia.fuentes["DIRECTO"] += 1
        dia.dispositivos["MOVIL"] += 1
        self.assertTrue(any("Junio" in e for e in sim.validar_dataset(ds)))


class PersistenciaTests(SimuladorBase):
    def test_persiste_todas_las_filas_y_la_auditoria(self):
        u = User.objects.create_user("staff", password="x", is_staff=True)
        g = sim.persistir_dataset(self.dataset, usuario=u)
        self.assertEqual(conteos(self.periodo), {"diarias": 122, "interacciones": 1098, "unicos": 22, "fuentes": 610, "dispositivos": 366})
        self.assertEqual((g.estado, g.huella_inicial, g.semilla, g.usuario), (EstadoGeneracion.GENERADA, self.dataset.checksum, SEMILLA, u))
        self.assertEqual((g.filas_diarias, g.usuarios_objetivo), (122, 360))
        self.assertLess(len(str(g.parametros)), 2500)
        self.assertEqual(MetricaDiaria.objects.filter(editado_manual=True).count(), 0)
        self.assertEqual(set(MetricaDiaria.objects.values_list("origen", flat=True)), {SIM})
        r = validar_periodo_metricas(self.periodo, SIM)
        self.assertEqual((r.estado, r.errores, r.advertencias), (COMPLETO, [], []))

    def test_lo_persistido_coincide_con_el_dataset(self):
        sim.persistir_dataset(self.dataset)
        f = self.dataset.diarias[40]
        m = MetricaDiaria.objects.get(periodo=self.periodo, fecha=f.fecha)
        self.assertEqual((m.sesiones, m.paginas_vistas, m.duracion_total_seg, m.usuarios_recurrentes),
                         (f.sesiones, f.paginas_vistas, f.duracion_total_seg, f.usuarios_recurrentes))
        self.assertEqual(dict(m.fuentes.values_list("fuente", "sesiones")), f.fuentes)
        self.assertEqual(dict(InteraccionDiaria.objects.filter(periodo=self.periodo, fecha=f.fecha).values_list("tipo", "cantidad")), f.interacciones)

    def test_la_edicion_manual_no_reescribe_la_huella(self):
        g = sim.persistir_dataset(self.dataset)
        MetricaDiaria.objects.filter(periodo=self.periodo).update(duracion_total_seg=999999, editado_manual=True)
        g.refresh_from_db()
        self.assertEqual(g.huella_inicial, self.dataset.checksum)
        with self.assertRaises(ValueError):
            g.huella_inicial = "x"
            g.save()
        g.refresh_from_db()
        g.estado = EstadoGeneracion.REEMPLAZADA
        g.save(update_fields=["estado"])  # el estado sí puede cambiar

    def test_sin_reemplazar_aborta_si_hay_datos_y_no_toca_nada(self):
        diaria(self.periodo, D(2026, 6, 1), nuevos=1)
        antes = conteos(self.periodo)
        with self.assertRaises(sim.DatosSimuladosExistentes) as ctx:
            sim.persistir_dataset(self.dataset)
        self.assertEqual(ctx.exception.conteos["metricas_diarias"], 1)
        self.assertEqual(conteos(self.periodo), antes)
        self.assertFalse(GeneracionSimulada.objects.exists())

    def test_reemplazar_solo_toca_simulado_de_este_periodo(self):
        manual = diaria(self.periodo, D(2026, 6, 1), nuevos=1)
        InteraccionDiaria.objects.create(periodo=self.periodo, origen=SIM, fecha=D(2026, 6, 1), tipo="ubicacion_click", cantidad=3)
        unicos(self.periodo, GranularidadUnicos.MES, D(2026, 6, 1), D(2026, 6, 30))
        anterior = GeneracionSimulada.objects.create(
            periodo=self.periodo, semilla=1, estado=EstadoGeneracion.GENERADA, huella_inicial="a" * 64,
        )
        # lo que NO debe tocarse
        for origen in (REAL, OrigenDato.GA4):
            diaria(self.periodo, D(2026, 6, 2), nuevos=2, origen=origen)
            InteraccionDiaria.objects.create(periodo=self.periodo, origen=origen, fecha=D(2026, 6, 2), tipo="ubicacion_click", cantidad=1)
            unicos(self.periodo, GranularidadUnicos.MES, D(2026, 6, 1), D(2026, 6, 30), origen=origen, recurrentes=2)
        otro = periodo_tesis("Otro periodo")
        diaria(otro, D(2026, 6, 1), nuevos=5)
        reales = (conteos(self.periodo, REAL), conteos(self.periodo, OrigenDato.GA4), conteos(otro))
        metas = list(MetaMuestraMensual.objects.values_list("pk", "nuevos_objetivo"))

        g = sim.persistir_dataset(self.dataset, reemplazar=True)

        self.assertEqual(conteos(self.periodo), {"diarias": 122, "interacciones": 1098, "unicos": 22, "fuentes": 610, "dispositivos": 366})
        self.assertFalse(MetricaDiaria.objects.filter(pk=manual.pk).exists())
        self.assertEqual((conteos(self.periodo, REAL), conteos(self.periodo, OrigenDato.GA4), conteos(otro)), reales)
        self.assertEqual(list(MetaMuestraMensual.objects.values_list("pk", "nuevos_objetivo")), metas)
        self.assertTrue(PeriodoEvaluacion.objects.filter(pk=self.periodo.pk).exists())
        anterior.refresh_from_db()
        self.assertEqual(anterior.estado, EstadoGeneracion.REEMPLAZADA)
        self.assertEqual(g.estado, EstadoGeneracion.GENERADA)

    def test_es_atomico_si_falla_a_mitad(self):
        diaria(self.periodo, D(2026, 6, 1), nuevos=1)
        antes = conteos(self.periodo)
        with mock.patch.object(sim, "_insertar_unicos", side_effect=RuntimeError("falla simulada")):
            with self.assertRaises(RuntimeError):
                sim.persistir_dataset(self.dataset, reemplazar=True)
        self.assertEqual(conteos(self.periodo), antes)  # el borrado previo y lo insertado se revirtieron
        fallida = GeneracionSimulada.objects.get()
        self.assertEqual(fallida.estado, EstadoGeneracion.FALLIDA)
        self.assertIn("falla simulada", fallida.observaciones)

    def test_dataset_invalido_no_escribe_nada_ni_deja_auditoria(self):
        ds = replace(self.dataset, diarias=[replace(f, fuentes=dict(f.fuentes)) for f in self.dataset.diarias])
        ds.diarias[0].fuentes["DIRECTO"] += 5
        with self.assertRaises(sim.DatasetInvalido) as ctx:
            sim.persistir_dataset(ds, reemplazar=True)
        self.assertTrue(ctx.exception.errores)
        self.assertEqual(sum(conteos(self.periodo).values()), 0)
        self.assertFalse(GeneracionSimulada.objects.exists())

    def test_se_puede_generar_de_nuevo_con_reemplazar_y_misma_huella(self):
        g1 = sim.persistir_dataset(self.dataset)
        g2 = sim.persistir_dataset(sim.simular_periodo(self.periodo, SEMILLA), reemplazar=True)
        self.assertEqual(g1.huella_inicial, g2.huella_inicial)
        g1.refresh_from_db()
        self.assertEqual(g1.estado, EstadoGeneracion.REEMPLAZADA)
        self.assertEqual(MetricaDiaria.objects.filter(periodo=self.periodo).count(), 122)


class ComandoTests(SimuladorBase):
    def ejecutar(self, *args, **kw):
        salida = StringIO()
        call_command("generar_metricas_simuladas", *args, stdout=salida, stderr=StringIO(), **kw)
        return salida.getvalue()

    def test_dry_run_no_escribe_y_muestra_el_resumen(self):
        texto = self.ejecutar("--periodo", str(self.periodo.pk), "--seed", str(SEMILLA), "--dry-run")
        self.assertEqual(sum(conteos().values()), 0)
        self.assertFalse(GeneracionSimulada.objects.exists())
        for esperado in ("Previsualización", str(SEMILLA), self.dataset.checksum, "Junio 2026", "exacta",
                         "Fuente de tráfico", "Dispositivo", "Interacciones", "DRY-RUN: no se escribió nada",
                         "Acceso directo", "Consulta al chatbot"):
            self.assertIn(esperado, texto)
        self.assertNotIn("POR ENCIMA", texto)
        self.assertNotIn("Detalle diario", texto)

    def test_dry_run_con_datos_existentes_advierte_pero_no_toca(self):
        diaria(self.periodo, D(2026, 6, 1), nuevos=1)
        antes = conteos()
        texto = self.ejecutar("--periodo", str(self.periodo.pk), "--seed", "1", "--dry-run")
        self.assertIn("ADVERTENCIA: el periodo ya tiene datos SIMULADOS (1 métricas", texto)
        self.assertEqual(conteos(), antes)
        texto = self.ejecutar("--periodo", self.periodo.nombre, "--seed", "1", "--dry-run", "--reemplazar", "--dias")
        self.assertIn("Con --reemplazar serían eliminados", texto)
        self.assertIn("Detalle diario", texto)
        self.assertEqual(conteos(), antes)

    def test_sin_reemplazar_aborta_con_conteos(self):
        diaria(self.periodo, D(2026, 6, 1), nuevos=1)
        antes = conteos()
        with self.assertRaisesMessage(CommandError, "1 métricas diarias"):
            self.ejecutar("--periodo", str(self.periodo.pk), "--seed", "1")
        self.assertEqual(conteos(), antes)

    def test_escritura_normal_y_reemplazo(self):
        User.objects.create_user("staff", password="x", is_staff=True)
        texto = self.ejecutar("--periodo", str(self.periodo.pk), "--seed", "7", "--usuario", "staff")
        self.assertIn("Dataset SIMULADO guardado", texto)
        self.assertEqual(MetricaDiaria.objects.filter(periodo=self.periodo).count(), 122)
        self.assertEqual(GeneracionSimulada.objects.get().usuario.username, "staff")
        with self.assertRaises(CommandError):
            self.ejecutar("--periodo", str(self.periodo.pk), "--seed", "8")
        self.ejecutar("--periodo", str(self.periodo.pk), "--seed", "8", "--reemplazar")
        self.assertEqual(GeneracionSimulada.objects.filter(estado=EstadoGeneracion.REEMPLAZADA).count(), 1)
        self.assertEqual(GeneracionSimulada.objects.get(estado=EstadoGeneracion.GENERADA).semilla, 8)

    def test_errores_de_uso(self):
        with self.assertRaisesMessage(CommandError, "no existe"):
            self.ejecutar("--periodo", "9999", "--seed", "1")
        with self.assertRaisesMessage(CommandError, "No existe el usuario"):
            self.ejecutar("--periodo", str(self.periodo.pk), "--seed", "1", "--usuario", "nadie")
        incompleto = periodo_tesis("Incompleto", cuotas=CUOTAS[:2])
        with self.assertRaisesMessage(CommandError, "Las metas mensuales suman"):
            self.ejecutar("--periodo", str(incompleto.pk), "--seed", "1", "--dry-run")
        periodo_tesis("Dup")
        periodo_tesis("Dup")
        with self.assertRaisesMessage(CommandError, "ambiguo"):
            self.ejecutar("--periodo", "Dup", "--seed", "1", "--dry-run")


class AdminGeneracionTests(SimuladorBase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.com", "clave12345"))
        self.g = sim.persistir_dataset(self.dataset)

    def test_lista_y_detalle_de_solo_consulta(self):
        r = self.client.get(reverse("admin:metricas_generacionsimulada_changelist"))
        self.assertContains(r, "20260601")
        self.assertContains(r, self.dataset.checksum[:12])
        detalle = self.client.get(reverse("admin:metricas_generacionsimulada_change", args=[self.g.pk]))
        self.assertContains(detalle, self.dataset.checksum)
        self.assertContains(detalle, "prob_retorno_base")
        self.assertNotContains(detalle, "_save")

    def test_sin_alta_edicion_ni_borrado(self):
        self.assertEqual(self.client.get(reverse("admin:metricas_generacionsimulada_add")).status_code, 403)
        cambiar = reverse("admin:metricas_generacionsimulada_change", args=[self.g.pk])
        self.assertEqual(self.client.post(cambiar, {"_save": "g", "semilla": 1}).status_code, 403)
        borrar = reverse("admin:metricas_generacionsimulada_delete", args=[self.g.pk])
        self.assertEqual(self.client.post(borrar, {"post": "yes"}).status_code, 403)
        self.g.refresh_from_db()
        self.assertEqual(self.g.semilla, SEMILLA)
        self.assertNotContains(self.client.get(reverse("admin:metricas_generacionsimulada_changelist")), "delete_selected")
