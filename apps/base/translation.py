from modeltranslation.translator import TranslationOptions, register

from .models import HomeHeroSlide


@register(HomeHeroSlide)
class HomeHeroSlideTranslationOptions(TranslationOptions):
    fields = ("etiqueta", "titulo_principal", "titulo_resaltado", "descripcion", "texto_alt")
