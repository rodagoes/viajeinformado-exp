"""Paginador de Servicios útiles: mismo componente que Restaurantes/Alojamientos, misma lógica de paginación."""
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from .models import CategoriaServicioTurista
from .tests import DatosTerritorialesMixin, crear_sede

import html as html_lib
import re


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


class PaginacionServiciosUtilesTests(DatosTerritorialesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.salud = CategoriaServicioTurista.objects.create(nombre="Salud", slug="salud")
        cls.seguridad = CategoriaServicioTurista.objects.create(nombre="Seguridad", slug="seguridad")
        # 14 de salud en Huánuco (3 páginas de 6), 3 de seguridad (1 página), 2 de salud en Amarilis.
        cls.sedes_salud = [crear_sede(cls.salud, f"Clínica {i:02d}", cls.distrito_huanuco, slug=f"clinica-{i:02d}", direccion=f"Jr. {i}") for i in range(14)]
        for i in range(3):
            crear_sede(cls.seguridad, f"Comisaría {i}", cls.distrito_huanuco, slug=f"comisaria-{i}", direccion=f"Av. {i}")
        for i in range(2):
            crear_sede(cls.salud, f"Posta {i}", cls.distrito_amarilis, slug=f"posta-{i}", direccion=f"Pje. {i}")

    def get(self, **params):
        return self.client.get(reverse("servicios_turista:servicios_utiles"), params)

    def test_usa_el_componente_compartido(self):
        r = self.get(zona="huanuco")
        self.assertContains(r, "assets/css/componentes/paginacion.css")
        nav, items = paginador(r.content.decode())
        self.assertIn('aria-label="Navegación de páginas"', nav)
        self.assertIn("d-flex justify-content-center vi-paginacion-contenedor", nav)
        self.assertIn('<ul class="pagination vi-paginacion">', nav)
        self.assertTrue(any(i["numero"] for i in items))

    def test_pagina_1_deshabilita_primera_y_anterior(self):
        _, items = paginador(self.get(zona="huanuco", categoria="salud").content.decode())
        self.assertEqual([i["texto"] for i in items], ["«", "‹", "1", "2", "3", "›", "»"])
        self.assertEqual([i["disabled"] for i in items], [True, True, False, False, False, False, False])
        for i in items[:2]:
            self.assertIsNone(i["href"])  # sin enlace engañoso
            self.assertTrue(i["aria_disabled"])
        self.assertEqual([i["activo"] for i in items], [False, False, True, False, False, False, False])
        self.assertEqual([i["label"] for i in items if i["texto"] in "«‹›»"], ["Primera", "Anterior", "Siguiente", "Última"])

    def test_pagina_intermedia_todos_los_enlaces_y_aria_current(self):
        _, items = paginador(self.get(zona="huanuco", categoria="salud", page="2").content.decode())
        self.assertFalse(any(i["disabled"] for i in items))
        self.assertEqual([i["texto"] for i in items if i["aria_current"]], ["2"])
        hrefs = [i["href"] for i in items if i["href"]]
        self.assertEqual(len(hrefs), 6)

    def test_ultima_pagina_deshabilita_siguiente_y_ultima(self):
        _, items = paginador(self.get(zona="huanuco", categoria="salud", page="3").content.decode())
        self.assertEqual([i["disabled"] for i in items], [False, False, False, False, False, True, True])
        self.assertEqual([i["texto"] for i in items if i["aria_current"]], ["3"])

    def test_los_filtros_persisten_en_todos_los_enlaces(self):
        _, items = paginador(self.get(zona="huanuco", categoria="salud", page="2").content.decode())
        for i in items:
            if i["href"]:
                self.assertIn("zona=huanuco", i["href"], i["href"])
                self.assertIn("categoria=salud", i["href"], i["href"])
        self.assertEqual([i["href"] for i in items if i["texto"] == "»"], ["?zona=huanuco&categoria=salud&page=3"])
        self.assertEqual([i["href"] for i in items if i["texto"] == "«"], ["?zona=huanuco&categoria=salud&page=1"])

    def test_sin_categoria_solo_persiste_la_zona(self):
        _, items = paginador(self.get(zona="todas").content.decode())
        for i in items:
            if i["href"]:
                self.assertTrue(i["href"].startswith("?zona=todas&page="), i["href"])
                self.assertNotIn("categoria", i["href"])

    def test_sin_resultados_de_mas_de_una_pagina_no_hay_paginador(self):
        self.assertIsNone(paginador(self.get(zona="huanuco", categoria="seguridad").content.decode())[0])
        self.assertIsNone(paginador(self.get(zona="amarilis").content.decode())[0])

    def test_navegacion_completa_sin_repetir_ni_perder_resultados(self):
        vistos = []
        for pagina in (1, 2, 3):
            r = self.get(zona="huanuco", categoria="salud", page=str(pagina))
            self.assertEqual(r.context["total_resultados"], 14)
            self.assertContains(r, "14 coincidencias encontradas")
            vistos += [t["id"] for t in r.context["tarjetas"]]
        self.assertEqual(len(vistos), 14)
        self.assertEqual(sorted(vistos), sorted(s.id for s in self.sedes_salud))

    def test_paginas_invalidas_conservan_el_comportamiento(self):
        self.assertEqual(self.get(zona="huanuco", categoria="salud", page="999").context["page_obj"].number, 3)
        self.assertEqual(self.get(zona="huanuco", categoria="salud", page="abc").context["page_obj"].number, 1)
        self.assertEqual(self.get(zona="huanuco", categoria="salud", page="-1").status_code, 200)

    def test_en_movil_solo_activa_y_vecinas_inmediatas(self):
        # 40 sedes de una sola categoría → 7 páginas; en la 4 deben verse (móvil) 3, 4 y 5.
        for i in range(26):
            crear_sede(self.salud, f"Extra {i:02d}", self.distrito_huanuco, slug=f"extra-{i:02d}", direccion=f"Extra {i}")
        _, items = paginador(self.get(zona="huanuco", categoria="salud", page="4").content.decode())
        numeros = [i for i in items if i["numero"]]
        self.assertEqual([i["texto"] for i in numeros], ["2", "3", "4", "5", "6"])  # escritorio: ventana de 5
        self.assertEqual([i["texto"] for i in numeros if not i["solo_desktop"]], ["3", "4", "5"])  # móvil: 3
        _, items = paginador(self.get(zona="huanuco", categoria="salud", page="1").content.decode())
        self.assertEqual([i["texto"] for i in items if i["numero"] and not i["solo_desktop"]], ["1", "2"])

    def test_seis_por_pagina(self):
        self.assertEqual(len(self.get(zona="huanuco", categoria="salud").context["tarjetas"]), 6)
        self.assertEqual(len(self.get(zona="huanuco", categoria="salud", page="3").context["tarjetas"]), 2)

    def test_etiquetas_en_ingles(self):
        self.addCleanup(translation.activate, "es")
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        nav, items = paginador(self.get(zona="huanuco", categoria="salud", page="2").content.decode())
        self.assertIn('aria-label="Page navigation"', nav)
        self.assertEqual([i["label"] for i in items if i["texto"] in "«‹›»"], ["First", "Previous", "Next", "Last"])
        _, items = paginador(self.get(zona="huanuco", categoria="salud").content.decode())
        self.assertEqual([i["label"] for i in items if i["texto"] in "«‹"], ["First", "Previous"])  # deshabilitados también con etiqueta

    def test_css_acotado_a_la_pagina_y_sin_estilos_globales_de_pagination(self):
        from pathlib import Path
        css = (Path(settings.BASE_DIR) / "static/assets/css/servicios-utiles.css").read_text(encoding="utf-8")
        trozo = css[css.index("---- Paginación ----"):]
        for linea in trozo.splitlines():
            if linea.strip().startswith(".") and "{" in linea:
                self.assertTrue(linea.strip().startswith((".servicios-utiles-page", ".su-layout", "@media")) or linea.strip().startswith("."), linea)
                self.assertNotIn(".pagination", linea.replace(".vi-paginacion", ""), linea)
