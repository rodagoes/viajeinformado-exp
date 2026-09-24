from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation


class CookieLocaleMiddleware(LocaleMiddleware):
    """LocaleMiddleware que decide el idioma solo por la cookie de
    set_language y, sin cookie (o con un idioma no soportado), siempre por
    LANGUAGE_CODE (español).

    # ponytail: se ignora Accept-Language a propósito (español por defecto
    # determinista). Para autodetectar el navegador basta usar LocaleMiddleware.
    """

    def process_request(self, request):
        codigo = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME) or settings.LANGUAGE_CODE
        try:
            idioma = translation.get_supported_language_variant(codigo)
        except LookupError:
            idioma = translation.get_supported_language_variant(settings.LANGUAGE_CODE)
        translation.activate(idioma)
        request.LANGUAGE_CODE = translation.get_language()
