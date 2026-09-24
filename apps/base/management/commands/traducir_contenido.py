"""Rellena, de forma MANUAL y OFFLINE, los campos `*_en` vacíos del contenido P1
con una traducción de Gemini.

    python manage.py traducir_contenido --dry-run
    python manage.py traducir_contenido --limit 5 --pausa 13
    python manage.py traducir_contenido --pausa 13

- Nunca se llama desde views ni requests: la web solo lee lo guardado en BD.
- Idempotente: solo rellena `campo_en` cuando está vacío y `campo_es` no lo está;
  nunca sobrescribe una traducción existente (el UPDATE es condicional).
- Alcance = modeltranslation P1 (base, turismo, establecimientos, gastronomia,
  eventos). Los nombres propios (`LugarTuristico.nombre`, `Evento.nombre`,
  `Establecimiento.nombre`, `PlatoTipico.nombre`) no están registrados y por
  tanto jamás se tocan.
- Una petición por REGISTRO: todos sus campos pendientes viajan en un JSON y se
  validan/guardan uno a uno (una traducción inválida no impide guardar las demás).
  Un registro muy grande se reparte en varias peticiones, nunca una por campo.
- Reintentos (429/503/timeout/conexión): máximo 3 intentos, respetando `retryDelay`
  si la API lo devuelve; si se agotan, el error se reporta, los `_en` quedan vacíos
  y se continúa con el siguiente registro.
- Reutiliza la configuración Gemini del chatbot (CHATBOT_AI_API_KEY,
  CHATBOT_AI_MODEL, CHATBOT_AI_TIMEOUT_MS) sin depender de CHATBOT_AI_PROVIDER.
"""
import json
import re
import time
from collections import deque

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from modeltranslation.translator import translator

APPS_P1 = ("base", "turismo", "establecimientos", "gastronomia", "eventos")

SYSTEM_INSTRUCTION = """You are a professional translator for a tourism website about Huánuco, Peru. You receive a JSON object whose values are Spanish texts. Translate every value into English.

Rules:
- Reply with ONLY a JSON object with EXACTLY the same keys as the input (no extra keys, none missing). Keys must not be translated.
- Translate faithfully. Do NOT summarize, reinterpret, embellish or add any information (no extra tourist advice, no marketing).
- Keep exactly the same paragraphs and line breaks inside each value.
- If a value contains HTML, keep every tag and attribute unchanged and translate only the text between tags.
- Keep proper names unchanged: places and toponyms, cultural festivals and traditions, traditional dishes, establishments and people (e.g. "Plaza de Armas de Huánuco", "Dámaso Beraún", "Pillco Marca", "Amarilis").
- Do translate ordinary Spanish common nouns that appear inside a description, according to context, even when they refer to a well-known local building or institution (e.g. "Municipalidad" -> "City Hall" or "Municipality", "Catedral" -> "Cathedral", "iglesia" -> "church", "mercado" -> "market", "pileta" -> "fountain"). Only the full proper name of a place stays in Spanish.
- Add nothing that is not in the source text: no extra adjectives, materials, features, details or qualities (e.g. "pileta" is "fountain", never "granite fountain" unless the source says "granito").
- Never translate or alter URLs, email addresses, phone numbers, addresses, codes or numbers.
- If a value is only a proper name, or is already in English, return it unchanged.
- No notes, no explanations, no markdown."""

# Tamaño máximo (caracteres de origen) de una petición; un campo suelto que lo supere va solo.
MAX_CARACTERES_LOTE = 6000
MAX_CAMPOS_LOTE = 12
MAX_INTENTOS = 3
BACKOFF_BASE = 5  # s: 5, 10 si la API no da retryDelay
MAX_ESPERA_REINTENTO = 120  # s

URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TELEFONO_RE = re.compile(r"\+?\d[\d\s-]{6,}\d")
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
SOLO_TECNICO_RE = re.compile(r"^[\W\d_]*$")


class ErrorTraduccion(Exception):
    pass


def _crear_cliente():
    """Cliente Gemini con la configuración del chatbot (no exige CHATBOT_AI_PROVIDER=gemini)."""
    from google import genai

    from apps.chatbot.services import llm_client

    if not settings.CHATBOT_AI_API_KEY:
        raise CommandError("CHATBOT_AI_API_KEY no está configurada; no se puede traducir con Gemini.")
    return genai.Client(
        api_key=settings.CHATBOT_AI_API_KEY,
        http_options=llm_client.opciones_http(int(settings.CHATBOT_AI_TIMEOUT_MS)),
    )


def _traducir_lote(cliente, campos, contexto):
    """UNA llamada a Gemini con `{campo: texto_es}`. Devuelve el dict (sin validar) de la respuesta JSON."""
    from google.genai import types

    contenido = f"Context: {contexto}.\n\nJSON to translate:\n" + json.dumps(campos, ensure_ascii=False, indent=1)
    esquema = {
        "type": "object",
        "properties": {campo: {"type": "string"} for campo in campos},
        "required": list(campos),
    }
    respuesta = cliente.models.generate_content(
        model=settings.CHATBOT_AI_MODEL,
        contents=contenido,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=esquema,
        ),
    )
    return _parsear_json(respuesta.text or "")


def _parsear_json(texto):
    texto = _limpiar_respuesta(texto)
    try:
        datos = json.loads(texto)
    except ValueError as exc:
        raise ErrorTraduccion(f"la respuesta no es JSON válido ({exc})") from exc
    if not isinstance(datos, dict):
        raise ErrorTraduccion("la respuesta JSON no es un objeto")
    return datos


def _dormir(segundos):
    time.sleep(segundos)


def _codigo_http(exc):
    for atributo in ("code", "status_code"):
        valor = getattr(exc, atributo, None)
        if isinstance(valor, int):
            return valor
    return None


def es_error_transitorio(exc):
    """429 RESOURCE_EXHAUSTED, 503 UNAVAILABLE, timeout o fallo de conexión."""
    import httpx

    if _codigo_http(exc) in (429, 503):
        return True
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError))


RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s|retry in (\d+(?:\.\d+)?)s", re.I)


def retry_delay(exc):
    """Segundos indicados por la API (retryDelay) o None."""
    m = RETRY_DELAY_RE.search(str(exc))
    if not m:
        return None
    return float(m.group(1) or m.group(2))


def _limpiar_respuesta(texto):
    """Quita envoltorios que el modelo pudiera añadir pese a la instrucción."""
    texto = texto.strip()
    m = re.fullmatch(r"```[a-z]*\n(.*?)\n```", texto, re.S)
    if m:
        texto = m.group(1).strip()
    m = re.fullmatch(r"<<<\s*(.*?)\s*>>>", texto, re.S)
    if m:
        texto = m.group(1).strip()
    return texto


def validar_traduccion(es, en):
    """Lanza ErrorTraduccion si la traducción viola las reglas (no se guarda nada)."""
    if not en:
        raise ErrorTraduccion("respuesta vacía")
    for nombre, regex in (("URL", URL_RE), ("email", EMAIL_RE), ("teléfono", TELEFONO_RE)):
        for dato in regex.findall(es):
            if dato.strip() not in en:
                raise ErrorTraduccion(f"se alteró o perdió un {nombre}: {dato.strip()!r}")
    if sorted(TAG_RE.findall(es)) != sorted(TAG_RE.findall(en)):
        raise ErrorTraduccion("las etiquetas HTML no coinciden")
    lineas_es = [l for l in es.splitlines() if l.strip()]
    lineas_en = [l for l in en.splitlines() if l.strip()]
    if len(lineas_es) != len(lineas_en):
        raise ErrorTraduccion(f"cambió el número de párrafos/líneas ({len(lineas_es)} -> {len(lineas_en)})")
    if len(es) > 30 and not (0.3 <= len(en) / len(es) <= 3.5):
        raise ErrorTraduccion("longitud sospechosa respecto al original")


def _contexto(modelo):
    return f'a "{modelo._meta.verbose_name}" record; the JSON keys are its field names'


def partir_en_lotes(pendientes):
    """Reparte los campos pendientes de UN registro en el mínimo de peticiones:
    lo normal es una sola; solo si el volumen lo exige (MAX_CARACTERES_LOTE /
    MAX_CAMPOS_LOTE) se divide. Nunca una petición por campo como estrategia."""
    lotes, actual, tamano = [], [], 0
    for campo, es in pendientes:
        if actual and (tamano + len(es) > MAX_CARACTERES_LOTE or len(actual) >= MAX_CAMPOS_LOTE):
            lotes.append(actual)
            actual, tamano = [], 0
        actual.append((campo, es))
        tamano += len(es)
    if actual:
        lotes.append(actual)
    return lotes


def _es_traducible(valor):
    """Vacío, solo símbolos/números o un email/URL suelto: nada que traducir."""
    valor = (valor or "").strip()
    if len(valor) < 3 or SOLO_TECNICO_RE.match(valor):
        return False
    if EMAIL_RE.fullmatch(valor) or URL_RE.fullmatch(valor):
        return False
    return True


def modelos_p1():
    """[(modelo, (campos...))] registrados en modeltranslation dentro de P1, orden estable."""
    modelos = []
    for modelo in translator.get_registered_models():
        if modelo._meta.app_label in APPS_P1:
            campos = tuple(translator.get_options_for_model(modelo).fields)
            modelos.append((modelo, campos))
    modelos.sort(key=lambda par: (APPS_P1.index(par[0]._meta.app_label), par[0].__name__))
    return modelos


def _campos_pendientes(obj, campos):
    """[(campo, texto_es)] con `_es` relleno y `_en` vacío."""
    pendientes = []
    for campo in campos:
        # Regla puntual: el nombre de una recomendación que es un plato típico es un nombre propio.
        if campo == "nombre" and getattr(obj, "plato_tipico", False):
            continue
        es = getattr(obj, f"{campo}_es", None)
        en = getattr(obj, f"{campo}_en", None)
        if (en is None or not str(en).strip()) and _es_traducible(es):
            pendientes.append((campo, es))
    return pendientes


def seleccionar_registros(limite=None):
    """Registros con algún campo pendiente. Con `limite`, reparte entre modelos
    (uno por modelo, por turnos) para que una muestra pequeña sea representativa."""
    colas = deque()
    for modelo, campos in modelos_p1():
        filas = []
        for obj in modelo._default_manager.all().order_by("pk"):
            pendientes = _campos_pendientes(obj, campos)
            if pendientes:
                filas.append((modelo, obj, pendientes))
        if filas:
            colas.append(deque(filas))
    elegidos = []
    while colas and (limite is None or len(elegidos) < limite):
        cola = colas.popleft()
        elegidos.append(cola.popleft())
        if cola:
            colas.append(cola)
    return elegidos


class ErrorTransitorioAgotado(Exception):
    pass


class Llamador:
    """Llamadas reales a Gemini con pausa entre ellas y reintentos transitorios."""

    def __init__(self, cliente, pausa=0.0):
        self.cliente = cliente
        self.pausa = pausa
        self.llamadas = 0
        self.reintentos = 0
        self._hubo_llamada = False

    def traducir(self, campos, contexto):
        espera = 0.0
        for intento in range(1, MAX_INTENTOS + 1):
            # La pausa se aplica solo entre llamadas reales; en un reintento manda el
            # retryDelay de la API (si es mayor que la pausa).
            if self._hubo_llamada:
                _dormir(max(self.pausa, espera))
            self._hubo_llamada = True
            self.llamadas += 1
            try:
                return _traducir_lote(self.cliente, campos, contexto)
            except Exception as exc:
                if not es_error_transitorio(exc):
                    raise
                if intento == MAX_INTENTOS:
                    raise ErrorTransitorioAgotado(f"{exc} (tras {MAX_INTENTOS} intentos)") from exc
                self.reintentos += 1
                delay = retry_delay(exc)
                if delay is not None:
                    espera = min(delay + 1, MAX_ESPERA_REINTENTO)  # +1 s de margen
                else:
                    espera = min(BACKOFF_BASE * 2 ** (intento - 1), MAX_ESPERA_REINTENTO)


class Command(BaseCommand):
    help = (
        "Rellena con Gemini los campos *_en vacíos del contenido P1 (offline, manual, idempotente). "
        "Una petición por registro. Nunca sobrescribe una traducción existente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Lista lo que se traduciría; no llama a Gemini ni guarda nada.")
        parser.add_argument("--limit", type=int, default=None, help="Máximo de REGISTROS a procesar (repartidos entre modelos).")
        parser.add_argument(
            "--pausa", type=float, default=0.0, metavar="SEGUNDOS",
            help="Segundos de espera entre llamadas REALES a Gemini (p. ej. 13 con la cuota gratuita de 5/min).",
        )

    def _guardar(self, modelo, obj, campo, en):
        # UPDATE condicional: jamás pisa una traducción existente (ni siquiera en una carrera).
        filtro = Q(**{f"{campo}_en__isnull": True}) | Q(**{f"{campo}_en": ""})
        return modelo._default_manager.filter(pk=obj.pk).filter(filtro).update(**{f"{campo}_en": en})

    def handle(self, *args, dry_run=False, limit=None, pausa=0.0, **options):
        if limit is not None and limit < 1:
            raise CommandError("--limit debe ser >= 1")
        if pausa < 0:
            raise CommandError("--pausa debe ser >= 0")

        seleccion = seleccionar_registros(limit)
        total_campos = sum(len(p) for _, _, p in seleccion)
        total_peticiones = sum(len(partir_en_lotes(p)) for _, _, p in seleccion)
        self.stdout.write(
            f"{'[DRY-RUN] ' if dry_run else ''}{len(seleccion)} registro(s), {total_campos} campo(s) pendiente(s), "
            f"{total_peticiones} petición(es) previstas (alcance P1: {', '.join(APPS_P1)})."
        )
        llamador = None if dry_run else Llamador(_crear_cliente(), pausa)

        intentados = guardados = omitidos = 0
        errores = []

        def fallo(modelo, obj, campo, es, mensaje):
            errores.append((f"{modelo._meta.label}#{obj.pk}.{campo}", mensaje))
            self.stdout.write(f"  • {campo}\n    ES: {es}")
            self.stdout.write(self.style.ERROR(f"    ERROR: {mensaje}"))

        for modelo, obj, pendientes in seleccion:
            self.stdout.write(f"\n=== {modelo._meta.label} #{obj.pk} — {obj}")
            if dry_run:
                for campo, es in pendientes:
                    self.stdout.write(f"  • {campo}\n    ES: {es}\n    EN: (dry-run: no se traduce)")
                continue

            for lote in partir_en_lotes(pendientes):
                intentados += len(lote)
                try:
                    respuesta = llamador.traducir(dict(lote), _contexto(modelo))
                except Exception as exc:  # petición fallida: sus campos quedan vacíos; se sigue con el siguiente
                    mensaje = f"{type(exc).__name__}: {exc}"
                    for campo, es in lote:
                        fallo(modelo, obj, campo, es, mensaje)
                    continue

                sobrantes = sorted(set(respuesta) - {c for c, _ in lote})
                if sobrantes:
                    self.stdout.write(self.style.WARNING(f"  (claves no solicitadas ignoradas: {', '.join(sobrantes)})"))
                for campo, es in lote:
                    try:
                        if campo not in respuesta:
                            raise ErrorTraduccion("la respuesta no incluye esta clave")
                        if not isinstance(respuesta[campo], str):
                            raise ErrorTraduccion("el valor devuelto no es texto")
                        en = _limpiar_respuesta(respuesta[campo])
                        validar_traduccion(es, en)
                        n = self._guardar(modelo, obj, campo, en)
                    except Exception as exc:  # una traducción inválida no impide guardar las demás
                        fallo(modelo, obj, campo, es, f"{type(exc).__name__}: {exc}")
                        continue
                    if n:
                        guardados += 1
                        self.stdout.write(f"  • {campo}\n    ES: {es}\n    EN: {en}")
                    else:
                        omitidos += 1
                        self.stdout.write(f"  • {campo}: ya tenía traducción, no se sobrescribe")

        self.stdout.write("\n" + "-" * 60)
        if dry_run:
            self.stdout.write(
                f"Dry-run: {total_campos} campo(s) en {total_peticiones} petición(es). No se llamó a Gemini ni se guardó nada."
            )
            return
        self.stdout.write(
            f"Llamadas reales a Gemini: {llamador.llamadas} (reintentos: {llamador.reintentos})\n"
            f"Campos intentados: {intentados} · guardados: {guardados} · ya traducidos (no pisados): {omitidos} "
            f"· con error: {len(errores)}"
        )
        for donde, mensaje in errores:
            self.stdout.write(self.style.ERROR(f"  - {donde}: {mensaje}"))
