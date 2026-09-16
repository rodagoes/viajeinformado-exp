"""
Selector explícito del proveedor de IA. Cada proveedor es un módulo con el
mismo contrato: iniciar_turno(system, historial, contenido) y
continuar_turno(estado, resultados), ambos devolviendo
(estado, {"texto", "tool_calls", "usage"}). Sin fallback automático.
"""
from django.conf import settings

from . import deepseek_client, llm_client

PROVEEDORES = {llm_client.NOMBRE: llm_client, deepseek_client.NOMBRE: deepseek_client}


def obtener_proveedor_activo():
    nombre = settings.CHATBOT_AI_PROVIDER
    if nombre not in PROVEEDORES:
        raise llm_client.ChatbotNoConfigurado(f"proveedor no soportado: {nombre}")
    return PROVEEDORES[nombre]
