from modeltranslation.translator import TranslationOptions, register

from .models import CategoriaPlatoTipico, IngredienteClavePlato, PlatoTipico


# ponytail: PlatoTipico.nombre (nombre del plato) no se traduce.
@register(CategoriaPlatoTipico)
class CategoriaPlatoTipicoTranslationOptions(TranslationOptions):
    fields = ("nombre",)


@register(PlatoTipico)
class PlatoTipicoTranslationOptions(TranslationOptions):
    fields = ("descripcion_corta", "texto_alt_imagen")


@register(IngredienteClavePlato)
class IngredienteClavePlatoTranslationOptions(TranslationOptions):
    fields = ("nombre",)
