"""Horario estructurado por sede: generación ES/EN, validación, regeneración condicionada,
formulario guiado del Admin y copia entre sedes."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from apps.chatbot.services.providers import servicios as prov_servicios

from .models import CategoriaServicioTurista, ServicioTurista, SedeServicioTurista
from .services import horarios as h
from .tests import DatosTerritorialesMixin, agregar_sede

LV_SA = {"lv": [["08:00", "18:00"]], "sa": [["08:00", "13:00"]]}


class GenerarHorarioTests(SimpleTestCase):
    def test_lunes_a_viernes_y_sabados_es_y_en(self):
        self.assertEqual(h.generar(LV_SA, "es"), "Lunes a viernes: 8:00 a. m. – 6:00 p. m.; Sábados: 8:00 a. m. – 1:00 p. m.")
        self.assertEqual(h.generar(LV_SA, "en"), "Monday to Friday: 8:00 a.m. – 6:00 p.m.; Saturdays: 8:00 a.m. – 1:00 p.m.")

    def test_domingo_cerrado(self):
        self.assertEqual(
            h.generar({**LV_SA, "do": []}, "es"),
            "Lunes a viernes: 8:00 a. m. – 6:00 p. m.; Sábados: 8:00 a. m. – 1:00 p. m.; Domingos: Cerrado",
        )
        self.assertTrue(h.generar({"do": []}, "en").endswith("Sundays: Closed"))

    def test_une_dias_contiguos_iguales(self):
        manana = [["09:00", "17:00"]]
        self.assertEqual(h.generar({"lv": manana, "sa": manana}, "es"), "Lunes a sábado: 9:00 a. m. – 5:00 p. m.")
        self.assertEqual(h.generar({"lv": manana, "sa": manana, "do": manana}, "es"), "Todos los días: 9:00 a. m. – 5:00 p. m.")
        self.assertEqual(h.generar({"lv": manana, "sa": manana, "do": manana}, "en"), "Every day: 9:00 a.m. – 5:00 p.m.")
        self.assertEqual(h.generar({"lv": manana, "sa": [], "do": []}, "es"), "Lunes a viernes: 9:00 a. m. – 5:00 p. m.; Sábados y domingos: Cerrado")

    def test_no_une_dias_no_contiguos_ni_distintos(self):
        manana = [["09:00", "17:00"]]
        self.assertEqual(h.generar({"lv": manana, "do": manana}, "es").count(";"), 1)

    def test_horario_partido(self):
        self.assertEqual(
            h.generar({"lv": [["08:00", "13:00"], ["15:00", "18:00"]]}, "es"),
            "Lunes a viernes: 8:00 a. m. – 1:00 p. m. y 3:00 p. m. – 6:00 p. m.",
        )
        self.assertIn(" and ", h.generar({"lv": [["08:00", "13:00"], ["15:00", "18:00"]]}, "en"))

    def test_nocturno_medianoche_y_mediodia(self):
        self.assertEqual(h.generar({"lv": [["22:00", "02:00"]]}, "es"), "Lunes a viernes: 10:00 p. m. – 2:00 a. m. (día siguiente)")
        self.assertEqual(h.generar({"lv": [["22:00", "02:00"]]}, "en"), "Monday to Friday: 10:00 p.m. – 2:00 a.m. (next day)")
        self.assertEqual(h.generar({"sa": [["12:00", "00:00"]]}, "es"), "Sábados: 12:00 p. m. – 12:00 a. m. (día siguiente)")

    def test_vacio_no_inventa_horario(self):
        self.assertEqual(h.generar({}, "es"), "")
        self.assertEqual(h.generar(None, "en"), "")


class ValidarHorarioTests(SimpleTestCase):
    def test_validos(self):
        self.assertEqual(h.validar_estructura({}), [])
        self.assertEqual(h.validar_estructura(LV_SA), [])
        self.assertEqual(h.validar_estructura({"lv": [["22:00", "02:00"]], "do": []}), [])

    def test_horas_iguales_formato_y_cantidad(self):
        self.assertTrue(h.validar_estructura({"lv": [["08:00", "08:00"]]}))
        self.assertTrue(h.validar_estructura({"lv": [["8:00", "18:00"]]}))
        self.assertTrue(h.validar_estructura({"lv": [["08:00", "25:00"]]}))
        self.assertTrue(h.validar_estructura({"lv": [["08:00", "09:00"], ["10:00", "11:00"], ["12:00", "13:00"]]}))
        self.assertTrue(h.validar_estructura({"xx": []}))
        self.assertTrue(h.validar_estructura(["lv"]))

    def test_solapamientos_incluida_la_medianoche(self):
        self.assertTrue(h.validar_estructura({"lv": [["08:00", "12:00"], ["11:00", "15:00"]]}))
        self.assertTrue(h.validar_estructura({"lv": [["22:00", "02:00"], ["01:00", "03:00"]]}))
        self.assertTrue(h.validar_estructura({"lv": [["08:00", "12:00"], ["08:00", "12:00"]]}))
        self.assertEqual(h.validar_estructura({"lv": [["08:00", "12:00"], ["12:00", "15:00"]]}), [])  # contiguos: válido
        self.assertEqual(h.validar_estructura({"lv": [["08:00", "12:00"], ["22:00", "02:00"]]}), [])


class HorarioEnModeloTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")
        cls.entidad = ServicioTurista.objects.create(categoria_principal=cls.categoria, nombre="Clínica", slug="clinica")

    def sede(self, **kw):
        kw.setdefault("disponibilidad", "horario")
        return agregar_sede(self.entidad, self.distrito_huanuco, nombre=f"S{SedeServicioTurista.objects.count()}", **kw)

    def test_crear_con_horario_genera_es_y_en(self):
        s = self.sede(horario=LV_SA)
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_es, h.generar(LV_SA, "es"))
        self.assertEqual(s.horario_atencion_en, h.generar(LV_SA, "en"))
        with translation.override("en"):
            self.assertEqual(s.horario_atencion, h.generar(LV_SA, "en"))
        with translation.override("es"):
            self.assertEqual(s.horario_atencion, h.generar(LV_SA, "es"))

    def test_cambiar_el_horario_regenera(self):
        s = self.sede(horario=LV_SA)
        s.horario = {"lv": [["09:00", "17:00"]]}
        s.save()
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_es, "Lunes a viernes: 9:00 a. m. – 5:00 p. m.")

    def test_editar_otros_datos_no_borra_traducciones_manuales(self):
        s = self.sede(horario=LV_SA)
        SedeServicioTurista.objects.filter(pk=s.pk).update(horario_atencion_en="Manual EN")
        s = SedeServicioTurista.objects.get(pk=s.pk)
        s.telefono = "000111222"
        s.save()
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_en, "Manual EN")
        s.save(update_fields=["telefono"])
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_en, "Manual EN")

    def test_update_fields_con_horario_incluye_los_textos(self):
        s = self.sede(horario=LV_SA)
        s.horario = {"sa": []}
        s.save(update_fields=["horario"])
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_es, "Sábados: Cerrado")

    def test_queryset_update_no_regenera_documentado(self):
        s = self.sede(horario=LV_SA)
        SedeServicioTurista.objects.filter(pk=s.pk).update(horario={"sa": []})
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_es, h.generar(LV_SA, "es"))  # no promete sincronización fuera de save()
        s.save()  # una edición oficial posterior sí corrige el texto
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_es, "Sábados: Cerrado")

    def test_modo_personalizado_no_se_toca(self):
        s = self.sede(horario_atencion_es="Texto libre", horario_atencion_en="Free text")
        s.telefono = "1"
        s.save()
        s.refresh_from_db()
        self.assertEqual((s.horario_atencion_es, s.horario_atencion_en, s.horario), ("Texto libre", "Free text", {}))

    def test_horario_incompatible_con_24_horas(self):
        s = SedeServicioTurista(servicio=self.entidad, distrito=self.distrito_huanuco, horario=LV_SA, disponibilidad="veinticuatro_horas")
        with self.assertRaises(ValidationError) as ctx:
            s.full_clean()
        self.assertIn("disponibilidad", ctx.exception.message_dict)

    def test_estructura_invalida_en_clean(self):
        s = SedeServicioTurista(servicio=self.entidad, distrito=self.distrito_huanuco, disponibilidad="horario", horario={"lv": [["08:00", "08:00"]]})
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_modal_y_chatbot_muestran_lo_mismo(self):
        s = self.sede(horario=LV_SA, direccion="Jr. X 1")
        self.addCleanup(translation.activate, "es")
        for idioma in ("es", "en"):
            self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = idioma
            tarjeta = next(t for t in self.client.get(reverse("servicios_turista:servicios_utiles")).context["tarjetas"] if t["id"] == s.id)
            with translation.override(idioma):
                item = next(i for i in prov_servicios.consultar_servicios_utiles()["items"] if i["id"] == s.id)
            self.assertEqual(tarjeta["disponibilidad_texto"], h.generar(LV_SA, idioma))
            self.assertEqual(item["horario_atencion"], tarjeta["disponibilidad_texto"])

    def test_24_horas_y_sin_horario_no_inventan_texto(self):
        s24 = self.sede(disponibilidad="veinticuatro_horas")
        sin = self.sede(disponibilidad="consultar", direccion="Jr. X 1")
        tarjetas = {t["id"]: t for t in self.client.get(reverse("servicios_turista:servicios_utiles")).context["tarjetas"]}
        self.assertEqual(tarjetas[s24.id]["disponibilidad_texto"], "Atención 24 h")
        self.assertEqual(tarjetas[sin.id]["disponibilidad_texto"], "")


class AdminSedeMixin(DatosTerritorialesMixin):
    """Entidades, superusuario y helpers (post/errores) para probar el formulario de sede del Admin."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")
        cls.entidad = ServicioTurista.objects.create(categoria_principal=cls.categoria, nombre="Clínica", slug="clinica")
        cls.otra_entidad = ServicioTurista.objects.create(categoria_principal=cls.categoria, nombre="Otra", slug="otra")
        cls.admin = get_user_model().objects.create_superuser("admin", "a@example.com", "Clave-admin-123")

    def setUp(self):
        self.client.force_login(self.admin)
        self.addCleanup(translation.activate, "es")

    def nueva(self, entidad=None, **kw):
        kw.setdefault("disponibilidad", "horario")
        kw.setdefault("direccion", f"Jr. Prueba {SedeServicioTurista.objects.count()}")
        return agregar_sede(entidad or self.entidad, self.distrito_huanuco, nombre=f"S{SedeServicioTurista.objects.count()}", **kw)

    def post(self, sede, bloques=None, **over):
        datos = {
            "servicio": sede.servicio_id, "nombre": sede.nombre, "distrito": sede.distrito_id, "direccion": sede.direccion,
            "telefono": sede.telefono, "maps_url": sede.maps_url, "embed_maps": sede.embed_maps,
            "disponibilidad": sede.disponibilidad,
            "horario_atencion_es": sede.horario_atencion_es or "", "horario_atencion_en": sede.horario_atencion_en or "",
            "referencia_es": "", "referencia_en": "", "latitud": "", "longitud": "", "slug": sede.slug, "activo": "on",
            "copiar_horario_de": "",
            "contactos-TOTAL_FORMS": "0", "contactos-INITIAL_FORMS": "0", "contactos-MIN_NUM_FORMS": "0", "contactos-MAX_NUM_FORMS": "1000",
        }
        for clave in ("lv", "sa", "do"):
            datos[f"{clave}_estado"] = ""
            for campo in ("d1", "h1", "d2", "h2"):
                datos[f"{clave}_{campo}"] = ""
        for clave, valor in (bloques or {}).items():
            estado, *horas = valor
            datos[f"{clave}_estado"] = estado
            for campo, hora in zip(("d1", "h1", "d2", "h2"), horas):
                datos[f"{clave}_{campo}"] = hora
        datos.update(over)
        return self.client.post(f"/admin/servicios_turista/sedeservicioturista/{sede.pk}/change/", datos)

    def errores(self, respuesta):
        return str(respuesta.context["adminform"].form.errors) + str(respuesta.context["adminform"].form.non_field_errors())


class HorarioEnAdminTests(AdminSedeMixin, TestCase):

    def test_formulario_muestra_bloques_y_vista_previa(self):
        s = self.nueva(horario=LV_SA)
        html = self.client.get(f"/admin/servicios_turista/sedeservicioturista/{s.pk}/change/").content.decode()
        for nombre in ("lv_estado", "lv_d1", "sa_h2", "do_estado", "copiar_horario_de", "maps_url", "embed_maps"):
            self.assertIn(f'name="{nombre}"', html)
        self.assertIn('type="time"', html)
        self.assertIn("Por bloques", html)
        self.assertIn("Lunes a viernes: 8:00 a. m.", html)

    def test_guardar_bloques_genera_json_y_textos(self):
        s = self.nueva()
        r = self.post(s, {"lv": ("abierto", "08:00", "18:00"), "sa": ("abierto", "08:00", "13:00"), "do": ("cerrado",)})
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual(s.horario, {"lv": [["08:00", "18:00"]], "sa": [["08:00", "13:00"]], "do": []})
        self.assertEqual(s.horario_atencion_es, "Lunes a viernes: 8:00 a. m. – 6:00 p. m.; Sábados: 8:00 a. m. – 1:00 p. m.; Domingos: Cerrado")
        self.assertTrue(s.horario_atencion_en.startswith("Monday to Friday"))

    def test_horario_partido_y_nocturno_desde_el_formulario(self):
        s = self.nueva()
        r = self.post(s, {"lv": ("abierto", "08:00", "13:00", "15:00", "18:00"), "sa": ("abierto", "22:00", "02:00")})
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual(s.horario["lv"], [["08:00", "13:00"], ["15:00", "18:00"]])
        self.assertIn("(día siguiente)", s.horario_atencion_es)

    def test_errores_de_bloques(self):
        s = self.nueva()
        casos = {
            "tramo incompleto": ({"lv": ("abierto", "08:00", "")}, "inicio y la de fin"),
            "abierto sin tramos": ({"lv": ("abierto",)}, "al menos un tramo"),
            "horas sin estado": ({"lv": ("", "08:00", "18:00")}, "Abierto» o «Cerrado"),
            "cerrado con horas": ({"lv": ("cerrado", "08:00", "18:00")}, "no lleva horas"),
            "iguales": ({"lv": ("abierto", "08:00", "08:00")}, "iguales"),
            "solape": ({"lv": ("abierto", "08:00", "12:00", "11:00", "15:00")}, "solapan"),
            "tramo 2 sin tramo 1": ({"lv": ("abierto", "", "", "15:00", "18:00")}, "tramo 1"),
        }
        for nombre, (bloques, texto) in casos.items():
            r = self.post(s, bloques)
            self.assertEqual(r.status_code, 200, nombre)
            self.assertIn(texto, self.errores(r), nombre)
            s.refresh_from_db()
            self.assertEqual(s.horario, {}, nombre)

    def test_bloques_con_24_horas_se_rechazan(self):
        s = self.nueva()
        r = self.post(s, {"lv": ("abierto", "08:00", "18:00")}, disponibilidad="veinticuatro_horas")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Horario específico", self.errores(r))

    def test_no_se_mezclan_bloques_y_texto_personalizado(self):
        s = self.nueva(horario_atencion_es="Antiguo", horario_atencion_en="Old")
        r = self.post(s, {"lv": ("abierto", "08:00", "18:00")}, horario_atencion_es="Otro texto")
        self.assertEqual(r.status_code, 200)
        self.assertIn("no ambos", self.errores(r))

    def test_pasar_de_texto_a_bloques_avisa_y_conserva_el_texto_anterior_en_el_aviso(self):
        s = self.nueva(horario_atencion_es="Texto anterior", horario_atencion_en="Previous text")
        r = self.post(s, {"lv": ("abierto", "08:00", "18:00")})
        self.assertEqual(r.status_code, 302)
        avisos = " ".join(str(m) for m in get_messages(r.wsgi_request))
        self.assertIn("Texto anterior", avisos)
        self.assertIn("Previous text", avisos)

    def test_editar_otro_dato_no_toca_horario_ni_traducciones(self):
        s = self.nueva(horario=LV_SA)
        SedeServicioTurista.objects.filter(pk=s.pk).update(horario_atencion_en="Manual EN")
        s.refresh_from_db()
        r = self.post(s, {"lv": ("abierto", "08:00", "18:00"), "sa": ("abierto", "08:00", "13:00")}, telefono="000999888")
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual((s.telefono, s.horario_atencion_en), ("000999888", "Manual EN"))

    def test_texto_en_modo_estructurado_esta_bloqueado(self):
        s = self.nueva(horario=LV_SA)
        r = self.post(s, {"lv": ("abierto", "08:00", "18:00"), "sa": ("abierto", "08:00", "13:00")}, horario_atencion_es="Intento de edición")
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.horario_atencion_es, h.generar(LV_SA, "es"))

    def test_pasar_a_texto_personalizado_conserva_el_ultimo_texto(self):
        s = self.nueva(horario=LV_SA)
        r = self.post(s, {})  # los tres bloques en «Sin indicar»
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual((s.horario, s.horario_atencion_es), ({}, h.generar(LV_SA, "es")))
        r = self.post(s, {}, horario_atencion_es="Personalizado ES", horario_atencion_en="Custom EN")
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual((s.horario_atencion_es, s.horario_atencion_en), ("Personalizado ES", "Custom EN"))

    def test_copiar_horario_de_otra_sede_es_una_copia_independiente(self):
        origen = self.nueva(horario=LV_SA)
        destino = self.nueva()
        r = self.post(destino, {}, copiar_horario_de=origen.pk)
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        destino.refresh_from_db()
        self.assertEqual(destino.horario, LV_SA)
        self.assertEqual(destino.horario_atencion_es, h.generar(LV_SA, "es"))
        origen.horario = {"sa": []}
        origen.save()
        destino.refresh_from_db()
        self.assertEqual(destino.horario, LV_SA)  # independiente

    def test_copiar_desde_una_sede_con_texto_personalizado(self):
        origen = self.nueva(disponibilidad="emergencia", horario_atencion_es="Urgencias 24 h", horario_atencion_en="Emergencies 24 h")
        destino = self.nueva()
        r = self.post(destino, {}, copiar_horario_de=origen.pk)
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        destino.refresh_from_db()
        self.assertEqual((destino.disponibilidad, destino.horario, destino.horario_atencion_es, destino.horario_atencion_en),
                         ("emergencia", {}, "Urgencias 24 h", "Emergencies 24 h"))

    def test_no_se_puede_copiar_de_otra_entidad(self):
        ajena = self.nueva(entidad=self.otra_entidad, horario=LV_SA)
        destino = self.nueva()
        r = self.post(destino, {}, copiar_horario_de=ajena.pk)
        self.assertEqual(r.status_code, 200)
        destino.refresh_from_db()
        self.assertEqual(destino.horario, {})

    def test_copiar_y_editar_a_la_vez_es_un_error_claro(self):
        origen = self.nueva(horario=LV_SA)
        destino = self.nueva()
        r = self.post(destino, {"sa": ("cerrado",)}, copiar_horario_de=origen.pk)
        self.assertEqual(r.status_code, 200)
        self.assertIn("una sola cosa", self.errores(r))

    def test_alta_de_sede_no_ofrece_copiar(self):
        html = self.client.get("/admin/servicios_turista/sedeservicioturista/add/").content.decode()
        self.assertIn("Disponible al editar la sede", html)

    def test_segundo_turno_guardado_vuelve_con_datos_y_sobrevive_a_otras_ediciones(self):
        s = self.nueva(horario={"lv": [["08:00", "13:00"], ["15:00", "18:00"]]})
        html = self.client.get(f"/admin/servicios_turista/sedeservicioturista/{s.pk}/change/").content.decode()
        self.assertIn('name="lv_d2" value="15:00"', html)  # el JS lo mostrará abierto porque tiene valores
        self.assertIn('name="lv_h2" value="18:00"', html)
        bloques = {"lv": ("abierto", "08:00", "13:00", "15:00", "18:00")}
        r = self.post(s, bloques, telefono="000111000")
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual(s.horario["lv"], [["08:00", "13:00"], ["15:00", "18:00"]])
        self.assertEqual(s.telefono, "000111000")

    def test_quitar_el_segundo_turno_se_guarda_al_enviar_el_formulario(self):
        s = self.nueva(horario={"lv": [["08:00", "13:00"], ["15:00", "18:00"]]})
        r = self.post(s, {"lv": ("abierto", "08:00", "13:00")})  # el JS envía d2/h2 vacíos al quitar el turno
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual(s.horario["lv"], [["08:00", "13:00"]])
        self.assertEqual(s.horario_atencion_es, "Lunes a viernes: 8:00 a. m. – 1:00 p. m.")

    def test_semantica_de_los_estados_no_cambia(self):
        s = self.nueva()
        r = self.post(s, {"lv": ("abierto", "22:00", "02:00"), "sa": ("cerrado",)})  # nocturno + cerrado; domingo sin indicar
        self.assertEqual(r.status_code, 302, r.context and self.errores(r))
        s.refresh_from_db()
        self.assertEqual(s.horario, {"lv": [["22:00", "02:00"]], "sa": []})  # «sin indicar» no es cerrado: no hay clave «do»
        self.assertNotIn("Domingos", s.horario_atencion_es)

    def test_pagina_carga_el_css_y_js_del_admin_de_sedes(self):
        from django.contrib.staticfiles import finders
        s = self.nueva(horario=LV_SA)
        html = self.client.get(f"/admin/servicios_turista/sedeservicioturista/{s.pk}/change/").content.decode()
        self.assertIn("assets/admin/sedes-admin.js", html)
        self.assertIn("assets/admin/sedes-admin.css", html)
        for ruta in ("assets/admin/sedes-admin.js", "assets/admin/sedes-admin.css"):
            self.assertIsNotNone(finders.find(ruta), ruta)

    def test_el_js_y_css_no_se_cargan_en_el_sitio_publico(self):
        html = self.client.get(reverse("servicios_turista:servicios_utiles")).content.decode()
        self.assertNotIn("sedes-admin", html)

    def test_vista_previa_legible_con_es_y_en_completos(self):
        largo = {"lv": [["08:00", "13:00"], ["15:00", "18:00"]], "sa": [["08:00", "13:00"], ["15:00", "17:00"]], "do": []}
        s = self.nueva(horario=largo)
        html = self.client.get(f"/admin/servicios_turista/sedeservicioturista/{s.pk}/change/").content.decode()
        self.assertIn("sede-vista-previa", html)
        self.assertIn("Español (ES)", html)
        self.assertIn("Inglés (EN)", html)
        self.assertIn("Por bloques", html)
        for idioma in ("es", "en"):
            self.assertIn(h.generar(largo, idioma), html)  # texto completo, sin truncar

    def test_vista_previa_de_texto_personalizado(self):
        s = self.nueva(horario_atencion_es="Atención por citas", horario_atencion_en="By appointment")
        html = self.client.get(f"/admin/servicios_turista/sedeservicioturista/{s.pk}/change/").content.decode()
        self.assertIn("Texto personalizado", html)
        self.assertIn("Atención por citas", html)
        self.assertIn("By appointment", html)
