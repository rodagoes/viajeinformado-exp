from modeltranslation.translator import TranslationOptions, register

from .models import (
    CategoriaServicioTurista, ContactoServicioTurista, ImagenServicioTurista, SedeServicioTurista,
    ServicioTurista,
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


# Los campos físicos de la entidad (referencia, horario_atencion) quedan
# registrados mientras existan las columnas legadas; la fuente real es la sede.
@register(SedeServicioTurista)
class SedeServicioTuristaTranslationOptions(TranslationOptions):
    fields = ("referencia", "horario_atencion")


@register(ContactoServicioTurista)
class ContactoServicioTuristaTranslationOptions(TranslationOptions):
    fields = ("etiqueta",)


@register(ImagenServicioTurista)
class ImagenServicioTuristaTranslationOptions(TranslationOptions):
    fields = ("titulo", "texto_alt")
