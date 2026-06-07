from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("turismo", "0003_lugar_imagen_historia_multimedia_video"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecomendacionLugarTuristico",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("titulo", models.CharField(help_text="Título corto del consejo. Ejemplo: Mejor horario para visitar.", max_length=140)),
                ("descripcion", models.TextField(help_text="Detalle breve de la recomendación. Evita textos largos; idealmente 1 o 2 líneas.")),
                ("icono_bootstrap", models.CharField(blank=True, default="bi bi-check-circle", help_text="Ejemplo: bi bi-camera, bi bi-shield-check, bi bi-sunrise", max_length=80)),
                ("orden", models.PositiveIntegerField(default=0)),
                ("activo", models.BooleanField(default=True)),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("actualizado", models.DateTimeField(auto_now=True)),
                ("lugar", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recomendaciones_items", to="turismo.lugarturistico", verbose_name="Lugar turístico")),
            ],
            options={
                "verbose_name": "Recomendación de lugar turístico",
                "verbose_name_plural": "Recomendaciones de lugares turísticos",
                "ordering": ["lugar__nombre", "orden", "id"],
            },
        ),
    ]
