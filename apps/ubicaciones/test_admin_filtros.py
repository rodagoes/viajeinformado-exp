from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.establecimientos.admin import ESTABLECIMIENTO_COLUMNAS_ADMIN, ESTABLECIMIENTO_FILTROS_ADMIN, EstablecimientoAdmin
from apps.eventos.admin import EVENTO_COLUMNAS_ADMIN, EVENTO_FILTROS_ADMIN, EventoAdmin
from apps.ubicaciones.models import Departamento, Distrito, Localidad, Provincia

URL = "admin:ubicaciones_localidad_changelist"


class FiltroProvinciaDistritoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("geo-admin", "g@example.com", "x-pass-123")
        dep = Departamento.objects.create(nombre_oficial="Huánuco", slug="huanuco")
        cls.p_a = Provincia.objects.create(departamento=dep, nombre_oficial="Huánuco", slug="huanuco")
        cls.p_b = Provincia.objects.create(departamento=dep, nombre_oficial="Leoncio Prado", slug="leoncio-prado")
        cls.d_a1 = Distrito.objects.create(provincia=cls.p_a, nombre_oficial="Amarilis", slug="amarilis", codigo_inei="100102")
        cls.d_a2 = Distrito.objects.create(provincia=cls.p_a, nombre_oficial="Pillco Marca", slug="pillco-marca", codigo_inei="100111")
        cls.d_b1 = Distrito.objects.create(provincia=cls.p_b, nombre_oficial="Rupa-Rupa", slug="rupa-rupa", codigo_inei="100601")
        for d in (cls.d_a1, cls.d_a2, cls.d_b1):
            Localidad.objects.create(distrito=d, nombre=f"Loc {d.nombre_oficial}", slug=f"loc-{d.slug}", tipo="Ciudad")

    def setUp(self):
        self.client.force_login(self.admin)

    def get(self, **params):
        return self.client.get(reverse(URL), params)

    def opciones_distrito(self, response):
        """Ids de las opciones del select Distrito (el valor de cada <option> es la URL que calculó Django)."""
        filtro = next(f for f in response.context["cl"].filter_specs if f.field_path == "distrito")
        return {pk for pk, _ in filtro.lookup_choices}

    def filtro(self, response, ruta):
        return next(f for f in response.context["cl"].filter_specs if f.field_path == ruta)

    def test_etiquetas_limpias_sin_sufijo_y_con_el_mismo_id(self):
        r = self.get()
        self.assertEqual(
            dict(self.filtro(r, "distrito__provincia").lookup_choices),
            {self.p_a.pk: "Huánuco", self.p_b.pk: "Leoncio Prado"},
        )
        self.assertEqual(
            dict(self.filtro(r, "distrito").lookup_choices),
            {self.d_a1.pk: "Amarilis", self.d_a2.pk: "Pillco Marca", self.d_b1.pk: "Rupa-Rupa"},
        )
        self.assertContains(r, f"distrito__id__exact={self.d_a1.pk}")  # el valor interno sigue siendo el id real
        self.assertContains(r, ">Todas</option>")
        self.assertContains(r, ">Todos</option>")

    def test_nombres_repetidos_se_desambiguan(self):
        d_dup = Distrito.objects.create(provincia=self.p_b, nombre_oficial="Amarilis", slug="amarilis-b", codigo_inei="100699")
        etiquetas = dict(self.filtro(self.get(), "distrito").lookup_choices)
        self.assertEqual(etiquetas[self.d_a1.pk], "Amarilis (Huánuco)")
        self.assertEqual(etiquetas[d_dup.pk], "Amarilis (Leoncio Prado)")
        self.assertEqual(etiquetas[self.d_a2.pk], "Pillco Marca")

    def test_provincia_todo_lista_todos_los_distritos(self):
        self.assertEqual(self.opciones_distrito(self.get()), {self.d_a1.pk, self.d_a2.pk, self.d_b1.pk})

    def test_provincia_especifica_limita_los_distritos(self):
        r = self.get(distrito__provincia__id__exact=self.p_a.pk)
        self.assertEqual(self.opciones_distrito(r), {self.d_a1.pk, self.d_a2.pk})

    def test_provincia_y_distrito_validos_filtran(self):
        r = self.get(distrito__provincia__id__exact=self.p_a.pk, distrito__id__exact=self.d_a1.pk)
        self.assertEqual(r.context["cl"].result_count, 1)

    def test_distrito_incoherente_se_ignora_sin_error(self):
        r = self.get(distrito__provincia__id__exact=self.p_b.pk, distrito__id__exact=self.d_a1.pk)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["cl"].result_count, 1)  # solo cuenta la provincia; el distrito de otra provincia no filtra

    def test_provincia_no_numerica_no_rompe(self):
        self.assertEqual(self.get(distrito__provincia__id__exact="abc").status_code, 302)  # Django lo trata como parámetro inválido

    def test_cambiar_de_provincia_descarta_el_distrito_y_conserva_el_resto(self):
        r = self.get(
            distrito__provincia__id__exact=self.p_a.pk, distrito__id__exact=self.d_a1.pk, activo__exact=1, tipo__exact="Ciudad", o="1",
        )
        html = r.content.decode()
        opcion_b = [l for l in html.splitlines() if "<option" in l and f"distrito__provincia__id__exact={self.p_b.pk}" in l]
        self.assertTrue(opcion_b)
        self.assertNotIn("distrito__id__exact", opcion_b[0])  # el distrito anterior se descarta
        for conservado in ("activo__exact=1", "tipo__exact=Ciudad", "o=1"):
            self.assertIn(conservado, opcion_b[0])

    def test_provincia_todo_conserva_el_distrito(self):
        r = self.get(distrito__provincia__id__exact=self.p_a.pk, distrito__id__exact=self.d_a1.pk)
        todo = [l for l in r.content.decode().splitlines() if "<option" in l and "distrito__id__exact=" in l and "provincia" not in l]
        self.assertTrue(todo)

    def test_distrito_unico_en_la_provincia_sigue_visible(self):
        r = self.get(distrito__provincia__id__exact=self.p_b.pk)
        self.assertContains(r, 'data-filter-title="distrito"')


class ConfiguracionEditableTests(TestCase):
    def test_los_admin_usan_las_constantes_de_columnas_y_filtros(self):
        self.assertIs(EventoAdmin.list_display, EVENTO_COLUMNAS_ADMIN)
        self.assertIs(EventoAdmin.list_filter, EVENTO_FILTROS_ADMIN)
        self.assertIs(EstablecimientoAdmin.list_display, ESTABLECIMIENTO_COLUMNAS_ADMIN)
        self.assertIs(EstablecimientoAdmin.list_filter, ESTABLECIMIENTO_FILTROS_ADMIN)

    def test_provincia_y_distrito_son_vecinos_en_los_filtros_de_eventos(self):
        nombres = [f if isinstance(f, str) else f[0] for f in EVENTO_FILTROS_ADMIN]
        self.assertEqual(nombres.index("distrito"), nombres.index("distrito__provincia") + 1)
