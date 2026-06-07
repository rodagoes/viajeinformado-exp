from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("turismo", "0002_add_embed_maps_and_maps_url_to_lugar"),
    ]

    operations = [
        migrations.AddField(
            model_name="lugarturistico",
            name="imagen_historia",
            field=models.ImageField(
                blank=True,
                help_text="Imagen antigua o histórica del lugar. Ejemplo: foto antigua de la plaza.",
                upload_to="turismo/lugares/historia/",
            ),
        ),
        migrations.AddField(
            model_name="lugarturistico",
            name="texto_alt_imagen_historia",
            field=models.CharField(
                blank=True,
                help_text="Texto alternativo para la imagen histórica.",
                max_length=180,
            ),
        ),
        migrations.AddField(
            model_name="imagenlugarturistico",
            name="tipo_media",
            field=models.CharField(
                choices=[("imagen", "Imagen"), ("video", "Video externo")],
                default="imagen",
                max_length=20,
                verbose_name="Tipo de multimedia",
            ),
        ),
        migrations.AddField(
            model_name="imagenlugarturistico",
            name="video_url",
            field=models.URLField(
                blank=True,
                help_text="URL de YouTube, Vimeo u otro video externo. Requerida cuando el tipo es Video externo.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="imagenlugarturistico",
            name="descripcion",
            field=models.TextField(
                blank=True,
                help_text="Descripción breve opcional para la galería.",
            ),
        ),
        migrations.AlterField(
            model_name="imagenlugarturistico",
            name="imagen",
            field=models.ImageField(
                blank=True,
                help_text="Imagen del lugar turístico. Requerida cuando el tipo es Imagen.",
                upload_to="turismo/lugares/galeria/",
            ),
        ),
        migrations.AlterModelOptions(
            name="imagenlugarturistico",
            options={
                "ordering": ["lugar__nombre", "orden", "id"],
                "verbose_name": "Multimedia de lugar turístico",
                "verbose_name_plural": "Multimedia de lugares turísticos",
            },
        ),
    ]
