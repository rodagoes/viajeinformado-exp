"""
Herramientas deterministas de acceso a datos de Viaje Informado.

Cada provider recibe argumentos ya estructurados, ejecuta consultas ORM
predefinidas (o reutiliza services existentes) y devuelve dicts
JSON-serializables. Sin NLP, sin IA, sin SQL dinámico.

Argumentos inválidos → ArgumentoInvalido (el catálogo la convierte en un
resultado {"ok": False}). Cero resultados NO es un error.
"""
import datetime

DEFAULT_LIMIT = 5
MAX_LIMIT = 10

INTERNAL = "internal"
EXTERNAL_TRUSTED = "external_trusted"
MIXED = "mixed"


class ArgumentoInvalido(ValueError):
    def __init__(self, campo, detalle):
        super().__init__(f"{campo}: {detalle}")
        self.campo = campo
        self.detalle = detalle


def normalizar_limit(limit, default=DEFAULT_LIMIT):
    if limit is None:
        return default
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ArgumentoInvalido("limit", "debe ser un entero")
    if not 1 <= limit <= MAX_LIMIT:
        raise ArgumentoInvalido("limit", f"debe estar entre 1 y {MAX_LIMIT}")
    return limit


def validar_texto(valor, campo):
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ArgumentoInvalido(campo, "debe ser texto")
    return valor.strip() or None


def validar_texto_obligatorio(valor, campo):
    valor = validar_texto(valor, campo)
    if valor is None:
        raise ArgumentoInvalido(campo, "es obligatorio")
    return valor


def validar_choice(valor, campo, choices):
    valor = validar_texto(valor, campo)
    if valor is None:
        return None
    validos = [opcion[0] for opcion in choices]
    if valor not in validos:
        raise ArgumentoInvalido(campo, f"valores permitidos: {', '.join(validos)}")
    return valor


def validar_bool(valor, campo):
    if valor is None or isinstance(valor, bool):
        return valor
    raise ArgumentoInvalido(campo, "debe ser true o false")


def validar_fecha(valor, campo):
    if valor is None:
        return None
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor
    if isinstance(valor, str):
        try:
            return datetime.date.fromisoformat(valor.strip())
        except ValueError:
            pass
    raise ArgumentoInvalido(campo, "debe ser una fecha ISO (YYYY-MM-DD)")


def validar_lista_texto(valor, campo):
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, (list, tuple)) or not all(isinstance(v, str) for v in valor):
        raise ArgumentoInvalido(campo, "debe ser texto o lista de textos")
    limpios = [v.strip() for v in valor if v.strip()]
    return limpios or None


def decimal_str(valor):
    return None if valor is None else str(valor)


def fecha_iso(valor):
    return None if valor is None else valor.isoformat()


def ubicacion_de(distrito, localidad=None):
    if distrito is None:
        return {"distrito": None, "distrito_slug": None, "provincia": None, "localidad": None}
    return {
        "distrito": distrito.nombre_oficial,
        "distrito_slug": distrito.slug,
        "provincia": distrito.provincia.nombre_oficial,
        "localidad": localidad.nombre if localidad else None,
    }


def kwargs_ubicacion(distrito, provincia, prefijo=""):
    """Filtros ORM por slug de distrito/provincia. Se devuelven como dict para
    aplicarlos en UN solo .filter() cuando el prefijo atraviesa una relación
    múltiple (ej. sucursales__) y así garantizar que sea la misma fila."""
    distrito = validar_texto(distrito, "distrito")
    provincia = validar_texto(provincia, "provincia")
    filtros = {}
    if distrito:
        filtros[f"{prefijo}distrito__slug"] = distrito
    if provincia:
        filtros[f"{prefijo}distrito__provincia__slug"] = provincia
    return filtros


def resultado_lista(tool, items, tipo_fuente=INTERNAL, **extra):
    return {
        "ok": True,
        "tool": tool,
        "tipo_fuente": tipo_fuente,
        "count": len(items),
        "items": items,
        **extra,
    }


def resultado_item(tool, item, tipo_fuente=INTERNAL):
    return {"ok": True, "tool": tool, "tipo_fuente": tipo_fuente, "item": item}
