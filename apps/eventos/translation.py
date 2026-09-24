from modeltranslation.translator import TranslationOptions, register

from .models import CategoriaEvento, Evento, ImagenEvento, RecomendacionEvento, TagExperiencia


# ponytail: Evento.nombre no se traduce (nombre propio de la festividad); se
# conserva en español. Evento.lugar sí (p. ej. "Diversos puntos de la ciudad").
@register(CategoriaEvento)
class CategoriaEventoTranslationOptions(TranslationOptions):
    fields = ("nombre", "descripcion")


@register(TagExperiencia)
class TagExperienciaTranslationOptions(TranslationOptions):
    fields = ("nombre",)


@register(Evento)
class EventoTranslationOptions(TranslationOptions):
    fields = (
        "descripcion_corta", "descripcion", "contexto_cultural", "recomendaciones",
        "descripcion_ubicacion", "lugar", "texto_alt_imagen",
    )


@register(ImagenEvento)
class ImagenEventoTranslationOptions(TranslationOptions):
    fields = ("titulo", "texto_alt")


@register(RecomendacionEvento)
class RecomendacionEventoTranslationOptions(TranslationOptions):
    fields = ("titulo", "descripcion")
