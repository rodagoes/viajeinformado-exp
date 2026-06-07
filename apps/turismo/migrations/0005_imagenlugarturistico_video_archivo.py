from django.core.validators import FileExtensionValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("turismo", "0004_recomendacionlugarturistico"),
    ]

    operations = [
        migrations.AddField(
            model_name="imagenlugarturistico",
            name="video_archivo",
            field=models.FileField(
                blank=True,
                help_text="Archivo MP4 del lugar turístico. Úsalo solo cuando el tipo sea Video MP4.",
                upload_to="turismo/lugares/videos/",
                validators=[FileExtensionValidator(allowed_extensions=["mp4"])],
            ),
        ),
        migrations.AlterField(
            model_name="imagenlugarturistico",
            name="tipo_media",
            field=models.CharField(
                choices=[
                    ("imagen", "Imagen / GIF"),
                    ("video", "Video externo"),
                    ("video_archivo", "Video MP4"),
                ],
                default="imagen",
                max_length=20,
                verbose_name="Tipo de multimedia",
            ),
        ),
        migrations.AlterField(
            model_name="imagenlugarturistico",
            name="imagen",
            field=models.ImageField(
                blank=True,
                help_text="Imagen del lugar turístico. Permite JPG, JPEG, PNG, WEBP o GIF. Si es GIF, máximo 15 segundos.",
                upload_to="turismo/lugares/galeria/",
                validators=[
                    FileExtensionValidator(
                        allowed_extensions=["jpg", "jpeg", "png", "webp", "gif"]
                    )
                ],
            ),
        ),
    ]
