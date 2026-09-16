"""Adaptador Gemini de los schemas neutrales (tool_schemas)."""
from .tool_schemas import declaraciones_funcion


def declaraciones_gemini():
    return declaraciones_funcion()
