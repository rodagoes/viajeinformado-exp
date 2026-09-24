from modeltranslation.translator import TranslationOptions, register

from .models import ContactoEmergencia, NumeroContactoAdicional


# ponytail: nombres oficiales de instituciones (ContactoEmergencia.nombre,
# fuente_nombre), zonas (topónimos), números y colores no se traducen.
@register(ContactoEmergencia)
class ContactoEmergenciaTranslationOptions(TranslationOptions):
    fields = ("descripcion", "horario")


@register(NumeroContactoAdicional)
class NumeroContactoAdicionalTranslationOptions(TranslationOptions):
    fields = ("etiqueta",)
