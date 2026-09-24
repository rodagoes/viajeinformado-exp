from modeltranslation.translator import TranslationOptions, register

from .models import CategoriaMovilidad, ConsejoMovilidad, RutaMovilidad, TransportePublico


# ponytail: solo lo que ve el turista en Cómo llegar / Tarifas de taxi. Nombres de
# ruta, origen/destino, operadores, teléfonos, slugs y precios no se traducen.
# ServicioMovilidad, OperadorMovilidad e ImagenRutaMovilidad no se muestran en el
# sitio público hoy: se registran cuando lo hagan.
@register(CategoriaMovilidad)
class CategoriaMovilidadTranslationOptions(TranslationOptions):
    fields = ("nombre", "descripcion")


@register(RutaMovilidad)
class RutaMovilidadTranslationOptions(TranslationOptions):
    fields = (
        "descripcion_corta", "descripcion", "punto_partida", "punto_llegada", "indicaciones",
        "duracion_estimada", "duracion_bus", "duracion_automovil", "frecuencia",
        "horario_referencial", "recomendaciones", "advertencias", "texto_alt_imagen",
    )


@register(TransportePublico)
class TransportePublicoTranslationOptions(TranslationOptions):
    fields = ("nombre", "nombre_alternativo", "descripcion", "texto_alt_imagen")


@register(ConsejoMovilidad)
class ConsejoMovilidadTranslationOptions(TranslationOptions):
    fields = ("texto",)
