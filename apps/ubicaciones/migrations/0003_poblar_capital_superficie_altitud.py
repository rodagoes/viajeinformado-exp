from django.db import migrations

# Fuente: INEI (superficie territorial por provincia, cifra oficial replicada en
# Wikipedia y deperu.com, verificadas cruzadamente) y altitud de la capital
# provincial según fuentes institucionales/Wikipedia. La altitud de Huánuco se
# mantiene en 1894 msnm para ser consistente con el resto de la página Historia.
DATOS_PROVINCIAS = {
    "huanuco": {"capital": "Huánuco", "superficie_km2": "3591.59", "altitud_m": 1894},
    "ambo": {"capital": "Ambo", "superficie_km2": "1575.18", "altitud_m": 2076},
    "dos-de-mayo": {"capital": "La Unión", "superficie_km2": "1468.07", "altitud_m": 3210},
    "huacaybamba": {"capital": "Huacaybamba", "superficie_km2": "1743.95", "altitud_m": 3191},
    "huamalies": {"capital": "Llata", "superficie_km2": "3144.50", "altitud_m": 3436},
    "leoncio-prado": {"capital": "Tingo María", "superficie_km2": "4942.89", "altitud_m": 660},
    "maranon": {"capital": "Huacrachuco", "superficie_km2": "4801.26", "altitud_m": 2893},
    "pachitea": {"capital": "Panao", "superficie_km2": "3069.02", "altitud_m": 2772},
    "puerto-inca": {"capital": "Puerto Inca", "superficie_km2": "10341.35", "altitud_m": 210},
    "lauricocha": {"capital": "Jesús", "superficie_km2": "1860.49", "altitud_m": 3485},
    "yarowilca": {"capital": "Chavinillo", "superficie_km2": "727.47", "altitud_m": 3254},
}


def poblar_datos(apps, schema_editor):
    Provincia = apps.get_model("ubicaciones", "Provincia")
    for slug, datos in DATOS_PROVINCIAS.items():
        Provincia.objects.filter(slug=slug).update(**datos)


def revertir_datos(apps, schema_editor):
    Provincia = apps.get_model("ubicaciones", "Provincia")
    Provincia.objects.filter(slug__in=DATOS_PROVINCIAS.keys()).update(
        capital="", superficie_km2=None, altitud_m=None
    )


class Migration(migrations.Migration):

    dependencies = [
        ("ubicaciones", "0002_provincia_altitud_m_provincia_capital_and_more"),
    ]

    operations = [
        migrations.RunPython(poblar_datos, revertir_datos),
    ]
