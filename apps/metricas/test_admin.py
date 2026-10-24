from datetime import date, datetime, timezone

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .choices import (
    DispositivoAcceso,
    FuenteTrafico,
    GranularidadUnicos,
    OrigenDato,
    TipoInteraccion,
)
from .models import (
    EventoMetrica,
    InteraccionDiaria,
    MetaMuestraMensual,
    MetricaDiaria,
    MetricaDiariaDispositivo,
    MetricaDiariaFuente,
    PeriodoEvaluacion,
    SesionMetrica,
    UnicosPeriodo,
    VisitanteMetrica,
)
from .tests import crear_periodo

SIM, REAL, GA4 = OrigenDato.SIMULADO, OrigenDato.REAL, OrigenDato.GA4


def url(modelo, accion, *args):
    return reverse(f"admin:metricas_{modelo}_{accion}", args=args)


def crear_diaria(periodo, fecha, origen=SIM, con_desglose=True, **extra):
    datos = dict(
        periodo=periodo, origen=origen, fecha=fecha, sesiones=10, paginas_vistas=30, duracion_total_seg=1200,
        sesiones_rebote=2, usuarios_nuevos=4, usuarios_recurrentes=0,
    )
    datos.update(extra)
    diaria = MetricaDiaria.objects.create(**datos)
    if con_desglose:
        MetricaDiariaFuente.objects.create(metrica_diaria=diaria, fuente=FuenteTrafico.DIRECTO, sesiones=6)
        MetricaDiariaFuente.objects.create(metrica_diaria=diaria, fuente=FuenteTrafico.SOCIAL, sesiones=4)
        MetricaDiariaDispositivo.objects.create(metrica_diaria=diaria, dispositivo=DispositivoAcceso.MOVIL, sesiones=7)
        MetricaDiariaDispositivo.objects.create(
            metrica_diaria=diaria, dispositivo=DispositivoAcceso.ESCRITORIO, sesiones=3,
        )
    return diaria


def inline(prefix, campo, opciones, padre=None, valores=None):
    """Datos POST de un inline de desglose: filas existentes primero y luego las categorías faltantes."""
    valores = dict(valores or {})
    existentes = list(getattr(padre, prefix).order_by("id")) if padre else []
    filas = [(getattr(e, campo), valores.pop(getattr(e, campo), e.sesiones), e.pk) for e in existentes]
    presentes = {f[0] for f in filas}
    filas += [(c, valores.pop(c, 0), None) for c, _ in opciones.choices if c not in presentes]
    datos = {
        f"{prefix}-TOTAL_FORMS": len(filas), f"{prefix}-INITIAL_FORMS": len(existentes),
        f"{prefix}-MIN_NUM_FORMS": 0, f"{prefix}-MAX_NUM_FORMS": len(opciones.choices),
    }
    for i, (cat, sesiones, pk) in enumerate(filas):
        datos[f"{prefix}-{i}-{campo}"] = cat
        datos[f"{prefix}-{i}-sesiones"] = sesiones
        datos[f"{prefix}-{i}-id"] = pk or ""
        datos[f"{prefix}-{i}-metrica_diaria"] = padre.pk if padre else ""
    return datos


def post_diaria(periodo, fecha, padre=None, fuentes=None, dispositivos=None, **campos):
    datos = {
        "_save": "Guardar", "periodo": periodo.pk, "fecha": fecha.isoformat(), "sesiones": 10, "paginas_vistas": 30,
        "duracion_total_seg": 1200, "sesiones_rebote": 2, "usuarios_nuevos": 4, "usuarios_recurrentes": 0,
    }
    datos.update(campos)
    datos.update(inline("fuentes", "fuente", FuenteTrafico, padre, fuentes or {"DIRECTO": 6, "SOCIAL": 4}))
    datos.update(inline("dispositivos", "dispositivo", DispositivoAcceso, padre, dispositivos or {"MOVIL": 7, "ESCRITORIO": 3}))
    return datos


class AdminBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superusuario = User.objects.create_superuser("admin", "admin@example.com", "clave12345")
        cls.periodo = crear_periodo(nombre="Periodo A")

    def setUp(self):
        self.client.force_login(self.superusuario)


class PeriodoAdminTests(AdminBase):
    def post_periodo(self, metas=(), **campos):
        datos = {
            "_save": "Guardar", "nombre": "Nuevo", "fecha_inicio": "2027-06-01", "fecha_fin": "2027-09-30",
            "alcance": "MUESTRA_REGISTRADA", "tamano_muestra": 100,
            "metas_mensuales-TOTAL_FORMS": len(metas), "metas_mensuales-INITIAL_FORMS": 0,
            "metas_mensuales-MIN_NUM_FORMS": 0, "metas_mensuales-MAX_NUM_FORMS": 1000,
        }
        datos.update(campos)
        for i, (anio, mes, n) in enumerate(metas):
            datos.update({
                f"metas_mensuales-{i}-anio": anio, f"metas_mensuales-{i}-mes": mes,
                f"metas_mensuales-{i}-nuevos_objetivo": n, f"metas_mensuales-{i}-id": "",
                f"metas_mensuales-{i}-periodo": "",
            })
        return datos

    def test_formulario_incluye_inline_de_metas_y_no_los_desgloses_como_menu(self):
        r = self.client.get(url("periodoevaluacion", "change", self.periodo.pk))
        self.assertContains(r, "metas_mensuales-TOTAL_FORMS")
        indice = self.client.get(reverse("admin:app_list", args=["metricas"])).content.decode()
        self.assertNotIn("metricadiariafuente", indice)
        self.assertNotIn("metamuestramensual", indice)
        self.assertIn("metricadiaria", indice)

    def test_lista_muestra_estado_de_metas(self):
        for mes, n in ((6, 42), (7, 76)):
            MetaMuestraMensual.objects.create(periodo=self.periodo, anio=2026, mes=mes, nuevos_objetivo=n)
        self.assertContains(self.client.get(url("periodoevaluacion", "changelist")), "Metas incompletas: 118 / 360")
        for mes, n in ((8, 110), (9, 132)):
            MetaMuestraMensual.objects.create(periodo=self.periodo, anio=2026, mes=mes, nuevos_objetivo=n)
        self.assertContains(self.client.get(url("periodoevaluacion", "changelist")), "Metas completas: 360 / 360")

    def test_lista_muestra_avance_sin_mezclar_origenes(self):
        crear_diaria(self.periodo, date(2026, 6, 1), usuarios_nuevos=5)
        crear_diaria(self.periodo, date(2026, 6, 1), origen=REAL, con_desglose=False, usuarios_nuevos=9)
        r = self.client.get(url("periodoevaluacion", "changelist"))
        self.assertContains(r, "Simulado: 5 / 360")
        self.assertContains(r, "Real: 9 / 360")
        self.assertEqual(self.periodo.nuevos_por_origen(), {"SIMULADO": 5, "REAL": 9})

    def test_alta_con_metas_incrementales_es_valida(self):
        r = self.client.post(url("periodoevaluacion", "add"), self.post_periodo(metas=[(2027, 6, 30), (2027, 7, 20)]))
        self.assertEqual(r.status_code, 302)
        periodo = PeriodoEvaluacion.objects.get(nombre="Nuevo")
        self.assertEqual(periodo.total_metas(), 50)
        self.assertFalse(periodo.metas_completas())

    def test_alta_rechaza_mes_repetido_fuera_de_periodo_y_exceso(self):
        casos = {
            "repetido": [(2027, 6, 10), (2027, 6, 5)],
            "fuera del periodo": [(2027, 12, 10)],
            "excede": [(2027, 6, 60), (2027, 7, 50)],
        }
        for nombre, metas in casos.items():
            with self.subTest(nombre):
                r = self.client.post(url("periodoevaluacion", "add"), self.post_periodo(metas=metas))
                self.assertEqual(r.status_code, 200)
                self.assertFalse(PeriodoEvaluacion.objects.filter(nombre="Nuevo").exists())

    def test_meta_negativa_o_mes_invalido_se_rechazan(self):
        for meta in ((2027, 6, -1), (2027, 13, 5), (2027, 0, 5)):
            with self.subTest(meta=meta):
                r = self.client.post(url("periodoevaluacion", "add"), self.post_periodo(metas=[meta]))
                self.assertEqual(r.status_code, 200)
                self.assertFalse(PeriodoEvaluacion.objects.filter(nombre="Nuevo").exists())

    def test_validaciones_del_periodo(self):
        r = self.client.post(url("periodoevaluacion", "add"), self.post_periodo(fecha_fin="2027-05-01"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(url("periodoevaluacion", "add"), self.post_periodo(tamano_muestra=""))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(PeriodoEvaluacion.objects.filter(nombre="Nuevo").exists())
        self.periodo.activo = True
        self.periodo.save()
        r = self.client.post(url("periodoevaluacion", "add"), self.post_periodo(activo="on"))
        self.assertContains(r, "Ya existe otro periodo activo")

    def test_no_se_pueden_reducir_fechas_dejando_datos_fuera(self):
        crear_diaria(self.periodo, date(2026, 9, 20))
        self.periodo.fecha_fin = date(2026, 8, 31)
        with self.assertRaises(ValidationError):
            self.periodo.full_clean()
        self.periodo.fecha_fin = date(2026, 9, 30)
        self.periodo.full_clean()

    def test_periodo_sin_acciones_masivas(self):
        r = self.client.get(url("periodoevaluacion", "changelist"))
        self.assertNotContains(r, "delete_selected")


class MetricaDiariaAdminTests(AdminBase):
    def test_alta_simulada_fija_origen_y_marca_editado_manual(self):
        r = self.client.post(url("metricadiaria", "add"), post_diaria(self.periodo, date(2026, 6, 10), origen="REAL"))
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        m = MetricaDiaria.objects.get()
        self.assertEqual(m.origen, SIM)
        self.assertTrue(m.editado_manual)
        self.assertEqual(m.fuentes.count(), 2)  # las categorías en 0 no se guardan
        self.assertEqual(m.dispositivos.count(), 2)

    def test_origen_del_alta_no_se_puede_forzar_por_querystring_ni_post(self):
        r = self.client.get(url("metricadiaria", "add") + "?origen=REAL")
        self.assertNotContains(r, '<option value="REAL"')
        self.assertNotContains(r, '<option value="GA4"')
        for origen in ("REAL", "GA4"):
            self.client.post(url("metricadiaria", "add"), post_diaria(self.periodo, date(2026, 6, 11), origen=origen))
            MetricaDiaria.objects.all().delete()
        self.assertFalse(MetricaDiaria.objects.exclude(origen=SIM).exists())

    def test_alta_ofrece_todas_las_categorias_en_la_misma_pantalla(self):
        r = self.client.get(url("metricadiaria", "add"))
        self.assertContains(r, 'name="fuentes-TOTAL_FORMS" value="5"')
        self.assertContains(r, 'name="dispositivos-TOTAL_FORMS" value="3"')

    def test_alta_duplicada_se_rechaza_sin_error_500(self):
        crear_diaria(self.periodo, date(2026, 6, 10))
        r = self.client.post(url("metricadiaria", "add"), post_diaria(self.periodo, date(2026, 6, 10)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(MetricaDiaria.objects.count(), 1)

    def test_fuentes_deben_sumar_las_sesiones(self):
        r = self.client.post(
            url("metricadiaria", "add"),
            post_diaria(self.periodo, date(2026, 6, 10), fuentes={"DIRECTO": 6, "SOCIAL": 3}),
        )
        self.assertContains(r, "La suma de sesiones por fuente de tráfico (9) debe ser igual a las sesiones del día (10)")
        self.assertFalse(MetricaDiaria.objects.exists())

    def test_dispositivos_deben_sumar_las_sesiones(self):
        r = self.client.post(
            url("metricadiaria", "add"),
            post_diaria(self.periodo, date(2026, 6, 10), dispositivos={"MOVIL": 8, "TABLET": 3}),
        )
        self.assertContains(r, "La suma de sesiones por dispositivo (11) debe ser igual a las sesiones del día (10)")
        self.assertFalse(MetricaDiaria.objects.exists())

    def test_una_sola_categoria_puede_cubrir_todo_el_total(self):
        r = self.client.post(
            url("metricadiaria", "add"),
            post_diaria(self.periodo, date(2026, 6, 10), fuentes={"OTROS": 10}, dispositivos={"TABLET": 10}),
        )
        self.assertEqual(r.status_code, 302)

    def test_categoria_duplicada_se_rechaza(self):
        datos = post_diaria(self.periodo, date(2026, 6, 10))
        datos["fuentes-1-fuente"] = datos["fuentes-0-fuente"]  # dos filas DIRECTO
        r = self.client.post(url("metricadiaria", "add"), datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(MetricaDiaria.objects.exists())

    def test_cambiar_sesiones_sin_ajustar_el_desglose_se_rechaza(self):
        m = crear_diaria(self.periodo, date(2026, 6, 10))
        datos = post_diaria(self.periodo, date(2026, 6, 10), padre=m, sesiones=12, paginas_vistas=40)
        r = self.client.post(url("metricadiaria", "change", m.pk), datos)
        self.assertContains(r, "debe ser igual a las sesiones del día (12)")
        m.refresh_from_db()
        self.assertEqual(m.sesiones, 10)

    def test_edicion_coherente_marca_editado_manual(self):
        m = crear_diaria(self.periodo, date(2026, 6, 10))
        self.assertFalse(m.editado_manual)
        datos = post_diaria(
            self.periodo, date(2026, 6, 10), padre=m, sesiones=12, paginas_vistas=40,
            fuentes={"DIRECTO": 8}, dispositivos={"MOVIL": 9},
        )
        r = self.client.post(url("metricadiaria", "change", m.pk), datos)
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.sesiones, 12)
        self.assertTrue(m.editado_manual)

    def test_guardar_sin_cambios_no_marca_editado_manual(self):
        m = crear_diaria(self.periodo, date(2026, 6, 10))
        r = self.client.post(url("metricadiaria", "change", m.pk), post_diaria(self.periodo, date(2026, 6, 10), padre=m))
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertFalse(m.editado_manual)

    def test_cambiar_solo_el_desglose_marca_editado_manual(self):
        m = crear_diaria(self.periodo, date(2026, 6, 10))
        datos = post_diaria(self.periodo, date(2026, 6, 10), padre=m, fuentes={"DIRECTO": 5, "SOCIAL": 4, "OTROS": 1})
        self.assertEqual(self.client.post(url("metricadiaria", "change", m.pk), datos).status_code, 302)
        m.refresh_from_db()
        self.assertTrue(m.editado_manual)

    def test_identidad_y_derivados_no_son_editables_en_simulado(self):
        otro = crear_periodo(nombre="Otro", fecha_inicio=date(2027, 1, 1), fecha_fin=date(2027, 12, 31), tamano_muestra=5)
        m = crear_diaria(self.periodo, date(2026, 6, 10))
        r = self.client.get(url("metricadiaria", "change", m.pk))
        for nombre in ("origen", "periodo", "fecha", "editado_manual", "usuarios_unicos", "tasa_rebote",
                       "porcentaje_nuevos", "paginas_por_sesion", "duracion_media"):
            self.assertNotContains(r, f'name="{nombre}"', msg_prefix=nombre)
        datos = post_diaria(otro, date(2026, 6, 11), padre=m, origen="REAL", editado_manual="", usuarios_unicos=99)
        self.client.post(url("metricadiaria", "change", m.pk), datos)
        m.refresh_from_db()
        self.assertEqual((m.origen, m.periodo_id, m.fecha), (SIM, self.periodo.pk, date(2026, 6, 10)))

    def test_indicadores_calculados_con_formato_legible(self):
        m = crear_diaria(self.periodo, date(2026, 6, 10), usuarios_recurrentes=0)
        r = self.client.get(url("metricadiaria", "change", m.pk))
        self.assertContains(r, "20,00 %")  # rebote 2/10
        self.assertContains(r, "100,00 %")  # % nuevos
        self.assertContains(r, "02:00")  # 1200 s / 10 sesiones
        self.assertContains(r, "3,00")  # páginas por sesión
        lista = self.client.get(url("metricadiaria", "changelist"))
        self.assertContains(lista, "20,00 %")
        self.assertContains(lista, "02:00")

    def test_sin_denominador_se_muestra_sin_dato_no_cero(self):
        m = crear_diaria(
            self.periodo, date(2026, 6, 10), con_desglose=False, sesiones=0, paginas_vistas=0, duracion_total_seg=0,
            sesiones_rebote=0, usuarios_nuevos=0, usuarios_recurrentes=0,
        )
        r = self.client.get(url("metricadiaria", "change", m.pk))
        self.assertNotContains(r, "0,00 %")
        self.assertContains(r, "—")

    def test_duracion_con_horas(self):
        from .admin import _duracion
        self.assertEqual(_duracion(3725), "1:02:05")
        self.assertEqual(_duracion(59.6), "01:00")
        self.assertEqual(_duracion(None), "—")

    # -- recurrentes

    def test_primer_dia_no_admite_recurrentes(self):
        r = self.client.post(
            url("metricadiaria", "add"), post_diaria(self.periodo, date(2026, 6, 1), usuarios_recurrentes=1),
        )
        self.assertContains(r, "deben ser 0")
        self.assertFalse(MetricaDiaria.objects.exists())

    def test_recurrentes_limitados_por_nuevos_acumulados_anteriores(self):
        crear_diaria(self.periodo, date(2026, 6, 1), usuarios_nuevos=4)
        ok = post_diaria(self.periodo, date(2026, 6, 2), usuarios_recurrentes=4)
        self.assertEqual(self.client.post(url("metricadiaria", "add"), ok).status_code, 302)
        mal = post_diaria(self.periodo, date(2026, 6, 3), usuarios_recurrentes=9, usuarios_nuevos=0)
        r = self.client.post(url("metricadiaria", "add"), mal)
        self.assertContains(r, "no pueden superar los nuevos acumulados de días anteriores (8)")

    def test_recurrentes_no_cuentan_nuevos_de_otro_origen_ni_de_otro_periodo(self):
        crear_diaria(self.periodo, date(2026, 6, 1), origen=REAL, con_desglose=False,
                      sesiones=100, paginas_vistas=300, usuarios_nuevos=50)
        r = self.client.post(
            url("metricadiaria", "add"), post_diaria(self.periodo, date(2026, 6, 2), usuarios_recurrentes=1),
        )
        self.assertContains(r, "deben ser 0")

    def test_bajar_nuevos_que_deja_imposible_un_dia_posterior_se_rechaza(self):
        d1 = crear_diaria(self.periodo, date(2026, 6, 1), usuarios_nuevos=4)
        crear_diaria(self.periodo, date(2026, 6, 2), usuarios_nuevos=1, usuarios_recurrentes=3)
        datos = post_diaria(self.periodo, date(2026, 6, 1), padre=d1, usuarios_nuevos=2)
        r = self.client.post(url("metricadiaria", "change", d1.pk), datos)
        self.assertContains(r, "dejaría imposible el día 02/06/2026")
        d1.refresh_from_db()
        self.assertEqual(d1.usuarios_nuevos, 4)

    # -- origen y permisos

    def test_real_y_ga4_son_de_solo_lectura(self):
        for origen in (REAL, GA4):
            with self.subTest(origen=origen):
                m = crear_diaria(self.periodo, date(2026, 6, 10), origen=origen, con_desglose=False)
                r = self.client.get(url("metricadiaria", "change", m.pk))
                self.assertEqual(r.status_code, 200)
                self.assertNotContains(r, 'name="sesiones"')
                self.assertNotContains(r, "_save")
                datos = post_diaria(self.periodo, date(2026, 6, 10), padre=m, sesiones=99)
                self.assertEqual(self.client.post(url("metricadiaria", "change", m.pk), datos).status_code, 403)
                self.assertEqual(self.client.post(url("metricadiaria", "delete", m.pk), {"post": "yes"}).status_code, 403)
                m.refresh_from_db()
                self.assertEqual((m.sesiones, m.origen), (10, origen))

    def test_simulado_puede_borrarse_y_arrastra_su_desglose(self):
        m = crear_diaria(self.periodo, date(2026, 6, 10))
        r = self.client.post(url("metricadiaria", "delete", m.pk), {"post": "yes"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(MetricaDiaria.objects.exists())
        self.assertFalse(MetricaDiariaFuente.objects.exists())

    def test_sin_acciones_masivas(self):
        m = crear_diaria(self.periodo, date(2026, 6, 10))
        r = self.client.get(url("metricadiaria", "changelist"))
        self.assertNotContains(r, "delete_selected")
        self.client.post(
            url("metricadiaria", "changelist"), {"action": "delete_selected", "_selected_action": [m.pk], "post": "yes"},
        )
        self.assertTrue(MetricaDiaria.objects.filter(pk=m.pk).exists())

    def test_filtros_de_la_lista(self):
        crear_diaria(self.periodo, date(2026, 6, 10))
        crear_diaria(self.periodo, date(2026, 6, 11), origen=REAL, con_desglose=False)
        r = self.client.get(url("metricadiaria", "changelist") + "?origen__exact=REAL")
        self.assertEqual(r.context["cl"].result_count, 1)
        r = self.client.get(url("metricadiaria", "changelist") + "?editado_manual__exact=0")
        self.assertEqual(r.context["cl"].result_count, 2)

    def test_filtros_anio_mes_y_titulo_personalizado(self):
        crear_diaria(self.periodo, date(2026, 6, 10))
        crear_diaria(self.periodo, date(2026, 7, 1), con_desglose=False)
        lista = url("metricadiaria", "changelist")
        r = self.client.get(lista)
        self.assertTemplateUsed(r, "admin/metricas/metricadiaria/change_list.html")  # el texto del título se edita ahí
        self.assertContains(r, 'value="?anio=2026"')
        self.assertContains(r, 'value="?mes=7"')
        self.assertNotContains(r, "dateline")  # sin la fila diaria de date_hierarchy
        self.assertNotContains(r, "Mostrar recuentos")
        self.assertEqual(self.client.get(lista + "?anio=2026&mes=6").context["cl"].result_count, 1)
        self.assertEqual(self.client.get(lista + "?mes=7").context["cl"].result_count, 1)


class InteraccionAdminTests(AdminBase):
    def crear(self, origen=SIM, tipo=TipoInteraccion.CHATBOT_CONSULTA, fecha=date(2026, 6, 10), cantidad=5):
        return InteraccionDiaria.objects.create(
            periodo=self.periodo, origen=origen, fecha=fecha, tipo=tipo, cantidad=cantidad,
        )

    def post(self, **extra):
        datos = {"_save": "g", "periodo": self.periodo.pk, "fecha": "2026-06-10", "tipo": "chatbot_consulta", "cantidad": 7}
        datos.update(extra)
        return datos

    def test_alta_simulada_fuerza_origen(self):
        r = self.client.post(url("interacciondiaria", "add"), self.post(origen="REAL"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(InteraccionDiaria.objects.get().origen, SIM)

    def test_alta_duplicada_se_rechaza_sin_error_500(self):
        self.crear()
        self.assertEqual(self.client.post(url("interacciondiaria", "add"), self.post()).status_code, 200)

    def test_nueve_tipos_con_etiquetas_en_espanol(self):
        r = self.client.get(url("interacciondiaria", "add"))
        for _, etiqueta in TipoInteraccion.choices:
            self.assertContains(r, etiqueta.replace("&", "&amp;"))
        self.assertEqual(len(TipoInteraccion.choices), 9)

    def test_simulado_edita_solo_cantidad(self):
        i = self.crear()
        r = self.client.post(
            url("interacciondiaria", "change", i.pk),
            {"_save": "g", "cantidad": 9, "tipo": "ubicacion_click", "origen": "REAL", "fecha": "2026-06-11"},
        )
        self.assertEqual(r.status_code, 302)
        i.refresh_from_db()
        self.assertEqual((i.cantidad, i.tipo, i.origen, i.fecha), (9, "chatbot_consulta", SIM, date(2026, 6, 10)))

    def test_real_y_ga4_son_de_solo_lectura(self):
        for origen in (REAL, GA4):
            with self.subTest(origen=origen):
                i = self.crear(origen=origen, tipo=TipoInteraccion.UBICACION_CLICK)
                self.assertEqual(self.client.get(url("interacciondiaria", "change", i.pk)).status_code, 200)
                r = self.client.post(url("interacciondiaria", "change", i.pk), {"_save": "g", "cantidad": 1})
                self.assertEqual(r.status_code, 403)
                self.assertEqual(self.client.post(url("interacciondiaria", "delete", i.pk), {"post": "yes"}).status_code, 403)
                i.refresh_from_db()
                self.assertEqual(i.cantidad, 5)

    def test_simulado_puede_borrarse_y_no_hay_acciones_masivas(self):
        i = self.crear()
        self.assertNotContains(self.client.get(url("interacciondiaria", "changelist")), "delete_selected")
        self.assertEqual(self.client.post(url("interacciondiaria", "delete", i.pk), {"post": "yes"}).status_code, 302)
        self.assertFalse(InteraccionDiaria.objects.exists())


class UnicosPeriodoAdminTests(AdminBase):
    def crear(self, origen=SIM, recurrentes=3):
        return UnicosPeriodo.objects.create(
            periodo=self.periodo, origen=origen, granularidad=GranularidadUnicos.SEMANA,
            inicio=date(2026, 6, 1), fin=date(2026, 6, 7), usuarios_recurrentes=recurrentes,
        )

    def test_sin_alta_manual(self):
        self.assertEqual(self.client.get(url("unicosperiodo", "add")).status_code, 403)

    def test_simulado_edita_solo_recurrentes(self):
        u = self.crear()
        r = self.client.post(url("unicosperiodo", "change", u.pk), {
            "_save": "g", "usuarios_recurrentes": 8, "granularidad": "MES", "origen": "REAL",
            "inicio": "2026-07-01", "fin": "2026-07-31", "periodo": self.periodo.pk,
        })
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertEqual(
            (u.usuarios_recurrentes, u.granularidad, u.origen, u.inicio, u.fin),
            (8, "SEMANA", SIM, date(2026, 6, 1), date(2026, 6, 7)),
        )

    def test_estructura_no_aparece_como_campos_editables(self):
        u = self.crear()
        r = self.client.get(url("unicosperiodo", "change", u.pk))
        for nombre in ("periodo", "origen", "granularidad", "inicio", "fin"):
            self.assertNotContains(r, f'name="{nombre}"', msg_prefix=nombre)
        self.assertContains(r, 'name="usuarios_recurrentes"')

    def test_muestra_nuevos_y_unicos_derivados(self):
        crear_diaria(self.periodo, date(2026, 6, 2), usuarios_nuevos=5, con_desglose=False)
        crear_diaria(self.periodo, date(2026, 6, 3), origen=REAL, usuarios_nuevos=77, con_desglose=False,
                      sesiones=100, paginas_vistas=300)
        u = self.crear(recurrentes=3)
        r = self.client.get(url("unicosperiodo", "changelist"))
        fila = r.content.decode()
        self.assertIn(">5<", fila)  # nuevos (solo SIMULADO)
        self.assertIn(">8<", fila)  # únicos = 5 + 3
        self.assertEqual((u.usuarios_nuevos, u.usuarios_unicos), (5, 8))

    def test_real_y_ga4_son_de_solo_lectura(self):
        for origen in (REAL, GA4):
            with self.subTest(origen=origen):
                u = self.crear(origen=origen)
                self.assertEqual(self.client.get(url("unicosperiodo", "change", u.pk)).status_code, 200)
                r = self.client.post(url("unicosperiodo", "change", u.pk), {"_save": "g", "usuarios_recurrentes": 1})
                self.assertEqual(r.status_code, 403)
                u.refresh_from_db()
                self.assertEqual(u.usuarios_recurrentes, 3)

    def test_sin_borrado(self):
        u = self.crear()
        self.assertEqual(self.client.post(url("unicosperiodo", "delete", u.pk), {"post": "yes"}).status_code, 403)
        self.assertTrue(UnicosPeriodo.objects.exists())


class HechosAdminTests(AdminBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.visitante = VisitanteMetrica.objects.create(origen=REAL, primera_visita=date(2026, 6, 1))
        cls.sesion = SesionMetrica.objects.create(
            visitante=cls.visitante, origen=REAL, fecha=date(2026, 6, 1),
            inicio=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc), paginas_vistas=2,
            fuente=FuenteTrafico.DIRECTO, dispositivo=DispositivoAcceso.MOVIL, idioma="es",
        )
        cls.evento = EventoMetrica.objects.create(
            visitante=cls.visitante, sesion=cls.sesion, origen=REAL, tipo=TipoInteraccion.UBICACION_CLICK,
            fecha=date(2026, 6, 1), entidad_tipo="lugar", entidad_id=3, meta={"via": "iniciar_ruta"},
        )

    def objetos(self):
        return {"visitantemetrica": self.visitante, "sesionmetrica": self.sesion, "eventometrica": self.evento}

    def test_lista_y_detalle_de_consulta(self):
        for modelo, obj in self.objetos().items():
            with self.subTest(modelo=modelo):
                self.assertEqual(self.client.get(url(modelo, "changelist")).status_code, 200)
                detalle = self.client.get(url(modelo, "change", obj.pk))
                self.assertEqual(detalle.status_code, 200)
                self.assertNotContains(detalle, "_save")

    def test_sin_alta_edicion_ni_borrado(self):
        for modelo, obj in self.objetos().items():
            with self.subTest(modelo=modelo):
                self.assertEqual(self.client.get(url(modelo, "add")).status_code, 403)
                self.assertEqual(self.client.post(url(modelo, "change", obj.pk), {"_save": "g"}).status_code, 403)
                self.assertEqual(self.client.get(url(modelo, "delete", obj.pk)).status_code, 403)
                self.assertEqual(self.client.post(url(modelo, "delete", obj.pk), {"post": "yes"}).status_code, 403)
                self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())
                self.assertNotContains(self.client.get(url(modelo, "changelist")), "delete_selected")

    def test_evento_muestra_meta_solo_en_detalle(self):
        self.assertNotContains(self.client.get(url("eventometrica", "changelist")), "iniciar_ruta")
        self.assertContains(self.client.get(url("eventometrica", "change", self.evento.pk)), "iniciar_ruta")

    def test_filtros_de_sesion_y_evento(self):
        r = self.client.get(url("sesionmetrica", "changelist") + "?fuente__exact=SOCIAL")
        self.assertEqual(r.context["cl"].result_count, 0)
        r = self.client.get(url("eventometrica", "changelist") + "?tipo__exact=ubicacion_click")
        self.assertEqual(r.context["cl"].result_count, 1)
