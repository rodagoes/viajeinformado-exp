from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.establecimientos.models import CategoriaEstablecimiento, Establecimiento
from apps.gastronomia.models import (
    CategoriaPlatoTipico,
    IngredienteClavePlato,
    PlatoEstablecimiento,
    PlatoTipico,
)


def crear_establecimiento(nombre="Recreo La Perricholi", tipo="restaurante"):
    categoria = CategoriaEstablecimiento.objects.create(nombre=f"Cat {nombre}", slug=f"cat-{nombre}".lower())
    return Establecimiento.objects.create(
        tipo=tipo,
        categoria_principal=categoria,
        nombre=nombre,
        slug=nombre.lower().replace(" ", "-"),
        activo=True,
    )


class ModelosTests(TestCase):
    def test_creacion_categoria_y_plato(self):
        categoria = CategoriaPlatoTipico.objects.create(nombre="Fondo Test", slug="fondo-test")
        plato = PlatoTipico.objects.create(
            categoria=categoria,
            nombre="Pachamanca huanuqueña",
            slug="pachamanca-huanuquena",
            es_plato_bandera=True,
        )
        self.assertEqual(str(plato), "Pachamanca huanuqueña")
        self.assertTrue(plato.es_plato_bandera)

    def test_ingredientes_ordenados(self):
        categoria = CategoriaPlatoTipico.objects.create(nombre="Sopas", slug="sopas")
        plato = PlatoTipico.objects.create(categoria=categoria, nombre="Locro", slug="locro")
        IngredienteClavePlato.objects.create(plato=plato, nombre="Papas", orden=2)
        IngredienteClavePlato.objects.create(plato=plato, nombre="Cerdo", orden=1)
        nombres = list(plato.ingredientes.order_by("orden").values_list("nombre", flat=True))
        self.assertEqual(nombres, ["Cerdo", "Papas"])

    def test_relacion_plato_establecimiento(self):
        categoria = CategoriaPlatoTipico.objects.create(nombre="Fondo", slug="fondo")
        plato = PlatoTipico.objects.create(categoria=categoria, nombre="Juane", slug="juane")
        establecimiento = crear_establecimiento()
        relacion = PlatoEstablecimiento.objects.create(plato=plato, establecimiento=establecimiento)
        self.assertIn(establecimiento, plato.establecimientos.all())
        self.assertEqual(str(relacion), f"{establecimiento.nombre} - {plato.nombre}")

    def test_no_permite_duplicar_relacion(self):
        categoria = CategoriaPlatoTipico.objects.create(nombre="Fondo2", slug="fondo2")
        plato = PlatoTipico.objects.create(categoria=categoria, nombre="Tacacho", slug="tacacho")
        establecimiento = crear_establecimiento(nombre="Restaurante Uno")
        PlatoEstablecimiento.objects.create(plato=plato, establecimiento=establecimiento)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PlatoEstablecimiento.objects.create(plato=plato, establecimiento=establecimiento)

    def test_no_permite_relacionar_alojamiento(self):
        categoria = CategoriaPlatoTipico.objects.create(nombre="Fondo3", slug="fondo3")
        plato = PlatoTipico.objects.create(categoria=categoria, nombre="Cuy", slug="cuy")
        alojamiento = crear_establecimiento(nombre="Hotel Uno", tipo="alojamiento")
        relacion = PlatoEstablecimiento(plato=plato, establecimiento=alojamiento)
        with self.assertRaises(ValidationError):
            relacion.full_clean()


class VistaPlatosTipicosTests(TestCase):
    def setUp(self):
        self.cat_fondo = CategoriaPlatoTipico.objects.create(nombre="Fondo", slug="fondo", orden=1)
        self.cat_postres = CategoriaPlatoTipico.objects.create(nombre="Postres", slug="postres", orden=2)
        self.plato_activo = PlatoTipico.objects.create(
            categoria=self.cat_fondo, nombre="Pachamanca", slug="pachamanca", activo=True
        )
        self.plato_inactivo = PlatoTipico.objects.create(
            categoria=self.cat_fondo, nombre="Inactivo", slug="inactivo", activo=False
        )
        self.plato_postre = PlatoTipico.objects.create(
            categoria=self.cat_postres, nombre="Mazamorra", slug="mazamorra", activo=True
        )

    def test_responde_200(self):
        response = self.client.get(reverse("gastronomia:platos_tipicos"))
        self.assertEqual(response.status_code, 200)

    def test_solo_muestra_platos_activos(self):
        response = self.client.get(reverse("gastronomia:platos_tipicos"))
        platos = list(response.context["page_obj"])
        self.assertIn(self.plato_activo, platos)
        self.assertNotIn(self.plato_inactivo, platos)

    def test_filtra_por_categoria(self):
        response = self.client.get(reverse("gastronomia:platos_tipicos"), {"categoria": "postres"})
        platos = list(response.context["page_obj"])
        self.assertEqual(platos, [self.plato_postre])

    def test_categoria_inexistente_no_rompe(self):
        response = self.client.get(reverse("gastronomia:platos_tipicos"), {"categoria": "no-existe"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["categoria_sel"], "")


class DondeComerTests(TestCase):
    def setUp(self):
        categoria = CategoriaPlatoTipico.objects.create(nombre="Fondo", slug="fondo")
        self.plato = PlatoTipico.objects.create(categoria=categoria, nombre="Pachamanca", slug="pachamanca")
        self.restaurante_con_plato = crear_establecimiento(nombre="Recreo Uno")
        self.restaurante_sin_plato = crear_establecimiento(nombre="Recreo Dos")
        self.alojamiento = crear_establecimiento(nombre="Hotel Uno", tipo="alojamiento")
        PlatoEstablecimiento.objects.create(plato=self.plato, establecimiento=self.restaurante_con_plato)

    def test_filtra_por_plato_valido(self):
        response = self.client.get(reverse("establecimientos:listado_restaurantes"), {"plato": "pachamanca"})
        establecimientos = [e for e in response.context["page_obj"]]
        self.assertIn(self.restaurante_con_plato, establecimientos)
        self.assertNotIn(self.restaurante_sin_plato, establecimientos)

    def test_no_devuelve_alojamientos(self):
        response = self.client.get(reverse("establecimientos:listado_restaurantes"), {"plato": "pachamanca"})
        establecimientos = [e for e in response.context["page_obj"]]
        self.assertNotIn(self.alojamiento, establecimientos)

    def test_no_devuelve_establecimientos_inactivos(self):
        self.restaurante_con_plato.activo = False
        self.restaurante_con_plato.save()
        response = self.client.get(reverse("establecimientos:listado_restaurantes"), {"plato": "pachamanca"})
        establecimientos = [e for e in response.context["page_obj"]]
        self.assertNotIn(self.restaurante_con_plato, establecimientos)

    def test_plato_invalido_no_causa_error_500(self):
        response = self.client.get(reverse("establecimientos:listado_restaurantes"), {"plato": "no-existe"})
        self.assertEqual(response.status_code, 200)

    def test_preserva_filtro_al_cambiar_orden(self):
        response = self.client.get(
            reverse("establecimientos:listado_restaurantes"), {"plato": "pachamanca", "orden": "nombre_asc"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["plato_sel"], "pachamanca")
        self.assertEqual(response.context["orden_sel"], "nombre_asc")
