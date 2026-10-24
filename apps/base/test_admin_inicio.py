from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.establecimientos.models import CategoriaEstablecimiento, Establecimiento
from apps.gastronomia.models import CategoriaPlatoTipico, PlatoTipico


class InicioAdminCardsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("inicio-admin", "a@example.com", "x-pass-123")
        cat = CategoriaEstablecimiento.objects.create(nombre="Cat", slug="cat")
        for i, (tipo, activo) in enumerate([("restaurante", True), ("restaurante", True), ("restaurante", False), ("alojamiento", True)]):
            Establecimiento.objects.create(tipo=tipo, categoria_principal=cat, nombre=f"E{i}", slug=f"e{i}", activo=activo)
        cat_plato = CategoriaPlatoTipico.objects.create(nombre="Platos", slug="platos")
        PlatoTipico.objects.create(categoria=cat_plato, nombre="Pachamanca", slug="pachamanca")

    def cards(self, usuario):
        self.client.force_login(usuario)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        return response, {c["titulo"]: c for c in response.context["cards"]}

    def test_cinco_cards_con_conteos_reales_y_enlaces(self):
        response, cards = self.cards(self.admin)
        self.assertEqual(list(cards), ["Restaurantes", "Alojamientos", "Lugares turísticos", "Eventos", "Platos típicos"])
        self.assertEqual((cards["Restaurantes"]["activos"], cards["Restaurantes"]["inactivos"]), (2, 1))
        self.assertEqual(cards["Alojamientos"]["activos"], 1)
        self.assertEqual(cards["Platos típicos"]["activos"], 1)
        self.assertEqual(cards["Eventos"]["activos"], 0)  # total 0 no rompe
        self.assertEqual(
            cards["Restaurantes"]["url"],
            reverse("admin:establecimientos_establecimiento_changelist") + "?tipo__exact=restaurante&activo__exact=1",
        )
        lista = self.client.get(cards["Restaurantes"]["url"])
        self.assertEqual(lista.context["cl"].result_count, 2)  # el número de la card coincide con el listado
        self.assertContains(response, 'class="vi-card"', count=5)
        contenido = response.content.decode().split('id="content-main"')[1]
        self.assertNotIn("app-auth", contenido)  # el catálogo de apps ya no está en el contenido (sigue en el sidebar)

    def test_sin_permiso_no_hay_card(self):
        staff = get_user_model().objects.create_user("sin-permisos", password="x-pass-123", is_staff=True)
        response, cards = self.cards(staff)
        self.assertEqual(cards, {})
