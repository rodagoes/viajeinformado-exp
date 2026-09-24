from modeltranslation.translator import TranslationOptions, register

from .models import (
    CategoriaEstablecimiento, ContactoSucursalEstablecimiento, Establecimiento,
    ImagenEstablecimiento, RecomendacionEstablecimiento, ServicioEstablecimiento,
    SucursalEstablecimiento,
)


# ponytail: Establecimiento.nombre y SucursalEstablecimiento.nombre (nombres
# propios), direcciones, teléfonos y mapas no se traducen.
@register(CategoriaEstablecimiento)
class CategoriaEstablecimientoTranslationOptions(TranslationOptions):
    fields = ("nombre", "descripcion")


@register(ServicioEstablecimiento)
class ServicioEstablecimientoTranslationOptions(TranslationOptions):
    fields = ("nombre", "descripcion")


@register(Establecimiento)
class EstablecimientoTranslationOptions(TranslationOptions):
    fields = ("descripcion_corta", "descripcion", "texto_alt_imagen")


@register(SucursalEstablecimiento)
class SucursalEstablecimientoTranslationOptions(TranslationOptions):
    fields = ("referencia", "horario_atencion")


@register(ImagenEstablecimiento)
class ImagenEstablecimientoTranslationOptions(TranslationOptions):
    fields = ("titulo", "texto_alt")


@register(RecomendacionEstablecimiento)
class RecomendacionEstablecimientoTranslationOptions(TranslationOptions):
    fields = ("nombre",)


@register(ContactoSucursalEstablecimiento)
class ContactoSucursalEstablecimientoTranslationOptions(TranslationOptions):
    fields = ("etiqueta",)
