from datetime import date
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.ubicaciones.models import Departamento, Distrito, Provincia

from .admin import ContactoEmergenciaForm
from .models import ContactoEmergencia, NumeroContactoAdicional, ZonaAtencionEmergencia
from .services.contactos import (
    generar_qr_data_uri,
    obtener_contactos_locales,
    obtener_contactos_nacionales,
    obtener_ultima_verificacion,
    obtener_zonas_activas,
    resolver_zona,
    zonas_agrupadas_por_provincia,
)


def crear_distrito(nombre_oficial, slug, provincia):
    return Distrito.objects.create(
        provincia=provincia,
        nombre_oficial=nombre_oficial,
        slug=slug,
        codigo_inei=slug[:6].ljust(6, "0"),
    )


class DatosTerritorialesMixin:
    """Réplica mínima (y ficticia) de la jerarquía territorial real de
    Huánuco, creada en el ORM para no depender de fixtures externas."""

    @classmethod
    def setUpTestData(cls):
        departamento = Departamento.objects.create(nombre_oficial="HUANUCO", slug="huanuco")
        prov_huanuco = Provincia.objects.create(
            departamento=departamento, nombre_oficial="HUANUCO", slug="huanuco", codigo_inei="1001"
        )
        prov_ambo = Provincia.objects.create(
            departamento=departamento, nombre_oficial="AMBO", slug="ambo", codigo_inei="1002"
        )
        prov_leoncio_prado = Provincia.objects.create(
            departamento=departamento, nombre_oficial="LEONCIO PRADO", slug="leoncio-prado", codigo_inei="1006"
        )

        cls.distrito_huanuco = crear_distrito("HUANUCO", "huanuco", prov_huanuco)
        cls.distrito_amarilis = crear_distrito("AMARILIS", "amarilis", prov_huanuco)
        cls.distrito_pillco_marca = crear_distrito("PILLCO MARCA", "pillco-marca", prov_huanuco)
        cls.distrito_ambo = crear_distrito("AMBO", "ambo", prov_ambo)
        cls.distrito_rupa_rupa = crear_distrito("RUPA-RUPA", "rupa-rupa", prov_leoncio_prado)

        cls.zona_huanuco = ZonaAtencionEmergencia.objects.create(
            distrito=cls.distrito_huanuco, slug="huanuco", orden=1
        )
        cls.zona_amarilis = ZonaAtencionEmergencia.objects.create(
            distrito=cls.distrito_amarilis, slug="amarilis", orden=2
        )
        cls.zona_pillco_marca = ZonaAtencionEmergencia.objects.create(
            distrito=cls.distrito_pillco_marca, nombre_publico="Pillco Marca", slug="pillco-marca", orden=3
        )
        cls.zona_ambo = ZonaAtencionEmergencia.objects.create(
            distrito=cls.distrito_ambo, slug="ambo", orden=1
        )
        cls.zona_tingo_maria = ZonaAtencionEmergencia.objects.create(
            distrito=cls.distrito_rupa_rupa, nombre_publico="Tingo María", slug="tingo-maria", orden=1
        )


class ZonaAtencionEmergenciaModelTests(DatosTerritorialesMixin, TestCase):
    def test_creacion_zona_vinculada_a_distrito_existente(self):
        self.assertEqual(self.zona_huanuco.distrito, self.distrito_huanuco)

    def test_no_duplica_zona_para_mismo_distrito(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ZonaAtencionEmergencia.objects.create(distrito=self.distrito_huanuco, slug="huanuco-2")

    def test_slug_unico(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ZonaAtencionEmergencia.objects.create(
                distrito=Distrito.objects.create(
                    provincia=self.distrito_huanuco.provincia,
                    nombre_oficial="OTRO DISTRITO",
                    slug="otro-distrito",
                    codigo_inei="999999",
                ),
                slug="huanuco",
            )

    def test_nombre_visible_usa_nombre_oficial_si_no_hay_nombre_publico(self):
        self.assertEqual(self.zona_huanuco.nombre_visible, "HUANUCO")

    def test_nombre_visible_usa_nombre_publico_cuando_existe(self):
        self.assertEqual(self.zona_tingo_maria.nombre_visible, "Tingo María")

    def test_zona_inactiva_no_aparece_entre_las_activas(self):
        self.zona_ambo.activo = False
        self.zona_ambo.save()
        self.assertNotIn(self.zona_ambo, obtener_zonas_activas())


class ContactoEmergenciaModelTests(DatosTerritorialesMixin, TestCase):
    def test_contacto_nacional_sin_zonas(self):
        contacto = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_NACIONAL,
            categoria="policia",
            nombre="Policía Nacional del Perú",
            numero_visible="105",
            numero_tel="105",
        )
        self.assertEqual(contacto.zonas.count(), 0)

    def test_contacto_local_con_zonas(self):
        contacto = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_LOCAL,
            categoria="serenazgo",
            nombre="Serenazgo de prueba",
            numero_visible="(062) 000-0000",
            numero_tel="062000000",
        )
        contacto.zonas.add(self.zona_huanuco)
        self.assertEqual(contacto.zonas.count(), 1)

    def test_numero_tel_valido_pasa_full_clean(self):
        contacto = ContactoEmergencia(
            ambito=ContactoEmergencia.AMBITO_NACIONAL,
            categoria="bomberos",
            nombre="Bomberos de prueba",
            numero_visible="116",
            numero_tel="+51116",
        )
        contacto.full_clean()

    def test_numero_tel_invalido_rechazado_por_full_clean(self):
        contacto = ContactoEmergencia(
            ambito=ContactoEmergencia.AMBITO_NACIONAL,
            categoria="bomberos",
            nombre="Bomberos de prueba",
            numero_visible="116",
            numero_tel="116 (línea)",
        )
        with self.assertRaises(ValidationError):
            contacto.full_clean()

    def test_horario_24_horas(self):
        contacto = ContactoEmergencia(es_24_horas=True, horario="")
        self.assertEqual(contacto.horario_texto, "Atención 24/7")

    def test_horario_especifico(self):
        contacto = ContactoEmergencia(es_24_horas=False, horario="Lunes a viernes, 8:00 a 16:00")
        self.assertEqual(contacto.horario_texto, "Lunes a viernes, 8:00 a 16:00")

    def test_contacto_inactivo_no_aparece_en_nacionales(self):
        ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_NACIONAL,
            categoria="salud",
            nombre="Contacto inactivo de prueba",
            numero_visible="000",
            numero_tel="000",
            activo=False,
        )
        nombres = [c.nombre for c in obtener_contactos_nacionales()]
        self.assertNotIn("Contacto inactivo de prueba", nombres)

    def test_admin_form_local_sin_zona_es_invalido(self):
        form = ContactoEmergenciaForm(data={
            "ambito": ContactoEmergencia.AMBITO_LOCAL,
            "categoria": "policia",
            "nombre": "Comisaría de prueba",
            "numero_visible": "999",
            "numero_tel": "999",
            "es_24_horas": False,
            "horario": "",
            "fuente_nombre": "",
            "fuente_url": "",
            "orden": 0,
            "activo": True,
            "zonas": [],
        })
        self.assertFalse(form.is_valid())

    def test_admin_form_local_con_zona_es_valido(self):
        form = ContactoEmergenciaForm(data={
            "ambito": ContactoEmergencia.AMBITO_LOCAL,
            "categoria": "policia",
            "nombre": "Comisaría de prueba",
            "numero_visible": "999",
            "numero_tel": "999",
            "es_24_horas": False,
            "horario": "",
            "fuente_nombre": "",
            "fuente_url": "",
            "orden": 0,
            "activo": True,
            "zonas": [self.zona_huanuco.pk],
        })
        self.assertTrue(form.is_valid())


class ServicioContactosTests(DatosTerritorialesMixin, TestCase):
    def setUp(self):
        self.nacional = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_NACIONAL,
            categoria="policia",
            nombre="Policía Nacional del Perú",
            numero_visible="105",
            numero_tel="105",
            orden=1,
            fecha_verificacion=date(2026, 6, 1),
        )
        self.local_huanuco = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_LOCAL,
            categoria="serenazgo",
            nombre="Serenazgo Huánuco",
            numero_visible="(062) 111-111",
            numero_tel="062111111",
            orden=1,
            fecha_verificacion=date(2026, 7, 1),
        )
        self.local_huanuco.zonas.add(self.zona_huanuco)

        self.local_multizona = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_LOCAL,
            categoria="municipal",
            nombre="Municipalidad conjunta de prueba",
            numero_visible="(062) 222-222",
            numero_tel="062222222",
            orden=2,
        )
        self.local_multizona.zonas.add(self.zona_huanuco, self.zona_amarilis)

        self.local_ambo = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_LOCAL,
            categoria="policia",
            nombre="Comisaría de Ambo",
            numero_visible="(062) 333-333",
            numero_tel="062333333",
        )
        self.local_ambo.zonas.add(self.zona_ambo)

    def test_huanuco_es_la_zona_predeterminada(self):
        self.assertEqual(resolver_zona(None).slug, "huanuco")

    def test_seleccion_amarilis(self):
        self.assertEqual(resolver_zona("amarilis").slug, "amarilis")

    def test_seleccion_pillco_marca(self):
        self.assertEqual(resolver_zona("pillco-marca").slug, "pillco-marca")

    def test_seleccion_ambo(self):
        self.assertEqual(resolver_zona("ambo").slug, "ambo")

    def test_seleccion_tingo_maria(self):
        zona = resolver_zona("tingo-maria")
        self.assertEqual(zona.distrito.nombre_oficial, "RUPA-RUPA")
        self.assertEqual(zona.nombre_visible, "Tingo María")

    def test_slug_invalido_cae_a_la_predeterminada(self):
        self.assertEqual(resolver_zona("no-existe").slug, "huanuco")

    def test_zona_inactiva_cae_a_la_predeterminada(self):
        self.zona_amarilis.activo = False
        self.zona_amarilis.save()
        self.assertEqual(resolver_zona("amarilis").slug, "huanuco")

    def test_contactos_nacionales_siempre_visibles(self):
        nombres = [c.nombre for c in obtener_contactos_nacionales()]
        self.assertIn("Policía Nacional del Perú", nombres)

    def test_contactos_locales_filtrados_por_zona(self):
        nombres = [c.nombre for c in obtener_contactos_locales(self.zona_huanuco)]
        self.assertIn("Serenazgo Huánuco", nombres)

    def test_contacto_puede_aparecer_en_varias_zonas(self):
        nombres_huanuco = [c.nombre for c in obtener_contactos_locales(self.zona_huanuco)]
        nombres_amarilis = [c.nombre for c in obtener_contactos_locales(self.zona_amarilis)]
        self.assertIn("Municipalidad conjunta de prueba", nombres_huanuco)
        self.assertIn("Municipalidad conjunta de prueba", nombres_amarilis)

    def test_contacto_local_de_otra_zona_no_aparece(self):
        nombres = [c.nombre for c in obtener_contactos_locales(self.zona_huanuco)]
        self.assertNotIn("Comisaría de Ambo", nombres)

    def test_contactos_inactivos_no_aparecen(self):
        self.local_huanuco.activo = False
        self.local_huanuco.save()
        nombres = [c.nombre for c in obtener_contactos_locales(self.zona_huanuco)]
        self.assertNotIn("Serenazgo Huánuco", nombres)

    def test_respeta_el_orden_configurado(self):
        nombres = [c.nombre for c in obtener_contactos_locales(self.zona_huanuco)]
        self.assertEqual(nombres, ["Serenazgo Huánuco", "Municipalidad conjunta de prueba"])

    def test_agrupacion_por_provincia(self):
        grupos = zonas_agrupadas_por_provincia()
        provincias = [g["provincia"].nombre_oficial for g in grupos]
        self.assertIn("HUANUCO", provincias)
        self.assertIn("AMBO", provincias)
        self.assertIn("LEONCIO PRADO", provincias)
        grupo_huanuco = next(g for g in grupos if g["provincia"].nombre_oficial == "HUANUCO")
        slugs = [z.slug for z in grupo_huanuco["zonas"]]
        self.assertEqual(set(slugs), {"huanuco", "amarilis", "pillco-marca"})

    def test_ultima_verificacion_es_la_fecha_mas_antigua_visible(self):
        contactos = obtener_contactos_nacionales() + obtener_contactos_locales(self.zona_huanuco)
        self.assertEqual(obtener_ultima_verificacion(contactos), date(2026, 6, 1))

    def test_qr_es_un_data_uri_svg_generado_localmente(self):
        data_uri = generar_qr_data_uri("https://viajeinformado.digital/planifica/emergencias/?zona=huanuco")
        self.assertTrue(data_uri.startswith("data:image/svg+xml"))


class EmergenciasViewTests(DatosTerritorialesMixin, TestCase):
    def setUp(self):
        self.nacional = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_NACIONAL,
            categoria="policia",
            nombre="Policía Nacional del Perú",
            numero_visible="105",
            numero_tel="105",
            fecha_verificacion=date(2026, 6, 1),
        )
        self.local = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_LOCAL,
            categoria="serenazgo",
            nombre="Serenazgo Huánuco",
            numero_visible="(062) 111-111",
            numero_tel="062111111",
            fecha_verificacion=date(2026, 7, 1),
        )
        self.local.zonas.add(self.zona_huanuco)

    def test_reverse_resuelve_ruta_publica(self):
        self.assertEqual(reverse("emergencias:emergencias"), "/planifica/emergencias/")

    def test_ruta_publica_responde_200(self):
        response = self.client.get("/planifica/emergencias/")
        self.assertEqual(response.status_code, 200)

    def test_usa_template_correcto(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertTemplateUsed(response, "emergencias/emergencias.html")

    def test_huanuco_es_la_zona_predeterminada_en_la_vista(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertEqual(response.context["zona_actual"].slug, "huanuco")

    def test_slug_invalido_en_querystring_cae_a_la_predeterminada(self):
        response = self.client.get(reverse("emergencias:emergencias"), {"zona": "invalida"})
        self.assertEqual(response.context["zona_actual"].slug, "huanuco")

    def test_seleccion_de_zona_por_querystring(self):
        response = self.client.get(reverse("emergencias:emergencias"), {"zona": "tingo-maria"})
        self.assertEqual(response.context["zona_actual"].slug, "tingo-maria")

    def test_boton_llamar_usa_tel_con_numero_normalizado(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertContains(response, 'href="tel:105"')

    def test_accion_copiar_presente_para_desktop(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertContains(response, 'data-copiar-numero="105"')

    def test_bloque_turistas_extranjeros_presente(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertContains(response, "Para turistas nacionales y extranjeros")
        self.assertContains(response, "If you need help")

    def test_bloque_antes_de_llamar_presente(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertContains(response, "¡IMPORTANTE!")
        self.assertContains(response, "Indicar tu ubicación exacta")

    def test_atribucion_fecha_de_verificacion_presente(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertContains(response, "Información verificada en")

    def test_selector_de_zona_es_accesible(self):
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertContains(response, 'for="emergencias-zona-select"')
        self.assertContains(response, 'id="emergencias-zona-select"')

    def test_mensaje_cuando_no_existen_contactos_locales(self):
        self.zona_amarilis.activo = True
        response = self.client.get(reverse("emergencias:emergencias"), {"zona": "amarilis"})
        self.assertContains(response, "Estamos verificando los contactos locales de esta zona")

    def test_nacionales_siguen_visibles_aunque_no_haya_locales(self):
        response = self.client.get(reverse("emergencias:emergencias"), {"zona": "amarilis"})
        self.assertContains(response, "Policía Nacional del Perú")

    def test_no_solicita_geolocalizacion_automaticamente(self):
        """No hay coordenadas por distrito en apps.ubicaciones (solo en
        Localidad, con un único registro), así que el botón "Usar mi
        ubicación" queda deliberadamente fuera de esta fase."""
        response = self.client.get(reverse("emergencias:emergencias"))
        self.assertNotContains(response, "Usar mi ubicación")

    @patch("apps.emergencias.services.contactos.segno.make")
    def test_qr_se_genera_con_la_url_de_la_zona_actual(self, mock_make):
        mock_make.return_value.svg_data_uri.return_value = "data:image/svg+xml;fake"
        response = self.client.get(reverse("emergencias:emergencias"), {"zona": "tingo-maria"})
        url_generada = mock_make.call_args[0][0]
        self.assertIn("zona=tingo-maria", url_generada)
        self.assertEqual(response.context["qr_data_uri"], "data:image/svg+xml;fake")


class NumeroContactoAdicionalTests(DatosTerritorialesMixin, TestCase):
    def setUp(self):
        self.contacto = ContactoEmergencia.objects.create(
            ambito=ContactoEmergencia.AMBITO_LOCAL,
            categoria="serenazgo",
            nombre="Serenazgo Huánuco",
            numero_visible="(062) 518080",
            numero_tel="062518080",
        )
        self.contacto.zonas.add(self.zona_huanuco)

    def test_contacto_puede_tener_varios_numeros_adicionales(self):
        NumeroContactoAdicional.objects.create(
            contacto=self.contacto, etiqueta="Móvil", numero_visible="987 654 321", numero_tel="987654321"
        )
        NumeroContactoAdicional.objects.create(
            contacto=self.contacto, etiqueta="Central", numero_visible="(062) 519090", numero_tel="062519090"
        )
        self.assertEqual(self.contacto.numeros_adicionales.count(), 2)

    def test_numero_adicional_aparece_en_la_vista(self):
        NumeroContactoAdicional.objects.create(
            contacto=self.contacto, etiqueta="Móvil", numero_visible="987 654 321", numero_tel="987654321"
        )
        response = self.client.get(reverse("emergencias:emergencias"), {"zona": "huanuco"})
        self.assertContains(response, "987 654 321")
        self.assertContains(response, 'href="tel:987654321"')

    def test_numero_tel_invalido_en_adicional_rechazado(self):
        numero = NumeroContactoAdicional(
            contacto=self.contacto, numero_visible="987-654-321", numero_tel="987 654 321"
        )
        with self.assertRaises(ValidationError):
            numero.full_clean()


class ReportarProblemaViewTests(TestCase):
    def test_reporte_valido_envia_correo_al_destinatario(self):
        response = self.client.post(
            reverse("emergencias:reportar_problema"),
            {
                "titulo": "Información errónea en los números de teléfono",
                "descripcion": "Los números de Serenazgo Huánuco no son los correctos.",
                "sitio_web": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("viajeinformadohuanuco@gmail.com", mail.outbox[0].to)
        self.assertIn("Información errónea", mail.outbox[0].subject)

    def test_reporte_sin_titulo_es_rechazado(self):
        response = self.client.post(
            reverse("emergencias:reportar_problema"),
            {"titulo": "", "descripcion": "Algo está mal.", "sitio_web": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(len(mail.outbox), 0)

    def test_honeypot_relleno_no_envia_correo_pero_responde_ok(self):
        response = self.client.post(
            reverse("emergencias:reportar_problema"),
            {"titulo": "x", "descripcion": "y", "sitio_web": "http://spam.example"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(len(mail.outbox), 0)

    def test_metodo_get_no_permitido(self):
        response = self.client.get(reverse("emergencias:reportar_problema"))
        self.assertEqual(response.status_code, 405)
