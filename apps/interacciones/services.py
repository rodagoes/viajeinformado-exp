from django.core.paginator import Paginator
from django.db.models import Avg, Count

from apps.establecimientos.models import Establecimiento
from apps.turismo.models import LugarTuristico

from .forms import ResenaForm
from .models import Resena

TIPOS_RECURSO = {"establecimiento": Establecimiento, "lugar": LugarTuristico}

ORDEN_OPCIONES = {
    "recientes": ("Más recientes", ("-creado",)),
    "antiguas": ("Más antiguas", ("creado",)),
    "mejor": ("Mejor valoradas", ("-valoracion", "-creado")),
    "peor": ("Peor valoradas", ("valoracion", "-creado")),
}
ORDEN_DEFAULT = "recientes"


def resolver_recurso(tipo, pk):
    modelo = TIPOS_RECURSO.get(tipo)
    if modelo is None:
        return None, None
    return modelo, modelo.objects.filter(pk=pk, activo=True).first()


def _filtro_recurso(tipo, recurso):
    if tipo == "establecimiento":
        return {"establecimiento": recurso}
    if tipo == "lugar":
        return {"lugar_turistico": recurso}
    raise ValueError(f"Tipo de recurso no soportado: {tipo!r}")


def obtener_resumen_resenas(tipo, recurso):
    publicadas = Resena.objects.filter(estado=Resena.ESTADO_PUBLICADO, **_filtro_recurso(tipo, recurso))
    agregado = publicadas.aggregate(promedio=Avg("valoracion"), total=Count("id"))
    total = agregado["total"] or 0
    por_estrella = {
        fila["valoracion"]: fila["cantidad"]
        for fila in publicadas.values("valoracion").annotate(cantidad=Count("id"))
    }
    distribucion = [
        {
            "estrella": n,
            "cantidad": por_estrella.get(n, 0),
            "porcentaje": round(por_estrella.get(n, 0) / total * 100) if total else 0,
        }
        for n in range(5, 0, -1)
    ]
    return {"promedio": agregado["promedio"], "total": total, "distribucion": distribucion}


def construir_contexto_resenas(request, tipo, recurso, form_resena=None, page_number=None, orden=None):
    filtro = _filtro_recurso(tipo, recurso)
    mi_resena = None
    if request.user.is_authenticated:
        mi_resena = Resena.objects.filter(usuario=request.user, **filtro).first()

    form = form_resena if form_resena is not None else ResenaForm(instance=mi_resena)

    orden_actual = orden if orden in ORDEN_OPCIONES else ORDEN_DEFAULT
    qs_publico = (
        Resena.objects.filter(estado=Resena.ESTADO_PUBLICADO, **filtro)
        .select_related("usuario", "usuario__perfil")
        .order_by(*ORDEN_OPCIONES[orden_actual][1])
    )

    paginator = Paginator(qs_publico, 5)
    resena_id_prefijo = f"review-edit-{mi_resena.pk}" if mi_resena else f"review-create-{tipo}-{recurso.pk}"

    return {
        "resumen_resenas": obtener_resumen_resenas(tipo, recurso),
        "mi_resena": mi_resena,
        "resena_form": form,
        "resenas_page": paginator.get_page(page_number),
        "resena_tipo": tipo,
        "resena_pk": recurso.pk,
        "resena_id_prefijo": resena_id_prefijo,
        "orden_actual": orden_actual,
        "orden_opciones": ORDEN_OPCIONES,
        "orden_label": ORDEN_OPCIONES[orden_actual][0],
    }
