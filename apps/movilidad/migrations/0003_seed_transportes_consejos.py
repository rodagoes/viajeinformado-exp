from decimal import Decimal

from django.db import migrations

TRANSPORTES = [
    {
        "slug": "mototaxi",
        "nombre": "Mototaxi",
        "nombre_alternativo": "Bajaj",
        "descripcion": "Ideal para trayectos cortos dentro de la ciudad.",
        "tarifa_minima": Decimal("3.00"),
        "orden": 1,
    },
    {
        "slug": "colectivos",
        "nombre": "Colectivos",
        "nombre_alternativo": "",
        "descripcion": "Transporte compartido en rutas urbanas.",
        "tarifa_minima": Decimal("2.00"),
        "orden": 2,
    },
    {
        "slug": "microbuses",
        "nombre": "Microbuses",
        "nombre_alternativo": "Micro(s)",
        "descripcion": "Cubre más rutas y sectores de la ciudad.",
        "tarifa_minima": Decimal("1.00"),
        "orden": 3,
    },
]

CONSEJOS = [
    (1, "Lleva siempre efectivo en soles para facilitar tus pagos."),
    (2, "Si es tu primera vez en la ciudad, consulta las tarifas antes de abordar."),
    (3, "Procura no olvidar tus pertenencias en los medios de transporte."),
    (4, "Evita movilizarte muy tarde en zonas poco iluminadas."),
    (5, "Pide ayuda a los locales si tienes dudas sobre rutas o tarifas."),
]


def seed(apps, schema_editor):
    TransportePublico = apps.get_model("movilidad", "TransportePublico")
    ConsejoMovilidad = apps.get_model("movilidad", "ConsejoMovilidad")

    for data in TRANSPORTES:
        data = dict(data)
        slug = data.pop("slug")
        TransportePublico.objects.get_or_create(slug=slug, defaults=data)

    for orden, texto in CONSEJOS:
        ConsejoMovilidad.objects.get_or_create(texto=texto, defaults={"orden": orden})


def unseed(apps, schema_editor):
    TransportePublico = apps.get_model("movilidad", "TransportePublico")
    ConsejoMovilidad = apps.get_model("movilidad", "ConsejoMovilidad")

    TransportePublico.objects.filter(
        slug__in=[t["slug"] for t in TRANSPORTES]
    ).delete()
    ConsejoMovilidad.objects.filter(
        texto__in=[texto for _orden, texto in CONSEJOS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("movilidad", "0002_consejomovilidad_transportepublico"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
