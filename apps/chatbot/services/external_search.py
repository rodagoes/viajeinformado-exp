"""
Fallback a fuentes externas confiables: una interacción Gemini compacta con
la tool nativa google_search (sin las 17 tools C3). El backend recibe,
extrae las url_citation estructuradas, las valida contra la allowlist y
presenta; nunca hace scraping ni acepta URLs escritas en texto libre.

DeepSeek web_search no se soporta como fallback confiable: su respuesta no
ofrece, en nuestro contrato, citas/URLs estructuradas verificables.
"""
from django.conf import settings
from django.utils import timezone

from . import llm_client, trusted_sources
from .providers import EXTERNAL_TRUSTED

NO_EVIDENCE = "no_evidence"
MAX_FUENTES = 3
MAX_EXTERNAL_SEARCHES_PER_TURN = 1
PROVEEDORES_SOPORTADOS = ("gemini",)
SENTINELA_SIN_EVIDENCIA = "SIN_EVIDENCIA"

TEXTO_SIN_EVIDENCIA = (
    "No tengo información suficiente y verificable para confirmarte ese dato en este momento."
)
TEXTO_NO_VERIFICADO = "No pude verificar ese dato en fuentes oficiales en este momento."


class BusquedaExternaNoDisponible(Exception):
    """Búsqueda deshabilitada o proveedor de búsqueda no soportado."""


_PLANTILLA_PROMPT = """Eres el verificador de fuentes oficiales de Pillco Bot (Viaje Informado, Huánuco, Perú).
Fecha local actual: {fecha}.

Busca únicamente evidencia en fuentes oficiales permitidas, realizando el mínimo número de búsquedas necesario.
Prioridad:
1. Instituciones públicas peruanas (*.gob.pe){preferidos}
2. PROMPERÚ / Peru Travel (peru.travel)
3. Y Tú Qué Planes (ytuqueplanes.com)

No uses blogs, redes sociales, Wikipedia, directorios comerciales, sitios de reseñas, medios ni tu conocimiento previo.
Responde en español, breve y en texto plano, empezando por "Según fuentes oficiales consultadas". No presentes una edición pasada de un evento como si fuera la actual.
Si no encuentras evidencia oficial suficiente, responde exactamente: {sentinela}"""


def construir_prompt_busqueda(tool=None, fecha_local=None):
    fecha = (fecha_local or timezone.localdate()).isoformat()
    preferidos = trusted_sources.DOMINIOS_PREFERIDOS.get(tool)
    texto = f", en especial {', '.join(preferidos)}" if preferidos else ""
    return _PLANTILLA_PROMPT.format(fecha=fecha, preferidos=texto, sentinela=SENTINELA_SIN_EVIDENCIA)


def construir_consulta(consulta, resumen_interno=None):
    if resumen_interno:
        return (
            f"Ya confirmado con datos internos de Viaje Informado: {resumen_interno}. "
            f"Busca únicamente lo que falta para responder: {consulta}"
        )
    return consulta


def _sin_evidencia():
    return {"ok": True, "tipo_fuente": NO_EVIDENCE, "texto": None, "fuentes": []}


def normalizar_grounding(interaccion):
    """
    Texto + url_citation estructuradas → contrato neutral. Sin citas, con el
    sentinela, o con UNA sola cita fuera de la allowlist → no_evidence
    (política conservadora). search_suggestions nunca se lee.
    """
    if interaccion.status in llm_client.ESTADOS_FALLIDOS:
        raise llm_client.ProveedorIAError(f"interaccion {interaccion.status}")

    textos, citas = [], []
    for paso in interaccion.steps or []:
        if getattr(paso, "type", None) != "model_output":
            continue
        for contenido in getattr(paso, "content", None) or []:
            if getattr(contenido, "type", None) != "text":
                continue
            textos.append(contenido.text or "")
            for anotacion in getattr(contenido, "annotations", None) or []:
                if getattr(anotacion, "type", None) == "url_citation" and getattr(anotacion, "url", None):
                    citas.append((getattr(anotacion, "title", None), anotacion.url))

    texto = "\n".join(t for t in textos if t).strip() or (interaccion.output_text or "").strip()
    if not texto or texto.upper().startswith(SENTINELA_SIN_EVIDENCIA) or not citas:
        return _sin_evidencia()

    fuentes, vistas = [], set()
    for titulo, url in citas:
        if not trusted_sources.es_url_confiable(url):
            return _sin_evidencia()
        if url in vistas:
            continue
        vistas.add(url)
        dominio = trusted_sources.dominio(url)
        fuentes.append({"titulo": (titulo or "").strip() or dominio, "url": url, "dominio": dominio})

    return {"ok": True, "tipo_fuente": EXTERNAL_TRUSTED, "texto": texto, "fuentes": fuentes[:MAX_FUENTES]}


def _buscar_gemini(consulta, tool, resumen_interno):
    interaccion = llm_client.crear_interaccion(
        input=construir_consulta(consulta, resumen_interno),
        system_instruction=construir_prompt_busqueda(tool),
        tools=[{"type": "google_search"}],
        generation_config=llm_client.configuracion_generacion(),
    )
    return normalizar_grounding(interaccion)


_BUSCADORES = {"gemini": _buscar_gemini}


def buscar(consulta, tool=None, resumen_interno=None):
    """Una búsqueda grounded. Errores del proveedor (ChatbotNoConfigurado,
    ProveedorIA*) se propagan para que el orquestador degrade con elegancia."""
    if not settings.CHATBOT_EXTERNAL_SEARCH_ENABLED:
        raise BusquedaExternaNoDisponible("deshabilitada")
    proveedor = settings.CHATBOT_EXTERNAL_SEARCH_PROVIDER
    if proveedor not in PROVEEDORES_SOPORTADOS:
        raise BusquedaExternaNoDisponible(f"proveedor de búsqueda no soportado: {proveedor}")
    resultado = _BUSCADORES[proveedor](consulta, tool, resumen_interno)
    resultado["provider"] = proveedor
    return resultado


def formatear_respuesta(resultado):
    lineas = [f"- {f['titulo']} — {f['url']}" for f in resultado["fuentes"][:MAX_FUENTES]]
    return f"{resultado['texto']}\n\nFuentes oficiales:\n" + "\n".join(lineas)
