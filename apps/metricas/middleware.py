import logging

from .services import real

logger = logging.getLogger(__name__)


class MetricasMiddleware:
    """Cuenta páginas vistas REALES tras resolver la vista y entrega las cookies analíticas pendientes.

    Va al final de MIDDLEWARE (necesita request.user). Con METRICAS_REAL_HABILITADAS=False no hace nada.
    Un fallo de métricas nunca altera la respuesta de la página.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not real.habilitado():
            return response
        try:
            if real.pagina_elegible(request, response):
                real.registrar_pagina_vista(request)
        except Exception:
            logger.exception("metricas: error en el middleware")
        real.aplicar_cookies(request, response)
        return response
