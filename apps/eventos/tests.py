import re
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.eventos.forms import PromocionarEventoForm, ReportarProblemaEventoForm
from apps.eventos.models import (
    CategoriaEvento,
    Evento,
    RecomendacionEvento,
    TagExperiencia,
    _ocurrencia_relativa_desde,
    ocurrencia_anual_relevante,
    ocurrencia_pascua_relevante,
    ocurrencia_relativa_relevante,
    pascua,
)
from apps.eventos.views import _ventana_paginas, celebracion_resumen, fecha_card, ubicacion_card_texto
from apps.ubicaciones.models import Departamento, Distrito, Localidad, Provincia


class EventosTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        cls.categoria = CategoriaEvento.objects.create(nombre="Festividades", slug="festividades")
        cls.departamento = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        cls.provincia = Provincia.objects.create(
            departamento=cls.departamento, nombre_oficial="Huánuco", slug="huanuco"
        )
        cls.distrito = Distrito.objects.create(
            provincia=cls.provincia, nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101"
        )
        cls.distrito_otro = Distrito.objects.create(
            provincia=cls.provincia, nombre_oficial="Amarilis", slug="amarilis", codigo_inei="100102"
        )

    def evento_base(self, **overrides):
        data = dict(
            categoria_principal=self.categoria,
            nombre="Evento de prueba",
            slug=f"evento-prueba-{Evento.objects.count()}",
            tipo_fecha="exacta",
            fecha_inicio=date(2026, 8, 15),
            tipo_horario="exacta",
            hora_inicio=time(10, 0),
            tipo_costo="gratis",
            tipo_ubicacion="lugar_exacto",
            distrito=self.distrito,
        )
        data.update(overrides)
        return Evento(**data)


class EventoValidacionesTests(EventosTestDataMixin, TestCase):

    def test_exacta_con_fecha_fin_es_invalido(self):
        evento = self.evento_base(fecha_inicio=date(2026, 8, 15), fecha_fin=date(2026, 8, 17))
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("fecha_fin", ctx.exception.message_dict)

    def test_rango_sin_fecha_fin_es_invalido(self):
        evento = self.evento_base(tipo_fecha="rango", fecha_inicio=date(2026, 8, 15), fecha_fin=None)
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("fecha_fin", ctx.exception.message_dict)

    def test_rango_valido(self):
        evento = self.evento_base(tipo_fecha="rango", fecha_inicio=date(2026, 8, 15), fecha_fin=date(2026, 8, 20))
        evento.full_clean()

    def test_anual_fija_con_fecha_inicio_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="anual_fija", fecha_inicio=date(2026, 8, 15),
            dia_inicio_anual=15, mes_inicio_anual=8,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("tipo_fecha", ctx.exception.message_dict)

    def test_anual_fija_dia_mes_invalido(self):
        evento = self.evento_base(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=31, mes_inicio_anual=4,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("dia_inicio_anual", ctx.exception.message_dict)

    def test_anual_fija_29_febrero_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=29, mes_inicio_anual=2,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("dia_inicio_anual", ctx.exception.message_dict)

    def test_anual_fija_fin_parcial_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12,
            dia_fin_anual=19, mes_fin_anual=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("dia_fin_anual", ctx.exception.message_dict)

    def test_anual_fija_valido_cruzando_anio(self):
        evento = self.evento_base(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12,
            dia_fin_anual=19, mes_fin_anual=1,
        )
        evento.full_clean()

    def test_anual_fija_de_un_solo_dia_es_valido(self):
        evento = self.evento_base(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=15, mes_inicio_anual=8,
        )
        evento.full_clean()

    def test_mes_aproximado_con_fecha_exacta_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="mes_aproximado", fecha_inicio=date(2027, 8, 1),
            mes_aproximado=8, anio_aproximado=2027,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("tipo_fecha", ctx.exception.message_dict)

    def test_mes_aproximado_valido(self):
        evento = self.evento_base(
            tipo_fecha="mes_aproximado", fecha_inicio=None,
            mes_aproximado=8, anio_aproximado=2027,
        )
        evento.full_clean()

    def test_por_confirmar_con_fecha_es_invalido(self):
        evento = self.evento_base(tipo_fecha="por_confirmar", fecha_inicio=date(2026, 8, 15))
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("tipo_fecha", ctx.exception.message_dict)

    def test_por_confirmar_valido(self):
        evento = self.evento_base(tipo_fecha="por_confirmar", fecha_inicio=None)
        evento.full_clean()

    def test_anual_relativa_sin_ancla_ordenes_1_a_4_son_validos(self):
        for orden in (1, 2, 3, 4):
            evento = self.evento_base(
                tipo_fecha="anual_relativa", fecha_inicio=None,
                orden_semana_relativa=orden, dia_semana_relativa=6, mes_relativa=1,
            )
            evento.full_clean()

    def test_anual_relativa_dia_semana_lunes_cero_es_valido(self):
        evento = self.evento_base(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=2, dia_semana_relativa=0, mes_relativa=9,
        )
        evento.full_clean()

    def test_anual_relativa_con_ancla_orden_1_es_valido(self):
        evento = self.evento_base(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        evento.full_clean()

    def test_anual_relativa_con_ancla_orden_mayor_a_1_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=2, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("orden_semana_relativa", ctx.exception.message_dict)

    def test_anual_relativa_ancla_dia_inexistente_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=4, dia_ancla_relativa=31,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("dia_ancla_relativa", ctx.exception.message_dict)

    def test_pascua_relativa_offset_cero_domingo_resurreccion_es_valido(self):
        evento = self.evento_base(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=0)
        evento.full_clean()

    def test_pascua_relativa_sin_offset_es_invalido(self):
        evento = self.evento_base(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=None)
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("offset_dias_pascua", ctx.exception.message_dict)

    def test_pascua_relativa_con_orden_semana_relativa_residual_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="pascua_relativa", fecha_inicio=None,
            offset_dias_pascua=-2, orden_semana_relativa=1,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("tipo_fecha", ctx.exception.message_dict)

    def test_pascua_relativa_con_dia_semana_relativa_residual_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="pascua_relativa", fecha_inicio=None,
            offset_dias_pascua=-2, dia_semana_relativa=4,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("tipo_fecha", ctx.exception.message_dict)

    def test_pascua_relativa_con_mes_relativa_residual_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="pascua_relativa", fecha_inicio=None,
            offset_dias_pascua=-2, mes_relativa=8,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("tipo_fecha", ctx.exception.message_dict)

    def test_pascua_relativa_con_dia_ancla_relativa_residual_es_invalido(self):
        evento = self.evento_base(
            tipo_fecha="pascua_relativa", fecha_inicio=None,
            offset_dias_pascua=-2, dia_ancla_relativa=15,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("tipo_fecha", ctx.exception.message_dict)

    def test_horario_variable_con_horas_es_invalido(self):
        evento = self.evento_base(tipo_horario="variable", hora_inicio=time(10, 0))
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("hora_inicio", ctx.exception.message_dict)

    def test_pagado_sin_precio_desde_es_invalido(self):
        evento = self.evento_base(tipo_costo="pagado", precio_desde=None)
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("precio_desde", ctx.exception.message_dict)

    def test_gratis_con_precio_es_invalido(self):
        evento = self.evento_base(tipo_costo="gratis", precio_desde=Decimal("20"))
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("precio_desde", ctx.exception.message_dict)

    def test_localidad_fuera_del_distrito_es_invalido(self):
        otra_localidad = Localidad.objects.create(
            distrito=self.distrito_otro, nombre="Otra", slug="otra", tipo="Ciudad"
        )
        evento = self.evento_base(distrito=self.distrito, localidad=otra_localidad)
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("localidad", ctx.exception.message_dict)

    def test_provincia_y_distrito_redundantes_es_invalido(self):
        evento = self.evento_base(distrito=self.distrito, provincia=self.provincia)
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn("provincia", ctx.exception.message_dict)

    def test_ambito_general_sin_territorio_es_valido(self):
        """Sin provincia ni distrito: ámbito regional (toda la Región Huánuco)."""
        evento = self.evento_base(tipo_ubicacion="ambito_general", distrito=None, provincia=None)
        evento.full_clean()

    def test_ambito_general_con_provincia_es_valido(self):
        evento = self.evento_base(tipo_ubicacion="ambito_general", distrito=None, provincia=self.provincia)
        evento.full_clean()

    def test_ambito_general_con_distrito_es_valido(self):
        evento = self.evento_base(tipo_ubicacion="ambito_general", distrito=self.distrito, provincia=None)
        evento.full_clean()


class OcurrenciaAnualRelevanteTests(TestCase):

    def test_cruce_de_anio_en_curso_26_diciembre(self):
        inicio, fin, en_curso = ocurrencia_anual_relevante(24, 12, 19, 1, date(2026, 12, 26))
        self.assertEqual(inicio, date(2026, 12, 24))
        self.assertEqual(fin, date(2027, 1, 19))
        self.assertTrue(en_curso)

    def test_cruce_de_anio_en_curso_10_enero(self):
        inicio, fin, en_curso = ocurrencia_anual_relevante(24, 12, 19, 1, date(2027, 1, 10))
        self.assertEqual(inicio, date(2026, 12, 24))
        self.assertEqual(fin, date(2027, 1, 19))
        self.assertTrue(en_curso)

    def test_cruce_de_anio_proxima_ocurrencia_20_febrero(self):
        inicio, fin, en_curso = ocurrencia_anual_relevante(24, 12, 19, 1, date(2027, 2, 20))
        self.assertEqual(inicio, date(2027, 12, 24))
        self.assertEqual(fin, date(2028, 1, 19))
        self.assertFalse(en_curso)

    def test_evento_anual_de_un_solo_dia_en_curso(self):
        inicio, fin, en_curso = ocurrencia_anual_relevante(15, 8, None, None, date(2026, 8, 15))
        self.assertEqual(inicio, date(2026, 8, 15))
        self.assertEqual(fin, date(2026, 8, 15))
        self.assertTrue(en_curso)

    def test_evento_anual_de_un_solo_dia_proximo(self):
        inicio, fin, en_curso = ocurrencia_anual_relevante(15, 8, None, None, date(2026, 1, 1))
        self.assertEqual(inicio, date(2026, 8, 15))
        self.assertFalse(en_curso)


class OcurrenciaRelativaTests(TestCase):
    """Valores verificados a mano contra los datos reales de festividades de Huánuco."""

    def test_segundo_domingo_de_enero(self):
        esperados = {2026: date(2026, 1, 11), 2027: date(2027, 1, 10), 2028: date(2028, 1, 9), 2029: date(2029, 1, 14)}
        for anio, esperado in esperados.items():
            self.assertEqual(_ocurrencia_relativa_desde(anio, 1, 2, 6), esperado)

    def test_segundo_sabado_de_septiembre(self):
        esperados = {2026: date(2026, 9, 12), 2027: date(2027, 9, 11), 2028: date(2028, 9, 9), 2029: date(2029, 9, 8)}
        for anio, esperado in esperados.items():
            self.assertEqual(_ocurrencia_relativa_desde(anio, 9, 2, 5), esperado)

    def test_dia_de_la_identidad_primer_viernes_despues_del_15_de_agosto(self):
        esperados = {2026: date(2026, 8, 21), 2027: date(2027, 8, 20), 2028: date(2028, 8, 18), 2029: date(2029, 8, 17)}
        for anio, esperado in esperados.items():
            self.assertEqual(_ocurrencia_relativa_desde(anio, 8, 1, 4, dia_ancla=15), esperado)

    def test_relevante_usa_proxima_ocurrencia_cuando_la_del_anio_actual_ya_paso(self):
        inicio, fin, en_curso = ocurrencia_relativa_relevante(1, 4, 8, 15, date(2026, 8, 22))
        self.assertEqual(inicio, date(2027, 8, 20))
        self.assertEqual(fin, date(2027, 8, 20))
        self.assertFalse(en_curso)

    def test_relevante_en_curso_el_mismo_dia(self):
        inicio, fin, en_curso = ocurrencia_relativa_relevante(2, 6, 1, None, date(2026, 1, 11))
        self.assertEqual(inicio, date(2026, 1, 11))
        self.assertTrue(en_curso)


class PascuaTests(TestCase):
    """Fechas verificadas con el algoritmo de Gauss/Meeus contra el calendario litúrgico publicado."""

    def test_domingo_de_pascua_fechas_conocidas(self):
        self.assertEqual(pascua(2024), date(2024, 3, 31))
        self.assertEqual(pascua(2026), date(2026, 4, 5))
        self.assertEqual(pascua(2027), date(2027, 3, 28))

    def test_ocurrencia_pascua_relevante_viernes_santo_2026(self):
        inicio, fin, en_curso = ocurrencia_pascua_relevante(-2, date(2026, 1, 1))
        self.assertEqual(inicio, date(2026, 4, 3))
        self.assertEqual(fin, date(2026, 4, 3))
        self.assertFalse(en_curso)

    def test_ocurrencia_pascua_relevante_domingo_resurreccion_en_curso(self):
        inicio, fin, en_curso = ocurrencia_pascua_relevante(0, date(2026, 4, 5))
        self.assertEqual(inicio, date(2026, 4, 5))
        self.assertTrue(en_curso)


class EventoQuerySetTests(EventosTestDataMixin, TestCase):

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_que_solapan_incluye_evento_exacto_dentro_del_rango(self):
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=date(2026, 8, 22))
        resultado = Evento.objects.que_solapan(date(2026, 8, 20), date(2026, 8, 25))
        self.assertIn(evento, resultado)

    def test_que_solapan_excluye_evento_exacto_fuera_del_rango(self):
        self.crear(tipo_fecha="exacta", fecha_inicio=date(2026, 8, 22))
        resultado = Evento.objects.que_solapan(date(2026, 9, 1), date(2026, 9, 5))
        self.assertEqual(resultado.count(), 0)

    def test_que_solapan_incluye_evento_exacto_en_el_dia_exacto(self):
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=date(2026, 8, 22))
        resultado = Evento.objects.que_solapan(date(2026, 8, 22), date(2026, 8, 22))
        self.assertIn(evento, resultado)

    def test_que_solapan_incluye_anual_fija_cruzando_anio(self):
        evento = self.crear(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12,
            dia_fin_anual=19, mes_fin_anual=1,
        )
        resultado = Evento.objects.que_solapan(date(2027, 1, 5), date(2027, 1, 10))
        self.assertIn(evento, resultado)

    def test_que_solapan_excluye_anual_fija_fuera_de_rango(self):
        self.crear(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12,
            dia_fin_anual=19, mes_fin_anual=1,
        )
        resultado = Evento.objects.que_solapan(date(2027, 3, 1), date(2027, 3, 7))
        self.assertEqual(resultado.count(), 0)

    def test_que_solapan_excluye_mes_aproximado(self):
        self.crear(
            tipo_fecha="mes_aproximado", fecha_inicio=None,
            mes_aproximado=8, anio_aproximado=2026,
        )
        resultado = Evento.objects.que_solapan(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(resultado.count(), 0)

    def test_que_solapan_excluye_por_confirmar(self):
        self.crear(tipo_fecha="por_confirmar", fecha_inicio=None)
        resultado = Evento.objects.que_solapan(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(resultado.count(), 0)

    def test_encadenamiento_conserva_filtros_previos(self):
        evento_activo = self.crear(tipo_fecha="exacta", fecha_inicio=date(2026, 8, 22))
        evento_inactivo = self.crear(tipo_fecha="exacta", fecha_inicio=date(2026, 8, 22), activo=False)
        otra_categoria = CategoriaEvento.objects.create(nombre="Ferias", slug="ferias")
        evento_otra_categoria = self.crear(
            tipo_fecha="exacta", fecha_inicio=date(2026, 8, 22), categoria_principal=otra_categoria,
        )

        resultado = Evento.objects.publicados().filter(
            categoria_principal=self.categoria
        ).que_solapan(date(2026, 8, 20), date(2026, 8, 25))

        self.assertIn(evento_activo, resultado)
        self.assertNotIn(evento_inactivo, resultado)
        self.assertNotIn(evento_otra_categoria, resultado)

    def test_que_solapan_incluye_anual_relativa_en_su_ocurrencia(self):
        evento = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        resultado = Evento.objects.que_solapan(date(2026, 8, 21), date(2026, 8, 21))
        self.assertIn(evento, resultado)

    def test_que_solapan_excluye_anual_relativa_fuera_de_su_ocurrencia(self):
        self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        resultado = Evento.objects.que_solapan(date(2026, 8, 22), date(2026, 8, 25))
        self.assertEqual(resultado.count(), 0)

    def test_que_solapan_incluye_pascua_relativa_en_su_ocurrencia(self):
        evento = self.crear(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=-2)
        resultado = Evento.objects.que_solapan(date(2026, 4, 3), date(2026, 4, 3))
        self.assertIn(evento, resultado)

    def test_encadenamiento_conserva_filtros_previos_con_anual_relativa(self):
        evento_activo = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        evento_inactivo = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None, activo=False,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        resultado = Evento.objects.publicados().que_solapan(date(2026, 8, 21), date(2026, 8, 21))
        self.assertIn(evento_activo, resultado)
        self.assertNotIn(evento_inactivo, resultado)


class EventosVistaTests(EventosTestDataMixin, TestCase):

    def setUp(self):
        self.hoy = timezone.localdate()

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_listado_responde_200(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertEqual(response.status_code, 200)

    def test_filtro_hoy_incluye_evento_de_hoy(self):
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "hoy"})
        self.assertIn(evento, response.context["eventos"])

    def test_filtro_hoy_excluye_evento_de_manana(self):
        self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=1))
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "hoy"})
        self.assertEqual(len(response.context["eventos"]), 0)

    def test_filtro_manana(self):
        manana = self.hoy + timedelta(days=1)
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=manana)
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "manana"})
        self.assertIn(evento, response.context["eventos"])

    def test_filtro_esta_semana(self):
        lunes = self.hoy - timedelta(days=self.hoy.weekday())
        domingo = lunes + timedelta(days=6)
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=domingo)
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "esta_semana"})
        self.assertIn(evento, response.context["eventos"])

    def test_filtro_fin_de_semana(self):
        lunes = self.hoy - timedelta(days=self.hoy.weekday())
        sabado = lunes + timedelta(days=5)
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=sabado)
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "fin_de_semana"})
        self.assertIn(evento, response.context["eventos"])

    def test_fecha_valida_filtra_ese_dia(self):
        objetivo = self.hoy + timedelta(days=10)
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=objetivo)
        otro = self.crear(tipo_fecha="exacta", fecha_inicio=objetivo + timedelta(days=1))
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": objetivo.isoformat()})
        eventos = response.context["eventos"]
        self.assertIn(evento, eventos)
        self.assertNotIn(otro, eventos)

    def test_fecha_invalida_no_produce_500(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": "no-es-una-fecha"})
        self.assertEqual(response.status_code, 200)

    def test_anual_fija_aparece_en_su_ocurrencia_vigente(self):
        evento = self.crear(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12,
            dia_fin_anual=19, mes_fin_anual=1,
        )
        inicio, fin, _en_curso = ocurrencia_anual_relevante(24, 12, 19, 1, self.hoy)
        dentro = inicio + (fin - inicio) // 2
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": dentro.isoformat()})
        self.assertIn(evento, response.context["eventos"])

    def test_anual_fija_no_aparece_fuera_de_su_rango(self):
        evento = self.crear(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12,
            dia_fin_anual=19, mes_fin_anual=1,
        )
        _inicio, fin, _en_curso = ocurrencia_anual_relevante(24, 12, 19, 1, self.hoy)
        fuera = fin + timedelta(days=60)
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": fuera.isoformat()})
        self.assertNotIn(evento, response.context["eventos"])

    def test_mes_aproximado_no_aparece_en_hoy(self):
        self.crear(
            tipo_fecha="mes_aproximado", fecha_inicio=None,
            mes_aproximado=self.hoy.month, anio_aproximado=self.hoy.year,
        )
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "hoy"})
        self.assertEqual(len(response.context["eventos"]), 0)

    def test_por_confirmar_no_aparece_en_hoy(self):
        self.crear(tipo_fecha="por_confirmar", fecha_inicio=None)
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "hoy"})
        self.assertEqual(len(response.context["eventos"]), 0)

    def test_anual_relativa_aparece_en_grupo1_del_listado_general(self):
        evento = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=2, dia_semana_relativa=6, mes_relativa=1,
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertIn(evento, response.context["eventos"])

    def test_pascua_relativa_aparece_en_grupo1_del_listado_general(self):
        evento = self.crear(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=-7)
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertIn(evento, response.context["eventos"])

    def test_selector_7_dias_usa_fecha_como_ancla_cuando_no_hay_semana(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": "2026-12-24"})

        fechas_selector = [dia["fecha"] for dia in response.context["dias_selector"]]
        self.assertIn(date(2026, 12, 24), fechas_selector)

        dia_activo = next(dia for dia in response.context["dias_selector"] if dia["fecha"] == date(2026, 12, 24))
        self.assertTrue(dia_activo["activo"])

        self.assertEqual(response.context["fecha_activa"], date(2026, 12, 24))

    def test_semana_residual_en_url_vieja_se_ignora_como_ancla(self):
        """B2: `semana` ya no es leído por el backend — una URL vieja con
        ?semana= no debe afectar el ancla del selector (?fecha= sigue siendo
        la única fuente real)."""
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"fecha": "2026-12-24", "semana": "2027-01-10"}
        )

        self.assertEqual(response.context["fecha_activa"], date(2026, 12, 24))

        fechas_selector = [dia["fecha"] for dia in response.context["dias_selector"]]
        self.assertIn(date(2026, 12, 24), fechas_selector)
        self.assertNotIn(date(2027, 1, 10), fechas_selector)

    def test_filtro_provincia_encuentra_ambito_provincial(self):
        evento = self.crear(
            tipo_ubicacion="ambito_general", distrito=None, provincia=self.provincia,
            tipo_fecha="exacta", fecha_inicio=self.hoy,
        )
        response = self.client.get(reverse("eventos:listado_eventos"), {"provincia": self.provincia.slug})
        self.assertIn(evento, response.context["eventos"])

    def test_filtro_provincia_encuentra_eventos_via_distrito(self):
        evento = self.crear(distrito=self.distrito, tipo_fecha="exacta", fecha_inicio=self.hoy)
        response = self.client.get(reverse("eventos:listado_eventos"), {"provincia": self.provincia.slug})
        self.assertIn(evento, response.context["eventos"])

    def test_filtro_provincia_incluye_evento_regional(self):
        evento = self.crear(
            tipo_ubicacion="ambito_general", distrito=None, provincia=None,
            tipo_fecha="exacta", fecha_inicio=self.hoy,
        )
        response = self.client.get(reverse("eventos:listado_eventos"), {"provincia": self.provincia.slug})
        self.assertIn(evento, response.context["eventos"])

    def test_filtro_distrito_incluye_evento_regional(self):
        evento = self.crear(
            tipo_ubicacion="ambito_general", distrito=None, provincia=None,
            tipo_fecha="exacta", fecha_inicio=self.hoy,
        )
        response = self.client.get(reverse("eventos:listado_eventos"), {"distrito": self.distrito.slug})
        self.assertIn(evento, response.context["eventos"])

    def test_evento_regional_aparece_sin_filtros_territoriales(self):
        evento = self.crear(
            tipo_ubicacion="ambito_general", distrito=None, provincia=None,
            tipo_fecha="exacta", fecha_inicio=self.hoy,
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertIn(evento, response.context["eventos"])

    def test_filtro_provincia_excluye_evento_de_otra_provincia(self):
        otro_departamento = Departamento.objects.create(nombre_oficial="Pasco", slug="pasco")
        otra_provincia = Provincia.objects.create(
            departamento=otro_departamento, nombre_oficial="Pasco", slug="pasco"
        )
        self.crear(
            tipo_ubicacion="ambito_general", distrito=None, provincia=otra_provincia,
            tipo_fecha="exacta", fecha_inicio=self.hoy,
        )
        response = self.client.get(reverse("eventos:listado_eventos"), {"provincia": self.provincia.slug})
        self.assertEqual(len(response.context["eventos"]), 0)

    def test_distrito_de_otra_provincia_se_ignora_en_vez_de_aplicarse(self):
        """Provincia=Huánuco + Distrito=Rupa-Rupa (que es de Leoncio Prado):
        combinación imposible en la UI. El backend debe ignorar el distrito
        en vez de tratar la combinación como válida (R1.2)."""
        provincia_leoncio_prado = Provincia.objects.create(
            departamento=self.departamento, nombre_oficial="Leoncio Prado", slug="leoncio-prado"
        )
        Distrito.objects.create(
            provincia=provincia_leoncio_prado, nombre_oficial="Rupa-Rupa", slug="rupa-rupa", codigo_inei="100601"
        )
        evento = self.crear(distrito=self.distrito, tipo_fecha="exacta", fecha_inicio=self.hoy)

        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"provincia": self.provincia.slug, "distrito": "rupa-rupa"},
        )

        self.assertEqual(response.context["filtros_activos"]["distrito"], "")
        self.assertIn(evento, response.context["eventos"])

    def test_distrito_en_su_propia_provincia_es_valido(self):
        """Provincia=Leoncio Prado + Distrito=Rupa-Rupa: combinación real, debe filtrar normalmente."""
        provincia_leoncio_prado = Provincia.objects.create(
            departamento=self.departamento, nombre_oficial="Leoncio Prado", slug="leoncio-prado"
        )
        distrito_rupa_rupa = Distrito.objects.create(
            provincia=provincia_leoncio_prado, nombre_oficial="Rupa-Rupa", slug="rupa-rupa", codigo_inei="100601"
        )
        evento = self.crear(distrito=distrito_rupa_rupa, tipo_fecha="exacta", fecha_inicio=self.hoy)
        otro = self.crear(distrito=self.distrito, tipo_fecha="exacta", fecha_inicio=self.hoy)

        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"provincia": provincia_leoncio_prado.slug, "distrito": "rupa-rupa"},
        )

        self.assertEqual(response.context["filtros_activos"]["distrito"], "rupa-rupa")
        self.assertIn(evento, response.context["eventos"])
        self.assertNotIn(otro, response.context["eventos"])

    def test_distrito_inexistente_se_ignora(self):
        evento = self.crear(distrito=self.distrito, tipo_fecha="exacta", fecha_inicio=self.hoy)
        response = self.client.get(reverse("eventos:listado_eventos"), {"distrito": "no-existe"})
        self.assertEqual(response.context["filtros_activos"]["distrito"], "")
        self.assertIn(evento, response.context["eventos"])

    def test_distrito_incompatible_no_se_arrastra_en_enlaces_de_navegacion(self):
        """El ?distrito= descartado no debe reaparecer en los enlaces de
        quick filters/selector de días/paginación: si no se corrige `get`
        junto con `distrito_slug`, cada click seguiría re-enviando la
        combinación imposible (aunque el backend la ignore otra vez)."""
        provincia_leoncio_prado = Provincia.objects.create(
            departamento=self.departamento, nombre_oficial="Leoncio Prado", slug="leoncio-prado"
        )
        Distrito.objects.create(
            provincia=provincia_leoncio_prado, nombre_oficial="Rupa-Rupa", slug="rupa-rupa", codigo_inei="100601"
        )
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"provincia": self.provincia.slug, "distrito": "rupa-rupa"},
        )
        self.assertNotIn("distrito=rupa-rupa", response.context["querystrings_cuando"]["hoy"])
        self.assertNotIn("distrito=rupa-rupa", response.context["querystring_paginacion"])

    def test_url_limpia_no_conserva_filtros(self):
        con_filtros = self.client.get(
            reverse("eventos:listado_eventos"),
            {"categoria": self.categoria.slug, "distrito": self.distrito.slug, "cuando": "hoy"},
        )
        self.assertTrue(con_filtros.context["hay_filtros_activos"])

        limpio = self.client.get(reverse("eventos:listado_eventos"))
        self.assertFalse(limpio.context["hay_filtros_activos"])
        self.assertEqual(limpio.context["filtros_activos"]["categoria"], "")
        self.assertEqual(limpio.context["filtros_activos"]["distrito"], "")
        self.assertEqual(limpio.context["cuando_activo"], "")

    def test_boton_limpiar_filtros_solo_aparece_con_filtros_activos(self):
        """R3/sección 14: 'Limpiar' vive dentro de la cabecera del propio
        contenedor de filtros (`ev-filtros__header`), no flotando fuera."""
        sin_filtros = self.client.get(reverse("eventos:listado_eventos"))
        self.assertNotContains(sin_filtros, "ev-filtros__limpiar")

        con_filtros = self.client.get(reverse("eventos:listado_eventos"), {"categoria": self.categoria.slug})
        self.assertContains(con_filtros, "ev-filtros__limpiar")
        self.assertContains(con_filtros, "ev-filtros__header")

    def test_precio_ya_no_aparece_en_el_filtro_publico(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertNotContains(response, "ev-filtro-costo")
        self.assertNotContains(response, ">Precio<")

    def test_experiencia_se_presenta_como_chips(self):
        TagExperiencia.objects.create(nombre="Chips test", slug="chips-test")
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, "ev-chip")
        # El checkbox real sigue existiendo (accesible), solo se oculta visualmente.
        self.assertContains(response, 'type="checkbox" name="tags" value="chips-test"')

    def test_sheet_mobile_es_bottom_sheet_no_fullscreen(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, "offcanvas-bottom")
        self.assertNotContains(response, "offcanvas-fullscreen")

    def test_contador_filtros_activos_no_cuenta_page_ni_semana(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"categoria": self.categoria.slug, "semana": (self.hoy + timedelta(days=7)).isoformat(), "page": 1},
        )
        self.assertEqual(response.context["cantidad_filtros_activos"], 1)

    def test_contador_filtros_activos_cuenta_fecha_y_cuando_como_un_solo_filtro(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"cuando": "hoy"})
        self.assertEqual(response.context["cantidad_filtros_activos"], 1)

    def test_categorias_secundarias_no_duplican_eventos(self):
        secundaria_1 = CategoriaEvento.objects.create(nombre="Gastronomía test", slug="gastronomia-test")
        secundaria_2 = CategoriaEvento.objects.create(nombre="Música test", slug="musica-test")
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        evento.categorias_secundarias.add(secundaria_1, secundaria_2)

        response = self.client.get(reverse("eventos:listado_eventos"), {"categoria": self.categoria.slug})
        eventos = list(response.context["eventos"])
        self.assertEqual(eventos.count(evento), 1)

    def test_tags_no_duplican_eventos(self):
        tag_1 = TagExperiencia.objects.create(nombre="Familias test", slug="familias-test")
        tag_2 = TagExperiencia.objects.create(nombre="Aventura test", slug="aventura-test")
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        evento.tags_experiencia.add(tag_1, tag_2)

        response = self.client.get(
            reverse("eventos:listado_eventos"), {"tags": ["familias-test", "aventura-test"]}
        )
        eventos = list(response.context["eventos"])
        self.assertEqual(eventos.count(evento), 1)

    def test_filtros_combinados(self):
        evento = self.crear(
            tipo_fecha="exacta", fecha_inicio=self.hoy, distrito=self.distrito, categoria_principal=self.categoria,
        )
        otro = self.crear(
            tipo_fecha="exacta", fecha_inicio=self.hoy, distrito=self.distrito_otro, categoria_principal=self.categoria,
        )
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"cuando": "hoy", "distrito": self.distrito.slug, "categoria": self.categoria.slug},
        )
        eventos = response.context["eventos"]
        self.assertIn(evento, eventos)
        self.assertNotIn(otro, eventos)

    def test_paginacion_6_por_pagina(self):
        for i in range(12):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i))
        response = self.client.get(reverse("eventos:listado_eventos"))
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.paginator.per_page, 6)
        self.assertEqual(len(page_obj.object_list), 6)

    def test_paginacion_pagina_2_conserva_filtros_get(self):
        for i in range(8):
            self.crear(
                tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i),
                distrito=self.distrito, categoria_principal=self.categoria,
            )
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"distrito": self.distrito.slug, "categoria": self.categoria.slug, "page": 2},
        )
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.number, 2)
        self.assertEqual(len(page_obj.object_list), 2)
        qs = response.context["querystring_paginacion"]
        self.assertIn(f"distrito={self.distrito.slug}", qs)
        self.assertIn(f"categoria={self.categoria.slug}", qs)
        self.assertNotIn("page=", qs)

    def test_filtros_se_conservan_en_querystring_de_paginacion(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"categoria": self.categoria.slug, "provincia": self.provincia.slug}
        )
        qs = response.context["querystring_paginacion"]
        self.assertIn(f"categoria={self.categoria.slug}", qs)
        self.assertIn(f"provincia={self.provincia.slug}", qs)

    def test_tags_multiples_se_preservan_en_querystring_de_paginacion(self):
        tag_1 = TagExperiencia.objects.create(nombre="Familias pag", slug="familias-pag")
        tag_2 = TagExperiencia.objects.create(nombre="Aventura pag", slug="aventura-pag")
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"tags": [tag_1.slug, tag_2.slug]},
        )
        qs = response.context["querystring_paginacion"]
        self.assertIn(f"tags={tag_1.slug}", qs)
        self.assertIn(f"tags={tag_2.slug}", qs)

    def test_pagina_1_de_2_primera_y_anterior_disabled(self):
        """Homologación con Establecimientos (R74 paginador): 6 controles
        siempre presentes, « y ‹ deshabilitados en la primera página."""
        for i in range(8):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i))
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(
            response,
            '<span class="page-link" aria-disabled="true" aria-label="Primera página">&laquo;</span>',
        )
        self.assertContains(
            response,
            '<span class="page-link" aria-disabled="true" aria-label="Página anterior">&lsaquo;</span>',
        )
        self.assertContains(response, 'aria-label="Página siguiente"')
        self.assertContains(response, 'aria-label="Última página"')

    def test_pagina_2_de_2_siguiente_y_ultima_disabled(self):
        for i in range(8):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i))
        response = self.client.get(reverse("eventos:listado_eventos"), {"page": 2})
        self.assertContains(
            response,
            '<span class="page-link" aria-disabled="true" aria-label="Página siguiente">&rsaquo;</span>',
        )
        self.assertContains(
            response,
            '<span class="page-link" aria-disabled="true" aria-label="Última página">&raquo;</span>',
        )
        self.assertContains(response, 'aria-label="Primera página"')
        self.assertContains(response, 'aria-label="Página anterior"')

    def test_primera_pagina_enlaza_a_page_1_preservando_filtros(self):
        for i in range(20):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-primera-{i}")
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"categoria": self.categoria.slug, "page": 3},
        )
        self.assertContains(
            response, f"categoria={self.categoria.slug}&page=1\" aria-label=\"Primera página\"",
        )

    def test_ultima_pagina_enlaza_al_total_de_paginas(self):
        for i in range(20):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-ultima-{i}")
        response = self.client.get(reverse("eventos:listado_eventos"))
        num_pages = response.context["page_obj"].paginator.num_pages
        self.assertContains(response, f"&page={num_pages}\" aria-label=\"Última página\"")

    def test_pagina_activa_tiene_aria_current(self):
        for i in range(8):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i))
        response = self.client.get(reverse("eventos:listado_eventos"), {"page": 2})
        self.assertContains(response, 'class="page-item page-number active" aria-current="page"')

    def test_muchas_paginas_limita_la_ventana_de_numeros(self):
        """No renderiza un número por cada página (R26): mismo criterio ya
        usado en Establecimientos, ventana de +/-2 alrededor de la actual."""
        for i in range(120):  # 120 eventos / 6 por página = 20 páginas
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-ventana-{i}")
        response = self.client.get(reverse("eventos:listado_eventos"), {"page": 10})
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 20)
        numeros_renderizados = response.content.decode().count('class="page-item page-number')
        self.assertLess(numeros_renderizados, 10)

    def _numeros_solo_desktop(self, response):
        return {p["numero"] for p in response.context["paginas_paginador"] if p["solo_desktop"]}

    def _numeros_totales(self, response):
        return [p["numero"] for p in response.context["paginas_paginador"]]

    def test_ventana_desktop_conserva_hasta_5_numeros_con_12_paginas(self):
        """R7/R31 (V2.1): desktop no cambia — sigue mostrando hasta 5
        números, mismo comportamiento ya homologado con Establecimientos."""
        for i in range(72):  # 72 / 6 por página = 12 páginas
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-desktop-{i}")
        casos = {1: [1, 2, 3, 4, 5], 6: [4, 5, 6, 7, 8], 12: [8, 9, 10, 11, 12]}
        for pagina, esperado in casos.items():
            response = self.client.get(reverse("eventos:listado_eventos"), {"page": pagina})
            self.assertEqual(self._numeros_totales(response), esperado, msg=f"página {pagina}")

    def test_ventana_mobile_maximo_3_numeros_con_12_paginas(self):
        """R5/R19 (V2.1): mobile limita a 3 números, centrados en la
        página actual, con primera/última página manejadas sin inventar
        números inexistentes."""
        for i in range(72):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-mobile-{i}")
        casos = {
            1: [1, 2, 3],
            2: [1, 2, 3],
            3: [2, 3, 4],
            6: [5, 6, 7],
            10: [9, 10, 11],
            11: [10, 11, 12],
            12: [10, 11, 12],
        }
        for pagina, esperado in casos.items():
            response = self.client.get(reverse("eventos:listado_eventos"), {"page": pagina})
            todos = response.context["paginas_paginador"]
            visibles_mobile = sorted(p["numero"] for p in todos if not p["solo_desktop"])
            self.assertEqual(visibles_mobile, esperado, msg=f"página {pagina}")
            # Máximo 7 controles mobile: « ‹ + hasta 3 números + › » (R2/R30).
            self.assertLessEqual(len(esperado), 3)

    def test_pagina_activa_nunca_queda_marcada_solo_desktop(self):
        for i in range(72):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-activa-{i}")
        for pagina in (1, 6, 12):
            response = self.client.get(reverse("eventos:listado_eventos"), {"page": pagina})
            activa = next(p for p in response.context["paginas_paginador"] if p["numero"] == pagina)
            self.assertFalse(activa["solo_desktop"], msg=f"página {pagina}")

    def test_pagina_1_de_2_ventana_mobile_no_inventa_numero_3(self):
        """R15: con solo 2 páginas reales, la ventana mobile (máx. 3) no
        debe rellenar con un tercer número inexistente."""
        for i in range(8):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i))
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertEqual(self._numeros_totales(response), [1, 2])
        self.assertEqual(self._numeros_solo_desktop(response), set())

    def test_1_de_3_paginas_todas_visibles_en_mobile_y_desktop(self):
        """R16-R18: con exactamente 3 páginas, ninguna queda marcada
        solo-desktop en ninguna de las tres, sea cual sea la activa."""
        for i in range(14):  # 14 / 6 = 3 páginas
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-tres-{i}")
        for pagina in (1, 2, 3):
            response = self.client.get(reverse("eventos:listado_eventos"), {"page": pagina})
            self.assertEqual(self._numeros_totales(response), [1, 2, 3], msg=f"página {pagina}")
            self.assertEqual(self._numeros_solo_desktop(response), set(), msg=f"página {pagina}")

    def test_numero_solo_desktop_lleva_la_clase_css_de_ocultamiento_mobile(self):
        for i in range(72):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i), slug=f"evento-clase-{i}")
        response = self.client.get(reverse("eventos:listado_eventos"), {"page": 6})
        self.assertContains(response, "page-number--solo-desktop")


    def test_orden_general_de_los_3_grupos(self):
        futuro = self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=5))
        en_curso = self.crear(
            tipo_fecha="rango",
            fecha_inicio=self.hoy - timedelta(days=2),
            fecha_fin=self.hoy + timedelta(days=2),
        )
        aproximado = self.crear(
            tipo_fecha="mes_aproximado", fecha_inicio=None,
            mes_aproximado=12, anio_aproximado=self.hoy.year + 1,
        )
        confirmar = self.crear(tipo_fecha="por_confirmar", fecha_inicio=None)

        response = self.client.get(reverse("eventos:listado_eventos"))
        eventos = list(response.context["eventos"])

        self.assertLess(eventos.index(en_curso), eventos.index(futuro))
        self.assertLess(eventos.index(futuro), eventos.index(aproximado))
        self.assertLess(eventos.index(aproximado), eventos.index(confirmar))


class VentanaPaginasTests(TestCase):
    """Tests unitarios de `_ventana_paginas` (paginador V2.1, sección 6):
    algoritmo puro, sin necesidad de eventos/DB — casos deterministas de
    la sección 5/19/20 del encargo, para mobile (tamano=3) y desktop
    (tamano=5)."""

    def test_pocas_paginas_devuelve_todas_sin_inventar(self):
        self.assertEqual(_ventana_paginas(1, 1, 3), [1])
        self.assertEqual(_ventana_paginas(1, 2, 3), [1, 2])
        self.assertEqual(_ventana_paginas(2, 2, 5), [1, 2])
        self.assertEqual(_ventana_paginas(2, 3, 3), [1, 2, 3])

    def test_mobile_tamano_3_con_12_paginas(self):
        casos = {
            1: [1, 2, 3], 2: [1, 2, 3], 3: [2, 3, 4],
            6: [5, 6, 7], 10: [9, 10, 11], 11: [10, 11, 12], 12: [10, 11, 12],
        }
        for actual, esperado in casos.items():
            self.assertEqual(_ventana_paginas(actual, 12, 3), esperado, msg=f"página {actual}")

    def test_desktop_tamano_5_con_12_paginas(self):
        casos = {1: [1, 2, 3, 4, 5], 6: [4, 5, 6, 7, 8], 12: [8, 9, 10, 11, 12]}
        for actual, esperado in casos.items():
            self.assertEqual(_ventana_paginas(actual, 12, 5), esperado, msg=f"página {actual}")

    def test_ventana_mobile_siempre_contenida_en_ventana_desktop(self):
        """Precondición de la que depende el template (una sola lista,
        marcada con `solo_desktop`): todo número de la ventana mobile debe
        existir también en la ventana desktop, para cualquier página y
        cualquier total de páginas."""
        for total in range(1, 21):
            for actual in range(1, total + 1):
                mobil = set(_ventana_paginas(actual, total, 3))
                desktop = set(_ventana_paginas(actual, total, 5))
                self.assertTrue(mobil.issubset(desktop), msg=f"total={total} actual={actual}")


class FechaCardRelativaTests(EventosTestDataMixin, TestCase):
    """La agenda pública debe mostrar la ocurrencia calculada (día y mes reales), no solo la
    regla — pero nunca el año, ni siquiera cuando la ocurrencia calculada "rueda" al año
    siguiente (R28: el usuario ya sabe qué año es por el filtro que aplicó)."""

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_rollover_anual_usa_la_proxima_ocurrencia_no_la_del_anio_actual(self):
        evento = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        resultado = fecha_card(evento, date(2026, 8, 22))
        self.assertEqual(resultado["principal"], "20 de agosto")
        self.assertEqual(resultado["nota"], "Primer viernes después del 15 de agosto · Cada año")

    def test_segundo_domingo_de_enero_muestra_dia_y_mes_sin_anio(self):
        evento = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=2, dia_semana_relativa=6, mes_relativa=1,
        )
        resultado = fecha_card(evento, date(2026, 1, 1))
        self.assertEqual(resultado["principal"], "11 de enero")
        self.assertEqual(resultado["nota"], "Segundo domingo de enero · Cada año")

    def test_pascua_relativa_muestra_dia_y_mes_sin_anio(self):
        evento = self.crear(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=-2)
        resultado = fecha_card(evento, date(2026, 1, 1))
        self.assertEqual(resultado["principal"], "3 de abril")
        self.assertEqual(resultado["nota"], "Viernes Santo · Fecha móvil")


class CelebracionResumenTests(EventosTestDataMixin, TestCase):
    """R74 (secciones 29-40): 'Se celebra:' en el modal explica CÓMO se
    celebra normalmente la festividad (la regla), nunca una ocurrencia/año
    calculado — a diferencia de fecha_card (ocurrencia contextual para la
    card, R28 sin año) y del extinto fecha_modal_texto (año + regla). Por
    eso celebracion_resumen no recibe `hoy` ni `rango`: el mismo evento
    produce siempre el mismo texto sin importar la fecha de hoy (B4,
    sección 39 — ya no se exige igualdad literal con fecha_card)."""

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_exacta_muestra_fecha_con_anio(self):
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=date(2026, 9, 12))
        self.assertEqual(celebracion_resumen(evento), "12 de septiembre de 2026")

    def test_rango_mismo_mes(self):
        evento = self.crear(
            tipo_fecha="rango", fecha_inicio=date(2026, 9, 12), fecha_fin=date(2026, 9, 15),
        )
        self.assertEqual(celebracion_resumen(evento), "12 – 15 de septiembre de 2026")

    def test_rango_meses_distintos(self):
        evento = self.crear(
            tipo_fecha="rango", fecha_inicio=date(2026, 9, 28), fecha_fin=date(2026, 10, 2),
        )
        self.assertEqual(celebracion_resumen(evento), "28 de septiembre – 2 de octubre de 2026")

    def test_anual_fija_un_solo_dia_no_muestra_anio(self):
        evento = self.crear(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=6,
        )
        self.assertEqual(celebracion_resumen(evento), "Cada 24 de junio")

    def test_anual_fija_rango_cruzando_anio_no_repite_cada_anio(self):
        evento = self.crear(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12, dia_fin_anual=19, mes_fin_anual=1,
        )
        self.assertEqual(celebracion_resumen(evento), "24 de diciembre – 19 de enero")

    def test_anual_relativa_nth_weekday_del_mes(self):
        evento = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=2, dia_semana_relativa=5, mes_relativa=9,
        )
        self.assertEqual(celebracion_resumen(evento), "Cada segundo sábado de septiembre")

    def test_anual_relativa_primer_dia_despues_del_ancla(self):
        evento = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        self.assertEqual(celebracion_resumen(evento), "Cada primer viernes después del 15 de agosto")

    def test_pascua_relativa_jueves_santo(self):
        evento = self.crear(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=-3)
        self.assertEqual(celebracion_resumen(evento), "Cada Jueves Santo")

    def test_pascua_relativa_domingo_resurreccion(self):
        evento = self.crear(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=0)
        self.assertEqual(celebracion_resumen(evento), "Cada Domingo de Resurrección")

    def test_mes_aproximado(self):
        evento = self.crear(
            tipo_fecha="mes_aproximado", fecha_inicio=None, mes_aproximado=9, anio_aproximado=2026,
        )
        self.assertEqual(celebracion_resumen(evento), "Durante septiembre de 2026")

    def test_por_confirmar(self):
        evento = self.crear(tipo_fecha="por_confirmar", fecha_inicio=None)
        self.assertEqual(celebracion_resumen(evento), "Fecha por confirmar")

    def test_no_depende_de_hoy_ni_de_filtro_temporal(self):
        """El mismo evento produce el mismo texto sin importar cuándo se
        consulte: a diferencia de fecha_card/estado_card, no hay `hoy` que
        pasar (B4, sección 39)."""
        evento = self.crear(
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )
        self.assertEqual(celebracion_resumen(evento), "Cada primer viernes después del 15 de agosto")

    def test_sin_datos_de_fecha_devuelve_cadena_vacia(self):
        """Evento a medio configurar (aún inválido para full_clean): la
        función no debe reventar, solo devolver "" como fecha_card."""
        evento = self.evento_base(tipo_fecha="anual_relativa", fecha_inicio=None)
        self.assertEqual(celebracion_resumen(evento), "")


class UbicacionCardTests(EventosTestDataMixin, TestCase):
    """Un evento de ámbito regional no debe mostrarse con ubicación vacía."""

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_regional_sin_descripcion_muestra_region_huanuco(self):
        evento = self.crear(tipo_ubicacion="ambito_general", distrito=None, provincia=None)
        self.assertEqual(ubicacion_card_texto(evento), "Región Huánuco")

    def test_regional_con_descripcion_la_complementa(self):
        descripcion = (
            "Celebración de alcance regional desarrollada en las once provincias de Huánuco. "
            "Las actividades y espacios participantes pueden variar según la programación de cada año."
        )
        evento = self.crear(
            tipo_ubicacion="ambito_general", distrito=None, provincia=None,
            descripcion_ubicacion=descripcion,
        )
        self.assertEqual(ubicacion_card_texto(evento), f"Región Huánuco — {descripcion}")

    def test_ambito_provincial_no_usa_texto_regional(self):
        evento = self.crear(tipo_ubicacion="ambito_general", distrito=None, provincia=self.provincia)
        self.assertEqual(ubicacion_card_texto(evento), "Provincia de Huánuco")


class EventosModalDatosTests(EventosTestDataMixin, TestCase):

    def setUp(self):
        self.hoy = timezone.localdate()

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_datos_modal_no_incluyen_campos_internos(self):
        self.crear(
            tipo_fecha="exacta", fecha_inicio=self.hoy,
            notas="SECRETO_INTERNO_NOTAS",
            url_fuente="https://fuente-interna.example/pagina",
            fecha_verificacion=self.hoy,
            publico_objetivo="SECRETO_PUBLICO_OBJETIVO",
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = response.context["datos_modal"]
        self.assertEqual(len(datos), 1)

        claves_prohibidas = {"notas", "url_fuente", "fecha_verificacion", "publico_objetivo"}
        self.assertFalse(claves_prohibidas & set(datos[0].keys()))

        contenido = response.content.decode("utf-8")
        self.assertNotIn("SECRETO_INTERNO_NOTAS", contenido)
        self.assertNotIn("fuente-interna.example", contenido)
        self.assertNotIn("SECRETO_PUBLICO_OBJETIVO", contenido)

    def test_datos_modal_solo_incluyen_eventos_de_la_pagina_actual(self):
        for i in range(12):
            self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i))
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertEqual(len(response.context["datos_modal"]), 6)
        self.assertEqual(len(response.context["page_obj"].object_list), 6)

    def test_evento_sin_contexto_cultural_no_rompe_render(self):
        self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy, contexto_cultural="")
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertEqual(response.status_code, 200)

    def test_evento_sin_recomendaciones_no_rompe_render(self):
        self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy, recomendaciones="")
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertEqual(response.status_code, 200)

    def test_evento_sin_galeria_secundaria_no_rompe_render(self):
        self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["datos_modal"][0]["galeria"], [])

    def test_tags_se_serializan_con_nombre_e_icono(self):
        """R74/sección 23: 'Ideal para' pinta chips con el icono OFICIAL del
        módulo (archivo propio, con fallback a Bootstrap Icon) — nunca un
        mapa hardcodeado en JS. datos_modal_para() debe entregar
        {nombre, icono_bootstrap, icono_archivo} por tag, sin disparar una
        query extra por tag (ya prefetched)."""
        con_icono_archivo = TagExperiencia.objects.create(
            nombre="Fotografía test", slug="fotografia", icono_bootstrap="bi-camera-fill"
        )
        solo_bootstrap = TagExperiencia.objects.create(
            nombre="Con bootstrap test", slug="con-bootstrap-test", icono_bootstrap="bi-star-fill"
        )
        sin_icono = TagExperiencia.objects.create(nombre="Sin icono test", slug="sin-icono-test")
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        evento.tags_experiencia.add(con_icono_archivo, solo_bootstrap, sin_icono)

        response = self.client.get(reverse("eventos:listado_eventos"))
        tags = response.context["datos_modal"][0]["tags"]
        por_nombre = {t["nombre"]: t for t in tags}

        # "fotografia" está en ICONOS_EXPERIENCIA (mismo mapeo que el filtro):
        # debe traer un archivo propio bajo static/assets/img/eventos/.
        self.assertIn("fotografia-iconovi.svg", por_nombre["Fotografía test"]["icono_archivo"])
        self.assertEqual(por_nombre["Fotografía test"]["icono_bootstrap"], "bi-camera-fill")

        # Slug sin archivo propio: sin icono_archivo, cae a Bootstrap Icon.
        self.assertEqual(por_nombre["Con bootstrap test"]["icono_archivo"], "")
        self.assertEqual(por_nombre["Con bootstrap test"]["icono_bootstrap"], "bi-star-fill")

        # Sin ningún icono: cadenas vacías, nunca None — el JS usa
        # `if (tag.icono_archivo)` y un valor ausente rompería esa
        # comprobación con KeyError.
        self.assertEqual(por_nombre["Sin icono test"]["icono_archivo"], "")
        self.assertEqual(por_nombre["Sin icono test"]["icono_bootstrap"], "")

    def test_evento_sin_contacto_serializa_campos_vacios(self):
        """Sin organizador/teléfono/whatsapp/correo/redes: el JS del modal
        no debe mostrar enlaces inventados. El backend entrega cadenas
        vacías (nunca None) para que `if (evento.telefono)` etc. en el
        cliente decida correctamente no renderizar nada (R4, sección 27-28)."""
        self.crear(
            tipo_fecha="exacta", fecha_inicio=self.hoy,
            organizador="", telefono="", whatsapp="", correo="",
            sitio_web="", facebook="", instagram="",
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = response.context["datos_modal"][0]
        for campo in ("organizador", "telefono", "whatsapp", "correo", "sitio_web", "facebook", "instagram"):
            self.assertEqual(datos[campo], "")

    def test_anual_fija_se_serializa_con_informacion_de_cada_anio(self):
        self.crear(
            tipo_fecha="anual_fija", fecha_inicio=None,
            dia_inicio_anual=24, mes_inicio_anual=12,
            dia_fin_anual=19, mes_fin_anual=1,
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = response.context["datos_modal"][0]
        self.assertEqual(datos["fecha"]["nota"], "Cada año")
        self.assertTrue(datos["recurrente"])

    def test_evento_regional_serializa_ubicacion_no_vacia(self):
        self.crear(
            tipo_fecha="exacta", fecha_inicio=self.hoy,
            tipo_ubicacion="ambito_general", distrito=None, provincia=None,
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = response.context["datos_modal"][0]
        self.assertEqual(datos["ubicacion"], "Región Huánuco")


class EventosRecomendacionesEstructuradasTests(EventosTestDataMixin, TestCase):
    """R74 (secciones 41-49/61): recomendaciones estructuradas (título +
    descripción + icono), con fallback al texto legado cuando el evento no
    tiene ninguna RecomendacionEvento activa. Mismo patrón que
    apps.turismo.RecomendacionLugarTuristico."""

    def setUp(self):
        self.hoy = timezone.localdate()

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_evento_sin_recomendaciones_estructuradas_usa_fallback_legacy(self):
        evento = self.crear(
            tipo_fecha="exacta", fecha_inicio=self.hoy,
            recomendaciones="Llega con anticipación, el aforo es limitado.",
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = {d["id"]: d for d in response.context["datos_modal"]}[evento.id]
        self.assertEqual(datos["recomendaciones_items"], [])
        self.assertEqual(datos["recomendaciones"], "Llega con anticipación, el aforo es limitado.")

    def test_evento_con_recomendaciones_estructuradas_ignora_el_texto_legacy(self):
        evento = self.crear(
            tipo_fecha="exacta", fecha_inicio=self.hoy,
            recomendaciones="Texto legado que ya no debe mostrarse.",
        )
        RecomendacionEvento.objects.create(
            evento=evento, titulo="Llega temprano", descripcion="El aforo es limitado.",
            icono_bootstrap="bi bi-clock", orden=0,
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = {d["id"]: d for d in response.context["datos_modal"]}[evento.id]
        self.assertEqual(len(datos["recomendaciones_items"]), 1)
        self.assertEqual(datos["recomendaciones_items"][0]["titulo"], "Llega temprano")
        self.assertEqual(datos["recomendaciones"], "")

    def test_cuatro_recomendaciones_respetan_el_orden(self):
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        for i, orden in enumerate([3, 1, 0, 2]):
            RecomendacionEvento.objects.create(
                evento=evento, titulo=f"Recomendación {i}", descripcion="Detalle.", orden=orden,
            )
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = {d["id"]: d for d in response.context["datos_modal"]}[evento.id]
        titulos = [item["titulo"] for item in datos["recomendaciones_items"]]
        self.assertEqual(titulos, ["Recomendación 2", "Recomendación 1", "Recomendación 3", "Recomendación 0"])

    def test_recomendacion_inactiva_no_aparece(self):
        evento = self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        RecomendacionEvento.objects.create(evento=evento, titulo="Activa", descripcion="X", activo=True)
        RecomendacionEvento.objects.create(evento=evento, titulo="Inactiva", descripcion="Y", activo=False)
        response = self.client.get(reverse("eventos:listado_eventos"))
        datos = {d["id"]: d for d in response.context["datos_modal"]}[evento.id]
        titulos = [item["titulo"] for item in datos["recomendaciones_items"]]
        self.assertEqual(titulos, ["Activa"])

    def test_recomendaciones_no_disparan_n_mas_1(self):
        """Mismo criterio que EventosRendimientoTests: el conteo de queries no
        debe crecer ~linealmente con la cantidad de eventos/recomendaciones
        gracias al Prefetch de recomendaciones_detalle."""
        def poblar(cantidad):
            Evento.objects.all().delete()
            for i in range(cantidad):
                evento = self.crear(
                    tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i),
                    slug=f"evento-reco-rendimiento-{i}",
                )
                RecomendacionEvento.objects.create(evento=evento, titulo="Consejo", descripcion="Detalle.")

        def contar_queries():
            with CaptureQueriesContext(connection) as contexto:
                self.client.get(reverse("eventos:listado_eventos"))
            return len(contexto.captured_queries)

        poblar(1)
        queries_1 = contar_queries()

        poblar(6)
        queries_6 = contar_queries()

        self.assertLess(
            queries_6 - queries_1, 5,
            f"Las queries crecieron de {queries_1} a {queries_6} con 6 eventos: posible N+1.",
        )


class RecomendacionEventoIconoTests(EventosTestDataMixin, TestCase):
    """R74 V3: icono_archivo (SVG propio) configurable por recomendación,
    con icono_bootstrap como fallback y validación ligera contra path
    traversal / URLs — sin inspeccionar el filesystem."""

    def setUp(self):
        self.hoy = timezone.localdate()

    def crear_evento(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_nombre_svg_valido_pasa_full_clean(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        reco = RecomendacionEvento(
            evento=evento, titulo="Consulta la programación", descripcion="Detalle.",
            icono_archivo="reco-programacion.svg",
        )
        reco.full_clean()  # no debe lanzar ValidationError

    def test_vacio_es_valido(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        reco = RecomendacionEvento(evento=evento, titulo="Sin SVG", descripcion="Detalle.")
        reco.full_clean()

    def test_rechaza_path_traversal(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        reco = RecomendacionEvento(
            evento=evento, titulo="Malicioso", descripcion="Detalle.",
            icono_archivo="../../etc/passwd.svg",
        )
        with self.assertRaises(ValidationError):
            reco.full_clean()

    def test_rechaza_url_absoluta(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        reco = RecomendacionEvento(
            evento=evento, titulo="URL externa", descripcion="Detalle.",
            icono_archivo="https://evil.example/x.svg",
        )
        with self.assertRaises(ValidationError):
            reco.full_clean()

    def test_rechaza_extension_distinta_de_svg(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        reco = RecomendacionEvento(
            evento=evento, titulo="PNG no permitido", descripcion="Detalle.",
            icono_archivo="reco-programacion.png",
        )
        with self.assertRaises(ValidationError):
            reco.full_clean()

    def test_payload_incluye_url_resuelta_del_icono_archivo(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        RecomendacionEvento.objects.create(
            evento=evento, titulo="Con SVG", descripcion="Detalle.",
            icono_archivo="reco-programacion.svg",
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        item = {d["id"]: d for d in response.context["datos_modal"]}[evento.id]["recomendaciones_items"][0]
        self.assertTrue(item["icono_archivo"].endswith("assets/img/eventos/reco-programacion.svg"))

    def test_payload_sin_icono_archivo_queda_vacio_y_conserva_bootstrap(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        RecomendacionEvento.objects.create(
            evento=evento, titulo="Solo bootstrap", descripcion="Detalle.",
            icono_bootstrap="bi bi-shield-check",
        )
        response = self.client.get(reverse("eventos:listado_eventos"))
        item = {d["id"]: d for d in response.context["datos_modal"]}[evento.id]["recomendaciones_items"][0]
        self.assertEqual(item["icono_archivo"], "")
        self.assertEqual(item["icono_bootstrap"], "bi bi-shield-check")

    def test_payload_expone_exactamente_las_claves_esperadas(self):
        evento = self.crear_evento(tipo_fecha="exacta", fecha_inicio=self.hoy)
        RecomendacionEvento.objects.create(evento=evento, titulo="Consejo", descripcion="Detalle.")
        response = self.client.get(reverse("eventos:listado_eventos"))
        item = {d["id"]: d for d in response.context["datos_modal"]}[evento.id]["recomendaciones_items"][0]
        self.assertEqual(set(item.keys()), {"titulo", "descripcion", "icono_archivo", "icono_bootstrap"})


class EventosFiltrosPersistenciaTests(EventosTestDataMixin, TestCase):
    """
    Ajuste de E4: cambiar un control de filtro no debe perder los demás
    filtros GET activos. Se verifica tanto el HTML renderizado (selects/
    checkboxes/hidden inputs del formulario de filtros, que es lo que el
    navegador reenviará al cambiar un solo campo) como los querystrings
    servidos para quick filters / selector de 7 días / flechas.
    """

    def setUp(self):
        self.hoy = timezone.localdate()
        self.tag = TagExperiencia.objects.create(nombre="Familias persist", slug="familias-persist")

    def test_cambiar_categoria_conserva_provincia(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"categoria": self.categoria.slug, "provincia": self.provincia.slug},
        )
        self.assertContains(response, f'value="{self.provincia.slug}" selected')

    def test_seleccionar_fecha_conserva_categoria_provincia_y_tags(self):
        objetivo = self.hoy + timedelta(days=10)
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {
                "fecha": objetivo.isoformat(),
                "categoria": self.categoria.slug,
                "provincia": self.provincia.slug,
                "tags": [self.tag.slug],
            },
        )
        self.assertContains(response, f'value="{self.categoria.slug}" selected')
        self.assertContains(response, f'value="{self.provincia.slug}" selected')
        # El checkbox del tag va en varias líneas (value="..." \n checked), sin espacio único.
        self.assertRegex(response.content.decode(), rf'value="{re.escape(self.tag.slug)}"\s+checked')
        self.assertContains(response, f'value="{objetivo.isoformat()}"')

    def test_quick_filter_temporal_conserva_filtros_no_temporales(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"cuando": "hoy", "categoria": self.categoria.slug, "provincia": self.provincia.slug},
        )
        qs_manana = response.context["querystrings_cuando"]["manana"]
        self.assertIn(f"categoria={self.categoria.slug}", qs_manana)
        self.assertIn(f"provincia={self.provincia.slug}", qs_manana)
        self.assertIn("cuando=manana", qs_manana)

    def test_selector_de_dia_conserva_filtros_no_temporales(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"categoria": self.categoria.slug, "provincia": self.provincia.slug},
        )
        for dia in response.context["dias_selector"]:
            self.assertIn(f"categoria={self.categoria.slug}", dia["querystring"])
            self.assertIn(f"provincia={self.provincia.slug}", dia["querystring"])

    def test_flechas_ya_no_generan_ni_navegan_con_semana(self):
        """B2: las flechas del selector son botones sin href (JS-only, 100%
        cliente) — el backend ya no expone querystrings de `semana` ni
        arrastra `?semana=` recibido hacia ningún enlace nuevo."""
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"categoria": self.categoria.slug, "semana": "2027-01-10", "cuando": "hoy"},
        )
        self.assertNotIn("querystring_semana_anterior", response.context)
        self.assertNotIn("querystring_semana_siguiente", response.context)
        self.assertNotIn("semana=", response.context["querystring_todos"])
        self.assertNotIn("semana=", response.context["querystring_paginacion"])
        contenido = response.content.decode("utf-8")
        self.assertIn('<button type="button" class="ev-selector-dias__flecha"', contenido)


class EventosE5AccesibilidadYUxTests(EventosTestDataMixin, TestCase):
    """
    Ajuste E5: quick filters limpian `fecha`/`semana` (nueva selección
    temporal), "Elegir fecha" sigue sin conservar `semana`, y el markup
    del modal/CTA mantiene los atributos accesibles principales.
    """

    def setUp(self):
        self.hoy = timezone.localdate()

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def test_quick_filters_eliminan_fecha_y_semana(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"fecha": "2027-01-10", "semana": "2027-01-10", "categoria": self.categoria.slug},
        )
        for valor, qs in response.context["querystrings_cuando"].items():
            self.assertNotIn("fecha=", qs)
            self.assertNotIn("semana=", qs)
            self.assertIn(f"cuando={valor}", qs)
            self.assertIn(f"categoria={self.categoria.slug}", qs)

        qs_todos = response.context["querystring_todos"]
        self.assertNotIn("fecha=", qs_todos)
        self.assertNotIn("semana=", qs_todos)

    def test_elegir_fecha_no_conserva_semana(self):
        """B2: `semana` se descarta al inicio de la vista — ya no debe
        aparecer en ningún formulario/hidden del HTML servido."""
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"semana": "2027-01-10", "categoria": self.categoria.slug},
        )
        contenido = response.content.decode("utf-8")
        self.assertEqual(contenido.count('name="semana"'), 0)

    def test_modal_mantiene_atributos_accesibles_principales(self):
        self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, 'id="ev-modal-info"')
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, 'aria-modal="true"')
        self.assertContains(response, 'aria-labelledby="ev-modal-info-titulo"')

    def test_modal_ya_no_es_fullscreen_en_mobile(self):
        """R4/sección 7: se retira modal-fullscreen-sm-down; el diálogo se
        dimensiona manualmente (calc(100% - 24px), 90dvh) para que se siga
        percibiendo como modal, no como una página nueva."""
        self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertNotContains(response, "modal-fullscreen-sm-down")
        self.assertContains(response, "ev-modal__meta-linea")
        self.assertContains(response, "ev-modal__cerrar")

    def test_dia_activo_usa_aria_current_date(self):
        objetivo = self.hoy + timedelta(days=2)
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": objetivo.isoformat()})
        self.assertContains(response, 'aria-current="date"')

    def test_cta_evento_referencia_modal_semanticamente(self):
        self.crear(tipo_fecha="exacta", fecha_inicio=self.hoy)
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, 'aria-haspopup="dialog"')
        self.assertContains(response, 'aria-controls="ev-modal-info"')

    def test_fecha_manual_activa_se_muestra_formateada_y_marca_pill_activo(self):
        """R2/sección 12: con ?fecha= activa, el pill de 'Elegir fecha' debe
        mostrar la fecha elegida (dd/mm/aaaa) y quedar visualmente activo."""
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": "2026-08-22"})
        self.assertContains(response, "22/08/2026")
        self.assertContains(response, 'class="ev-fecha-picker is-active"')

    def test_sin_fecha_activa_el_pill_dice_elegir_fecha(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, "Elegir fecha")
        self.assertNotContains(response, "is-active")


class EventosRendimientoTests(EventosTestDataMixin, TestCase):
    """
    E6: detectar N+1 evidente en el listado paginado. No mide microoptimización,
    solo confirma que el número de queries no crece ~linealmente con la
    cantidad de eventos renderizados (select_related/prefetch_related activos).
    """

    def setUp(self):
        self.hoy = timezone.localdate()
        self.tag = TagExperiencia.objects.create(nombre="Rendimiento", slug="rendimiento")

    def _poblar(self, cantidad):
        Evento.objects.all().delete()
        for i in range(cantidad):
            evento = self.evento_base(
                tipo_fecha="exacta", fecha_inicio=self.hoy + timedelta(days=i),
                slug=f"evento-rendimiento-{i}",
            )
            evento.full_clean()
            evento.save()
            evento.tags_experiencia.add(self.tag)
            evento.categorias_secundarias.add(self.categoria)

    def _contar_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("eventos:listado_eventos"))
            self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_queries_no_crecen_linealmente_con_la_cantidad_de_eventos(self):
        self._poblar(1)
        queries_1 = self._contar_queries()

        self._poblar(9)
        queries_9 = self._contar_queries()

        # Un N+1 real crecería ~1 query adicional por evento (+8 con 9 eventos).
        # Un margen de 5 tolera diferencias legítimas sin ocultar una regresión evidente.
        self.assertLess(
            queries_9 - queries_1, 5,
            f"Las queries crecieron de {queries_1} a {queries_9} con 9 eventos: posible N+1.",
        )


class EventosParametrosInvalidosTests(EventosTestDataMixin, TestCase):
    """E6: ningún parámetro GET malformado o inexistente debe producir 500."""

    def test_pagina_no_numerica_no_produce_500(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"page": "no-es-numero"})
        self.assertEqual(response.status_code, 200)

    def test_pagina_demasiado_alta_no_produce_500(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"page": "9999"})
        self.assertEqual(response.status_code, 200)

    def test_categoria_inexistente_no_produce_500(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"categoria": "no-existe"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["eventos"]), 0)

    def test_provincia_inexistente_no_produce_500(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"provincia": "no-existe"})
        self.assertEqual(response.status_code, 200)

    def test_distrito_inexistente_no_produce_500(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"distrito": "no-existe"})
        self.assertEqual(response.status_code, 200)

    def test_costo_ya_no_es_un_filtro_publico(self):
        """R3/sección 13: 'costo' se retiró del filtro público. Un
        ?costo=gratis manual no debe filtrar resultados, no debe aparecer
        en 'filtros_activos', ni viajar en los enlaces de navegación (nada
        de filtro invisible que el usuario no controle desde la UI)."""
        hoy = timezone.localdate()
        gratis = self.evento_base(tipo_fecha="exacta", fecha_inicio=hoy, tipo_costo="gratis")
        gratis.full_clean()
        gratis.save()
        pagado = self.evento_base(tipo_fecha="exacta", fecha_inicio=hoy, tipo_costo="pagado", precio_desde=10)
        pagado.full_clean()
        pagado.save()

        response = self.client.get(reverse("eventos:listado_eventos"), {"costo": "gratis"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(gratis, response.context["eventos"])
        self.assertIn(pagado, response.context["eventos"])
        self.assertNotIn("costo", response.context["filtros_activos"])
        self.assertNotIn("costo=", response.context["querystring_paginacion"])
        self.assertNotContains(response, 'name="costo"')

    def test_tag_inexistente_no_produce_500(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"tags": "no-existe"})
        self.assertEqual(response.status_code, 200)

    def test_fecha_y_semana_invalidas_simultaneas_no_producen_500(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"fecha": "no-es-fecha", "semana": "tampoco-es-fecha"}
        )
        self.assertEqual(response.status_code, 200)


class PromocionarEventoFormTests(EventosTestDataMixin, TestCase):
    """CTA "Promociona tu evento" (sección 28): validación del Form, sin
    tocar la vista todavía."""

    def datos_validos(self, **overrides):
        data = dict(
            nombre_evento="Festival Gastronómico de Amarilis",
            tipo_evento=self.categoria.slug,
            descripcion_evento="Feria de comida típica con stands y música en vivo.",
            correo="organizador@correo.com",
            website="",
        )
        data.update(overrides)
        return data

    def test_form_valido(self):
        form = PromocionarEventoForm(self.datos_validos())
        self.assertTrue(form.is_valid(), form.errors)

    def test_nombre_obligatorio(self):
        form = PromocionarEventoForm(self.datos_validos(nombre_evento=""))
        self.assertFalse(form.is_valid())
        self.assertIn("nombre_evento", form.errors)

    def test_tipo_evento_obligatorio(self):
        form = PromocionarEventoForm(self.datos_validos(tipo_evento=""))
        self.assertFalse(form.is_valid())
        self.assertIn("tipo_evento", form.errors)

    def test_tipo_evento_otro_es_valido(self):
        form = PromocionarEventoForm(self.datos_validos(tipo_evento="otro"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_tipo_evento_solo_admite_categorias_activas_o_otro(self):
        """Ni una categoría inactiva ni un slug inventado deben colarse (R14:
        nada de choices hardcodeados/abiertos en el cliente)."""
        categoria_inactiva = CategoriaEvento.objects.create(
            nombre="Inactiva", slug="inactiva", activo=False
        )
        form = PromocionarEventoForm(self.datos_validos(tipo_evento=categoria_inactiva.slug))
        self.assertFalse(form.is_valid())
        self.assertIn("tipo_evento", form.errors)

        form_inventado = PromocionarEventoForm(self.datos_validos(tipo_evento="no-existe"))
        self.assertFalse(form_inventado.is_valid())
        self.assertIn("tipo_evento", form_inventado.errors)

    def test_descripcion_obligatoria(self):
        form = PromocionarEventoForm(self.datos_validos(descripcion_evento=""))
        self.assertFalse(form.is_valid())
        self.assertIn("descripcion_evento", form.errors)

    def test_correo_invalido_es_rechazado(self):
        form = PromocionarEventoForm(self.datos_validos(correo="no-es-un-correo"))
        self.assertFalse(form.is_valid())
        self.assertIn("correo", form.errors)

    def test_honeypot_relleno_es_rechazado(self):
        form = PromocionarEventoForm(self.datos_validos(website="http://spam.example"))
        self.assertFalse(form.is_valid())
        self.assertIn("website", form.errors)


class ReportarProblemaEventoFormTests(TestCase):
    """CTA "Reportar un problema" (sección 28)."""

    def datos_validos(self, **overrides):
        data = dict(
            nombre_problema="Información errónea",
            descripcion_problema='La información del evento "X" no está actualizada.',
            website="",
        )
        data.update(overrides)
        return data

    def test_form_valido(self):
        form = ReportarProblemaEventoForm(self.datos_validos())
        self.assertTrue(form.is_valid(), form.errors)

    def test_nombre_obligatorio(self):
        form = ReportarProblemaEventoForm(self.datos_validos(nombre_problema=""))
        self.assertFalse(form.is_valid())
        self.assertIn("nombre_problema", form.errors)

    def test_descripcion_obligatoria(self):
        form = ReportarProblemaEventoForm(self.datos_validos(descripcion_problema=""))
        self.assertFalse(form.is_valid())
        self.assertIn("descripcion_problema", form.errors)

    def test_honeypot_relleno_es_rechazado(self):
        form = ReportarProblemaEventoForm(self.datos_validos(website="http://spam.example"))
        self.assertFalse(form.is_valid())
        self.assertIn("website", form.errors)


class PromocionarEventoVistaTests(EventosTestDataMixin, TestCase):
    """Sección 29 (email con locmem) + 30 (seguridad) + 18 (sin publicación
    automática) para POST /eventos/promocionar/."""

    def datos_validos(self, **overrides):
        data = dict(
            nombre_evento="Festival Gastronómico de Amarilis",
            tipo_evento=self.categoria.slug,
            descripcion_evento="Feria de comida típica con stands y música en vivo.",
            correo="organizador@correo.com",
            website="",
            next="/eventos/?categoria=festividades",
        )
        data.update(overrides)
        return data

    def test_get_no_permitido(self):
        response = self.client.get(reverse("eventos:promocionar_evento"))
        self.assertEqual(response.status_code, 405)

    def test_post_valido_envia_correo_y_redirige_a_next(self):
        cantidad_eventos_antes = Evento.objects.count()

        response = self.client.post(reverse("eventos:promocionar_evento"), self.datos_validos())

        self.assertRedirects(response, "/eventos/?categoria=festividades")
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, [settings.EVENTOS_CONTACT_EMAIL])
        self.assertIn("Festival Gastronómico de Amarilis", correo.subject)
        self.assertIn("Festival Gastronómico de Amarilis", correo.body)
        self.assertIn("Feria de comida típica", correo.body)
        self.assertIn("organizador@correo.com", correo.body)
        self.assertEqual(correo.reply_to, ["organizador@correo.com"])
        # R18: nunca se crea un Evento automáticamente a partir de la propuesta.
        self.assertEqual(Evento.objects.count(), cantidad_eventos_antes)

    def test_post_invalido_no_envia_correo(self):
        response = self.client.post(reverse("eventos:promocionar_evento"), self.datos_validos(correo="invalido"))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(response.status_code, 302)

    def test_honeypot_relleno_no_envia_correo(self):
        response = self.client.post(
            reverse("eventos:promocionar_evento"), self.datos_validos(website="http://spam.example")
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(response.status_code, 302)

    def test_next_externo_no_redirige_fuera_del_dominio(self):
        response = self.client.post(
            reverse("eventos:promocionar_evento"), self.datos_validos(next="https://evil.example/robo")
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.url.startswith("https://evil.example"))

    def test_sin_next_redirige_al_listado(self):
        datos = self.datos_validos()
        del datos["next"]
        response = self.client.post(reverse("eventos:promocionar_evento"), datos)
        self.assertRedirects(response, reverse("eventos:listado_eventos"))


class ReportarProblemaEventoVistaTests(TestCase):
    """Sección 29/30 para POST /eventos/reportar/."""

    def datos_validos(self, **overrides):
        data = dict(
            nombre_problema="Información errónea",
            descripcion_problema='La información del evento "X" no está actualizada.',
            website="",
            next="/eventos/?page=2",
        )
        data.update(overrides)
        return data

    def test_get_no_permitido(self):
        response = self.client.get(reverse("eventos:reportar_problema_evento"))
        self.assertEqual(response.status_code, 405)

    def test_post_valido_envia_correo_y_redirige_a_next(self):
        response = self.client.post(reverse("eventos:reportar_problema_evento"), self.datos_validos())

        self.assertRedirects(response, "/eventos/?page=2")
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, [settings.EVENTOS_CONTACT_EMAIL])
        self.assertIn("Información errónea", correo.subject)
        self.assertIn("no está actualizada", correo.body)
        # El reporte no tiene correo de remitente, así que no debe forzar un Reply-To.
        self.assertFalse(correo.reply_to)

    def test_post_invalido_no_envia_correo(self):
        response = self.client.post(
            reverse("eventos:reportar_problema_evento"), self.datos_validos(nombre_problema="")
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(response.status_code, 302)

    def test_honeypot_relleno_no_envia_correo(self):
        response = self.client.post(
            reverse("eventos:reportar_problema_evento"), self.datos_validos(website="http://spam.example")
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(response.status_code, 302)

    def test_next_externo_no_redirige_fuera_del_dominio(self):
        response = self.client.post(
            reverse("eventos:reportar_problema_evento"), self.datos_validos(next="http://evil.example/robo")
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.url.startswith("http://evil.example"))


class EventosCtaComunidadTemplateTests(EventosTestDataMixin, TestCase):
    """Sección 31: el CTA y los dos modales existen en el HTML servido,
    con labels reales y CSRF — nada de aserciones frágiles sobre CSS."""

    def test_cta_y_botones_existen(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, "¿Tienes un evento para compartir?")
        self.assertContains(response, "Promociona tu evento")
        self.assertContains(response, "Reportar un problema")

    def test_modal_promocionar_existe_con_labels_y_csrf(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, 'id="ev-modal-promocionar"')
        self.assertContains(response, 'action="/eventos/promocionar/"')
        self.assertContains(response, "Nombre del evento")
        self.assertContains(response, "Tipo de evento")
        self.assertContains(response, "Describe brevemente tu evento")
        self.assertContains(response, "Ingresa tu correo electrónico")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_modal_reportar_existe_con_labels_y_csrf(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, 'id="ev-modal-reportar"')
        self.assertContains(response, 'action="/eventos/reportar/"')
        self.assertContains(response, "Nombre del problema")
        self.assertContains(response, "Describe el problema")

    def test_select_tipo_evento_usa_categorias_activas(self):
        CategoriaEvento.objects.create(nombre="Inactiva", slug="inactiva", activo=False)
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, f'value="{self.categoria.slug}"')
        self.assertNotContains(response, 'value="inactiva"')

    def test_cta_tiene_una_instancia_desktop_y_una_mobile(self):
        """E5/sección 26-30: el CTA se resuelve con un partial incluido dos
        veces (una por breakpoint) en vez de HTML duplicado a mano — ambas
        instancias deben existir, cada una con su clase responsive."""
        response = self.client.get(reverse("eventos:listado_eventos"))
        contenido = response.content.decode()
        self.assertEqual(contenido.count('class="ev-cta-comunidad d-none d-lg-block"'), 1)
        self.assertEqual(
            contenido.count('class="ev-cta-comunidad d-lg-none ev-cta-comunidad--final"'), 1
        )

    def test_cta_mobile_va_despues_de_la_paginacion_en_el_dom(self):
        """E23: el orden en el HTML debe ser cards -> paginación -> CTA."""
        hoy = timezone.localdate()
        for i in range(7):
            evento = self.evento_base(fecha_inicio=hoy + timedelta(days=i))
            evento.full_clean()
            evento.save()

        response = self.client.get(reverse("eventos:listado_eventos"))
        contenido = response.content.decode()
        pos_paginacion = contenido.find('class="ev-paginacion"')
        pos_cta_mobile = contenido.find("ev-cta-comunidad--final")
        self.assertGreater(pos_paginacion, 0)
        self.assertGreater(pos_cta_mobile, pos_paginacion)

    def test_modales_promocionar_y_reportar_tienen_header_body_footer(self):
        """E15/E18: misma arquitectura estructural en los dos modales de
        formulario (sin aserciones de CSS, solo de estructura)."""
        response = self.client.get(reverse("eventos:listado_eventos"))
        contenido = response.content.decode()
        for modal_id in ("ev-modal-promocionar", "ev-modal-reportar"):
            inicio = contenido.find(f'id="{modal_id}"')
            self.assertGreater(inicio, 0, f"{modal_id} no encontrado")
            fin = contenido.find("</form>", inicio)
            bloque = contenido[inicio:fin]
            self.assertIn("modal-header", bloque)
            self.assertIn("modal-body", bloque)
            self.assertIn("modal-footer", bloque)
            self.assertIn("Cancelar", bloque)


class EventosBug1FechaPickerTests(EventosTestDataMixin, TestCase):
    """B1: el <input type=date> nativo sigue siendo el único control real de
    'Elegir fecha'; con JS activo nunca debe existir un botón externo de
    confirmación (el mecanismo nativo del dispositivo es la única confirmación)."""

    def test_input_date_nativo_presente(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        self.assertContains(response, 'type="date" id="ev-fecha-input" name="fecha"')

    def test_no_existe_boton_externo_de_aplicar_fecha_fuera_de_noscript(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        contenido = response.content.decode()
        # El único botón "Ver" vive dentro de <noscript> (fallback sin JS);
        # con JS activo (caso normal) no debe existir fuera de ese bloque.
        antes_noscript = contenido.split("<noscript>")[0]
        for texto_prohibido in ("Aplicar fecha", "Ver fecha", "Confirmar fecha"):
            self.assertNotIn(texto_prohibido, antes_noscript)

    def test_fecha_valida_activa_el_filtro(self):
        objetivo = timezone.localdate() + timedelta(days=5)
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": objetivo.isoformat()})
        self.assertEqual(response.context["fecha_activa"], objetivo)

    def test_fecha_invalida_se_ignora_sin_activar_filtro(self):
        response = self.client.get(reverse("eventos:listado_eventos"), {"fecha": "no-es-una-fecha"})
        self.assertIsNone(response.context["fecha_activa"])


class EventosBug2FlechasSelectorTests(EventosTestDataMixin, TestCase):
    """B2: las flechas del calendario son navegación visual pura — botones
    sin href, visibles en cualquier tamaño, que nunca generan `semana` ni
    tocan el backend (el desplazamiento real ocurre en agenda-eventos.js)."""

    def test_flechas_son_botones_con_data_direccion_visibles_en_cualquier_tamano(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        contenido = response.content.decode()
        self.assertIn('<button type="button" class="ev-selector-dias__flecha" data-direccion="anterior"', contenido)
        self.assertIn('<button type="button" class="ev-selector-dias__flecha" data-direccion="siguiente"', contenido)
        self.assertNotIn("d-none d-lg-inline-flex", contenido)

    def test_dias_del_selector_incluyen_data_date(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        primero = response.context["dias_selector"][0]
        self.assertContains(response, f'data-date="{primero["fecha"].isoformat()}"')

    def test_selector_expone_estado_inicial_para_js_client_side(self):
        response = self.client.get(reverse("eventos:listado_eventos"))
        contenido = response.content.decode()
        self.assertIn("data-hoy=", contenido)
        self.assertIn("data-fecha-activa=", contenido)
        self.assertIn("data-ancla=", contenido)
        self.assertIn("data-base-query=", contenido)

    def test_click_en_dia_si_filtra_y_nunca_arrastra_semana(self):
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"provincia": self.provincia.slug, "semana": "2026-08-24"},
        )
        dia = response.context["dias_selector"][3]
        self.assertIn(f"provincia={self.provincia.slug}", dia["querystring"])
        self.assertIn(f"fecha={dia['fecha'].isoformat()}", dia["querystring"])
        self.assertNotIn("semana=", dia["querystring"])


class EventosBug3TagsANDTests(EventosTestDataMixin, TestCase):
    """B3: seleccionar varios tags de Experiencia debe exigir TODOS (AND),
    no alguno (OR)."""

    def setUp(self):
        self.hoy = timezone.localdate()
        self.tag_foto = TagExperiencia.objects.create(nombre="Fotografía b3", slug="fotografia-b3")
        self.tag_gastro = TagExperiencia.objects.create(nombre="Gastronomía b3", slug="gastronomia-b3")
        self.tag_nocturna = TagExperiencia.objects.create(nombre="Vida nocturna b3", slug="vida-nocturna-b3")

    def crear(self, **overrides):
        evento = self.evento_base(fecha_inicio=self.hoy, **overrides)
        evento.full_clean()
        evento.save()
        return evento

    def _poblar_abc(self):
        a = self.crear(slug="evento-a-b3")
        a.tags_experiencia.add(self.tag_foto)
        b = self.crear(slug="evento-b-b3")
        b.tags_experiencia.add(self.tag_foto, self.tag_gastro)
        c = self.crear(slug="evento-c-b3")
        c.tags_experiencia.add(self.tag_foto, self.tag_gastro, self.tag_nocturna)
        return a, b, c

    def test_un_tag_incluye_los_tres(self):
        a, b, c = self._poblar_abc()
        response = self.client.get(reverse("eventos:listado_eventos"), {"tags": ["fotografia-b3"]})
        eventos = response.context["eventos"]
        self.assertIn(a, eventos)
        self.assertIn(b, eventos)
        self.assertIn(c, eventos)

    def test_dos_tags_excluye_al_que_no_tiene_ambos(self):
        a, b, c = self._poblar_abc()
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"tags": ["fotografia-b3", "gastronomia-b3"]}
        )
        eventos = response.context["eventos"]
        self.assertNotIn(a, eventos)
        self.assertIn(b, eventos)
        self.assertIn(c, eventos)

    def test_tres_tags_solo_incluye_al_que_tiene_todos(self):
        a, b, c = self._poblar_abc()
        response = self.client.get(
            reverse("eventos:listado_eventos"),
            {"tags": ["fotografia-b3", "gastronomia-b3", "vida-nocturna-b3"]},
        )
        eventos = response.context["eventos"]
        self.assertNotIn(a, eventos)
        self.assertNotIn(b, eventos)
        self.assertIn(c, eventos)

    def test_tag_valido_sin_match_completo_produce_estado_vacio(self):
        """Ningún evento registrado tiene 'vida-nocturna-b3' a la vez que
        'gastronomia-b3' (el único con vida-nocturna, evento C, también trae
        fotografía y gastronomía — no sirve para probar un AND que falle).
        Se usa un evento aislado con un solo tag que nunca coincide."""
        solo_gastro = self.crear(slug="evento-solo-gastro-b3")
        solo_gastro.tags_experiencia.add(self.tag_gastro)
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"tags": ["gastronomia-b3", "vida-nocturna-b3"]}
        )
        self.assertNotIn(solo_gastro, response.context["eventos"])
        self.assertEqual(len(response.context["eventos"]), 0)

    def test_tags_duplicados_no_alteran_el_resultado(self):
        a = self.crear(slug="evento-dup-b3")
        a.tags_experiencia.add(self.tag_foto)
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"tags": ["fotografia-b3", "fotografia-b3"]}
        )
        self.assertIn(a, response.context["eventos"])

    def test_tag_invalido_manipulado_se_ignora_sin_romper_el_and(self):
        a = self.crear(slug="evento-inv-b3")
        a.tags_experiencia.add(self.tag_foto)
        response = self.client.get(
            reverse("eventos:listado_eventos"), {"tags": ["fotografia-b3", "no-existe-b3"]}
        )
        self.assertIn(a, response.context["eventos"])
        self.assertEqual(response.context["filtros_activos"]["tags"], ["fotografia-b3"])

    def test_and_de_tags_no_produce_n_mas_1(self):
        _a, _b, c = self._poblar_abc()
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                reverse("eventos:listado_eventos"),
                {"tags": ["fotografia-b3", "gastronomia-b3", "vida-nocturna-b3"]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(c, response.context["eventos"])
        self.assertLess(len(ctx.captured_queries), 15)


class EventosBug4OcurrenciaContextualTests(EventosTestDataMixin, TestCase):
    """
    B4: cuando un evento recurrente aparece por un filtro temporal, la
    card/modal/orden deben mostrar la ocurrencia que hizo match con ese
    filtro, no la "vigente/próxima respecto a hoy". Fecha de referencia fija
    (23/08/2026, domingo — la del reporte original) vía mock de
    timezone.localdate, para que la suite no dependa de la fecha real de
    ejecución.
    """

    HOY = date(2026, 8, 23)

    def crear(self, **overrides):
        evento = self.evento_base(**overrides)
        evento.full_clean()
        evento.save()
        return evento

    def _get(self, params=None, hoy=None):
        with patch("apps.eventos.views.timezone.localdate", return_value=hoy or self.HOY):
            return self.client.get(reverse("eventos:listado_eventos"), params or {})

    def _crear_identidad(self):
        # "Primer viernes después del 15 de agosto": 21/08/2026, próxima 20/08/2027.
        return self.crear(
            slug="dia-identidad-b4",
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=4, mes_relativa=8, dia_ancla_relativa=15,
        )

    def test_esta_semana_muestra_la_ocurrencia_que_hizo_match(self):
        evento = self._crear_identidad()
        response = self._get({"cuando": "esta_semana"})

        tarjetas = {t["evento"].id: t for t in response.context["tarjetas"]}
        self.assertIn(evento.id, tarjetas)
        self.assertEqual(tarjetas[evento.id]["fecha"]["principal"], "21 de agosto")

        datos_modal = {d["id"]: d for d in response.context["datos_modal"]}
        self.assertEqual(datos_modal[evento.id]["fecha"]["principal"], "21 de agosto")

    def test_sin_filtro_temporal_muestra_la_proxima_ocurrencia_general(self):
        evento = self._crear_identidad()
        response = self._get()
        tarjetas = {t["evento"].id: t for t in response.context["tarjetas"]}
        self.assertEqual(tarjetas[evento.id]["fecha"]["principal"], "20 de agosto")

    def test_estado_no_marca_hoy_ni_en_curso_para_ocurrencia_ya_pasada(self):
        """21/08/2026 (viernes) ya pasó respecto a hoy=23/08/2026 (domingo):
        no debe verse contradictorio marcar 'Hoy'/'En curso' en esa card."""
        evento = self._crear_identidad()
        response = self._get({"cuando": "esta_semana"})
        tarjetas = {t["evento"].id: t for t in response.context["tarjetas"]}
        self.assertIsNone(tarjetas[evento.id]["estado"])

    def test_orden_usa_la_ocurrencia_contextual_dentro_del_rango(self):
        tardio = self._crear_identidad()  # 21 ago 2026 (viernes)
        temprano = self.crear(
            slug="lunes-temprano-b4",
            tipo_fecha="anual_relativa", fecha_inicio=None,
            orden_semana_relativa=1, dia_semana_relativa=0, mes_relativa=8, dia_ancla_relativa=16,
        )  # primer lunes después del 16/08 -> 17 ago 2026
        response = self._get({"cuando": "esta_semana"})
        eventos = list(response.context["eventos"])
        self.assertLess(eventos.index(temprano), eventos.index(tardio))

    def test_pascua_relativa_esta_semana_muestra_la_ocurrencia_del_rango(self):
        evento = self.crear(tipo_fecha="pascua_relativa", fecha_inicio=None, offset_dias_pascua=-2)
        # Viernes Santo 2026 = 3 abr 2026; Domingo de Resurrección = 5 abr
        # 2026 (verificado en PascuaTests). "hoy" cae en esa misma semana
        # (lunes 30 mar - domingo 5 abr) para activar el filtro temporal.
        response = self._get({"cuando": "esta_semana"}, hoy=date(2026, 4, 5))
        tarjetas = {t["evento"].id: t for t in response.context["tarjetas"]}
        self.assertEqual(tarjetas[evento.id]["fecha"]["principal"], "3 de abril")
