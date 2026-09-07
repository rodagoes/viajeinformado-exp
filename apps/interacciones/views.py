from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.establecimientos.models import SucursalEstablecimiento

from .models import Favorito, Resena
from .services import TIPOS_RECURSO as TIPOS_FAVORITO
from .services import _filtro_recurso, resolver_recurso

FILTROS_VALIDOS = {"todos", "lugares", "restaurantes", "alojamientos"}

RECURSO_ACTIVO = Q(establecimiento__isnull=True) | Q(establecimiento__activo=True)
RECURSO_ACTIVO &= Q(lugar_turistico__isnull=True) | Q(lugar_turistico__activo=True)


@require_POST
def toggle_favorito(request, tipo, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "auth_required": True}, status=401)

    modelo = TIPOS_FAVORITO.get(tipo)
    if modelo is None:
        return JsonResponse({"ok": False, "error": "tipo_invalido"}, status=400)

    try:
        recurso = modelo.objects.get(pk=pk, activo=True)
    except modelo.DoesNotExist:
        return JsonResponse({"ok": False, "error": "no_encontrado"}, status=404)

    campo = "establecimiento" if tipo == "establecimiento" else "lugar_turistico"
    favorito = Favorito.objects.filter(usuario=request.user, **{campo: recurso}).first()

    if favorito:
        favorito.delete()
        return JsonResponse({"ok": True, "es_favorito": False, "accion": "eliminado"})

    try:
        with transaction.atomic():
            Favorito.objects.create(usuario=request.user, **{campo: recurso})
    except IntegrityError:
        pass  # doble clic / carrera: el UniqueConstraint de F1 ya lo creó, se responde como éxito

    return JsonResponse({"ok": True, "es_favorito": True, "accion": "agregado"})


@login_required
def favoritos(request):
    tipo = request.GET.get("tipo", "todos")
    if tipo not in FILTROS_VALIDOS:
        tipo = "todos"

    sucursales_prefetch = Prefetch(
        "establecimiento__sucursales",
        queryset=SucursalEstablecimiento.objects.filter(activo=True)
        .select_related("distrito", "localidad")
        .order_by("-es_principal", "id"),
    )

    qs = (
        Favorito.objects.filter(usuario=request.user)
        .filter(RECURSO_ACTIVO)
        .select_related(
            "establecimiento__categoria_principal",
            "lugar_turistico__distrito",
            "lugar_turistico__localidad",
        )
        .prefetch_related(sucursales_prefetch)
    )

    if tipo == "lugares":
        qs = qs.filter(lugar_turistico__isnull=False)
    elif tipo == "restaurantes":
        qs = qs.filter(establecimiento__tipo="restaurante")
    elif tipo == "alojamientos":
        qs = qs.filter(establecimiento__tipo="alojamiento")

    favoritos_list = list(qs)

    est_ids = [f.establecimiento_id for f in favoritos_list if f.establecimiento_id]
    lugar_ids = [f.lugar_turistico_id for f in favoritos_list if f.lugar_turistico_id]

    ratings_est = {
        r["establecimiento_id"]: (r["promedio"], r["total"])
        for r in Resena.objects.filter(
            estado=Resena.ESTADO_PUBLICADO, establecimiento_id__in=est_ids
        ).values("establecimiento_id").annotate(promedio=Avg("valoracion"), total=Count("id"))
    }
    ratings_lugar = {
        r["lugar_turistico_id"]: (r["promedio"], r["total"])
        for r in Resena.objects.filter(
            estado=Resena.ESTADO_PUBLICADO, lugar_turistico_id__in=lugar_ids
        ).values("lugar_turistico_id").annotate(promedio=Avg("valoracion"), total=Count("id"))
    }

    for favorito in favoritos_list:
        if favorito.establecimiento_id:
            favorito.rating = ratings_est.get(favorito.establecimiento_id)
        else:
            favorito.rating = ratings_lugar.get(favorito.lugar_turistico_id)

    if favoritos_list:
        tiene_favoritos_globales = True
    elif tipo == "todos":
        tiene_favoritos_globales = False
    else:
        tiene_favoritos_globales = Favorito.objects.filter(usuario=request.user).filter(RECURSO_ACTIVO).exists()

    return render(
        request,
        "interacciones/favoritos.html",
        {
            "favoritos": favoritos_list,
            "tipo": tipo,
            "tiene_favoritos_globales": tiene_favoritos_globales,
        },
    )


@login_required
@require_POST
def eliminar_resena(request, tipo, pk):
    modelo, recurso = resolver_recurso(tipo, pk)
    if modelo is None:
        return HttpResponseBadRequest()
    if recurso is None:
        raise Http404
    Resena.objects.filter(usuario=request.user, **_filtro_recurso(tipo, recurso)).delete()
    messages.success(request, "Reseña eliminada.")
    return redirect(f"{recurso.get_absolute_url()}#resenas")
