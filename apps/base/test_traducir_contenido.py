from io import StringIO
from unittest.mock import patch

import httpx
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.base.management.commands import traducir_contenido as cmd
from apps.eventos.models import CategoriaEvento
from apps.turismo.models import CategoriaLugarTuristico, LugarTuristico
from apps.ubicaciones.models import Departamento, Distrito, Provincia

RUTA = "apps.base.management.commands.traducir_contenido"


def ejecutar(**opciones):
    salida = StringIO()
    call_command("traducir_contenido", stdout=salida, **opciones)
    return salida.getvalue()


def falso_lote(cliente, campos, contexto):
    return {k: "EN:" + v for k, v in campos.items()}


class ErrorApi(Exception):
    """Imita google.genai.errors.APIError (atributo `code`)."""

    def __init__(self, code, mensaje=""):
        super().__init__(f"{code} {mensaje}")
        self.code = code


class AlcanceTests(SimpleTestCase):
    def test_solo_apps_p1_y_sin_nombres_propios(self):
        modelos = cmd.modelos_p1()
        apps = {m._meta.app_label for m, _ in modelos}
        self.assertEqual(apps, set(cmd.APPS_P1))
        prohibidos = {("LugarTuristico", "nombre"), ("Evento", "nombre"), ("Establecimiento", "nombre"), ("PlatoTipico", "nombre")}
        for modelo, campos in modelos:
            for campo in campos:
                self.assertNotIn((modelo.__name__, campo), prohibidos)

    def test_instruccion_de_sistema_contiene_las_reglas_estrictas(self):
        for regla in ("EXACTLY the same keys", "Do NOT summarize", "line breaks", "HTML", "proper names", "URLs", "no explanations"):
            self.assertIn(regla, cmd.SYSTEM_INSTRUCTION)

    def test_instruccion_traduce_sustantivos_comunes_y_no_enriquece(self):
        for regla in ("Municipalidad", "City Hall", "Catedral", "Cathedral", "Plaza de Armas de Huánuco", "Pillco Marca",
                      "Add nothing that is not in the source text", "granite fountain"):
            self.assertIn(regla, cmd.SYSTEM_INSTRUCTION)


class ValidacionTests(SimpleTestCase):
    def test_acepta_traduccion_fiel(self):
        cmd.validar_traduccion("Plaza principal de la ciudad.", "Main square of the city.")

    def test_rechaza_vacia_url_email_telefono_html_y_parrafos(self):
        casos = [
            ("Texto largo de prueba", ""),
            ("Visita https://ejemplo.com hoy", "Visit the site today"),
            ("Escribe a info@ejemplo.com hoy", "Write to us today"),
            ("Llama al +51 962 123 456 hoy", "Call us today"),
            ("<p>Hola</p>", "Hello"),
            ("Primero\n\nSegundo", "First and second"),
        ]
        for es, en in casos:
            with self.assertRaises(cmd.ErrorTraduccion, msg=es):
                cmd.validar_traduccion(es, en)

    def test_preserva_html_y_parrafos(self):
        cmd.validar_traduccion("<p>Hola</p>\n\n<p>Adiós</p>", "<p>Hello</p>\n\n<p>Goodbye</p>")

    def test_limpia_envoltorios(self):
        self.assertEqual(cmd._limpiar_respuesta("```\nHello\n```"), "Hello")

    def test_no_traduce_valores_tecnicos(self):
        for v in ("", "  ", "12345", "info@ejemplo.com", "https://ejemplo.com", "--"):
            self.assertFalse(cmd._es_traducible(v), v)
        self.assertTrue(cmd._es_traducible("Templo antiguo"))

    def test_parsea_json_estructurado(self):
        self.assertEqual(cmd._parsear_json('{"a": "x"}'), {"a": "x"})
        self.assertEqual(cmd._parsear_json('```json\n{"a": "x"}\n```'), {"a": "x"})
        for malo in ("no es json", "[1, 2]"):
            with self.assertRaises(cmd.ErrorTraduccion):
                cmd._parsear_json(malo)


class LotesTests(SimpleTestCase):
    def test_un_registro_normal_va_en_una_sola_peticion(self):
        pendientes = [(f"campo{i}", "texto " * 50) for i in range(6)]
        self.assertEqual(len(cmd.partir_en_lotes(pendientes)), 1)

    def test_un_registro_enorme_se_divide_sin_una_peticion_por_campo(self):
        pendientes = [(f"campo{i}", "x" * 2500) for i in range(6)]  # 15 000 caracteres
        lotes = cmd.partir_en_lotes(pendientes)
        self.assertGreater(len(lotes), 1)
        self.assertLess(len(lotes), len(pendientes))
        self.assertEqual([c for lote in lotes for c, _ in lote], [c for c, _ in pendientes])
        for lote in lotes:
            self.assertLessEqual(sum(len(t) for _, t in lote), cmd.MAX_CARACTERES_LOTE)

    def test_limite_de_campos_por_peticion(self):
        pendientes = [(f"c{i}", "hola mundo") for i in range(cmd.MAX_CAMPOS_LOTE + 3)]
        self.assertEqual([len(l) for l in cmd.partir_en_lotes(pendientes)], [cmd.MAX_CAMPOS_LOTE, 3])


class ErroresTransitoriosTests(SimpleTestCase):
    def test_clasificacion(self):
        for exc in (ErrorApi(429), ErrorApi(503), httpx.ReadTimeout("t"), httpx.ConnectError("c"), TimeoutError()):
            self.assertTrue(cmd.es_error_transitorio(exc), repr(exc))
        for exc in (ErrorApi(400), ErrorApi(401), ValueError("x"), cmd.ErrorTraduccion("x")):
            self.assertFalse(cmd.es_error_transitorio(exc), repr(exc))

    def test_retry_delay_de_la_api(self):
        self.assertEqual(cmd.retry_delay(ErrorApi(429, "Please retry in 32.68s.")), 32.68)
        self.assertEqual(cmd.retry_delay(ErrorApi(429, "{'retryDelay': '26s'}")), 26.0)
        self.assertIsNone(cmd.retry_delay(ErrorApi(503, "high demand")))


class LlamadorTests(SimpleTestCase):
    def llamador(self, pausa=0.0):
        return cmd.Llamador(cliente=object(), pausa=pausa)

    def test_reintenta_hasta_tener_exito_y_respeta_retry_delay(self):
        secuencia = [ErrorApi(429, "Please retry in 10s"), {"a": "ok"}]

        def lote(cliente, campos, contexto):
            r = secuencia.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        esperas = []
        with patch(f"{RUTA}._traducir_lote", side_effect=lote), patch(f"{RUTA}._dormir", side_effect=esperas.append):
            ll = self.llamador()
            self.assertEqual(ll.traducir({"a": "hola"}, "ctx"), {"a": "ok"})
        self.assertEqual((ll.llamadas, ll.reintentos), (2, 1))
        self.assertEqual(esperas, [11.0])  # retryDelay + 1 s de margen

    def test_backoff_progresivo_sin_retry_delay_y_maximo_3_intentos(self):
        esperas = []
        with patch(f"{RUTA}._traducir_lote", side_effect=ErrorApi(503, "high demand")) as lote, patch(
            f"{RUTA}._dormir", side_effect=esperas.append
        ):
            ll = self.llamador()
            with self.assertRaises(cmd.ErrorTransitorioAgotado) as ctx:
                ll.traducir({"a": "hola"}, "ctx")
        self.assertEqual(lote.call_count, 3)  # nunca indefinidamente
        self.assertEqual(esperas, [5, 10])
        self.assertIn("tras 3 intentos", str(ctx.exception))
        self.assertEqual((ll.llamadas, ll.reintentos), (3, 2))

    def test_error_no_transitorio_no_se_reintenta(self):
        with patch(f"{RUTA}._traducir_lote", side_effect=ErrorApi(400, "bad")) as lote, patch(f"{RUTA}._dormir"):
            with self.assertRaises(ErrorApi):
                self.llamador().traducir({"a": "hola"}, "ctx")
        self.assertEqual(lote.call_count, 1)

    def test_pausa_solo_entre_llamadas_reales(self):
        esperas = []
        with patch(f"{RUTA}._traducir_lote", return_value={"a": "x"}), patch(f"{RUTA}._dormir", side_effect=esperas.append):
            ll = self.llamador(pausa=13)
            ll.traducir({"a": "hola"}, "ctx")  # la primera no espera
            ll.traducir({"a": "hola"}, "ctx")
            ll.traducir({"a": "hola"}, "ctx")
        self.assertEqual(esperas, [13, 13])


class ComandoTests(TestCase):
    def setUp(self):
        self.cat = CategoriaEvento.objects.create(nombre="Festividades", slug="festividades", descripcion="Fiestas tradicionales")
        CategoriaEvento.objects.create(nombre="Ferias", slug="ferias", descripcion="Ferias locales", descripcion_en="Local fairs")

    def leer(self, obj):
        return CategoriaEvento.objects.filter(pk=obj.pk).values("nombre_en", "descripcion_en").first()

    def parchear(self, **kw):
        kw.setdefault("side_effect", falso_lote)
        return patch(f"{RUTA}._crear_cliente"), patch(f"{RUTA}._traducir_lote", **kw), patch(f"{RUTA}._dormir")

    def test_dry_run_no_llama_a_gemini_ni_guarda(self):
        with patch(f"{RUTA}._crear_cliente") as cliente, patch(f"{RUTA}._traducir_lote") as lote:
            salida = ejecutar(dry_run=True)
        cliente.assert_not_called()
        lote.assert_not_called()
        self.assertIn("DRY-RUN", salida)
        self.assertIn("petición(es) previstas", salida)
        self.assertIn("Fiestas tradicionales", salida)
        self.assertEqual(self.leer(self.cat), {"nombre_en": None, "descripcion_en": None})

    def test_una_sola_llamada_por_registro_con_todos_sus_campos(self):
        c, l, d = self.parchear()
        with c, l as lote, d:
            ejecutar()
        # Festividades tiene 2 campos pendientes (nombre y descripcion) -> UNA llamada, no dos.
        llamadas_festividades = [
            a for a in lote.call_args_list if set(a.args[1]) == {"nombre", "descripcion"} and a.args[1]["nombre"] == "Festividades"
        ]
        self.assertEqual(len(llamadas_festividades), 1)
        self.assertEqual(self.leer(self.cat), {"nombre_en": "EN:Festividades", "descripcion_en": "EN:Fiestas tradicionales"})

    def test_nunca_sobrescribe_una_traduccion_existente(self):
        ferias = CategoriaEvento.objects.get(slug="ferias")
        c, l, d = self.parchear()
        with c, l as lote, d:
            ejecutar()
        self.assertEqual(self.leer(ferias)["descripcion_en"], "Local fairs")
        self.assertEqual(self.leer(ferias)["nombre_en"], "EN:Ferias")
        # ...y ni siquiera se le pidió la traducción de la descripción ya existente.
        ferias_pedido = [a.args[1] for a in lote.call_args_list if a.args[1].get("nombre") == "Ferias"][0]
        self.assertEqual(set(ferias_pedido), {"nombre"})

    def test_es_idempotente(self):
        c, l, d = self.parchear()
        with c, l as lote, d:
            ejecutar()
            llamadas = lote.call_count
            salida = ejecutar()
        self.assertEqual(lote.call_count, llamadas)
        self.assertIn("0 registro(s)", salida)

    def test_update_condicional_no_pisa_una_carrera(self):
        def lote_con_carrera(cliente, campos, contexto):
            CategoriaEvento.objects.filter(pk=self.cat.pk).update(descripcion_en="Escrita por el admin")
            return falso_lote(cliente, campos, contexto)

        c, l, d = self.parchear(side_effect=lote_con_carrera)
        with c, l, d:
            salida = ejecutar()
        self.assertEqual(self.leer(self.cat)["descripcion_en"], "Escrita por el admin")
        self.assertIn("no se sobrescribe", salida)

    def test_limit_cuenta_registros(self):
        CategoriaEvento.objects.create(nombre="Otra", slug="otra", descripcion="Descripción")
        c, l, d = self.parchear()
        with c, l, d:
            salida = ejecutar(limit=1)
        self.assertIn("1 registro(s)", salida)
        self.assertEqual(salida.count("=== "), 1)

    def test_limit_reparte_entre_modelos(self):
        dep = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        prov = Provincia.objects.create(departamento=dep, nombre_oficial="Huánuco", slug="huanuco")
        dist = Distrito.objects.create(provincia=prov, nombre_oficial="Huánuco", slug="huanuco", codigo_inei="100101")
        cat = CategoriaLugarTuristico.objects.create(nombre="Arqueológico", slug="arqueologico")
        LugarTuristico.objects.create(categoria_principal=cat, distrito=dist, nombre="Kotosh", slug="kotosh", descripcion="Templo")
        modelos = [m.__name__ for m, _, _ in cmd.seleccionar_registros(limite=3)]
        self.assertEqual(len(set(modelos)), len(modelos))

    def test_una_traduccion_invalida_no_impide_guardar_las_otras_del_registro(self):
        def lote(cliente, campos, contexto):
            r = falso_lote(cliente, campos, contexto)
            if "descripcion" in r and campos.get("nombre") == "Festividades":
                r["descripcion"] = ""  # inválida
            return r

        c, l, d = self.parchear(side_effect=lote)
        with c, l, d:
            salida = ejecutar()
        self.assertEqual(self.leer(self.cat), {"nombre_en": "EN:Festividades", "descripcion_en": None})
        self.assertIn("con error: 1", salida)

    def test_respuesta_con_clave_faltante_o_sobrante(self):
        def lote(cliente, campos, contexto):
            if campos.get("nombre") == "Festividades":
                return {"nombre": "Festivities", "otra_clave": "no pedida"}  # falta descripcion, sobra otra_clave
            return falso_lote(cliente, campos, contexto)

        c, l, d = self.parchear(side_effect=lote)
        with c, l, d:
            salida = ejecutar()
        self.assertEqual(self.leer(self.cat), {"nombre_en": "Festivities", "descripcion_en": None})
        self.assertIn("claves no solicitadas ignoradas: otra_clave", salida)
        self.assertIn("la respuesta no incluye esta clave", salida)

    def test_error_tras_reintentos_deja_vacio_y_continua_con_el_siguiente_registro(self):
        def lote(cliente, campos, contexto):
            if campos.get("nombre") == "Festividades":
                raise ErrorApi(503, "high demand")
            return falso_lote(cliente, campos, contexto)

        c, l, d = self.parchear(side_effect=lote)
        with c, l as m, d:
            salida = ejecutar()
        self.assertEqual(self.leer(self.cat), {"nombre_en": None, "descripcion_en": None})
        self.assertEqual(CategoriaEvento.objects.get(slug="ferias").nombre_en, "EN:Ferias")  # siguió adelante
        self.assertIn("tras 3 intentos", salida)
        self.assertIn("reintentos: 2", salida)

    def test_resumen_de_llamadas_campos_y_guardados(self):
        c, l, d = self.parchear()
        with c, l as lote, d:
            salida = ejecutar()
        self.assertIn(f"Llamadas reales a Gemini: {lote.call_count}", salida)
        self.assertIn("guardados:", salida)

    def test_pausa_se_pasa_al_llamador(self):
        esperas = []
        with patch(f"{RUTA}._crear_cliente"), patch(f"{RUTA}._traducir_lote", side_effect=falso_lote), patch(
            f"{RUTA}._dormir", side_effect=esperas.append
        ):
            ejecutar(pausa=7)
        self.assertTrue(esperas)
        self.assertTrue(all(e == 7 for e in esperas))

    def test_pausa_negativa_es_invalida(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            ejecutar(pausa=-1)

    def test_nunca_se_llama_desde_views(self):
        from django.conf import settings

        for ruta in (settings.BASE_DIR / "apps").rglob("views.py"):
            self.assertNotIn("traducir_contenido", ruta.read_text(encoding="utf-8"), str(ruta))
