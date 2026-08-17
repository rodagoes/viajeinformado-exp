from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.ubicaciones.models import Departamento, Distrito, Provincia

from .models import CategoriaServicioTurista, ContactoServicioTurista, ServicioTurista
from .services.zonas import NOMBRES_PUBLICOS_ZONA, nombre_publico_zona


def crear_distrito(nombre_oficial, slug, provincia):
    return Distrito.objects.create(
        provincia=provincia,
        nombre_oficial=nombre_oficial,
        slug=slug,
        codigo_inei=slug[:6].ljust(6, "0"),
    )


class DatosTerritorialesMixin:
    """Réplica mínima (y ficticia) de la jerarquía territorial real de
    Huánuco, creada en el ORM para no depender de fixtures externas. No
    modifica apps.ubicaciones: solo crea objetos temporales de prueba."""

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


class NombrePublicoZonaTests(DatosTerritorialesMixin, TestCase):
    def test_rupa_rupa_muestra_tingo_maria(self):
        self.assertEqual(nombre_publico_zona(self.distrito_rupa_rupa), "Tingo María")

    def test_huanuco_muestra_huanuco_con_tilde(self):
        self.assertEqual(nombre_publico_zona(self.distrito_huanuco), "Huánuco")

    def test_distrito_sin_excepcion_cae_al_nombre_oficial(self):
        otro = crear_distrito("CHURUBAMBA", "churubamba", self.distrito_huanuco.provincia)
        self.assertEqual(nombre_publico_zona(otro), "CHURUBAMBA")


class ServiciosUtilesViewTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.categoria_salud = CategoriaServicioTurista.objects.create(
            nombre="Salud y farmacias", slug="salud"
        )
        cls.categoria_seguridad = CategoriaServicioTurista.objects.create(
            nombre="Seguridad", slug="seguridad"
        )
        cls.categoria_sin_servicios = CategoriaServicioTurista.objects.create(
            nombre="Bancos y cajeros", slug="bancos"
        )

        cls.hospital = ServicioTurista.objects.create(
            categoria_principal=cls.categoria_salud,
            nombre="Hospital Regional Hermilio Valdizán",
            slug="hospital-regional-hermilio-valdizan",
            distrito=cls.distrito_huanuco,
            direccion="Av. principal 123",
            latitud=Decimal("-9.9281900"),
            longitud=Decimal("-76.2405600"),
            telefono="(062) 512021",
            disponibilidad="veinticuatro_horas",
        )
        cls.comisaria = ServicioTurista.objects.create(
            categoria_principal=cls.categoria_seguridad,
            nombre="Comisaría de Huánuco",
            slug="comisaria-huanuco",
            distrito=cls.distrito_huanuco,
            direccion="Jr. Huallayco 456",
            horario_atencion="Lunes a domingo: 24 horas",
        )
        cls.servicio_tingo_maria = ServicioTurista.objects.create(
            categoria_principal=cls.categoria_salud,
            nombre="Centro de Salud Tingo María",
            slug="centro-salud-tingo-maria",
            distrito=cls.distrito_rupa_rupa,
            direccion="Jr. Raimondi 789",
        )
        cls.servicio_inactivo = ServicioTurista.objects.create(
            categoria_principal=cls.categoria_salud,
            nombre="Servicio inactivo de prueba",
            slug="servicio-inactivo-prueba",
            distrito=cls.distrito_huanuco,
            activo=False,
        )

    def _get(self, **params):
        return self.client.get(reverse("servicios_turista:servicios_utiles"), params)

    def test_get_responde_200(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)

    def test_huanuco_es_zona_por_defecto(self):
        response = self._get()
        self.assertEqual(response.context["zona_actual_slug"], "huanuco")
        self.assertContains(response, "Hospital Regional Hermilio Valdizán")
        self.assertContains(response, "Comisaría de Huánuco")

    def test_filtro_por_zona_rupa_rupa(self):
        response = self._get(zona="rupa-rupa")
        self.assertEqual(response.context["zona_actual_slug"], "rupa-rupa")
        self.assertContains(response, "Centro de Salud Tingo María")
        self.assertNotContains(response, "Hospital Regional Hermilio Valdizán")

    def test_rupa_rupa_filtra_por_distrito_real_pero_muestra_tingo_maria(self):
        response = self._get(zona="rupa-rupa")
        self.assertEqual(response.context["zona_actual"], self.distrito_rupa_rupa)
        self.assertEqual(response.context["zona_actual_nombre"], "Tingo María")
        self.assertContains(response, "Tingo María")
        self.assertNotContains(response, "RUPA-RUPA")

    def test_filtro_por_categoria(self):
        response = self._get(zona="huanuco", categoria="seguridad")
        self.assertContains(response, "Comisaría de Huánuco")
        self.assertNotContains(response, "Hospital Regional Hermilio Valdizán")

    def test_zona_y_categoria_juntos(self):
        response = self._get(zona="huanuco", categoria="salud")
        self.assertContains(response, "Hospital Regional Hermilio Valdizán")
        self.assertNotContains(response, "Comisaría de Huánuco")

    def test_slug_de_zona_invalido_cae_a_huanuco_sin_404(self):
        response = self._get(zona="no-existe")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["zona_actual_slug"], "huanuco")

    def test_solo_muestra_servicios_activos(self):
        response = self._get()
        self.assertNotContains(response, "Servicio inactivo de prueba")

    def test_solo_zonas_con_servicios_activos_en_el_selector(self):
        response = self._get()
        zonas_slugs = [z["slug"] for z in response.context["zonas_opciones"]]
        self.assertIn("huanuco", zonas_slugs)
        self.assertIn("rupa-rupa", zonas_slugs)
        # amarilis, pillco-marca y ambo existen como distrito pero no
        # tienen ningún ServicioTurista activo en este set de datos.
        self.assertNotIn("amarilis", zonas_slugs)
        self.assertNotIn("ambo", zonas_slugs)

    def test_solo_categorias_con_servicios_activos_en_la_zona_actual(self):
        response = self._get(zona="huanuco")
        categorias_slugs = [c["slug"] for c in response.context["categorias_opciones"]]
        self.assertIn("salud", categorias_slugs)
        self.assertIn("seguridad", categorias_slugs)
        self.assertNotIn("bancos", categorias_slugs)

    def test_estado_sin_resultados(self):
        response = self._get(zona="huanuco", categoria="bancos")
        self.assertFalse(response.context["hay_resultados"])
        self.assertContains(response, "No encontramos servicios")

    def test_zona_todas_muestra_servicios_de_varios_distritos(self):
        response = self._get(zona="todas")
        self.assertEqual(response.context["zona_actual_slug"], "todas")
        self.assertContains(response, "Hospital Regional Hermilio Valdizán")
        self.assertContains(response, "Centro de Salud Tingo María")

    def test_paginacion_muestra_6_por_pagina(self):
        for i in range(7):
            ServicioTurista.objects.create(
                categoria_principal=self.categoria_salud,
                nombre=f"Servicio Extra {i}",
                slug=f"servicio-extra-{i}",
                distrito=self.distrito_huanuco,
            )
        response = self._get(zona="huanuco", categoria="salud")
        self.assertEqual(response.context["total_resultados"], 8)  # 7 nuevos + hospital
        self.assertEqual(len(response.context["page_obj"]), 6)

        response_p2 = self._get(zona="huanuco", categoria="salud", page="2")
        self.assertEqual(len(response_p2.context["page_obj"]), 2)

    def test_servicio_sin_imagen_no_rompe_la_card(self):
        response = self._get()
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == self.hospital.id)
        self.assertEqual(tarjeta["imagen_url"], "")

    def test_servicio_sin_telefono_no_expone_dato_para_llamar(self):
        response = self._get()
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == self.comisaria.id)
        self.assertEqual(tarjeta["telefono_tel"], "")

    def test_telefono_se_normaliza_para_tel(self):
        # "(062) 512021" -> solo dígitos, sin espacios ni paréntesis.
        response = self._get()
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == self.hospital.id)
        self.assertEqual(tarjeta["telefono_tel"], "062512021")

    def test_servicio_sin_coordenadas_ni_direccion_no_tiene_mapa(self):
        sin_ubicacion = ServicioTurista.objects.create(
            categoria_principal=self.categoria_salud,
            nombre="Servicio sin ubicación",
            slug="servicio-sin-ubicacion",
            distrito=self.distrito_huanuco,
        )
        response = self._get()
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == sin_ubicacion.id)
        self.assertIsNone(tarjeta["mapa"])

    def test_servicio_con_solo_direccion_si_tiene_mapa(self):
        response = self._get()
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == self.comisaria.id)
        self.assertIsNotNone(tarjeta["mapa"])

    def test_servicio_con_embed_maps_usa_ese_embed_no_lat_lng(self):
        # embed_maps (pegado desde "Insertar mapa" de Google) tiene prioridad
        # sobre lat/lng: así el pin muestra la ficha real del negocio
        # (nombre, calificación) en vez de un pin genérico de coordenadas.
        embed_src = "https://www.google.com/maps/embed?pb=!1m18!ficha-real"
        servicio_con_embed = ServicioTurista.objects.create(
            categoria_principal=self.categoria_salud,
            nombre="Farmacia con ficha en Google Maps",
            slug="farmacia-con-ficha-google-maps",
            distrito=self.distrito_huanuco,
            direccion="Jr. Dos de Mayo 100",
            latitud=Decimal("-9.9281900"),
            longitud=Decimal("-76.2405600"),
            embed_maps=f'<iframe src="{embed_src}" width="600" height="450"></iframe>',
        )
        response = self._get()
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == servicio_con_embed.id)
        self.assertEqual(tarjeta["mapa"]["embed_url"], embed_src)

    def test_servicio_veinticuatro_horas_muestra_atencion_24h(self):
        response = self._get()
        tarjeta = next(t for t in response.context["tarjetas"] if t["id"] == self.hospital.id)
        self.assertEqual(tarjeta["disponibilidad_texto"], "Atención 24 h")

    def test_cta_usa_namespace_emergencias(self):
        response = self._get()
        self.assertContains(response, reverse("emergencias:emergencias"))

    def test_card_no_muestra_horario_visible(self):
        # hospital y comisaria tienen dirección: antes del refinamiento,
        # cada card emitía dos filas "su-card__dato" (dirección + horario).
        # Ahora la card solo debe mostrar dirección: una fila por card.
        response = self._get()
        contenido = response.content.decode()
        self.assertEqual(contenido.count('class="su-card__dato"'), 2)

    def test_modal_info_recibe_horario_para_hidratar(self):
        # El horario no se ve en la card, pero sí debe llegar al modal vía
        # json_script (data-info-fila="horario" existe para que el JS lo
        # muestre/oculte según el dato real).
        response = self._get()
        self.assertContains(response, 'data-info-fila="horario"')
        self.assertContains(response, 'id="su-servicios-data"')


class ContactosYEnlacesTests(DatosTerritorialesMixin, TestCase):
    """ContactoServicioTurista + ServicioTurista.telefono consolidados, y
    enlaces oficiales (sitio_web/facebook/instagram) para el modal."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")

        cls.servicio = ServicioTurista.objects.create(
            categoria_principal=cls.categoria,
            nombre="Hospital Regional Hermilio Valdizán",
            slug="hospital-regional-hermilio-valdizan",
            distrito=cls.distrito_huanuco,
            direccion="Av. principal 123",
            telefono="(062) 512400",
            sitio_web="https://hospitalhv.gob.pe",
            facebook="https://facebook.com/hospitalhv",
        )
        cls.contacto_principal = ContactoServicioTurista.objects.create(
            servicio=cls.servicio,
            tipo_contacto="celular",
            etiqueta="Emergencias",
            valor="970 814 422",
            es_principal=True,
            orden=1,
        )
        # Duplicado del mismo teléfono general, con formato distinto: no
        # debe aparecer dos veces en la lista de contactos del modal.
        cls.contacto_duplicado = ContactoServicioTurista.objects.create(
            servicio=cls.servicio,
            tipo_contacto="telefono",
            etiqueta="Central",
            valor="062512400",
            orden=2,
        )

        cls.servicio_sin_extras = ServicioTurista.objects.create(
            categoria_principal=cls.categoria,
            nombre="Comisaría de Huánuco",
            slug="comisaria-huanuco",
            distrito=cls.distrito_huanuco,
            direccion="Jr. Huallayco 456",
            telefono="987654321",
        )

    def _get(self, **params):
        return self.client.get(reverse("servicios_turista:servicios_utiles"), params)

    def _tarjeta(self, response, servicio):
        return next(t for t in response.context["tarjetas"] if t["id"] == servicio.id)

    def test_contacto_principal_aparece_primero(self):
        response = self._get()
        tarjeta = self._tarjeta(response, self.servicio)
        self.assertEqual(tarjeta["contactos"][0]["etiqueta"], "Emergencias")
        self.assertEqual(tarjeta["contactos"][0]["valor"], "970 814 422")

    def test_deduplica_telefono_repetido_con_distinto_formato(self):
        # "(062) 512400" (ServicioTurista.telefono) y "062512400"
        # (ContactoServicioTurista "Central") son el mismo número: solo
        # debe quedar una entrada, la del ContactoServicioTurista.
        response = self._get()
        tarjeta = self._tarjeta(response, self.servicio)
        valores_tel = [c["valor_tel"] for c in tarjeta["contactos"]]
        self.assertEqual(len(valores_tel), 2)
        self.assertEqual(valores_tel.count("062512400"), 1)

    def test_telefono_llamar_usa_contacto_principal(self):
        response = self._get()
        tarjeta = self._tarjeta(response, self.servicio)
        self.assertEqual(tarjeta["telefono_tel"], "970814422")

    def test_telefono_llamar_cae_a_telefono_general_sin_contactos(self):
        response = self._get()
        tarjeta = self._tarjeta(response, self.servicio_sin_extras)
        self.assertEqual(tarjeta["telefono_tel"], "987654321")
        self.assertEqual(
            tarjeta["contactos"],
            [{"etiqueta": "", "valor": "987654321", "valor_tel": "987654321"}],
        )

    def test_enlaces_oficiales_solo_incluye_los_presentes(self):
        response = self._get()
        tarjeta = self._tarjeta(response, self.servicio)
        tipos = [e["tipo"] for e in tarjeta["enlaces"]]
        self.assertEqual(tipos, ["sitio_web", "facebook"])
        self.assertNotIn("instagram", tipos)

    def test_enlaces_oficiales_vacio_sin_ningun_dato(self):
        response = self._get()
        tarjeta = self._tarjeta(response, self.servicio_sin_extras)
        self.assertEqual(tarjeta["enlaces"], [])


class ZonaNoMapeadaTests(DatosTerritorialesMixin, TestCase):
    """Prueba arquitectónica: un distrito activo con ServicioTurista activo
    debe aparecer y ser filtrable SIN registrarse en NOMBRES_PUBLICOS_ZONA.
    El mapping es solo presentación, no una whitelist de zonas permitidas."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.distrito_churubamba = crear_distrito(
            "CHURUBAMBA", "churubamba", cls.distrito_huanuco.provincia
        )
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")
        cls.servicio_churubamba = ServicioTurista.objects.create(
            categoria_principal=cls.categoria,
            nombre="Posta de Churubamba",
            slug="posta-churubamba",
            distrito=cls.distrito_churubamba,
            direccion="Plaza principal",
        )

    def _get(self, **params):
        return self.client.get(reverse("servicios_turista:servicios_utiles"), params)

    def test_distrito_no_mapeado_no_esta_en_el_mapping(self):
        # Precondición del test: si algún día se agrega "churubamba" al
        # mapping, este test deja de probar lo que debe probar.
        self.assertNotIn("churubamba", NOMBRES_PUBLICOS_ZONA)

    def test_distrito_no_mapeado_aparece_en_el_selector(self):
        response = self._get()
        zonas_slugs = [z["slug"] for z in response.context["zonas_opciones"]]
        self.assertIn("churubamba", zonas_slugs)

    def test_distrito_no_mapeado_es_filtrable_por_slug(self):
        response = self._get(zona="churubamba")
        self.assertEqual(response.context["zona_actual_slug"], "churubamba")
        self.assertContains(response, "Posta de Churubamba")

    def test_distrito_no_mapeado_usa_nombre_oficial_como_fallback(self):
        response = self._get(zona="churubamba")
        self.assertEqual(response.context["zona_actual_nombre"], "CHURUBAMBA")
