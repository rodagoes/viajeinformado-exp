"""Carga OFFLINE de traducciones EN del contenido dinámico (P1 + movilidad, servicios y emergencias)
desde un archivo JSON versionable.

Sin llamadas a ninguna API. El mismo archivo sirve en local y en producción:
- cada registro se localiza por una clave natural estable (slug, o padre + orden/valor)
  y, si no existe, por PK; el PK es solo una referencia auxiliar;
- antes de escribir se valida que el texto ES actual coincida con el del archivo
  (así una traducción nunca se aplica a un contenido distinto);
- nunca se sobrescribe un `campo_en` existente (UPDATE condicional);
- un registro que no existe en el entorno (la BD de producción no es la local) NO es un error:
  se cuenta como `no_encontrados` y el resto sigue.

Formato (ver apps/base/data/traducciones_en.json):
  {"_meta": {...},
   "modelos": {"app.Modelo": [
       {"locator": {"slug": "..."} | null, "pk": 1, "_ref": "texto de referencia",
        "campos": {"campo": {"es": "...", "en": "...", "es_corregido": "... (opcional)"}}}]}}
"""
import io
import json
from dataclasses import dataclass, field

from django.apps import apps
from django.db.models import Q
from modeltranslation.translator import translator

from .management.commands.traducir_contenido import validar_traduccion, ErrorTraduccion

RUTA_POR_DEFECTO = "apps/base/data/traducciones_en.json"

# Apps cuyo contenido dinámico se puede cargar desde el JSON (P1 + ampliación).
APPS_ALCANCE = (
    "base", "turismo", "establecimientos", "gastronomia", "eventos",
    "movilidad", "servicios_turista", "emergencias",
)

# Clave natural estable por modelo (lookups del ORM). Se usa como `locator` en el JSON.
LOCATORS = {
    "base.HomeHeroSlide": ("orden",),
    "turismo.CategoriaLugarTuristico": ("slug",),
    "turismo.ServicioLugarTuristico": ("slug",),
    "turismo.LugarTuristico": ("slug",),
    "turismo.ImagenLugarTuristico": ("lugar__slug", "orden"),
    "turismo.RecomendacionLugarTuristico": ("lugar__slug", "orden"),
    "establecimientos.CategoriaEstablecimiento": ("slug",),
    "establecimientos.ServicioEstablecimiento": ("slug",),
    "establecimientos.Establecimiento": ("slug",),
    "establecimientos.SucursalEstablecimiento": ("establecimiento__slug", "slug"),
    "establecimientos.ContactoSucursalEstablecimiento": ("sucursal__establecimiento__slug", "sucursal__slug", "valor"),
    "establecimientos.ImagenEstablecimiento": ("establecimiento__slug", "orden"),
    "establecimientos.RecomendacionEstablecimiento": ("establecimiento__slug", "orden"),
    "gastronomia.CategoriaPlatoTipico": ("slug",),
    "gastronomia.PlatoTipico": ("slug",),
    "gastronomia.IngredienteClavePlato": ("plato__slug", "nombre_es"),
    "eventos.CategoriaEvento": ("slug",),
    "eventos.TagExperiencia": ("slug",),
    "eventos.Evento": ("slug",),
    "eventos.ImagenEvento": ("evento__slug", "orden"),
    "eventos.RecomendacionEvento": ("evento__slug", "orden"),
    "movilidad.CategoriaMovilidad": ("slug",),
    "movilidad.RutaMovilidad": ("slug",),
    "movilidad.TransportePublico": ("slug",),
    "movilidad.ConsejoMovilidad": ("texto_es",),
    "servicios_turista.CategoriaServicioTurista": ("slug",),
    "servicios_turista.ServicioTurista": ("slug",),
    "servicios_turista.ContactoServicioTurista": ("servicio__slug", "valor"),
    "servicios_turista.ImagenServicioTurista": ("servicio__slug", "orden"),
    "emergencias.ContactoEmergencia": ("ambito", "categoria", "nombre"),
    "emergencias.NumeroContactoAdicional": ("contacto__nombre", "numero_visible"),
}

# Nunca se traducen (nombres propios): el importador los rechaza aunque estén en el archivo.
CAMPOS_PROHIBIDOS = {
    "turismo.LugarTuristico": {"nombre"},
    "eventos.Evento": {"nombre"},
    "establecimientos.Establecimiento": {"nombre"},
    "gastronomia.PlatoTipico": {"nombre"},
}


class ArchivoInvalido(Exception):
    """El archivo no tiene la estructura esperada (falla antes de escribir nada)."""


def normalizar(texto):
    """Compara ES ignorando saltos de línea CRLF y espacios de los extremos."""
    return (texto or "").replace("\r\n", "\n").strip()


def permitidos():
    return {
        m._meta.label: set(translator.get_options_for_model(m).fields)
        for m in translator.get_registered_models()
        if m._meta.app_label in APPS_ALCANCE
    }


def valor_de(obj, ruta):
    """getattr encadenado con '__' (p. ej. 'lugar__slug')."""
    for parte in ruta.split("__"):
        obj = getattr(obj, parte)
    return obj


def locator_de(obj):
    """{lookup: valor} de la clave natural del objeto, o None si no identifica un único registro."""
    lookups = LOCATORS.get(obj._meta.label)
    if not lookups:
        return None
    loc = {l: valor_de(obj, l) for l in lookups}
    if any(v in (None, "") for v in loc.values()):
        return None
    if obj.__class__._default_manager.filter(**loc).count() != 1:
        return None
    return loc


def cargar_archivo(ruta):
    try:
        with io.open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError as exc:
        raise ArchivoInvalido(f"No existe el archivo: {ruta}") from exc
    except (ValueError, OSError) as exc:
        raise ArchivoInvalido(f"No se pudo leer el JSON ({exc})") from exc
    return datos


def validar_estructura(datos):
    """Valida TODO el archivo (estructura, modelos y campos permitidos). Devuelve la lista de errores."""
    errores = []
    if not isinstance(datos, dict) or not isinstance(datos.get("modelos"), dict):
        return ["falta la clave 'modelos' (objeto)"]
    ok = permitidos()
    for label, registros in datos["modelos"].items():
        if label not in ok:
            errores.append(f"{label}: modelo fuera del alcance / no registrado en modeltranslation")
            continue
        if not isinstance(registros, list):
            errores.append(f"{label}: debe ser una lista de registros")
            continue
        for i, reg in enumerate(registros):
            donde = f"{label}[{i}]"
            if not isinstance(reg, dict) or not isinstance(reg.get("campos"), dict) or not reg["campos"]:
                errores.append(f"{donde}: falta 'campos' (objeto no vacío)")
                continue
            loc, pk = reg.get("locator"), reg.get("pk")
            if not (isinstance(loc, dict) and loc) and not isinstance(pk, int):
                errores.append(f"{donde}: necesita 'locator' (objeto) o 'pk' (entero)")
            if isinstance(loc, dict) and loc and set(loc) != set(LOCATORS.get(label, ())):
                errores.append(f"{donde}: locator {sorted(loc)} distinto del esperado {sorted(LOCATORS.get(label, ()))}")
            for campo, val in reg["campos"].items():
                if campo in CAMPOS_PROHIBIDOS.get(label, ()):
                    errores.append(f"{donde}.{campo}: campo prohibido (nombre propio)")
                elif campo not in ok[label]:
                    errores.append(f"{donde}.{campo}: campo no permitido (no registrado para traducción)")
                if not isinstance(val, dict) or not isinstance(val.get("es"), str) or not isinstance(val.get("en"), str):
                    errores.append(f"{donde}.{campo}: debe ser {{'es': str, 'en': str}}")
                elif not val["en"].strip():
                    errores.append(f"{donde}.{campo}: 'en' vacío")
                elif "es_corregido" in val and not isinstance(val["es_corregido"], str):
                    errores.append(f"{donde}.{campo}: 'es_corregido' debe ser texto")
    return errores


@dataclass
class Resultado:
    registros: int = 0
    a_cargar: int = 0       # campos que se cargarían / cargados
    cargados: int = 0
    ya_traducidos: int = 0  # `_en` ya existía: no se sobrescribe
    es_corregidos: int = 0
    errores: list = field(default_factory=list)  # (donde, tipo, mensaje)
    no_encontrados: list = field(default_factory=list)  # (donde, motivo): el registro no existe en este entorno
    detalle: list = field(default_factory=list)  # líneas de informe


def resolver(modelo, reg):
    """Devuelve (obj, via) o lanza LookupError con el motivo."""
    loc = reg.get("locator")
    if isinstance(loc, dict) and loc:
        qs = list(modelo._default_manager.filter(**loc)[:2])
        if len(qs) == 1:
            return qs[0], "locator"
        raise LookupError(f"locator {loc} no resuelve un único registro ({'ninguno' if not qs else 'ambiguo'})")
    pk = reg.get("pk")
    try:
        return modelo._default_manager.get(pk=pk), "pk"
    except modelo.DoesNotExist as exc:
        raise LookupError(f"no existe pk={pk}") from exc


def importar(datos, dry_run=False):
    res = Resultado()
    for label, registros in datos["modelos"].items():
        modelo = apps.get_model(label)
        for reg in registros:
            res.registros += 1
            ref = reg.get("_ref") or reg.get("pk") or reg.get("locator")
            try:
                obj, via = resolver(modelo, reg)
            except LookupError as exc:
                res.no_encontrados.append((f"{label} · {ref}", str(exc)))
                continue
            for campo, val in reg["campos"].items():
                donde = f"{label}#{obj.pk} ({obj}).{campo}"
                es_bd = normalizar(getattr(obj, f"{campo}_es", None))
                es_json = normalizar(val["es"])
                nuevo_es = normalizar(val["es_corregido"]) if val.get("es_corregido") else None
                corregir = False
                if nuevo_es and es_bd == es_json:
                    corregir = True  # la BD aún tiene el texto original: se corrige a es_corregido
                elif es_bd not in (es_json, nuevo_es):
                    res.errores.append((donde, "es_distinto", f"el ES de la BD no coincide con el archivo: {es_bd[:80]!r}"))
                    continue
                fuente_es = nuevo_es or es_json
                en_actual = getattr(obj, f"{campo}_en", None)
                if en_actual and str(en_actual).strip():
                    res.ya_traducidos += 1
                    continue
                try:
                    validar_traduccion(fuente_es, normalizar(val["en"]))
                except ErrorTraduccion as exc:
                    res.errores.append((donde, "validacion", str(exc)))
                    continue
                res.a_cargar += 1
                if corregir:
                    res.es_corregidos += 1
                if dry_run:
                    continue
                if corregir:
                    # rewrite(False): actualiza también la columna original (no la redirige al idioma activo)
                    modelo._default_manager.rewrite(False).filter(pk=obj.pk).update(
                        **{campo: nuevo_es, f"{campo}_es": nuevo_es}
                    )
                filtro = Q(**{f"{campo}_en__isnull": True}) | Q(**{f"{campo}_en": ""})
                n = modelo._default_manager.filter(pk=obj.pk).filter(filtro).update(**{f"{campo}_en": normalizar(val["en"])})
                if n:
                    res.cargados += 1
                else:
                    res.ya_traducidos += 1  # alguien lo rellenó entre la lectura y la escritura
                    res.a_cargar -= 1
    return res
