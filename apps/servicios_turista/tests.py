from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.ubicaciones.models import Departamento, Distrito, Provincia

from .models import (
    CategoriaServicioTurista,
    ContactoServicioTurista,
    ImagenServicioTurista,
    SedeServicioTurista,
    ServicioTurista,
)
from .services.contactos import contactos_de_sede, telefono_llamar
from .services.zonas import NOMBRES_PUBLICOS_ZONA, nombre_publico_zona


def crear_distrito(nombre_oficial, slug, provincia):
    return Distrito.objects.create(
        provincia=provincia,
        nombre_oficial=nombre_oficial,
        slug=slug,
        codigo_inei=slug[:6].ljust(6, "0"),
    )


def crear_sede(categoria, nombre, distrito, slug=None, *, servicio_kw=None, sede_nombre="", **sede_kw):
    """Crea entidad + una sede y devuelve la sede (la tarjeta es una por sede)."""
    servicio = ServicioTurista.objects.create(
        categoria_principal=categoria,
        nombre=nombre,
        slug=slug or nombre.lower().replace(" ", "-"),
        **(servicio_kw or {}),
    )
    return SedeServicioTurista.objects.create(servicio=servicio, nombre=sede_nombre, distrito=distrito, **sede_kw)


def agregar_sede(servicio, distrito, **kw):
    return SedeServicioTurista.objects.create(servicio=servicio, distrito=distrito, **kw)


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

        cls.hospital = crear_sede(
            cls.categoria_salud, "Hospital Regional Hermilio Valdizán", cls.distrito_huanuco,
            slug="hospital-regional-hermilio-valdizan",
            direccion="Av. principal 123",
            latitud=Decimal("-9.9281900"),
            longitud=Decimal("-76.2405600"),
            telefono="(062) 512021",
            disponibilidad="veinticuatro_horas",
        )
        cls.comisaria = crear_sede(
            cls.categoria_seguridad, "Comisaría de Huánuco", cls.distrito_huanuco,
            slug="comisaria-huanuco",
            direccion="Jr. Huallayco 456",
            horario_atencion="Lunes a domingo: 24 horas",
        )
        cls.servicio_tingo_maria = crear_sede(
            cls.categoria_salud, "Centro de Salud Tingo María", cls.distrito_rupa_rupa,
            slug="centro-salud-tingo-maria", direccion="Jr. Raimondi 789",
        )
        cls.servicio_inactivo = crear_sede(
            cls.categoria_salud, "Servicio inactivo de prueba", cls.distrito_huanuco,
            slug="servicio-inactivo-prueba", servicio_kw={"activo": False},
        )

    def _get(self, **params):
        return self.client.get(reverse("servicios_turista:servicios_utiles"), params)

    def _tarjeta(self, response, sede):
        return next(t for t in response.context["tarjetas"] if t["id"] == sede.id)

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
        # tienen ninguna sede activa en este set de datos.
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
            crear_sede(
                self.categoria_salud, f"Servicio Extra {i}", self.distrito_huanuco, slug=f"servicio-extra-{i}"
            )
        response = self._get(zona="huanuco", categoria="salud")
        self.assertEqual(response.context["total_resultados"], 8)  # 7 nuevos + hospital
        self.assertEqual(len(response.context["page_obj"]), 6)

        response_p2 = self._get(zona="huanuco", categoria="salud", page="2")
        self.assertEqual(len(response_p2.context["page_obj"]), 2)

    def test_servicio_sin_imagen_no_rompe_la_card(self):
        tarjeta = self._tarjeta(self._get(), self.hospital)
        self.assertEqual(tarjeta["imagen_url"], "")

    def test_servicio_sin_telefono_no_expone_dato_para_llamar(self):
        tarjeta = self._tarjeta(self._get(), self.comisaria)
        self.assertEqual(tarjeta["telefono_tel"], "")

    def test_telefono_se_normaliza_para_tel(self):
        # "(062) 512021" -> solo dígitos, sin espacios ni paréntesis.
        tarjeta = self._tarjeta(self._get(), self.hospital)
        self.assertEqual(tarjeta["telefono_tel"], "062512021")

    def test_servicio_sin_coordenadas_ni_direccion_no_tiene_mapa(self):
        sin_ubicacion = crear_sede(
            self.categoria_salud, "Servicio sin ubicación", self.distrito_huanuco, slug="servicio-sin-ubicacion"
        )
        tarjeta = self._tarjeta(self._get(), sin_ubicacion)
        self.assertIsNone(tarjeta["mapa"])

    def test_servicio_con_solo_direccion_si_tiene_mapa(self):
        tarjeta = self._tarjeta(self._get(), self.comisaria)
        self.assertIsNotNone(tarjeta["mapa"])

    def test_servicio_con_embed_maps_usa_ese_embed_no_lat_lng(self):
        # embed_maps (pegado desde "Insertar mapa" de Google) tiene prioridad
        # sobre lat/lng: así el pin muestra la ficha real del negocio.
        embed_src = "https://www.google.com/maps/embed?pb=!1m18!ficha-real"
        con_embed = crear_sede(
            self.categoria_salud, "Farmacia con ficha en Google Maps", self.distrito_huanuco,
            slug="farmacia-con-ficha-google-maps",
            direccion="Jr. Dos de Mayo 100",
            latitud=Decimal("-9.9281900"),
            longitud=Decimal("-76.2405600"),
            embed_maps=f'<iframe src="{embed_src}" width="600" height="450"></iframe>',
        )
        tarjeta = self._tarjeta(self._get(), con_embed)
        self.assertEqual(tarjeta["mapa"]["embed_url"], embed_src)

    def test_maps_url_se_abre_tal_cual_y_la_ruta_usa_las_coordenadas_del_admin(self):
        # Ver test_mapas_sede.py para la prioridad completa (ficha, pin, iframe, dirección).
        sede = crear_sede(
            self.categoria_salud, "Con ficha", self.distrito_huanuco, slug="con-ficha",
            direccion="Jr. X 1", latitud=Decimal("-9.9"), longitud=Decimal("-76.2"),
            maps_url="https://www.google.com/maps/place/Con+ficha/@-9.93,-76.24,17z/data=!3d-9.93!4d-76.24",
        )
        mapa = self._tarjeta(self._get(), sede)["mapa"]
        self.assertEqual(mapa["open_url"], sede.maps_url)
        self.assertIn("destination=-9.9000000%2C-76.2000000", mapa["route_url"])
        self.assertEqual(mapa["precision"], "pin_admin")

    def test_servicio_veinticuatro_horas_muestra_atencion_24h(self):
        tarjeta = self._tarjeta(self._get(), self.hospital)
        self.assertEqual(tarjeta["disponibilidad_texto"], "Atención 24 h")

    def test_cta_usa_namespace_emergencias(self):
        response = self._get()
        self.assertContains(response, reverse("emergencias:emergencias"))

    def test_card_no_muestra_horario_visible(self):
        # hospital y comisaria tienen dirección: la card solo muestra
        # dirección, una fila por card.
        contenido = self._get().content.decode()
        self.assertEqual(contenido.count('class="su-card__dato"'), 2)

    def test_modal_info_recibe_horario_para_hidratar(self):
        response = self._get()
        self.assertContains(response, 'data-info-fila="horario"')
        self.assertContains(response, 'id="su-servicios-data"')

    def test_claves_de_tarjeta_y_contexto_estables(self):
        response = self._get()
        for clave in ("zona_actual_slug", "zonas_opciones", "categorias_opciones", "total_resultados",
                      "tarjetas", "tarjetas_con_mapa", "hay_resultados", "page_obj"):
            self.assertIn(clave, response.context)
        self.assertEqual(
            set(self._tarjeta(response, self.hospital)),
            {"id", "nombre", "categoria", "descripcion_corta", "direccion", "disponibilidad_texto",
             "telefono_tel", "contactos", "enlaces", "imagen_url", "imagen_alt", "mapa"},
        )

    def test_proxy_de_mapa_usa_el_id_de_la_sede(self):
        response = self._get()
        self.assertContains(response, f'data-servicio-id="{self.hospital.id}"')


class EntidadConVariasSedesTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bancos = CategoriaServicioTurista.objects.create(nombre="Bancos", slug="bancos")
        cls.salud = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")
        cls.banco = ServicioTurista.objects.create(
            categoria_principal=cls.bancos, nombre="Banco de la Nación", slug="banco-de-la-nacion",
            descripcion_corta="Banco del Estado", sitio_web="https://www.bn.com.pe",
        )
        cls.agencias = [
            agregar_sede(cls.banco, cls.distrito_huanuco, nombre=f"Agencia {i}", direccion=f"Jr. Prueba {i}")
            for i in range(1, 5)
        ]
        cls.agencia_ambo = agregar_sede(cls.banco, cls.distrito_ambo, nombre="Agencia Ambo", direccion="Plaza Ambo")
        cls.sede_unica = crear_sede(cls.salud, "Comisaría de Huánuco", cls.distrito_huanuco, slug="comisaria-huanuco",
                                    direccion="Jr. Huallayco 456")

    def _get(self, **params):
        return self.client.get(reverse("servicios_turista:servicios_utiles"), params)

    def test_cuatro_sedes_en_el_mismo_distrito_son_cuatro_tarjetas_y_contador_cuatro(self):
        response = self._get(zona="huanuco", categoria="bancos")
        self.assertEqual(response.context["total_resultados"], 4)
        ids = [t["id"] for t in response.context["tarjetas"]]
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual(
            [t["nombre"] for t in response.context["tarjetas"]],
            [f"Banco de la Nación - Agencia {i}" for i in range(1, 5)],
        )

    def test_las_sedes_comparten_datos_de_la_entidad(self):
        for tarjeta in self._get(zona="huanuco", categoria="bancos").context["tarjetas"]:
            self.assertEqual(tarjeta["descripcion_corta"], "Banco del Estado")
            self.assertEqual(tarjeta["categoria"], "Bancos")
            self.assertEqual([e["tipo"] for e in tarjeta["enlaces"]], ["sitio_web"])

    def test_sedes_en_varias_zonas_y_todas(self):
        self.assertEqual(self._get(zona="ambo").context["total_resultados"], 1)
        self.assertEqual(self._get(zona="huanuco").context["total_resultados"], 5)  # 4 agencias + comisaría
        self.assertEqual(self._get(zona="todas").context["total_resultados"], 6)

    def test_sede_generica_no_lleva_sufijo(self):
        tarjeta = self._get(zona="huanuco", categoria="salud").context["tarjetas"][0]
        self.assertEqual(tarjeta["nombre"], "Comisaría de Huánuco")

    def test_sede_inactiva_desaparece_solo_ella(self):
        self.agencias[0].activo = False
        self.agencias[0].save()
        self.assertEqual(self._get(zona="huanuco", categoria="bancos").context["total_resultados"], 3)

    def test_entidad_inactiva_oculta_todas_sus_sedes_y_zonas(self):
        self.banco.activo = False
        self.banco.save()
        self.assertEqual(self._get(zona="todas", categoria="bancos").context["total_resultados"], 0)
        zonas = [z["slug"] for z in self._get().context["zonas_opciones"]]
        self.assertNotIn("ambo", zonas)

    def test_categoria_secundaria_encuentra_todas_las_sedes_sin_duplicar(self):
        self.banco.categorias_secundarias.add(self.salud)
        response = self._get(zona="huanuco", categoria="salud")
        self.assertEqual(response.context["total_resultados"], 5)  # 4 agencias + comisaría, sin duplicados

    def test_paginacion_de_seis_con_sedes(self):
        for i in range(5, 9):
            agregar_sede(self.banco, self.distrito_huanuco, nombre=f"Agencia {i}")
        response = self._get(zona="huanuco", categoria="bancos")
        self.assertEqual(response.context["total_resultados"], 8)
        self.assertEqual(len(response.context["page_obj"]), 6)


class ContactosYEnlacesTests(DatosTerritorialesMixin, TestCase):
    """Contactos de sede + contactos generales + teléfonos consolidados, y
    enlaces oficiales (sitio_web/facebook/instagram) para el modal."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")

        cls.sede = crear_sede(
            cls.categoria, "Hospital Regional Hermilio Valdizán", cls.distrito_huanuco,
            slug="hospital-regional-hermilio-valdizan",
            direccion="Av. principal 123",
            servicio_kw={
                "telefono": "(062) 512400",
                "sitio_web": "https://hospitalhv.gob.pe",
                "facebook": "https://facebook.com/hospitalhv",
            },
        )
        cls.servicio = cls.sede.servicio
        cls.contacto_principal = ContactoServicioTurista.objects.create(
            servicio=cls.servicio, sede=cls.sede, tipo_contacto="celular", etiqueta="Emergencias",
            valor="970 814 422", es_principal=True, orden=1,
        )
        # Duplicado del teléfono general de la entidad, con formato distinto.
        cls.contacto_duplicado = ContactoServicioTurista.objects.create(
            servicio=cls.servicio, tipo_contacto="telefono", etiqueta="Central", valor="062512400", orden=2,
        )

        cls.sede_sin_extras = crear_sede(
            cls.categoria, "Comisaría de Huánuco", cls.distrito_huanuco, slug="comisaria-huanuco",
            direccion="Jr. Huallayco 456", telefono="987654321",
        )

    def _tarjeta(self, sede):
        response = self.client.get(reverse("servicios_turista:servicios_utiles"))
        return next(t for t in response.context["tarjetas"] if t["id"] == sede.id)

    def test_contacto_de_la_sede_aparece_primero(self):
        tarjeta = self._tarjeta(self.sede)
        self.assertEqual(tarjeta["contactos"][0]["etiqueta"], "Emergencias")
        self.assertEqual(tarjeta["contactos"][0]["valor"], "970 814 422")

    def test_deduplica_telefono_repetido_con_distinto_formato(self):
        # "(062) 512400" (ServicioTurista.telefono) y "062512400" (contacto
        # general "Central") son el mismo número: solo una entrada.
        valores_tel = [c["valor_tel"] for c in self._tarjeta(self.sede)["contactos"]]
        self.assertEqual(len(valores_tel), 2)
        self.assertEqual(valores_tel.count("062512400"), 1)

    def test_telefono_llamar_usa_contacto_principal_de_la_sede(self):
        self.assertEqual(self._tarjeta(self.sede)["telefono_tel"], "970814422")

    def test_telefono_de_sede_prevalece_sobre_el_de_la_entidad(self):
        sede = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Anexo", telefono="062 111 222")
        self.assertEqual(telefono_llamar(sede), "062111222")
        self.assertEqual([c["valor"] for c in contactos_de_sede(sede)][:2], ["062 111 222", "062512400"])

    def test_sede_sin_telefono_hereda_los_contactos_generales(self):
        sede = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Otra")
        valores = [c["valor"] for c in contactos_de_sede(sede)]
        self.assertEqual(valores, ["062512400"])  # general; el teléfono de entidad es el mismo número

    def test_contactos_de_otra_sede_no_se_filtran(self):
        otra = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Otra")
        self.assertNotIn("970 814 422", [c["valor"] for c in contactos_de_sede(otra)])

    def test_telefono_llamar_cae_a_telefono_de_sede_sin_contactos(self):
        tarjeta = self._tarjeta(self.sede_sin_extras)
        self.assertEqual(tarjeta["telefono_tel"], "987654321")
        self.assertEqual(
            tarjeta["contactos"],
            [{"etiqueta": "", "valor": "987654321", "valor_tel": "987654321"}],
        )

    def test_contacto_inactivo_no_se_muestra(self):
        ContactoServicioTurista.objects.create(
            servicio=self.servicio, tipo_contacto="correo", valor="info@hospital.pe", activo=False,
        )
        self.assertNotIn("info@hospital.pe", [c["valor"] for c in self._tarjeta(self.sede)["contactos"]])

    def test_enlaces_oficiales_solo_incluye_los_presentes(self):
        tipos = [e["tipo"] for e in self._tarjeta(self.sede)["enlaces"]]
        self.assertEqual(tipos, ["sitio_web", "facebook"])
        self.assertNotIn("instagram", tipos)

    def test_enlaces_oficiales_vacio_sin_ningun_dato(self):
        self.assertEqual(self._tarjeta(self.sede_sin_extras)["enlaces"], [])


class ZonaNoMapeadaTests(DatosTerritorialesMixin, TestCase):
    """Prueba arquitectónica: un distrito activo con una sede activa debe
    aparecer y ser filtrable SIN registrarse en NOMBRES_PUBLICOS_ZONA."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.distrito_churubamba = crear_distrito(
            "CHURUBAMBA", "churubamba", cls.distrito_huanuco.provincia
        )
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")
        cls.sede_churubamba = crear_sede(
            cls.categoria, "Posta de Churubamba", cls.distrito_churubamba,
            slug="posta-churubamba", direccion="Plaza principal",
        )

    def _get(self, **params):
        return self.client.get(reverse("servicios_turista:servicios_utiles"), params)

    def test_distrito_no_mapeado_no_esta_en_el_mapping(self):
        self.assertNotIn("churubamba", NOMBRES_PUBLICOS_ZONA)

    def test_distrito_no_mapeado_aparece_en_el_selector(self):
        zonas_slugs = [z["slug"] for z in self._get().context["zonas_opciones"]]
        self.assertIn("churubamba", zonas_slugs)

    def test_distrito_no_mapeado_es_filtrable_por_slug(self):
        response = self._get(zona="churubamba")
        self.assertEqual(response.context["zona_actual_slug"], "churubamba")
        self.assertContains(response, "Posta de Churubamba")

    def test_distrito_no_mapeado_usa_nombre_oficial_como_fallback(self):
        self.assertEqual(self._get(zona="churubamba").context["zona_actual_nombre"], "CHURUBAMBA")


class SedeSlugYValidacionTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Bancos", slug="bancos")
        cls.servicio = ServicioTurista.objects.create(
            categoria_principal=cls.categoria, nombre="Banco de la Nación", slug="banco-de-la-nacion"
        )
        cls.otro = ServicioTurista.objects.create(
            categoria_principal=cls.categoria, nombre="BCP", slug="bcp"
        )

    def test_sede_sin_nombre_recibe_slug_principal(self):
        self.assertEqual(agregar_sede(self.servicio, self.distrito_huanuco).slug, "principal")

    def test_sedes_sin_nombre_repetidas_reciben_sufijos(self):
        slugs = [agregar_sede(self.servicio, self.distrito_huanuco).slug for _ in range(3)]
        self.assertEqual(slugs, ["principal", "principal-2", "principal-3"])

    def test_slug_sin_tildes_y_nombres_repetidos(self):
        a = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Sucursal Huánuco")
        b = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Sucursal Huánuco")
        self.assertEqual((a.slug, b.slug), ("sucursal-huanuco", "sucursal-huanuco-2"))

    def test_mismo_slug_permitido_en_otra_entidad(self):
        a = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Centro")
        b = agregar_sede(self.otro, self.distrito_huanuco, nombre="Centro")
        self.assertEqual(a.slug, b.slug)

    def test_slug_estable_al_renombrar(self):
        sede = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Agencia Ambo")
        sede.nombre = "Agencia Ambo Centro"
        sede.save()
        sede.refresh_from_db()
        self.assertEqual(sede.slug, "agencia-ambo")

    def test_bd_rechaza_slug_repetido_en_la_misma_entidad(self):
        agregar_sede(self.servicio, self.distrito_huanuco, nombre="Centro")
        with self.assertRaises(IntegrityError), transaction.atomic():
            SedeServicioTurista.objects.create(
                servicio=self.servicio, distrito=self.distrito_huanuco, nombre="x", slug="centro"
            )

    def test_mismo_nombre_y_distrito_son_validos(self):
        agregar_sede(self.servicio, self.distrito_huanuco, nombre="Agencia", direccion="Jr. A 1").full_clean()
        sede = SedeServicioTurista(
            servicio=self.servicio, distrito=self.distrito_huanuco, nombre="Agencia", direccion="Jr. B 2"
        )
        sede.full_clean()  # no lanza

    def test_misma_direccion_en_el_mismo_distrito_se_rechaza(self):
        agregar_sede(self.servicio, self.distrito_huanuco, nombre="A", direccion="Jr. A 1")
        repetida = SedeServicioTurista(
            servicio=self.servicio, distrito=self.distrito_huanuco, nombre="B", direccion="jr. a 1"
        )
        with self.assertRaises(ValidationError):
            repetida.full_clean()

    def test_misma_direccion_en_otra_entidad_es_valida(self):
        agregar_sede(self.servicio, self.distrito_huanuco, direccion="Jr. A 1")
        SedeServicioTurista(servicio=self.otro, distrito=self.distrito_huanuco, direccion="Jr. A 1").full_clean()

    def test_coordenadas_incompletas_se_rechazan(self):
        sede = SedeServicioTurista(servicio=self.servicio, distrito=self.distrito_huanuco, latitud=Decimal("-9.9"))
        with self.assertRaises(ValidationError):
            sede.full_clean()

    def test_nombre_publico(self):
        con = agregar_sede(self.servicio, self.distrito_huanuco, nombre="Agencia Ambo")
        sin = agregar_sede(self.otro, self.distrito_huanuco)
        self.assertEqual(con.nombre_publico, "Banco de la Nación - Agencia Ambo")
        self.assertEqual(sin.nombre_publico, "BCP")


class IntegridadContactosTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Bancos", slug="bancos")
        cls.servicio = ServicioTurista.objects.create(
            categoria_principal=cls.categoria, nombre="Banco", slug="banco"
        )
        cls.otro_servicio = ServicioTurista.objects.create(
            categoria_principal=cls.categoria, nombre="BCP", slug="bcp"
        )
        cls.sede = agregar_sede(cls.servicio, cls.distrito_huanuco, nombre="A")
        cls.sede2 = agregar_sede(cls.servicio, cls.distrito_huanuco, nombre="B")
        cls.sede_ajena = agregar_sede(cls.otro_servicio, cls.distrito_huanuco, nombre="C")

    def test_save_completa_la_entidad_desde_la_sede(self):
        contacto = ContactoServicioTurista.objects.create(sede=self.sede, tipo_contacto="telefono", valor="062111111")
        self.assertEqual(contacto.servicio_id, self.servicio.id)

    def test_sede_de_otra_entidad_se_rechaza(self):
        contacto = ContactoServicioTurista(
            servicio=self.servicio, sede=self.sede_ajena, tipo_contacto="telefono", valor="062222222"
        )
        with self.assertRaises(ValidationError):
            contacto.full_clean()

    def test_mismo_numero_no_se_repite_en_la_entidad(self):
        ContactoServicioTurista.objects.create(sede=self.sede, tipo_contacto="telefono", valor="062333333")
        repetido = ContactoServicioTurista(servicio=self.servicio, sede=self.sede2, tipo_contacto="telefono", valor="062333333")
        with self.assertRaises(ValidationError):
            repetido.full_clean()

    def test_un_principal_por_tipo_y_por_nivel(self):
        ContactoServicioTurista.objects.create(
            sede=self.sede, tipo_contacto="telefono", valor="062444444", es_principal=True
        )
        # Misma sede y tipo: rechazado.
        mismo_nivel = ContactoServicioTurista(
            servicio=self.servicio, sede=self.sede, tipo_contacto="telefono", valor="062555555", es_principal=True
        )
        with self.assertRaises(ValidationError):
            mismo_nivel.full_clean()
        # Otra sede y nivel entidad: permitido.
        ContactoServicioTurista(
            servicio=self.servicio, sede=self.sede2, tipo_contacto="telefono", valor="062666666", es_principal=True
        ).full_clean()
        ContactoServicioTurista(
            servicio=self.servicio, tipo_contacto="telefono", valor="062777777", es_principal=True
        ).full_clean()

    def test_borrar_sede_borra_sus_contactos_pero_no_los_generales(self):
        ContactoServicioTurista.objects.create(sede=self.sede, tipo_contacto="telefono", valor="062888888")
        general = ContactoServicioTurista.objects.create(
            servicio=self.servicio, tipo_contacto="telefono", valor="062999999"
        )
        self.sede.delete()
        self.assertEqual(list(ContactoServicioTurista.objects.values_list("pk", flat=True)), [general.pk])


class AdminSedesTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Bancos", slug="bancos")
        cls.admin = get_user_model().objects.create_superuser("admin", "a@example.com", "Clave-admin-123")

    def setUp(self):
        self.client.force_login(self.admin)

    def _datos_entidad(self, **extra):
        datos = {
            "categoria_principal": self.categoria.pk,
            "nombre": "Banco de la Nación",
            "slug": "banco-de-la-nacion",
            "tipo_atencion": "presencial",
            "sedes-TOTAL_FORMS": "1", "sedes-INITIAL_FORMS": "0", "sedes-MIN_NUM_FORMS": "1", "sedes-MAX_NUM_FORMS": "1000",
            "sedes-0-nombre": "Agencia Ambo", "sedes-0-distrito": self.distrito_ambo.pk,
            "sedes-0-direccion": "Plaza Ambo", "sedes-0-activo": "on",
            "contactos-TOTAL_FORMS": "0", "contactos-INITIAL_FORMS": "0",
            "contactos-MIN_NUM_FORMS": "0", "contactos-MAX_NUM_FORMS": "1000",
        }
        datos.update(extra)
        return datos

    def test_paginas_de_admin_responden(self):
        for ruta in ("servicioturista", "sedeservicioturista"):
            self.assertEqual(self.client.get(f"/admin/servicios_turista/{ruta}/").status_code, 200)
            self.assertEqual(self.client.get(f"/admin/servicios_turista/{ruta}/add/").status_code, 200)

    def test_formulario_de_entidad_no_muestra_campos_fisicos(self):
        html = self.client.get("/admin/servicios_turista/servicioturista/add/").content.decode()
        for campo in ("name=\"direccion\"", "name=\"latitud\"", "name=\"embed_maps\"", "name=\"notas"):
            self.assertNotIn(campo, html)
        self.assertIn('name="sedes-0-direccion"', html)

    def test_alta_de_entidad_con_su_primera_sede(self):
        respuesta = self.client.post("/admin/servicios_turista/servicioturista/add/", self._datos_entidad())
        self.assertEqual(respuesta.status_code, 302, getattr(respuesta, "context", None) and respuesta.context["errors"])
        sede = SedeServicioTurista.objects.get()
        self.assertEqual((sede.servicio.slug, sede.slug, sede.nombre_publico),
                         ("banco-de-la-nacion", "agencia-ambo", "Banco de la Nación - Agencia Ambo"))

    def test_entidad_nueva_sin_sede_se_rechaza(self):
        respuesta = self.client.post(
            "/admin/servicios_turista/servicioturista/add/",
            self._datos_entidad(**{"sedes-TOTAL_FORMS": "0"}),
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(ServicioTurista.objects.exists())

    def test_lista_muestra_sedes_activas_y_total(self):
        servicio = ServicioTurista.objects.create(categoria_principal=self.categoria, nombre="BCP", slug="bcp")
        agregar_sede(servicio, self.distrito_huanuco, nombre="A")
        agregar_sede(servicio, self.distrito_huanuco, nombre="B", activo=False)
        self.assertContains(self.client.get("/admin/servicios_turista/servicioturista/"), "1 / 2")

    def test_contactos_de_sede_solo_al_editar(self):
        servicio = ServicioTurista.objects.create(categoria_principal=self.categoria, nombre="BCP", slug="bcp")
        sede = agregar_sede(servicio, self.distrito_huanuco, nombre="A")
        self.assertNotContains(self.client.get("/admin/servicios_turista/sedeservicioturista/add/"), "contactos-TOTAL_FORMS")
        self.assertContains(
            self.client.get(f"/admin/servicios_turista/sedeservicioturista/{sede.pk}/change/"), "contactos-TOTAL_FORMS"
        )


class LimpiezaServiciosUtilesTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.categoria = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")
        cls.sede = crear_sede(cls.categoria, "Hospital", cls.distrito_huanuco, slug="hospital")
        ContactoServicioTurista.objects.create(servicio=cls.sede.servicio, sede=cls.sede, tipo_contacto="telefono", valor="062123456")
        ImagenServicioTurista.objects.create(servicio=cls.sede.servicio, imagen="servicios_turista/galeria/x.png")

    def _correr(self, *args):
        salida = StringIO()
        call_command("limpiar_servicios_utiles", *args, stdout=salida)
        return salida.getvalue()

    def _nombre_bd(self):
        from django.db import connection
        return connection.settings_dict["NAME"]

    def test_por_defecto_solo_simula(self):
        salida = self._correr()
        self.assertIn("SIMULACIÓN", salida)
        self.assertEqual(
            (ServicioTurista.objects.count(), SedeServicioTurista.objects.count(),
             ContactoServicioTurista.objects.count(), ImagenServicioTurista.objects.count()),
            (1, 1, 1, 1),
        )

    def test_confirmacion_incorrecta_no_borra(self):
        with self.assertRaises(CommandError):
            self._correr("--confirmar", "otra_bd")
        self.assertEqual(ServicioTurista.objects.count(), 1)

    def test_confirmacion_correcta_borra_solo_servicios_utiles(self):
        salida = self._correr("--confirmar", self._nombre_bd())
        self.assertIn("Limpieza completada", salida)
        self.assertEqual(
            (ServicioTurista.objects.count(), SedeServicioTurista.objects.count(),
             ContactoServicioTurista.objects.count(), ImagenServicioTurista.objects.count()),
            (0, 0, 0, 0),
        )
        # No toca categorías ni la jerarquía territorial.
        self.assertEqual(CategoriaServicioTurista.objects.count(), 1)
        self.assertTrue(Distrito.objects.filter(slug="huanuco").exists())
