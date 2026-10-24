import uuid
from datetime import date, datetime, timezone

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, skipUnlessDBFeature

from . import calculos
from .choices import (
    AlcancePeriodo,
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


def crear_periodo(**extra):
    datos = dict(
        nombre="Periodo de prueba",
        fecha_inicio=date(2026, 6, 1),
        fecha_fin=date(2026, 9, 30),
        tamano_muestra=360,
        alcance=AlcancePeriodo.MUESTRA_REGISTRADA,
    )
    datos.update(extra)
    return PeriodoEvaluacion.objects.create(**datos)


def metrica(periodo, **extra):
    datos = dict(
        periodo=periodo, origen=OrigenDato.SIMULADO, fecha=date(2026, 6, 10),
        sesiones=10, paginas_vistas=30, duracion_total_seg=1200, sesiones_rebote=2,
        usuarios_nuevos=4, usuarios_recurrentes=3,
    )
    datos.update(extra)
    return MetricaDiaria(**datos)


class CalculosTests(TestCase):
    def test_denominador_cero_es_none(self):
        self.assertIsNone(calculos.dividir(5, 0))
        self.assertIsNone(calculos.porcentaje(0, 0))
        self.assertIsNone(calculos.redondear(None))

    def test_porcentaje_y_redondeo(self):
        self.assertEqual(calculos.porcentaje(1, 4), 25)
        self.assertEqual(calculos.redondear(2 / 3, 2), 0.67)
        self.assertEqual(calculos.porcentaje(0, 5), 0)  # 0 real, no "sin dato"


class ChoicesTests(TestCase):
    def test_codigos_estables(self):
        self.assertEqual({c for c, _ in OrigenDato.choices}, {"SIMULADO", "REAL", "GA4"})
        self.assertEqual({c for c, _ in AlcancePeriodo.choices}, {"MUESTRA_REGISTRADA", "TODOS_VISITANTES"})
        self.assertEqual({c for c, _ in DispositivoAcceso.choices}, {"MOVIL", "ESCRITORIO", "TABLET"})
        self.assertEqual({c for c, _ in GranularidadUnicos.choices}, {"SEMANA", "MES"})
        self.assertEqual(
            {c for c, _ in FuenteTrafico.choices}, {"DIRECTO", "ORGANICO", "SOCIAL", "REFERIDO", "OTROS"},
        )

    def test_nueve_tipos_de_interaccion(self):
        self.assertEqual(
            {c for c, _ in TipoInteraccion.choices},
            {
                "chatbot_consulta", "lugar_detalle_click", "restaurante_detalle_click",
                "alojamiento_detalle_click", "evento_detalle_click", "gastronomia_donde_comer_click",
                "favorito_agregado", "ubicacion_click", "idioma_cambiado",
            },
        )


class PeriodoEvaluacionTests(TestCase):
    def test_periodo_valido(self):
        PeriodoEvaluacion(
            nombre="x", fecha_inicio=date(2026, 6, 1), fecha_fin=date(2026, 6, 1),
            tamano_muestra=1, alcance=AlcancePeriodo.MUESTRA_REGISTRADA,
        ).full_clean()

    def test_fin_anterior_a_inicio_falla(self):
        p = PeriodoEvaluacion(nombre="x", fecha_inicio=date(2026, 6, 2), fecha_fin=date(2026, 6, 1), tamano_muestra=1)
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_muestra_registrada_requiere_tamano_positivo(self):
        for tamano in (None, 0):
            p = PeriodoEvaluacion(
                nombre="x", fecha_inicio=date(2026, 6, 1), fecha_fin=date(2026, 6, 2),
                alcance=AlcancePeriodo.MUESTRA_REGISTRADA, tamano_muestra=tamano,
            )
            with self.assertRaises(ValidationError, msg=f"tamano={tamano}"):
                p.full_clean()

    def test_todos_visitantes_admite_tamano_nulo(self):
        PeriodoEvaluacion(
            nombre="x", fecha_inicio=date(2026, 6, 1), fecha_fin=date(2026, 6, 2),
            alcance=AlcancePeriodo.TODOS_VISITANTES, tamano_muestra=None,
        ).full_clean()

    def test_segundo_periodo_activo_falla(self):
        crear_periodo(activo=True)
        otro = PeriodoEvaluacion(
            nombre="otro", fecha_inicio=date(2027, 1, 1), fecha_fin=date(2027, 1, 31),
            tamano_muestra=10, activo=True,
        )
        with self.assertRaises(ValidationError) as ctx:
            otro.full_clean()
        self.assertIn("activo", ctx.exception.message_dict)

    def test_periodo_activo_puede_revalidarse_y_conviven_inactivos(self):
        activo = crear_periodo(activo=True)
        activo.full_clean()  # no choca consigo mismo
        otro = crear_periodo(nombre="inactivo", activo=False)
        otro.full_clean()

    def test_contiene(self):
        p = crear_periodo()
        self.assertTrue(p.contiene(date(2026, 6, 1)))
        self.assertTrue(p.contiene(date(2026, 9, 30)))
        self.assertFalse(p.contiene(date(2026, 10, 1)))

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_check_en_bd_fin_anterior(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PeriodoEvaluacion.objects.create(
                nombre="x", fecha_inicio=date(2026, 6, 2), fecha_fin=date(2026, 6, 1), tamano_muestra=1,
            )


class MetaMuestraMensualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = crear_periodo()

    def test_meta_valida_y_unica(self):
        MetaMuestraMensual.objects.create(periodo=self.periodo, anio=2026, mes=6, nuevos_objetivo=42)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MetaMuestraMensual.objects.create(periodo=self.periodo, anio=2026, mes=6, nuevos_objetivo=1)
        duplicada = MetaMuestraMensual(periodo=self.periodo, anio=2026, mes=6, nuevos_objetivo=1)
        with self.assertRaises(ValidationError):
            duplicada.full_clean()

    def test_mes_fuera_del_periodo_falla(self):
        for anio, mes in ((2026, 5), (2026, 10), (2025, 7)):
            meta = MetaMuestraMensual(periodo=self.periodo, anio=anio, mes=mes, nuevos_objetivo=1)
            with self.assertRaises(ValidationError, msg=f"{anio}-{mes}"):
                meta.full_clean()

    def test_mes_entre_1_y_12(self):
        anual = crear_periodo(nombre="anual", fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31))
        for mes in (1, 12):
            MetaMuestraMensual(periodo=anual, anio=2026, mes=mes, nuevos_objetivo=1).full_clean()
        for mes in (0, 13, -1, -12):
            meta = MetaMuestraMensual(periodo=anual, anio=2026, mes=mes, nuevos_objetivo=1)
            with self.subTest(mes=mes), self.assertRaises(ValidationError) as ctx:
                meta.full_clean()
            self.assertIn("mes", ctx.exception.message_dict)

    def test_anio_absurdo_falla(self):
        for anio in (26, 202, 3026):
            meta = MetaMuestraMensual(periodo=self.periodo, anio=anio, mes=6, nuevos_objetivo=1)
            with self.subTest(anio=anio), self.assertRaises(ValidationError):
                meta.full_clean()

    def test_mes_parcialmente_dentro_del_periodo_vale(self):
        periodo = crear_periodo(nombre="parcial", fecha_inicio=date(2026, 6, 15), fecha_fin=date(2026, 7, 10))
        for mes in (6, 7):
            MetaMuestraMensual(periodo=periodo, anio=2026, mes=mes, nuevos_objetivo=1).full_clean()

    def test_negativos_y_mes_invalido_fallan(self):
        for datos in ({"nuevos_objetivo": -1, "mes": 6}, {"nuevos_objetivo": 1, "mes": 13}, {"nuevos_objetivo": 1, "mes": 0}):
            meta = MetaMuestraMensual(periodo=self.periodo, anio=2026, **datos)
            with self.assertRaises(ValidationError, msg=str(datos)):
                meta.full_clean()

    def test_suma_de_metas_es_validacion_agregada_no_bloqueante(self):
        for mes, n in ((6, 42), (7, 76), (8, 110)):
            MetaMuestraMensual.objects.create(periodo=self.periodo, anio=2026, mes=mes, nuevos_objetivo=n)
        self.assertEqual(self.periodo.total_metas(), 228)
        self.assertFalse(self.periodo.metas_completas())  # creación incremental permitida
        MetaMuestraMensual.objects.create(periodo=self.periodo, anio=2026, mes=9, nuevos_objetivo=132)
        self.assertEqual(self.periodo.total_metas(), 360)
        self.assertTrue(self.periodo.metas_completas())

    def test_metas_completas_sin_tamano_es_false(self):
        p = crear_periodo(nombre="abierto", alcance=AlcancePeriodo.TODOS_VISITANTES, tamano_muestra=None)
        self.assertFalse(p.metas_completas())


class MetricaDiariaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = crear_periodo()

    def test_fila_valida(self):
        metrica(self.periodo).full_clean()

    def test_unicidad_periodo_origen_fecha(self):
        metrica(self.periodo).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            metrica(self.periodo).save()
        with self.assertRaises(ValidationError):
            metrica(self.periodo).full_clean()
        # otro origen, misma fecha: permitido (no se mezclan orígenes)
        metrica(self.periodo, origen=OrigenDato.REAL).full_clean()

    def test_fecha_fuera_del_periodo(self):
        for fecha in (date(2026, 5, 31), date(2026, 10, 1)):
            with self.assertRaises(ValidationError, msg=str(fecha)):
                metrica(self.periodo, fecha=fecha).full_clean()

    def test_negativos(self):
        for campo in ("sesiones", "paginas_vistas", "duracion_total_seg", "sesiones_rebote", "usuarios_nuevos", "usuarios_recurrentes"):
            with self.assertRaises(ValidationError, msg=campo):
                metrica(self.periodo, **{campo: -1}).full_clean()

    def test_rebotes_mayores_que_sesiones(self):
        with self.assertRaises(ValidationError):
            metrica(self.periodo, sesiones=3, sesiones_rebote=4, paginas_vistas=50, usuarios_nuevos=0, usuarios_recurrentes=0).full_clean()

    def test_unicos_mayores_que_sesiones(self):
        with self.assertRaises(ValidationError):
            metrica(self.periodo, sesiones=5, paginas_vistas=20, sesiones_rebote=0, usuarios_nuevos=3, usuarios_recurrentes=3).full_clean()
        metrica(self.periodo, sesiones=6, paginas_vistas=20, sesiones_rebote=0, usuarios_nuevos=3, usuarios_recurrentes=3).full_clean()

    def test_coherencia_de_paginas(self):
        # 10 sesiones, 2 rebote -> minimo 2 + 2*8 = 18 paginas
        metrica(self.periodo, paginas_vistas=18).full_clean()
        with self.assertRaises(ValidationError):
            metrica(self.periodo, paginas_vistas=17).full_clean()
        # todas rebote: basta 1 pagina por sesion
        metrica(self.periodo, sesiones_rebote=10, paginas_vistas=10).full_clean()
        with self.assertRaises(ValidationError):
            metrica(self.periodo, sesiones_rebote=10, paginas_vistas=9).full_clean()

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_checks_en_bd(self):
        invalidas = (
            dict(sesiones_rebote=11),
            dict(paginas_vistas=17),
            dict(sesiones=5, usuarios_nuevos=3, usuarios_recurrentes=3),
        )
        for extra in invalidas:
            with self.subTest(extra=extra), self.assertRaises(IntegrityError), transaction.atomic():
                metrica(self.periodo, **extra).save()

    def test_propiedades_calculadas(self):
        m = metrica(self.periodo)
        self.assertEqual(m.usuarios_unicos, 7)
        self.assertEqual(m.paginas_por_sesion, 3)
        self.assertEqual(m.duracion_media, 120)
        self.assertEqual(m.tasa_rebote, 20)
        self.assertAlmostEqual(m.porcentaje_nuevos, 4 / 7 * 100)
        self.assertAlmostEqual(m.porcentaje_recurrentes, 3 / 7 * 100)
        self.assertAlmostEqual(m.porcentaje_nuevos + m.porcentaje_recurrentes, 100)

    def test_denominador_cero_devuelve_none(self):
        m = metrica(
            self.periodo, sesiones=0, paginas_vistas=0, duracion_total_seg=0, sesiones_rebote=0,
            usuarios_nuevos=0, usuarios_recurrentes=0,
        )
        m.full_clean()
        self.assertEqual(m.usuarios_unicos, 0)
        for propiedad in ("paginas_por_sesion", "duracion_media", "tasa_rebote", "porcentaje_nuevos", "porcentaje_recurrentes"):
            self.assertIsNone(getattr(m, propiedad), propiedad)

    def test_unicos_cero_con_sesiones_no_fabrica_porcentaje(self):
        m = metrica(self.periodo, usuarios_nuevos=0, usuarios_recurrentes=0)
        self.assertIsNone(m.porcentaje_nuevos)
        self.assertEqual(m.tasa_rebote, 20)

    def test_no_se_guardan_campos_derivados(self):
        campos = {f.name for f in MetricaDiaria._meta.get_fields()}
        for derivado in ("usuarios_unicos", "paginas_por_sesion", "duracion_media", "tasa_rebote", "porcentaje_nuevos", "porcentaje_recurrentes"):
            self.assertNotIn(derivado, campos)

    def test_nuevos_no_estan_atados_a_metas_de_muestra(self):
        # Sin metas creadas (o distintas) la fila sigue siendo válida: la igualdad es del generador.
        MetaMuestraMensual.objects.create(periodo=self.periodo, anio=2026, mes=6, nuevos_objetivo=1)
        metrica(self.periodo, usuarios_nuevos=5).full_clean()


class DesgloseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = crear_periodo()
        cls.diaria = metrica(cls.periodo)
        cls.diaria.save()

    def test_fuente_valida_unica_y_choices(self):
        MetricaDiariaFuente(metrica_diaria=self.diaria, fuente=FuenteTrafico.DIRECTO, sesiones=4).full_clean()
        MetricaDiariaFuente.objects.create(metrica_diaria=self.diaria, fuente=FuenteTrafico.DIRECTO, sesiones=4)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MetricaDiariaFuente.objects.create(metrica_diaria=self.diaria, fuente=FuenteTrafico.DIRECTO, sesiones=1)
        with self.assertRaises(ValidationError):
            MetricaDiariaFuente(metrica_diaria=self.diaria, fuente="TIKTOK", sesiones=1).full_clean()
        with self.assertRaises(ValidationError):
            MetricaDiariaFuente(metrica_diaria=self.diaria, fuente=FuenteTrafico.SOCIAL, sesiones=-1).full_clean()

    def test_dispositivo_valido_unico_y_choices(self):
        MetricaDiariaDispositivo(metrica_diaria=self.diaria, dispositivo=DispositivoAcceso.MOVIL, sesiones=6).full_clean()
        MetricaDiariaDispositivo.objects.create(metrica_diaria=self.diaria, dispositivo=DispositivoAcceso.MOVIL, sesiones=6)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MetricaDiariaDispositivo.objects.create(metrica_diaria=self.diaria, dispositivo=DispositivoAcceso.MOVIL, sesiones=1)
        with self.assertRaises(ValidationError):
            MetricaDiariaDispositivo(metrica_diaria=self.diaria, dispositivo="SMART_TV", sesiones=1).full_clean()
        with self.assertRaises(ValidationError):
            MetricaDiariaDispositivo(metrica_diaria=self.diaria, dispositivo=DispositivoAcceso.TABLET, sesiones=-1).full_clean()

    def test_la_suma_no_se_valida_en_el_modelo(self):
        # Σ fuentes != sesiones es válido a nivel de modelo; lo valida el formset/servicio.
        MetricaDiariaFuente(metrica_diaria=self.diaria, fuente=FuenteTrafico.OTROS, sesiones=999).full_clean()

    def test_se_eliminan_con_la_diaria(self):
        MetricaDiariaFuente.objects.create(metrica_diaria=self.diaria, fuente=FuenteTrafico.OTROS, sesiones=1)
        MetricaDiariaDispositivo.objects.create(metrica_diaria=self.diaria, dispositivo=DispositivoAcceso.TABLET, sesiones=1)
        self.diaria.delete()
        self.assertFalse(MetricaDiariaFuente.objects.exists())
        self.assertFalse(MetricaDiariaDispositivo.objects.exists())


class InteraccionDiariaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = crear_periodo()

    def nueva(self, **extra):
        datos = dict(
            periodo=self.periodo, origen=OrigenDato.SIMULADO, fecha=date(2026, 6, 10),
            tipo=TipoInteraccion.CHATBOT_CONSULTA, cantidad=5,
        )
        datos.update(extra)
        return InteraccionDiaria(**datos)

    def test_valida_y_unica(self):
        self.nueva().full_clean()
        self.nueva().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.nueva().save()
        with self.assertRaises(ValidationError):
            self.nueva().full_clean()
        self.nueva(tipo=TipoInteraccion.UBICACION_CLICK).full_clean()  # otro tipo, mismo día

    def test_tipo_invalido(self):
        with self.assertRaises(ValidationError):
            self.nueva(tipo="vista_pasiva").full_clean()

    def test_fecha_fuera_del_periodo(self):
        with self.assertRaises(ValidationError):
            self.nueva(fecha=date(2026, 10, 1)).full_clean()

    def test_cantidad_negativa(self):
        with self.assertRaises(ValidationError):
            self.nueva(cantidad=-1).full_clean()
        self.nueva(cantidad=0).full_clean()


class UnicosPeriodoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.periodo = crear_periodo()

    def nuevo(self, **extra):
        datos = dict(
            periodo=self.periodo, origen=OrigenDato.SIMULADO, granularidad=GranularidadUnicos.SEMANA,
            inicio=date(2026, 6, 1), fin=date(2026, 6, 7), usuarios_recurrentes=2,
        )
        datos.update(extra)
        return UnicosPeriodo(**datos)

    def test_valido_y_unico(self):
        self.nuevo().full_clean()
        self.nuevo().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.nuevo().save()
        with self.assertRaises(ValidationError):
            self.nuevo().full_clean()
        # misma fecha de inicio pero otra granularidad u origen: permitido
        self.nuevo(granularidad=GranularidadUnicos.MES, fin=date(2026, 6, 30)).full_clean()
        self.nuevo(origen=OrigenDato.REAL).full_clean()

    def test_granularidad_invalida(self):
        with self.assertRaises(ValidationError):
            self.nuevo(granularidad="DIA").full_clean()

    def test_inicio_posterior_a_fin(self):
        with self.assertRaises(ValidationError):
            self.nuevo(inicio=date(2026, 6, 8), fin=date(2026, 6, 7)).full_clean()

    def test_intervalo_fuera_del_periodo(self):
        for extra in (dict(inicio=date(2026, 5, 25)), dict(fin=date(2026, 10, 4), inicio=date(2026, 9, 28))):
            with self.assertRaises(ValidationError, msg=str(extra)):
                self.nuevo(**extra).full_clean()

    def test_recurrentes_negativos(self):
        with self.assertRaises(ValidationError):
            self.nuevo(usuarios_recurrentes=-1).full_clean()

    def test_nuevos_y_unicos_derivados_de_las_diarias(self):
        u = self.nuevo(usuarios_recurrentes=3)
        u.save()
        for dia, nuevos in ((1, 5), (3, 2), (7, 1), (8, 40)):  # el día 8 queda fuera del intervalo
            metrica(
                self.periodo, fecha=date(2026, 6, dia), usuarios_nuevos=nuevos, usuarios_recurrentes=0,
                sesiones=nuevos + 1, paginas_vistas=(nuevos + 1) * 2, sesiones_rebote=0,
            ).save()
        # otro origen no se mezcla
        metrica(
            self.periodo, origen=OrigenDato.REAL, fecha=date(2026, 6, 2), usuarios_nuevos=99,
            usuarios_recurrentes=0, sesiones=100, paginas_vistas=200, sesiones_rebote=0,
        ).save()
        self.assertEqual(u.usuarios_nuevos, 8)
        self.assertEqual(u.usuarios_unicos, 11)

    def test_sin_diarias_los_nuevos_son_cero(self):
        u = self.nuevo(usuarios_recurrentes=0)
        self.assertEqual(u.usuarios_nuevos, 0)
        self.assertEqual(u.usuarios_unicos, 0)

    def test_no_se_guardan_nuevos_ni_unicos(self):
        campos = {f.name for f in UnicosPeriodo._meta.get_fields()}
        self.assertNotIn("usuarios_nuevos", campos)
        self.assertNotIn("usuarios_unicos", campos)


class VisitanteSesionEventoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(username="turista", password="clave12345")
        cls.visitante = VisitanteMetrica.objects.create(origen=OrigenDato.REAL, primera_visita=date(2026, 6, 1))

    def test_visitante_anonimo_real_es_valido(self):
        v = VisitanteMetrica(origen=OrigenDato.REAL, primera_visita=date(2026, 6, 1))
        v.full_clean()
        self.assertIsInstance(v.uuid, uuid.UUID)

    def test_uuid_unico(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            VisitanteMetrica.objects.create(uuid=self.visitante.uuid, origen=OrigenDato.REAL, primera_visita=date(2026, 6, 1))

    def test_visitante_registrado_con_usuario(self):
        VisitanteMetrica(
            origen=OrigenDato.REAL, es_registrado=True, usuario=self.usuario, primera_visita=date(2026, 6, 3),
        ).full_clean()

    def test_visitante_no_guarda_pertenencia_a_muestra(self):
        self.assertNotIn("fecha_alta_muestra", {f.name for f in VisitanteMetrica._meta.get_fields()})

    def test_visitante_solo_real(self):
        VisitanteMetrica(origen=OrigenDato.REAL, primera_visita=date(2026, 6, 1)).full_clean()
        for origen in (OrigenDato.SIMULADO, OrigenDato.GA4):
            with self.subTest(origen=origen), self.assertRaises(ValidationError):
                VisitanteMetrica(origen=origen, primera_visita=date(2026, 6, 1)).full_clean()

    def test_origen_por_defecto_es_real(self):
        self.assertEqual(VisitanteMetrica(primera_visita=date(2026, 6, 1)).origen, OrigenDato.REAL)

    def test_reglas_de_coherencia_del_visitante(self):
        invalidos = (
            dict(origen=OrigenDato.REAL, es_registrado=False, usuario=self.usuario),
        )
        for extra in invalidos:
            v = VisitanteMetrica(primera_visita=date(2026, 6, 1), **extra)
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                v.full_clean()

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_checks_del_visitante_en_bd(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            VisitanteMetrica.objects.create(
                origen=OrigenDato.REAL, es_registrado=False, usuario=self.usuario, primera_visita=date(2026, 6, 1),
            )
        for origen in (OrigenDato.SIMULADO, OrigenDato.GA4):
            with self.subTest(origen=origen), self.assertRaises(IntegrityError), transaction.atomic():
                VisitanteMetrica.objects.create(origen=origen, primera_visita=date(2026, 6, 1))

    def test_borrar_usuario_no_borra_el_visitante(self):
        v = VisitanteMetrica.objects.create(
            origen=OrigenDato.REAL, es_registrado=True, usuario=self.usuario, primera_visita=date(2026, 6, 1),
        )
        self.usuario.delete()
        v.refresh_from_db()
        self.assertIsNone(v.usuario)

    def sesion(self, **extra):
        datos = dict(
            visitante=self.visitante, origen=OrigenDato.REAL, fecha=date(2026, 6, 1),
            inicio=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc), paginas_vistas=1,
            fuente=FuenteTrafico.DIRECTO, dispositivo=DispositivoAcceso.MOVIL,
        )
        datos.update(extra)
        return SesionMetrica(**datos)

    def test_sesion_valida_y_rebote_derivado(self):
        s = self.sesion()
        s.full_clean()
        self.assertTrue(s.es_rebote)
        self.assertFalse(self.sesion(paginas_vistas=2).es_rebote)
        self.assertNotIn("rebote", {f.name for f in SesionMetrica._meta.get_fields()})

    def test_sesion_paginas_y_duracion(self):
        with self.assertRaises(ValidationError):
            self.sesion(paginas_vistas=0).full_clean()
        with self.assertRaises(ValidationError):
            self.sesion(duracion_seg=-1).full_clean()

    def test_sesion_choices_y_fin(self):
        with self.assertRaises(ValidationError):
            self.sesion(fuente="X").full_clean()
        with self.assertRaises(ValidationError):
            self.sesion(dispositivo="X").full_clean()
        with self.assertRaises(ValidationError):
            self.sesion(fin=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)).full_clean()

    def test_sesion_solo_real(self):
        self.sesion(origen=OrigenDato.REAL).full_clean()
        for origen in (OrigenDato.SIMULADO, OrigenDato.GA4):
            with self.subTest(origen=origen), self.assertRaises(ValidationError):
                self.sesion(origen=origen).full_clean()

    def test_sesion_origen_debe_coincidir_con_el_visitante(self):
        # Defensa que subsiste aunque todo hecho sea REAL: se prueba clean() directamente.
        with self.assertRaises(ValidationError) as ctx:
            self.sesion(origen=OrigenDato.GA4).clean()
        self.assertIn("origen", ctx.exception.message_dict)
        self.sesion().clean()

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_sesion_solo_real_en_bd(self):
        for origen in (OrigenDato.SIMULADO, OrigenDato.GA4):
            with self.subTest(origen=origen), self.assertRaises(IntegrityError), transaction.atomic():
                self.sesion(origen=origen).save()

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_sesion_check_paginas_en_bd(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.sesion(paginas_vistas=0).save()

    def evento(self, **extra):
        datos = dict(
            visitante=self.visitante, origen=OrigenDato.REAL, tipo=TipoInteraccion.CHATBOT_CONSULTA,
            fecha=date(2026, 6, 1),
        )
        datos.update(extra)
        return EventoMetrica(**datos)

    def test_evento_valido_sin_click_id(self):
        self.evento().full_clean()
        self.evento().save()
        self.evento().save()  # varios NULL conviven en el índice único
        self.assertEqual(EventoMetrica.objects.filter(click_id__isnull=True).count(), 2)

    def test_click_id_idempotente(self):
        click = uuid.uuid4()
        self.evento(click_id=click).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.evento(click_id=click).save()
        with self.assertRaises(ValidationError):
            self.evento(click_id=click).full_clean()

    def test_evento_solo_real(self):
        self.evento(origen=OrigenDato.REAL).full_clean()
        for origen in (OrigenDato.SIMULADO, OrigenDato.GA4):
            with self.subTest(origen=origen), self.assertRaises(ValidationError):
                self.evento(origen=origen).full_clean()

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_evento_solo_real_en_bd(self):
        for origen in (OrigenDato.SIMULADO, OrigenDato.GA4):
            with self.subTest(origen=origen), self.assertRaises(IntegrityError), transaction.atomic():
                self.evento(origen=origen).save()

    def test_evento_tipo_invalido(self):
        with self.assertRaises(ValidationError):
            self.evento(tipo="scroll").full_clean()

    def test_evento_meta_pequena_y_objeto(self):
        self.evento(meta={"via": "iniciar_ruta", "resultado": "ok"}).full_clean()
        with self.assertRaises(ValidationError):
            self.evento(meta={"texto": "x" * 600}).full_clean()
        with self.assertRaises(ValidationError):
            self.evento(meta=["no", "objeto"]).full_clean()

    def test_evento_coherencia_con_sesion(self):
        s = self.sesion()
        s.save()
        self.evento(sesion=s).full_clean()
        with self.assertRaises(ValidationError) as ctx:
            self.evento(sesion=s, origen=OrigenDato.GA4).clean()  # defensa propia de clean()
        self.assertIn("origen", ctx.exception.message_dict)
        otro = VisitanteMetrica.objects.create(origen=OrigenDato.REAL, primera_visita=date(2026, 6, 1))
        with self.assertRaises(ValidationError):
            self.evento(sesion=s, visitante=otro).full_clean()

    def test_evento_sobrevive_al_borrado_de_la_sesion(self):
        s = self.sesion()
        s.save()
        e = self.evento(sesion=s)
        e.save()
        s.delete()
        e.refresh_from_db()
        self.assertIsNone(e.sesion)
