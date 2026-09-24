"""Utilidad para las migraciones de django-modeltranslation.

Al añadir las columnas `campo_es`/`campo_en`, los datos que ya existían (o que
otra migración sembró) solo están en la columna original. `poblar_es` copia ese
valor a `campo_es` dentro de la propia migración: así los consultas en español
(que leen `campo_es`) encuentran los datos existentes y no hace falta acordarse
de ejecutar `update_translation_fields` en cada entorno.
"""
from django.db.models import F


def poblar_es(especificacion):
    """RunPython (forward) para `{("app", "Modelo"): ("campo", ...)}`.

    Idempotente: solo rellena `campo_es` donde todavía es NULL.
    """

    def forward(apps, schema_editor):
        for (app_label, model_name), campos in especificacion.items():
            modelo = apps.get_model(app_label, model_name)
            for campo in campos:
                modelo.objects.filter(**{f"{campo}_es__isnull": True}).update(**{f"{campo}_es": F(campo)})

    return forward
