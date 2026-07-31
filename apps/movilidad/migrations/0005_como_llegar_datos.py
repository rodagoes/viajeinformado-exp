from decimal import Decimal

from django.db import migrations

CATEGORIAS = [
    {
        "slug": "via-terrestre",
        "nombre": "Vía terrestre",
        "icono_bootstrap": "bi-bus-front-fill",
    },
    {
        "slug": "via-aerea",
        "nombre": "Vía aérea",
        "icono_bootstrap": "bi-airplane-fill",
    },
]

CONSEJOS_TERRESTRES = [
    (1, "Verifica el estado de la carretera antes de viajar."),
    (2, "Si viajas en bus, reserva con anticipación durante feriados."),
    (3, "Lleva ropa de abrigo para los tramos de mayor altitud."),
    (4, "Los tiempos pueden variar por el clima, el tráfico o el estado de la vía."),
]

CONSEJOS_AEREOS = [
    (1, "Confirma la programación del vuelo antes de dirigirte al aeropuerto."),
    (2, "Llega con anticipación y revisa las condiciones de equipaje."),
    (3, "La disponibilidad de vuelos puede variar."),
    (4, "Organiza con anticipación tu traslado desde el aeropuerto."),
]

RUTAS_TERRESTRES = [
    {
        "orden": 1,
        "nombre": "Lima – La Oroya – Huánuco",
        "slug": "lima-la-oroya-huanuco",
        "origen_texto": "Lima",
        "destino_texto": "Huánuco",
        "distancia_km": Decimal("410"),
    },
    {
        "orden": 2,
        "nombre": "Lima – Canta – Huayllay – Huánuco",
        "slug": "lima-canta-huayllay-huanuco",
        "origen_texto": "Lima",
        "destino_texto": "Huánuco",
        "distancia_km": Decimal("378"),
    },
    {
        "orden": 3,
        "nombre": "Pucallpa – Tingo María – Huánuco",
        "slug": "pucallpa-tingo-maria-huanuco",
        "origen_texto": "Pucallpa",
        "destino_texto": "Huánuco",
        "distancia_km": Decimal("367"),
    },
    {
        "orden": 4,
        "nombre": "Huaraz – La Unión – Huánuco",
        "slug": "huaraz-la-union-huanuco",
        "origen_texto": "Huaraz",
        "destino_texto": "Huánuco",
        "distancia_km": Decimal("347"),
    },
    {
        "orden": 5,
        "nombre": "Tarapoto – Tocache – Tingo María – Huánuco",
        "slug": "tarapoto-tocache-tingo-maria-huanuco",
        "origen_texto": "Tarapoto",
        "destino_texto": "Huánuco",
        "distancia_km": Decimal("594"),
    },
]

RUTA_AEREA = {
    "orden": 1,
    "nombre": "Lima – Huánuco",
    "slug": "lima-huanuco-aereo",
    "origen_texto": "Lima",
    "destino_texto": "Huánuco",
    "punto_partida": "Aeropuerto Internacional Jorge Chávez",
    "punto_llegada": "Aeropuerto Alférez FAP David Figueroa Fernandini",
    "duracion_estimada": "45 a 60 minutos",
}


def seed(apps, schema_editor):
    CategoriaMovilidad = apps.get_model("movilidad", "CategoriaMovilidad")
    ConsejoMovilidad = apps.get_model("movilidad", "ConsejoMovilidad")
    RutaMovilidad = apps.get_model("movilidad", "RutaMovilidad")

    categorias = {}
    for data in CATEGORIAS:
        data = dict(data)
        slug = data.pop("slug")
        categoria, _ = CategoriaMovilidad.objects.get_or_create(
            slug=slug, defaults={**data, "slug": slug}
        )
        categorias[slug] = categoria

    # Los consejos ya sembrados en 0003 quedan asociados a "Transporte y tarifas".
    ConsejoMovilidad.objects.update(seccion="tarifas_taxi")

    for orden, texto in CONSEJOS_TERRESTRES:
        ConsejoMovilidad.objects.get_or_create(
            texto=texto,
            seccion="como_llegar_terrestre",
            defaults={"orden": orden},
        )

    for orden, texto in CONSEJOS_AEREOS:
        ConsejoMovilidad.objects.get_or_create(
            texto=texto,
            seccion="como_llegar_aerea",
            defaults={"orden": orden},
        )

    categoria_terrestre = categorias["via-terrestre"]
    for data in RUTAS_TERRESTRES:
        data = dict(data)
        slug = data.pop("slug")
        RutaMovilidad.objects.get_or_create(
            slug=slug,
            defaults={
                **data,
                "seccion": "como_llegar",
                "categoria_principal": categoria_terrestre,
                "activo": True,
            },
        )

    categoria_aerea = categorias["via-aerea"]
    data = dict(RUTA_AEREA)
    slug = data.pop("slug")
    RutaMovilidad.objects.get_or_create(
        slug=slug,
        defaults={
            **data,
            "seccion": "como_llegar",
            "categoria_principal": categoria_aerea,
            "activo": True,
        },
    )


def unseed(apps, schema_editor):
    CategoriaMovilidad = apps.get_model("movilidad", "CategoriaMovilidad")
    ConsejoMovilidad = apps.get_model("movilidad", "ConsejoMovilidad")
    RutaMovilidad = apps.get_model("movilidad", "RutaMovilidad")

    slugs = [r["slug"] for r in RUTAS_TERRESTRES] + [RUTA_AEREA["slug"]]
    RutaMovilidad.objects.filter(slug__in=slugs).delete()

    textos_como_llegar = [t for _o, t in CONSEJOS_TERRESTRES] + [t for _o, t in CONSEJOS_AEREOS]
    ConsejoMovilidad.objects.filter(
        seccion__in=["como_llegar_terrestre", "como_llegar_aerea"],
        texto__in=textos_como_llegar,
    ).delete()

    CategoriaMovilidad.objects.filter(
        slug__in=[c["slug"] for c in CATEGORIAS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("movilidad", "0004_como_llegar_campos"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
