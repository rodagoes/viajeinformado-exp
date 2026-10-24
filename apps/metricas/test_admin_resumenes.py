from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .choices import GranularidadUnicos, OrigenDato
from .models import (
    InteraccionDiaria,
    MetaMuestraMensual,
    MetricaDiaria,
    PeriodoEvaluacion,
    UnicosPeriodo,
)
from .services.unicos import asegurar_intervalos_unicos
from .test_admin import AdminBase, url
from .test_servicios import D, SIM, diaria, periodo_corto, unicos
from .tests import crear_periodo

REAL = OrigenDato.REAL


def vista(nombre):
    return reverse(f"admin:metricas_periodoevaluacion_resumen_{nombre}")


class AccesoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = crear_periodo()

    def test_requiere_login_de_staff(self):
        for nombre in ("semanal", "mensual", "total"):
            with self.subTest(vista=nombre):
                r = self.client.get(vista(nombre))
                self.assertEqual(r.status_code, 302)
                self.assertIn("/admin/login/", r["Location"])
        User.objects.create_user("turista", password="clave12345")  # no staff
        self.client.login(username="turista", password="clave12345")
        self.assertEqual(self.client.get(vista("semanal")).status_code, 302)

    def test_staff_sin_permiso_de_ver_recibe_403(self):
        User.objects.create_user("staff", password="clave12345", is_staff=True)
        self.client.login(username="staff", password="clave12345")
        self.assertEqual(self.client.get(vista("semanal")).status_code, 403)

    def test_staff_con_permiso_de_ver_accede(self):
        from django.contrib.auth.models import Permission
        usuario = User.objects.create_user("lector", password="clave12345", is_staff=True)
        usuario.user_permissions.add(Permission.objects.get(codename="view_periodoevaluacion"))
        self.client.login(username="lector", password="clave12345")
        self.assertEqual(self.client.get(vista("semanal")).status_code, 200)


class VistasResumenTests(AdminBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for mes, n in ((6, 42), (7, 76), (8, 110), (9, 132)):
            MetaMuestraMensual.objects.create(periodo=cls.periodo, anio=2026, mes=mes, nuevos_objetivo=n)
        diaria(cls.periodo, D(2026, 6, 1), nuevos=6, sesiones=10, rebote=2, paginas=30, duracion=1200)
        diaria(cls.periodo, D(2026, 6, 2), nuevos=2, recurrentes=3, sesiones=10, rebote=2, paginas=30, duracion=1200)
        InteraccionDiaria.objects.create(
            periodo=cls.periodo, origen=SIM, fecha=D(2026, 6, 1), tipo="lugar_detalle_click", cantidad=3,
        )

    def get(self, nombre, **params):
        params.setdefault("periodo", self.periodo.pk)
        return self.client.get(vista(nombre), params)

    def test_semanal_muestra_18_semanas(self):
        r = self.get("semanal")
        self.assertEqual(r.status_code, 200)
        indicadores = r.context["tablas"][0]
        self.assertEqual(len(indicadores["filas"]), 18)
        primera = indicadores["filas"][0]
        self.assertEqual(primera[0], "01/06 – 07/06/2026")
        self.assertEqual(primera[1], "2 / 7")
        self.assertEqual(primera[2], "20")  # sesiones
        self.assertEqual(primera[3], "8")  # nuevos
        self.assertEqual(primera[4], "—")  # recurrentes: aún no existe la fila de únicos
        self.assertEqual(primera[5], "—")
        self.assertEqual(primera[9], "20,00 %")  # rebote 4/20
        self.assertEqual(primera[8], "02:00")  # 2400 / 20
        self.assertEqual(indicadores["filas"][-1][0], "28/09 – 30/09/2026")
        self.assertEqual([t["titulo"] for t in r.context["tablas"]],
                         ["Indicadores", "Sesiones por fuente de tráfico", "Sesiones por dispositivo", "Interacciones"])

    def test_semanal_con_unicos_creados(self):
        asegurar_intervalos_unicos(self.periodo)
        fila = self.get("semanal").context["tablas"][0]["filas"][0]
        self.assertEqual((fila[4], fila[5]), ("0", "8"))
        self.assertEqual((fila[10], fila[11]), ("100,00 %", "0,00 %"))

    def test_mensual_muestra_4_meses_con_meta(self):
        r = self.get("mensual")
        filas = r.context["tablas"][0]["filas"]
        self.assertEqual([f[0] for f in filas], ["Junio 2026", "Julio 2026", "Agosto 2026", "Septiembre 2026"])
        self.assertEqual(filas[0][3], "8")
        self.assertEqual(filas[0][12], "42")
        self.assertEqual(filas[0][13], "19,05 %")  # 8 / 42
        self.assertEqual(filas[1][9], "—")  # julio sin sesiones: rebote sin dato, no 0 %
        interacciones = r.context["tablas"][3]
        self.assertIn("3", interacciones["filas"][0])
        self.assertEqual(len(interacciones["encabezados"]), 11)  # intervalo + 9 tipos + total

    def test_total_y_estado_en_progreso(self):
        r = self.get("total")
        self.assertContains(r, "En progreso")
        self.assertContains(r, "El periodo está en progreso.")
        self.assertContains(r, "Validar periodo")
        self.assertNotContains(r, "Faltan métricas diarias")  # el detalle solo aparece al pedir la validación
        indicadores = dict(map(tuple, r.context["tablas"][0]["filas"]))
        self.assertEqual(indicadores["Usuarios nuevos totales"], "8")
        self.assertEqual(indicadores["Usuarios únicos de la muestra"], "8 (parcial)")
        self.assertEqual(indicadores["Avance de la muestra"], "8 / 360 (2,22 %)")
        self.assertEqual(indicadores["Tasa de rebote"], "20,00 %")
        self.assertNotIn("% nuevos", indicadores)

    def test_validar_periodo_muestra_mensajes(self):
        r = self.get("total", validar="1")
        self.assertContains(r, "Faltan métricas diarias para 120 días")
        self.assertContains(r, "Junio: 8 / 42 usuarios nuevos.")
        self.assertContains(r, "Los intervalos de únicos todavía están incompletos")
        self.assertContains(r, "Metas completas: 360 / 360.")
        self.assertContains(r, f"--periodo {self.periodo.pk}")

    def test_las_vistas_no_modifican_la_bd(self):
        modelos = (MetricaDiaria, UnicosPeriodo, InteraccionDiaria, MetaMuestraMensual, PeriodoEvaluacion)
        antes = [(m, list(m.objects.values())) for m in modelos]
        for nombre in ("semanal", "mensual", "total"):
            self.assertEqual(self.get(nombre, validar="1").status_code, 200)
        for modelo, filas in antes:
            self.assertEqual(list(modelo.objects.values()), filas, modelo.__name__)

    def test_selector_de_periodo_y_origen(self):
        otro = periodo_corto(nombre="Otro periodo")
        diaria(otro, D(2026, 6, 1), nuevos=4, origen=REAL, desglose=False, sesiones=5)
        r = self.client.get(vista("total"), {"periodo": otro.pk, "origen": "REAL"})
        self.assertEqual((r.context["periodo"], r.context["origen"]), (otro, "REAL"))
        self.assertContains(r, 'value="REAL" selected')
        self.assertContains(r, "Otro periodo")
        indicadores = dict(map(tuple, r.context["tablas"][0]["filas"]))
        self.assertEqual(indicadores["Usuarios nuevos totales"], "4")
        # mismo periodo, otro origen: no se mezclan
        r = self.client.get(vista("total"), {"periodo": otro.pk, "origen": "SIMULADO"})
        self.assertEqual(dict(map(tuple, r.context["tablas"][0]["filas"]))["Usuarios nuevos totales"], "0")

    def test_parametros_invalidos_usan_valores_por_defecto(self):
        r = self.client.get(vista("semanal"), {"periodo": "abc", "origen": "XX"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["origen"], "SIMULADO")
        self.assertIsNotNone(r.context["periodo"])
        r = self.client.get(vista("semanal"), {"periodo": "99999"})
        self.assertEqual(r.status_code, 200)

    def test_sin_periodos(self):
        MetricaDiaria.objects.all().delete()
        InteraccionDiaria.objects.all().delete()
        PeriodoEvaluacion.objects.all().delete()
        r = self.client.get(vista("semanal"))
        self.assertContains(r, "Aún no hay periodos de evaluación")

    def test_enlaces_desde_el_listado_y_el_formulario_del_periodo(self):
        for pagina in (url("periodoevaluacion", "changelist"), url("periodoevaluacion", "change", self.periodo.pk)):
            r = self.client.get(pagina)
            for nombre in ("semanal", "mensual", "total"):
                self.assertContains(r, vista(nombre) + f"?periodo={self.periodo.pk}&amp;origen=SIMULADO")

    def test_numero_de_consultas_no_crece_con_los_datos(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        medidas = []
        for extra in (0, 10):
            for dia in range(3, 3 + extra):
                diaria(self.periodo, D(2026, 6, dia), nuevos=0)
            with CaptureQueriesContext(connection) as ctx:
                self.get("semanal")
            medidas.append(len(ctx))
        self.assertEqual(medidas[0], medidas[1])


class UnicosAdminValidacionTests(AdminBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.corto = periodo_corto(nombre="Corto")
        for dia in range(1, 8):
            diaria(cls.corto, D(2026, 6, dia), nuevos=3, recurrentes=0 if dia == 1 else 1)
        for dia in range(8, 15):
            diaria(cls.corto, D(2026, 6, dia), nuevos=1, recurrentes=2)
        cls.semana2 = unicos(cls.corto, GranularidadUnicos.SEMANA, D(2026, 6, 8), D(2026, 6, 14), recurrentes=0)

    def guardar(self, valor, fila=None):
        fila = fila or self.semana2
        return self.client.post(url("unicosperiodo", "change", fila.pk), {"_save": "g", "usuarios_recurrentes": valor})

    def test_valor_dentro_de_cotas_se_acepta(self):
        self.assertEqual(self.guardar(14).status_code, 302)
        self.semana2.refresh_from_db()
        self.assertEqual(self.semana2.usuarios_recurrentes, 14)

    def test_valor_fuera_de_cotas_se_rechaza_sin_modificar(self):
        r = self.guardar(15)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "superan la suma de recurrentes diarios del intervalo (14)")
        self.semana2.refresh_from_db()
        self.assertEqual(self.semana2.usuarios_recurrentes, 0)

    def test_primera_semana_rechaza_recurrentes(self):
        semana1 = unicos(self.corto, GranularidadUnicos.SEMANA, D(2026, 6, 1), D(2026, 6, 7))
        r = self.guardar(2, semana1)
        self.assertContains(r, "usuarios nuevos anteriores al intervalo (0)")

    def test_no_concluyente_se_acepta_con_advertencia(self):
        p = periodo_corto(nombre="Poco")
        diaria(p, D(2026, 6, 8), nuevos=1)
        fila = unicos(p, GranularidadUnicos.SEMANA, D(2026, 6, 8), D(2026, 6, 14))
        r = self.guardar(5, fila)
        self.assertEqual(r.status_code, 302)
        fila.refresh_from_db()
        self.assertEqual(fila.usuarios_recurrentes, 5)
        mensajes = [str(m) for m in self.client.get(url("unicosperiodo", "changelist")).context["messages"]]
        self.assertTrue(any("no concluyente" in m for m in mensajes))
