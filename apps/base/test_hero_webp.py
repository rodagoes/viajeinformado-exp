import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from .models import HomeHeroSlide


def _subida(nombre, formato, tam=(2400, 1200)):
    buf = BytesIO()
    Image.new("RGB", tam, (10, 120, 200)).save(buf, formato)
    return SimpleUploadedFile(nombre, buf.getvalue())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class HeroWebpTests(TestCase):
    def crear(self, archivo, **extra):
        return HomeHeroSlide.objects.create(
            etiqueta="e", titulo_principal="t", titulo_resaltado="r", descripcion="d", archivo=archivo, **extra)

    def test_imagen_subida_se_guarda_como_webp_y_se_reduce(self):
        slide = self.crear(_subida("hero.png", "PNG"))
        self.assertTrue(slide.archivo.name.endswith(".webp"))
        with Image.open(slide.archivo.path) as img:
            self.assertEqual(img.format, "WEBP")
            self.assertEqual(img.size, (1600, 800))

    def test_no_recomprime_al_guardar_de_nuevo(self):
        slide = self.crear(_subida("hero.png", "PNG", (800, 400)))
        nombre = slide.archivo.name
        slide.save()
        self.assertEqual(slide.archivo.name, nombre)

    def test_gif_no_se_convierte(self):
        slide = self.crear(_subida("anim.gif", "GIF", (100, 50)), tipo_archivo="gif")
        self.assertTrue(slide.archivo.name.endswith(".gif"))

    def test_editar_otros_campos_no_toca_la_imagen(self):
        slide = self.crear(_subida("hero.png", "PNG", (800, 400)))
        with open(slide.archivo.path, "rb") as f:
            antes = f.read()
        slide = HomeHeroSlide.objects.get(pk=slide.pk)
        slide.titulo_principal = "otro"
        slide.save()
        with open(slide.archivo.path, "rb") as f:
            self.assertEqual(f.read(), antes)

    def test_archivo_ilegible_se_guarda_tal_cual(self):
        slide = self.crear(SimpleUploadedFile("roto.png", b"no es una imagen"))
        self.assertTrue(slide.archivo.name.endswith(".png"))
        with open(slide.archivo.path, "rb") as f:
            self.assertEqual(f.read(), b"no es una imagen")

    def test_conserva_transparencia(self):
        buf = BytesIO()
        Image.new("RGBA", (100, 50), (0, 0, 0, 0)).save(buf, "PNG")
        slide = self.crear(SimpleUploadedFile("t.png", buf.getvalue()))
        with Image.open(slide.archivo.path) as img:
            self.assertIn("A", img.getbands())
