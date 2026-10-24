import uuid

from django.db import migrations, models


def asignar_uuid(apps, schema_editor):
    """Cada sesión ya existente recibe su propio UUID (un default único reutilizado violaría el índice único)."""
    Sesion = apps.get_model("metricas", "SesionMetrica")
    for pk in Sesion.objects.values_list("pk", flat=True):
        Sesion.objects.filter(pk=pk).update(uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ("metricas", "0002_generacion_simulada"),
    ]

    operations = [
        migrations.AddField(
            model_name="sesionmetrica",
            name="uuid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(asignar_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sesionmetrica",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
