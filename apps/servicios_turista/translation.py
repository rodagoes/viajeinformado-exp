from modeltranslation.translator import TranslationOptions, register

from .models import (
    CategoriaServicioTurista, ContactoServicioTurista, ImagenServicioTurista, ServicioTurista,
)


# ponytail: ServicioTurista.nombre (nombre propio del hospital/comisaría/botica),
# direcciones, teléfonos y mapas no se traducen.
@register(CategoriaServicioTurista)
class CategoriaServicioTuristaTranslationOptions(TranslationOptions):
    fields = ("nombre", "descripcion")


@register(ServicioTurista)
class ServicioTuristaTranslationOptions(TranslationOptions):
    fields = (
        "descripcion_corta", "descripcion", "referencia", "horario_atencion",
        "recomendaciones", "notas", "texto_alt_imagen",
    )


@register(ContactoServicioTurista)
class ContactoServicioTuristaTranslationOptions(TranslationOptions):
    fields = ("etiqueta",)


@register(ImagenServicioTurista)
class ImagenServicioTuristaTranslationOptions(TranslationOptions):
    fields = ("titulo", "texto_alt")
