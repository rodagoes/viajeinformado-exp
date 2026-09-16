"""
Favoritos del turista autenticado (apps.interacciones.Favorito: lugar
turístico o establecimiento). La identidad NUNCA llega como argumento del
modelo ni del cliente: tool_catalog la inyecta (`usuario`) desde la
conversación, que el backend ya ligó al request.user autenticado.
"""
from collections import Counter

from apps.interacciones.models import Favorito

from . import normalizar_limit, resultado_lista, validar_bool, validar_choice
from .establecimientos import _base as _base_establecimientos
from .establecimientos import _resumen as _resumen_establecimiento
from .turismo import _base as _base_lugares
from .turismo import _resumen as _resumen_lugar

TIPO_CHOICES = [
    ("lugar", "Lugar turístico"),
    ("restaurante", "Restaurante"),
    ("alojamiento", "Alojamiento"),
]
TIPO_LABEL = dict(TIPO_CHOICES)
MAX_SUGERENCIAS = 4


def ids_favoritos(usuario):
    """→ (ids de lugares, ids de establecimientos) del usuario, más recientes primero.
    Vacíos para anónimo. Usado también por el planificador de itinerarios."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return [], []
    favoritos = Favorito.objects.filter(usuario=usuario).order_by("-creado", "-id")
    lugares = [f.lugar_turistico_id for f in favoritos if f.lugar_turistico_id]
    establecimientos = [f.establecimiento_id for f in favoritos if f.establecimiento_id]
    return lugares, establecimientos


def _ordenados(qs, ids):
    """Objetos de `qs` (solo activos) en el orden de `ids`."""
    por_id = {o.pk: o for o in qs.filter(pk__in=ids)}
    return [por_id[i] for i in ids if i in por_id]


def _item(tipo, resumen):
    return {"tipo": tipo, **resumen}


def _sugerencias(lugares, establecimientos, tipo):
    """Personalización conservadora: solo categorías reales de los favoritos
    (la más repetida primero) + 1 opción destacada distinta para no encerrar
    al turista en sus favoritos. Sin scoring ni perfil persistente."""
    sugerencias = []
    grupos = [
        ("lugar", lugares, _base_lugares(), _resumen_lugar, "lugares"),
        ("restaurante", [e for e in establecimientos if e.tipo == "restaurante"], _base_establecimientos("restaurante"), _resumen_establecimiento, "restaurantes"),
        ("alojamiento", [e for e in establecimientos if e.tipo == "alojamiento"], _base_establecimientos("alojamiento"), _resumen_establecimiento, "alojamientos"),
    ]
    for tipo_grupo, favoritos, qs, resumen, plural in grupos:
        if not favoritos or (tipo and tipo != tipo_grupo):
            continue
        excluidos = [f.pk for f in favoritos]
        categorias = Counter(f.categoria_principal for f in favoritos).most_common()
        afines = []
        for categoria, _ in categorias:
            cupo = MAX_SUGERENCIAS - 1 - len(afines)
            if cupo <= 0:
                break
            vistos = excluidos + [a["id"] for a in afines]
            for obj in qs.filter(categoria_principal=categoria).exclude(pk__in=vistos).order_by("-destacado", "nombre", "id")[:cupo]:
                afines.append({
                    **_item(tipo_grupo, resumen(obj)),
                    "motivo": f"Porque tienes guardados {plural} de la categoría {categoria.nombre}",
                })
        sugerencias.extend(afines)
        distinto = (
            qs.exclude(pk__in=excluidos + [a["id"] for a in afines])
            .exclude(categoria_principal__in=[c for c, _ in categorias])
            .order_by("-destacado", "nombre", "id")
            .first()
        )
        if distinto is not None:
            sugerencias.append({
                **_item(tipo_grupo, resumen(distinto)),
                "motivo": f"Opción {'destacada ' if distinto.destacado else ''}de otra categoría, distinta a tus {plural} guardados",
            })
    return sugerencias


def consultar_favoritos(tipo=None, sugerencias=None, limit=None, *, usuario=None):
    """
    Favoritos activos del usuario autenticado (`usuario` lo inyecta el
    backend; nunca es un argumento del modelo). Anónimo → lista vacía con
    autenticado=false. `sugerencias=true` añade opciones afines explicadas.
    """
    tipo = validar_choice(tipo, "tipo", TIPO_CHOICES)
    sugerencias = validar_bool(sugerencias, "sugerencias")
    limit = normalizar_limit(limit)
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return resultado_lista("consultar_favoritos", [], autenticado=False)

    ids_lugares, ids_establecimientos = ids_favoritos(usuario)
    lugares = _ordenados(_base_lugares(), ids_lugares) if tipo in (None, "lugar") else []
    establecimientos = (
        _ordenados(_base_establecimientos(), ids_establecimientos)
        if tipo != "lugar" else []
    )
    if tipo in ("restaurante", "alojamiento"):
        establecimientos = [e for e in establecimientos if e.tipo == tipo]

    items = [_item("lugar", _resumen_lugar(l)) for l in lugares]
    items += [_item(e.tipo, _resumen_establecimiento(e)) for e in establecimientos]
    extra = {"autenticado": True, "tipo": tipo}
    if sugerencias:
        extra["sugerencias"] = _sugerencias(lugares, establecimientos, tipo)
    return resultado_lista("consultar_favoritos", items[:limit], **extra)
