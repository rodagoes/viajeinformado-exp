from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import render

from .models import CategoriaPlatoTipico, IngredienteClavePlato, PlatoTipico


def platos_tipicos(request):
    categorias = CategoriaPlatoTipico.objects.filter(activo=True).order_by("orden", "nombre")

    categoria_slug = request.GET.get("categoria", "").strip()
    categoria_sel = None
    if categoria_slug:
        categoria_sel = categorias.filter(slug=categoria_slug).first()
        if not categoria_sel:
            categoria_slug = ""

    qs = PlatoTipico.objects.filter(activo=True, categoria__activo=True).select_related(
        "categoria"
    ).prefetch_related(
        Prefetch(
            "ingredientes",
            queryset=IngredienteClavePlato.objects.filter(activo=True).order_by("orden", "id")
        )
    )

    if categoria_sel:
        qs = qs.filter(categoria=categoria_sel)

    paginator = Paginator(qs, 9)
    page_obj = paginator.get_page(request.GET.get("page"))

    categorias_opciones = [
        {"slug": c.slug, "nombre": c.nombre, "selected": c.slug == categoria_slug}
        for c in categorias
    ]

    context = {
        "titulo": "Sabores de Huánuco",
        "subtitulo": (
            "Una fusión entre la sierra y la selva. Descubre la riqueza culinaria "
            "que forma parte de la identidad huanuqueña."
        ),
        "page_obj": page_obj,
        "categorias_opciones": categorias_opciones,
        "categoria_sel": categoria_slug,
        "total_resultados": paginator.count,
    }
    return render(request, "gastronomia/platos_tipicos.html", context)
