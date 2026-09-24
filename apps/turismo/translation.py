from modeltranslation.translator import TranslationOptions, register

from .models import (
    CategoriaLugarTuristico, ImagenLugarTuristico, LugarTuristico,
    RecomendacionLugarTuristico, ServicioLugarTuristico,
)


# ponytail: LugarTuristico.nombre (nombre propio), direccion, embed_maps y
# maps_url no se traducen; conservan su valor original.
@register(CategoriaLugarTuristico)
class CategoriaLugarTuristicoTranslationOptions(TranslationOptions):
    fields = ("nombre", "descripcion")


@register(ServicioLugarTuristico)
class ServicioLugarTuristicoTranslationOptions(TranslationOptions):
    fields = ("nombre", "descripcion")


@register(LugarTuristico)
class LugarTuristicoTranslationOptions(TranslationOptions):
    fields = (
        "descripcion_corta", "descripcion", "historia", "texto_alt_imagen_historia",
        "referencia", "horario_visita", "tiempo_visita_estimado", "recomendaciones",
        "como_llegar", "texto_alt_imagen",
    )


@register(ImagenLugarTuristico)
class ImagenLugarTuristicoTranslationOptions(TranslationOptions):
    fields = ("titulo", "descripcion", "texto_alt")


@register(RecomendacionLugarTuristico)
class RecomendacionLugarTuristicoTranslationOptions(TranslationOptions):
    fields = ("titulo", "descripcion")
