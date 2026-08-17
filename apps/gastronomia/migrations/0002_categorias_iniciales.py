from django.db import migrations
from django.utils.text import slugify

CATEGORIAS_INICIALES = [
    "Platos de fondo",
    "Sopas y caldos",
    "Entradas",
    "Postres y dulces",
    "Bebidas tradicionales",
]


def crear_categorias(apps, schema_editor):
    CategoriaPlatoTipico = apps.get_model("gastronomia", "CategoriaPlatoTipico")
    for orden, nombre in enumerate(CATEGORIAS_INICIALES, start=1):
        CategoriaPlatoTipico.objects.get_or_create(
            nombre=nombre,
            defaults={"slug": slugify(nombre), "orden": orden},
        )


def eliminar_categorias(apps, schema_editor):
    CategoriaPlatoTipico = apps.get_model("gastronomia", "CategoriaPlatoTipico")
    CategoriaPlatoTipico.objects.filter(nombre__in=CATEGORIAS_INICIALES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gastronomia', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_categorias, eliminar_categorias),
    ]
