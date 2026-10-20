import html as html_lib
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

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


def paginador(html):
    """Extrae del HTML el <nav> del componente compartido vi-paginacion: (tag nav, <li> como dicts)."""
    m = re.search(r'<nav[^>]*vi-paginacion-contenedor[^>]*>(.*?)</nav>', html, re.S)
    if not m:
        return None, []
    items = []
    for li in re.findall(r'<li class="([^"]*)"([^>]*)>(.*?)</li>', m.group(1), re.S):
        clases, extra, interior = li
        enlace = re.search(r'<a class="page-link" href="([^"]+)"(?: aria-label="([^"]*)")?', interior)
        texto = html_lib.unescape(re.sub(r"<[^>]+>", "", interior)).strip()
        items.append({
            "solo_desktop": "page-number--solo-desktop" in clases.split(),
            "disabled": "disabled" in clases.split(),
            "numero": "page-number" in clases.split(),
            "activo": "active" in clases.split(),
            "aria_current": 'aria-current="page"' in extra,
            "href": enlace.group(1).replace("&amp;", "&") if enlace else None,
            "label": enlace.group(2) if enlace and enlace.group(2) else (re.search(r'aria-label="([^"]*)"', interior) or [None, None])[1],
            "aria_disabled": 'aria-disabled="true"' in interior,
            "texto": texto,
        })
    return m.group(0), items


class PaginacionPlatosTipicosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fondo = CategoriaPlatoTipico.objects.create(nombre="Fondo", slug="fondo", orden=1)
        cls.postres = CategoriaPlatoTipico.objects.create(nombre="Postres", slug="postres", orden=2)
        cls.platos_fondo = [
            PlatoTipico.objects.create(categoria=cls.fondo, nombre=f"Fondo {i:02d}", slug=f"fondo-{i:02d}") for i in range(20)
        ]  # 20 de fondo → 3 páginas de 9
        for i in range(3):
            PlatoTipico.objects.create(categoria=cls.postres, nombre=f"Postre {i}", slug=f"postre-{i}")

    def get(self, **params):
        return self.client.get(reverse("gastronomia:platos_tipicos"), params)

    def test_usa_el_componente_compartido_con_primera_y_ultima(self):
        r = self.get(categoria="fondo")
        self.assertContains(r, "assets/css/componentes/paginacion.css")
        nav, items = paginador(r.content.decode())
        self.assertIn("d-flex justify-content-center vi-paginacion-contenedor", nav)
        self.assertIn('<ul class="pagination vi-paginacion">', nav)
        self.assertEqual([i["texto"] for i in items], ["«", "‹", "1", "2", "3", "›", "»"])
        self.assertNotIn("pt-pagination", nav)

    def test_pagina_1_y_ultima_deshabilitan_sus_controles(self):
        _, p1 = paginador(self.get(categoria="fondo").content.decode())
        self.assertEqual([i["disabled"] for i in p1], [True, True, False, False, False, False, False])
        self.assertTrue(all(i["href"] is None and i["aria_disabled"] for i in p1[:2]))
        self.assertEqual([i["texto"] for i in p1 if i["aria_current"]], ["1"])
        _, p3 = paginador(self.get(categoria="fondo", page="3").content.decode())
        self.assertEqual([i["disabled"] for i in p3], [False, False, False, False, False, True, True])
        _, p2 = paginador(self.get(categoria="fondo", page="2").content.decode())
        self.assertFalse(any(i["disabled"] for i in p2))
        self.assertEqual([i["texto"] for i in p2 if i["aria_current"]], ["2"])

    def test_el_filtro_de_categoria_persiste_y_sin_filtro_no_se_agrega(self):
        _, items = paginador(self.get(categoria="fondo", page="2").content.decode())
        hrefs = [i["href"] for i in items if i["href"]]
        self.assertEqual(len(hrefs), 6)
        self.assertTrue(all(h.endswith("&categoria=fondo") for h in hrefs), hrefs)
        self.assertEqual([i["href"] for i in items if i["texto"] == "»"], ["?page=3&categoria=fondo"])
        _, sin = paginador(self.get(page="2").content.decode())
        self.assertTrue(all("categoria" not in i["href"] for i in sin if i["href"]))

    def test_nueve_por_pagina_sin_repetir_ni_perder_platos(self):
        vistos = []
        for pagina in (1, 2, 3):
            r = self.get(categoria="fondo", page=str(pagina))
            self.assertEqual(r.context["total_resultados"], 20)
            vistos += [p.pk for p in r.context["page_obj"]]
        self.assertEqual([9, 9, 2], [len(self.get(categoria="fondo", page=str(n)).context["page_obj"]) for n in (1, 2, 3)])
        self.assertEqual(sorted(vistos), sorted(p.pk for p in self.platos_fondo))
        self.assertEqual(len(set(vistos)), 20)

    def test_en_movil_solo_activa_y_vecinas_inmediatas(self):
        for i in range(30):
            PlatoTipico.objects.create(categoria=self.fondo, nombre=f"Extra {i:02d}", slug=f"extra-{i:02d}")  # 50 → 6 páginas
        _, items = paginador(self.get(categoria="fondo", page="3").content.decode())
        numeros = [i for i in items if i["numero"]]
        self.assertEqual([i["texto"] for i in numeros], ["1", "2", "3", "4", "5"])
        self.assertEqual([i["texto"] for i in numeros if not i["solo_desktop"]], ["2", "3", "4"])

    def test_sin_mas_de_una_pagina_no_hay_paginador(self):
        self.assertIsNone(paginador(self.get(categoria="postres").content.decode())[0])

    def test_paginas_invalidas_conservan_el_comportamiento(self):
        self.assertEqual(self.get(categoria="fondo", page="999").context["page_obj"].number, 3)
        self.assertEqual(self.get(categoria="fondo", page="abc").context["page_obj"].number, 1)

    def test_etiquetas_en_ingles(self):
        self.addCleanup(translation.activate, "es")
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        _, items = paginador(self.get(categoria="fondo", page="2").content.decode())
        self.assertEqual([i["label"] for i in items if i["texto"] in "«‹›»"], ["First", "Previous", "Next", "Last"])
