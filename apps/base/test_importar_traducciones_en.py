import json
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from apps.base import traducciones_en as t
from apps.base.models import HomeHeroSlide
from apps.eventos.models import CategoriaEvento, Evento, TagExperiencia


def escribir(contenido):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    tmp.write(contenido if isinstance(contenido, str) else json.dumps(contenido, ensure_ascii=False))
    tmp.close()
    return tmp.name


def archivo(*registros, label="eventos.CategoriaEvento"):
    return escribir({"_meta": {}, "modelos": {label: list(registros)}})


def reg(slug, campos, pk=None):
    return {"locator": {"slug": slug}, "pk": pk, "_ref": slug, "campos": campos}


def campo(es, en, **extra):
    return {"es": es, "en": en, **extra}


def correr(ruta, **opciones):
    salida = StringIO()
    call_command("importar_traducciones_en", archivo=ruta, stdout=salida, **opciones)
    return salida.getvalue()


class ImportadorTestBase(TestCase):
    def setUp(self):
        self.cat = CategoriaEvento.objects.create(nombre="Festividades", slug="festividades", descripcion="Fiestas tradicionales")
        self.otra = CategoriaEvento.objects.create(nombre="Ferias", slug="ferias", descripcion="Ferias locales")

    def en(self, obj, campo):
        return type(obj)._default_manager.filter(pk=obj.pk).values_list(f"{campo}_en", flat=True).first()


class ImportacionTests(ImportadorTestBase):
    def test_dry_run_no_escribe(self):
        ruta = archivo(reg("festividades", {"nombre": campo("Festividades", "Festivals")}))
        salida = correr(ruta, dry_run=True)
        self.assertIn("DRY-RUN", salida)
        self.assertIn("Campos que se cargarían: 1", salida)
        self.assertIsNone(self.en(self.cat, "nombre"))

    def test_importacion_correcta_por_locator(self):
        ruta = archivo(
            reg("festividades", {"nombre": campo("Festividades", "Festivals"), "descripcion": campo("Fiestas tradicionales", "Traditional festivities")}),
            reg("ferias", {"nombre": campo("Ferias", "Fairs")}),
        )
        salida = correr(ruta)
        self.assertIn("Campos cargados: 3", salida)
        self.assertEqual(self.en(self.cat, "nombre"), "Festivals")
        self.assertEqual(self.en(self.cat, "descripcion"), "Traditional festivities")
        self.assertEqual(self.en(self.otra, "nombre"), "Fairs")

    def test_el_locator_funciona_aunque_el_pk_no_coincida(self):
        ruta = archivo(reg("festividades", {"nombre": campo("Festividades", "Festivals")}, pk=99999))
        correr(ruta)
        self.assertEqual(self.en(self.cat, "nombre"), "Festivals")

    def test_sin_locator_se_usa_el_pk(self):
        ruta = archivo({"locator": None, "pk": self.cat.pk, "_ref": "x", "campos": {"nombre": campo("Festividades", "Festivals")}})
        correr(ruta)
        self.assertEqual(self.en(self.cat, "nombre"), "Festivals")

    def test_no_sobrescribe_un_en_existente(self):
        CategoriaEvento.objects.filter(pk=self.cat.pk).update(nombre_en="Escrita a mano")
        ruta = archivo(reg("festividades", {"nombre": campo("Festividades", "Festivals"), "descripcion": campo("Fiestas tradicionales", "Traditional festivities")}))
        salida = correr(ruta)
        self.assertEqual(self.en(self.cat, "nombre"), "Escrita a mano")
        self.assertEqual(self.en(self.cat, "descripcion"), "Traditional festivities")
        self.assertIn("Ya traducidos (no se sobrescriben): 1", salida)

    def test_segunda_ejecucion_no_modifica_nada(self):
        ruta = archivo(reg("festividades", {"nombre": campo("Festividades", "Festivals")}))
        correr(ruta)
        salida = correr(ruta)
        self.assertIn("Campos cargados: 0", salida)
        self.assertIn("Ya traducidos (no se sobrescriben): 1", salida)
        self.assertEqual(self.en(self.cat, "nombre"), "Festivals")

    def test_registro_inexistente_no_es_error_y_continua(self):
        ruta = archivo(
            reg("no-existe", {"nombre": campo("X", "X en")}, pk=424242),
            reg("ferias", {"nombre": campo("Ferias", "Fairs")}),
        )
        salida = correr(ruta)
        self.assertIn("[no_encontrado]", salida)
        self.assertIn("No encontrados en este entorno (no aplica, no es error): 1", salida)
        self.assertIn("Errores: 0", salida)
        self.assertEqual(self.en(self.otra, "nombre"), "Fairs")  # siguió adelante

    def test_es_distinto_se_reporta_y_no_se_escribe(self):
        ruta = archivo(reg("festividades", {"nombre": campo("Otro texto ES", "Festivals"), "descripcion": campo("Fiestas tradicionales", "Traditional festivities")}))
        salida = correr(ruta)
        self.assertIn("es_distinto", salida)
        self.assertIsNone(self.en(self.cat, "nombre"))
        self.assertEqual(self.en(self.cat, "descripcion"), "Traditional festivities")  # el resto del registro sí

    def test_es_con_crlf_y_espacios_es_equivalente(self):
        CategoriaEvento.objects.filter(pk=self.cat.pk).update(descripcion_es="Linea 1\r\nLinea 2 ")
        ruta = archivo(reg("festividades", {"descripcion": campo("Linea 1\nLinea 2", "Line 1\nLine 2")}))
        self.assertIn("Campos cargados: 1", correr(ruta))

    def test_traduccion_invalida_se_rechaza_y_no_impide_las_otras(self):
        CategoriaEvento.objects.filter(pk=self.cat.pk).update(descripcion_es="Mira https://ejemplo.com hoy")
        ruta = archivo(reg("festividades", {
            "descripcion": campo("Mira https://ejemplo.com hoy", "Look at the site today"),  # pierde la URL
            "nombre": campo("Festividades", "Festivals"),
        }))
        salida = correr(ruta)
        self.assertIn("[validacion]", salida)
        self.assertIsNone(self.en(self.cat, "descripcion"))
        self.assertEqual(self.en(self.cat, "nombre"), "Festivals")

    def test_no_llama_a_ninguna_api(self):
        fuente = Path(t.__file__).read_text(encoding="utf-8")
        for prohibido in ("genai", "requests", "httpx", "urllib", "socket"):
            self.assertNotIn(f"import {prohibido}", fuente)


class CorreccionDelEsTests(TestCase):
    def setUp(self):
        self.slide = HomeHeroSlide.objects.create(
            etiqueta="x", titulo_principal="y", titulo_resaltado="z", descripcion="d", archivo="home/hero/a.png", orden=7,
            texto_alt="Vista de estatus de los negritos",
        )

    def ruta(self):
        return escribir({"_meta": {}, "modelos": {"base.HomeHeroSlide": [{
            "locator": {"orden": 7}, "pk": None, "_ref": "slide",
            "campos": {"texto_alt": campo("Vista de estatus de los negritos", "View of the statues", es_corregido="Vista de estatuas de los Negritos")},
        }]}})

    def columnas(self):
        from django.db import connection

        with connection.cursor() as c:
            c.execute("SELECT texto_alt, texto_alt_es, texto_alt_en FROM base_homeheroslide WHERE id=%s", [self.slide.pk])
            return c.fetchone()

    def test_dry_run_no_corrige(self):
        salida = correr(self.ruta(), dry_run=True)
        self.assertIn("Correcciones del ES fuente previstas: 1", salida)
        self.assertEqual(self.columnas(), ("Vista de estatus de los negritos",) * 2 + (None,))

    def test_corrige_es_en_ambas_columnas_y_carga_en(self):
        salida = correr(self.ruta())
        self.assertIn("aplicadas: 1", salida)
        self.assertEqual(self.columnas(), ("Vista de estatuas de los Negritos", "Vista de estatuas de los Negritos", "View of the statues"))

    def test_segunda_ejecucion_es_idempotente(self):
        correr(self.ruta())
        salida = correr(self.ruta())
        self.assertIn("Campos cargados: 0", salida)
        self.assertIn("Errores: 0", salida)


class ArchivoInvalidoTests(ImportadorTestBase):
    def assertFalla(self, ruta, texto=None):
        with self.assertRaises(CommandError) as ctx:
            correr(ruta)
        if texto:
            self.assertIn(texto, str(ctx.exception))
        return ctx

    def test_no_existe(self):
        self.assertFalla("/no/existe/traducciones.json", "No existe")

    def test_json_roto(self):
        self.assertFalla(escribir("{esto no es json"), "JSON")

    def test_sin_modelos(self):
        self.assertFalla(escribir({"_meta": {}}), "válido")

    def test_campo_no_permitido_se_rechaza_sin_escribir_nada(self):
        ruta = archivo(reg("festividades", {"nombre": campo("Festividades", "Festivals"), "slug": campo("festividades", "festivals")}))
        self.assertFalla(ruta)
        self.assertIsNone(self.en(self.cat, "nombre"))  # ni siquiera el campo válido

    def test_nombre_propio_prohibido(self):
        ruta = escribir({"modelos": {"eventos.Evento": [{"locator": {"slug": "x"}, "pk": 1, "campos": {"nombre": campo("A", "B")}}]}})
        self.assertFalla(ruta)

    def test_modelo_fuera_de_p1(self):
        ruta = escribir({"modelos": {"movilidad.RutaMovilidad": [reg("x", {"nombre": campo("a", "b")})]}})
        self.assertFalla(ruta)

    def test_registro_sin_locator_ni_pk_y_valores_mal_formados(self):
        errores = t.validar_estructura({"modelos": {"eventos.CategoriaEvento": [
            {"campos": {"nombre": {"es": "a", "en": "b"}}},
            {"locator": {"slug": "x"}, "campos": {"nombre": {"es": "a"}}},
            {"locator": {"slug": "x"}, "campos": {"nombre": {"es": "a", "en": "  "}}},
            {"locator": {"otro": 1}, "campos": {"nombre": {"es": "a", "en": "b"}}},
        ]}})
        self.assertEqual(len(errores), 4)


class ArchivoDelProyectoTests(SimpleTestCase):
    """El JSON versionado es estructuralmente válido (sin tocar la BD)."""

    def test_estructura_valida_y_solo_p1(self):
        datos = t.cargar_archivo(str(settings.BASE_DIR / t.RUTA_POR_DEFECTO))
        self.assertEqual(t.validar_estructura(datos), [])

    def test_no_incluye_datos_de_prueba_ni_nombres_de_archivo(self):
        datos = t.cargar_archivo(str(settings.BASE_DIR / t.RUTA_POR_DEFECTO))
        for regs in datos["modelos"].values():
            for r in regs:
                for c in r["campos"].values():
                    self.assertNotIn("QA ", c["es"])
                    self.assertNotRegex(c["es"], r"^[a-z0-9]+(_[a-z0-9]+)+$")

    def test_cada_registro_tiene_locator_estable(self):
        datos = t.cargar_archivo(str(settings.BASE_DIR / t.RUTA_POR_DEFECTO))
        for label, regs in datos["modelos"].items():
            for r in regs:
                self.assertEqual(set(r["locator"]), set(t.LOCATORS[label]), f"{label} {r['_ref']}")
