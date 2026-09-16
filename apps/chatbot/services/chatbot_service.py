"""
Motor conversacional de Pillco Bot (arquitectura híbrida):

- Fast Path:    acción rápida registrada → tool → renderer     (0 llamadas de IA)
- Simple Path:  texto libre → 1 function_call direct-render
                → tool → renderer                               (1 llamada de IA)
- Complex Path: varias tools, tool no renderizable o argumentos
                a corregir → ronda(s) de síntesis del modelo     (2+ llamadas)

La IA solo propone llamadas; TOOL_REGISTRY las ejecuta. El backend decide
tipo_fuente y persiste el turno solo con respuesta final válida.
"""
import json
import logging
import re
import time

from django.db import transaction

from ..models import Conversacion, Mensaje
from . import (
    ai_provider,
    context_builder,
    external_search,
    llm_client,
    natural_quick_actions,
    presenters,
    quick_actions,
    response_renderers,
    tool_catalog,
)
from .providers import EXTERNAL_TRUSTED, INTERNAL, MAX_LIMIT, MIXED
from .system_prompt import construir_system_prompt

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 1000
MAX_TOOL_ROUNDS = 4


class MensajeInvalido(ValueError):
    def __init__(self, codigo):
        super().__init__(codigo)
        self.codigo = codigo


class OrquestacionError(Exception):
    """El ciclo de tool calling no terminó en una respuesta válida."""


def normalizar_mensaje(valor):
    if not isinstance(valor, str):
        raise MensajeInvalido("mensaje_invalido")
    mensaje = valor.strip()
    if not mensaje:
        raise MensajeInvalido("mensaje_vacio")
    if len(mensaje) > MAX_MESSAGE_LENGTH:
        raise MensajeInvalido("mensaje_demasiado_largo")
    return mensaje


def obtener_o_crear_conversacion(usuario=None, session_key=""):
    if usuario is not None:
        filtros = {"usuario": usuario}
        session_key = ""
    elif session_key:
        filtros = {"usuario__isnull": True, "session_key": session_key}
    else:
        raise ValueError("Se requiere un usuario o una session_key.")

    conversacion = (
        Conversacion.objects.filter(**filtros)
        .order_by("-ultima_actividad", "-id")
        .first()
    )
    if conversacion is None:
        conversacion = Conversacion.objects.create(
            usuario=usuario, session_key=session_key
        )
    return conversacion


def _tiene_datos(resultado):
    if not resultado.get("ok"):
        return False
    # Suficiencia de evidencia: la entidad puede existir (ej. el plato) sin el
    # dato concreto preguntado (ej. ingredientes). El provider lo declara.
    if resultado.get("evidencia_suficiente") is False:
        return False
    if resultado.get("count", 0) > 0:
        return True
    item = resultado.get("item")
    if isinstance(item, dict):
        return item.get("disponible", True)
    return item is not None


def calcular_tipo_fuente(resultados):
    """El backend decide la fuente a partir de los resultados reales de las tools."""
    if not resultados:
        return ""
    con_datos = [r for r in resultados if _tiene_datos(r)]
    if not con_datos:
        return Mensaje.TipoFuente.NO_EVIDENCE
    fuentes = {r.get("tipo_fuente") for r in con_datos}
    if MIXED in fuentes or {INTERNAL, EXTERNAL_TRUSTED} <= fuentes:
        return MIXED
    if fuentes == {EXTERNAL_TRUSTED}:
        return EXTERNAL_TRUSTED
    return INTERNAL


def _ms(inicio):
    return (time.perf_counter() - inicio) * 1000


def _ejecutar_tool(conversacion, tool, argumentos):
    inicio = time.perf_counter()
    if argumentos is None:
        resultado = {
            "ok": False, "tool": tool,
            "error": "argumentos_invalidos", "detail": "los argumentos no son JSON válido",
        }
    elif tool in tool_catalog.TOOLS_CON_USUARIO:
        # Identidad segura: la conversación ya está ligada al usuario autenticado
        # por el backend (nunca del payload del cliente ni de argumentos del modelo).
        resultado = tool_catalog.ejecutar_herramienta(tool, argumentos, usuario=conversacion.usuario)
    else:
        resultado = tool_catalog.ejecutar_herramienta(tool, argumentos)
    logger.debug(
        "chatbot_tool conversacion=%s tool=%s ms=%.0f ok=%s",
        conversacion.pk, tool, _ms(inicio), bool(resultado.get("ok")),
    )
    if not resultado.get("ok"):
        logger.info(
            "tool rechazada conversacion=%s tool=%s error=%s",
            conversacion.pk, tool, resultado.get("error"),
        )
    return resultado


def _huella(tool, argumentos):
    """Identidad conservadora de una búsqueda: misma tool + mismos argumentos
    (sin `limit`, claves ordenadas, texto en minúsculas). Sin similitud semántica."""
    if not isinstance(argumentos, dict):
        return None
    relevantes = {k: v for k, v in argumentos.items() if k != "limit"}
    return tool, json.dumps(relevantes, sort_keys=True, ensure_ascii=False, default=str).lower()


_RESULTADO_REPETIDO = {
    "error": "consulta_ya_realizada_sin_resultados",
    "detail": (
        "esta búsqueda ya se ejecutó en este turno y no devolvió resultados; "
        "no la repitas: responde con la evidencia disponible."
    ),
}


def _ejecutar_llamadas(llamadas, conversacion, huellas_vacias=None):
    """`huellas_vacias` (por turno): una búsqueda que ya devolvió count=0 no se
    vuelve a ejecutar; el modelo recibe un error controlado en su lugar."""
    resultados, pasos = [], []
    for llamada in llamadas:
        huella = _huella(llamada["name"], llamada["arguments"])
        if huellas_vacias is not None and huella in huellas_vacias:
            resultado = {"ok": False, "tool": llamada["name"], **_RESULTADO_REPETIDO}
            logger.info("tool repetida sin resultados conversacion=%s tool=%s", conversacion.pk, llamada["name"])
        else:
            resultado = _ejecutar_tool(conversacion, llamada["name"], llamada["arguments"])
            if huellas_vacias is not None and huella and resultado.get("ok") and "items" in resultado and not resultado.get("count"):
                huellas_vacias.add(huella)
        resultados.append(resultado)
        pasos.append({
            "call_id": llamada["id"],
            "name": llamada["name"],
            "result": resultado,
            "is_error": not resultado.get("ok", False),
        })
    return resultados, pasos


def _tool_simple(llamadas, resultados):
    """Simple Path: exactamente 1 call, tool direct-render y resultado ok → nombre de la tool."""
    if len(llamadas) != 1 or len(resultados) != 1:
        return None
    tool = llamadas[0]["name"]
    if tool not in response_renderers.DIRECT_RENDER_TOOLS or not resultados[0].get("ok"):
        return None
    return tool


def _renderizar(tool, resultado):
    """(texto, presentacion|None): delega en el presentador estructurado si
    existe uno para `tool`; si no, en el renderer textual de siempre."""
    return presenters.texto_y_presentacion(tool, resultado)


# --- Fallback a fuentes externas confiables (C5) ---------------------------

def _resumen_interno(resultados):
    """Solo nombres de tool y conteos de lo ya confirmado; nunca payloads."""
    partes = [
        f"{r.get('tool')} ({r.get('count', 1)} resultado(s))"
        for r in resultados if _tiene_datos(r)
    ]
    return "; ".join(partes) or None


def _buscar_externo(conversacion, contador, consulta, tool=None, resumen_interno=None):
    """
    Único fallback externo del turno. → (estado, resultado) con estado en
    no_disponible | error | sin_evidencia | evidencia. Solo los errores
    esperados del proveedor degradan; un bug propio se propaga.
    """
    if contador["busquedas"] >= external_search.MAX_EXTERNAL_SEARCHES_PER_TURN:
        return "no_disponible", None
    contador["busquedas"] += 1
    inicio = time.perf_counter()
    try:
        resultado = external_search.buscar(consulta, tool=tool, resumen_interno=resumen_interno)
    except external_search.BusquedaExternaNoDisponible as exc:
        logger.info("external_search_skipped conversacion=%s motivo=%s", conversacion.pk, exc)
        return "no_disponible", None
    except (llm_client.ChatbotNoConfigurado, llm_client.ProveedorIAError) as exc:
        logger.warning("external_search_error conversacion=%s error=%s", conversacion.pk, exc)
        return "error", None
    estado = "evidencia" if resultado["tipo_fuente"] == EXTERNAL_TRUSTED else "sin_evidencia"
    logger.info(
        "external_search_used conversacion=%s provider=%s fuentes=%s tipo_fuente=%s ms=%.0f",
        conversacion.pk, resultado.get("provider"), len(resultado["fuentes"]),
        resultado["tipo_fuente"], _ms(inicio),
    )
    return estado, resultado


def _texto_sin_evidencia(estado):
    if estado == "error":
        return external_search.TEXTO_NO_VERIFICADO
    return external_search.TEXTO_SIN_EVIDENCIA


def _completar_sin_evidencia(conversacion, contador, consulta, tool=None):
    """Sin evidencia interna: un fallback externo o cierre determinista en no_evidence."""
    estado, resultado = _buscar_externo(conversacion, contador, consulta, tool=tool)
    if estado == "evidencia":
        return external_search.formatear_respuesta(resultado), EXTERNAL_TRUSTED
    return _texto_sin_evidencia(estado), Mensaje.TipoFuente.NO_EVIDENCE


def _completar_complejo(conversacion, contador, consulta, texto, resultados):
    """Tras la síntesis: fallback solo si hubo ejecución interna válida sin evidencia (total o parcial)."""
    tipo_fuente = calcular_tipo_fuente(resultados)
    validos = [r for r in resultados if r.get("ok")]
    if not validos:
        return texto, tipo_fuente
    if tipo_fuente == Mensaje.TipoFuente.NO_EVIDENCE:
        # Sin evidencia interna: nunca se conserva la redacción del modelo
        return _completar_sin_evidencia(conversacion, contador, consulta)
    if all(_tiene_datos(r) for r in validos):
        return texto, tipo_fuente
    estado, externo = _buscar_externo(
        conversacion, contador, consulta, resumen_interno=_resumen_interno(resultados)
    )
    if estado == "evidencia":
        return f"{texto}\n\n{external_search.formatear_respuesta(externo)}", MIXED
    if estado == "error":
        return f"{texto}\n\n{external_search.TEXTO_NO_VERIFICADO}", tipo_fuente
    return texto, tipo_fuente


_DOMINIO_VACIO = {
    "buscar_lugares": "lugares turísticos",
    "buscar_restaurantes": "restaurantes",
    "buscar_alojamientos": "alojamientos",
    "buscar_restaurantes_por_plato": "restaurantes que sirvan ese plato",
    "buscar_platos": "platos típicos",
    "buscar_eventos": "eventos",
    "buscar_ubicaciones": "ubicaciones",
    "consultar_servicios_utiles": "servicios útiles",
    "consultar_emergencias": "contactos de emergencia",
    "consultar_como_llegar": "rutas",
    "consultar_favoritos": "favoritos",
}


def _sintesis_parcial(resultados):
    """Cierre determinista sin el modelo: renderiza la evidencia obtenida y
    nombra lo que no se encontró. Se usa cuando el modelo agota las rondas
    insistiendo en búsquedas vacías teniendo ya evidencia parcial (ej. clima
    disponible + lugares count 0) — nunca un 502 en ese caso."""
    partes, sin_datos = [], []
    for r in resultados:
        if not r.get("ok"):
            continue
        if _tiene_datos(r):
            texto, _ = _renderizar(r["tool"], r)
            if texto and texto not in partes:
                partes.append(texto)
        elif "items" in r:
            dominio = _DOMINIO_VACIO.get(r["tool"], "resultados")
            if dominio not in sin_datos:
                sin_datos.append(dominio)
    if sin_datos:
        partes.append(f"No encontré {' ni '.join(sin_datos)} registrados para esa búsqueda.")
    return "\n\n".join(partes)


def _ronda(conversacion, numero, ejecutar):
    inicio = time.perf_counter()
    estado, respuesta = ejecutar()
    logger.debug(
        "chatbot_ai_round conversacion=%s ronda=%s ms=%.0f calls=%s",
        conversacion.pk, numero, _ms(inicio), len(respuesta["tool_calls"]),
    )
    return estado, respuesta


def generar_respuesta(conversacion, contenido):
    """
    Ciclo proveedor <-> tools sin ninguna transacción de BD abierta.
    Devuelve (texto_final, tipo_fuente, presentacion|None).
    """
    inicio_turno = time.perf_counter()
    proveedor = ai_provider.obtener_proveedor_activo()
    system = construir_system_prompt()
    historial = context_builder.construir_historial(conversacion)
    contador = {"busquedas": 0}
    huellas_vacias = set()

    ronda = 1
    estado, respuesta = _ronda(
        conversacion, ronda, lambda: proveedor.iniciar_turno(system, historial, contenido)
    )
    resultados = []
    while respuesta["tool_calls"]:
        if ronda > MAX_TOOL_ROUNDS:
            logger.warning("rondas de tools agotadas conversacion=%s", conversacion.pk)
            if any(_tiene_datos(r) for r in resultados):
                # Evidencia parcial: se conserva y se cierra sin el modelo.
                # tipo_fuente solo con la evidencia realmente obtenida.
                tipo_fuente = calcular_tipo_fuente(resultados)
                logger.debug(
                    "chatbot_turn conversacion=%s provider=%s ms=%.0f ruta=parcial rondas=%s tools=%s tipo_fuente=%s",
                    conversacion.pk, proveedor.NOMBRE, _ms(inicio_turno), ronda, len(resultados), tipo_fuente,
                )
                return _sintesis_parcial(resultados), tipo_fuente, None
            raise OrquestacionError("rondas_agotadas")
        nuevos, pasos = _ejecutar_llamadas(respuesta["tool_calls"], conversacion, huellas_vacias)
        resultados.extend(nuevos)
        if ronda == 1:
            tool = _tool_simple(respuesta["tool_calls"], nuevos)
            if tool:
                presentacion = None
                if _tiene_datos(nuevos[0]):
                    texto, presentacion = _renderizar(tool, nuevos[0])
                    tipo_fuente = calcular_tipo_fuente(resultados)
                elif tool in presenters.TIPO_FUENTE_VACIO:
                    # C8: un vacío es respuesta completa (sin favoritos / sin datos
                    # para planificar); nunca se rellena con fuentes externas.
                    texto, presentacion = _renderizar(tool, nuevos[0])
                    tipo_fuente = presenters.TIPO_FUENTE_VACIO[tool]
                else:
                    texto, tipo_fuente = _completar_sin_evidencia(
                        conversacion, contador, contenido, tool=tool
                    )
                logger.debug(
                    "chatbot_turn conversacion=%s provider=%s ms=%.0f ruta=simple rondas=1 tools=1 "
                    "busquedas=%s tipo_fuente=%s",
                    conversacion.pk, proveedor.NOMBRE, _ms(inicio_turno), contador["busquedas"], tipo_fuente,
                )
                return texto, tipo_fuente, presentacion
        ronda += 1
        estado, respuesta = _ronda(
            conversacion, ronda, lambda: proveedor.continuar_turno(estado, pasos)
        )

    texto = (respuesta["texto"] or "").strip()
    if not texto:
        raise OrquestacionError("respuesta_vacia")
    if resultados:
        texto, tipo_fuente = _completar_complejo(conversacion, contador, contenido, texto, resultados)
    else:
        tipo_fuente = ""
    logger.debug(
        "chatbot_turn conversacion=%s provider=%s ms=%.0f ruta=%s rondas=%s tools=%s busquedas=%s tipo_fuente=%s",
        conversacion.pk, proveedor.NOMBRE, _ms(inicio_turno),
        "compleja" if resultados else "directa", ronda, len(resultados), contador["busquedas"], tipo_fuente,
    )
    # Complejo/redactado por el modelo: nunca hay presentacion estructurada.
    return texto, tipo_fuente, None


# Lista cerrada de nombres técnicos que nunca deben llegar al turista en texto
# libre. Solo infraestructura conocida; nunca fuentes oficiales (C5), nombres
# de negocios, entidades, URLs, precios o fechas. "Google Search" queda solo
# en la regla del prompt: distinguirlo de una fuente citada no es seguro aquí.
_NOMBRES_TECNICOS = r"(?:Open[\s-]?Meteo|DeepSeek|Gemini|TOOL_REGISTRY)"
_PATRONES_SANITIZAR = [
    # "(Open-Meteo)", "(fuente: Open-Meteo)", "(vía DeepSeek)"
    re.compile(r"\s*\((?:fuente:?|v[ií]a|seg[uú]n|por)?\s*" + _NOMBRES_TECNICOS + r"\s*\)", re.IGNORECASE),
    # "Fuente: Open-Meteo", "— Open-Meteo", "- Open-Meteo" al final de una frase
    re.compile(r"\s*(?:fuente:?|—|–|-)\s*" + _NOMBRES_TECNICOS + r"\b\.?", re.IGNORECASE),
    # "Según Open-Meteo, ...", "vía DeepSeek", "de Gemini"
    re.compile(r"\b(?:seg[uú]n|v[ií]a|de|por|en)\s+" + _NOMBRES_TECNICOS + r"\b,?\s*", re.IGNORECASE),
    # Cualquier mención suelta restante
    re.compile(r"\b" + _NOMBRES_TECNICOS + r"\b", re.IGNORECASE),
]
_ARREGLOS_PUNTUACION = [
    (re.compile(r"\(\s*\)"), ""),
    (re.compile(r"\s+([.,;:!?])"), r"\1"),
    (re.compile(r"([.,;:])\s*\1+"), r"\1"),
    (re.compile(r"[ \t]{2,}"), " "),
    (re.compile(r"^\s*[Ff]uente:?\s*$", re.MULTILINE), ""),
    (re.compile(r"\n{3,}"), "\n\n"),
]


def _sanitizar_respuesta_publica(texto):
    """Elimina de la respuesta textual final nombres técnicos conocidos
    (lista cerrada) y arregla la puntuación resultante. Determinista y
    conservador: no toca el resto del contenido."""
    if not texto:
        return texto
    limpio = texto
    for patron in _PATRONES_SANITIZAR:
        limpio = patron.sub("", limpio)
    if limpio == texto:
        return texto
    for patron, reemplazo in _ARREGLOS_PUNTUACION:
        limpio = patron.sub(reemplazo, limpio)
    # Tras quitar "Según X, " la frase puede quedar en minúscula inicial.
    limpio = re.sub(r"(^|[.!?]\s+)([a-záéíóúñ])", lambda m: m.group(1) + m.group(2).upper(), limpio)
    return limpio.strip()


def _persistir_turno(conversacion, contenido_usuario, texto, tipo_fuente, presentacion=None):
    # Único punto por el que pasa todo texto del asistente antes de persistirse
    # y devolverse por HTTP (Fast/Simple/Complex Path y C5 por igual).
    texto = _sanitizar_respuesta_publica(texto)
    with transaction.atomic():
        mensaje_usuario = Mensaje.objects.create(
            conversacion=conversacion,
            rol=Mensaje.Rol.USUARIO,
            contenido=contenido_usuario,
        )
        respuesta = Mensaje.objects.create(
            conversacion=conversacion,
            rol=Mensaje.Rol.ASISTENTE,
            contenido=texto,
            tipo_fuente=tipo_fuente,
        )
        # auto_now solo se aplica al guardar la conversación, no al crear mensajes hijos
        conversacion.save(update_fields=["ultima_actividad"])
    # Nunca se persiste: la UI estructurada es efímera, solo viaja en la respuesta HTTP.
    respuesta.presentacion = presentacion
    return mensaje_usuario, respuesta


def _procesar_via_quick_action(conversacion, texto_persistido, accion_id):
    """
    Fast Path (0 llamadas de IA): ejecuta la tool de una Quick Action ya
    registrada y la renderiza. Compartido por el botón de Quick Action (que
    persiste su label humano) y por el Natural Fast Path (que persiste el
    mensaje original del turista). Los argumentos son siempre estáticos y
    válidos: un resultado no-ok aquí es un bug real, no un caso a esconder.
    """
    inicio_turno = time.perf_counter()
    _, tool, argumentos = quick_actions.resolver(accion_id)
    resultado = _ejecutar_tool(conversacion, tool, argumentos)
    if not resultado.get("ok"):
        raise RuntimeError(f"accion rapida {accion_id} rechazada: {resultado.get('error')}")
    contador = {"busquedas": 0}
    presentacion = None
    # buscar_eventos es un catálogo temporal (agenda de los próximos 7 días):
    # una lista vacía significa "no hay nada programado ahora", una respuesta
    # interna completa y confiable con su propio texto (ver
    # presenters.presentar_eventos), no evidencia insuficiente que amerite
    # buscar fuentes externas — a diferencia de otras Quick Actions como
    # alojamientos/restaurantes "destacados", donde un vacío sí dispara el
    # fallback externo (ver FallbackQuickActionTests, comportamiento previo
    # a C6.2 que no cambia).
    if tool == "buscar_eventos" or tool in presenters.TIPO_FUENTE_VACIO or _tiene_datos(resultado):
        texto, presentacion = _renderizar(tool, resultado)
        tipo_fuente = calcular_tipo_fuente([resultado]) if _tiene_datos(resultado) else INTERNAL
    else:
        texto, tipo_fuente = _completar_sin_evidencia(conversacion, contador, texto_persistido, tool=tool)
    logger.debug(
        "chatbot_turn conversacion=%s provider=none ms=%.0f ruta=rapida rondas=0 tools=1 busquedas=%s tipo_fuente=%s",
        conversacion.pk, _ms(inicio_turno), contador["busquedas"], tipo_fuente,
    )
    return _persistir_turno(conversacion, texto_persistido, texto, tipo_fuente, presentacion)


def _procesar_emergencia_zona(conversacion, texto_persistido, zona):
    """Natural Fast Path — 'emergencias en <zona>' (0 IA): reutiliza
    consultar_emergencias(distrito=...) y el presentador de 2 niveles."""
    resultado = _ejecutar_tool(
        conversacion,
        "consultar_emergencias",
        {"distrito": zona["slug"], "ambito": "local", "limit": MAX_LIMIT},
    )
    if not resultado.get("ok"):
        raise RuntimeError(f"consultar_emergencias por zona rechazada: {resultado.get('error')}")
    texto, presentacion = presenters.presentar_emergencias(resultado, zona_nombre=zona["nombre"])
    tipo_fuente = calcular_tipo_fuente([resultado]) if resultado.get("items") else INTERNAL
    return _persistir_turno(conversacion, texto_persistido, texto, tipo_fuente, presentacion)


# Scope guard determinista (0 IA, 0 C5) solo para consultas médicas/sanitarias
# explícitas de alta confianza: condición de salud declarada + petición de
# seguridad/consejo. Una simple pregunta de ingredientes ("¿lleva maní?") no
# coincide y sigue el flujo gastronómico normal. Ante la duda, no bloquea.
TEXTO_FUERA_ALCANCE_MEDICO = (
    "PillcoBot está enfocado en información turística de Huánuco. Puedo contarte sobre los "
    "ingredientes o la preparación de un plato, pero no evaluar si es seguro para una alergia "
    "o condición de salud. Para eso, consulta a un profesional de salud."
)
_CONDICION_SALUD = re.compile(
    r"al[eé]rgi|intoleran|diabet|hipertens|cel[ií]ac|embaraz|gastritis|colesterol|enfermedad|"
    r"me cay[oó] mal|me hizo da[ñn]o|intoxic|malestar|dolor de est[oó]mago|mi salud|condici[oó]n de salud",
    re.IGNORECASE,
)
_PETICION_SALUD = re.compile(
    r"segur[oa]|puedo comer|debo comer|debo tomar|qu[eé] tomo|qu[eé] tomar|conviene|"
    r"recomiendas|recomendar[ií]as|me hace da[ñn]o|me har[aá] da[ñn]o|apto|puedo consumir",
    re.IGNORECASE,
)


def detectar_consulta_medica(mensaje):
    return bool(_CONDICION_SALUD.search(mensaje) and _PETICION_SALUD.search(mensaje))


def procesar_turno(conversacion, contenido):
    # Scope guard: consulta médica/sanitaria explícita → respuesta controlada sin IA ni C5.
    if detectar_consulta_medica(contenido):
        return _persistir_turno(conversacion, contenido, TEXTO_FUERA_ALCANCE_MEDICO, "")
    # Natural Fast Path — emergencias por zona (dinámico, valida contra zonas reales).
    zona = natural_quick_actions.detectar_emergencia_zona(contenido)
    if zona is not None:
        return _procesar_emergencia_zona(conversacion, contenido, zona)
    # Natural Fast Path: solo si el mensaje coincide sin ambigüedad con una
    # Quick Action existente (lista blanca) — nunca para consultas complejas.
    accion_id = natural_quick_actions.detectar(contenido)
    if accion_id is not None:
        return _procesar_via_quick_action(conversacion, contenido, accion_id)
    # La llamada remota ocurre fuera de la transacción; el turno se persiste
    # solo con respuesta final válida (nunca un mensaje de usuario huérfano).
    texto, tipo_fuente, presentacion = generar_respuesta(conversacion, contenido)
    return _persistir_turno(conversacion, contenido, texto, tipo_fuente, presentacion)


def procesar_accion(conversacion, accion_id):
    """Fast Path (botón): 0 llamadas de IA. El label de la acción queda como mensaje del usuario."""
    label, _, _ = quick_actions.resolver(accion_id)
    return _procesar_via_quick_action(conversacion, label, accion_id)
