from django.urls import NoReverseMatch, reverse

from .navegacion import HEADER_NAV_ITEMS, resolver_seccion_activa


def _resolve(item):
    resolved = dict(item)
    # `url_name` se conserva (no se descarta) para que el template pueda
    # comparar el link exacto del dropdown contra la página actual y
    # marcarlo como "item actual" dentro del submenú (ver header.html).
    url_name = resolved.get("url_name")
    if url_name:
        try:
            resolved["href"] = reverse(url_name)
        except NoReverseMatch:
            resolved["href"] = "#"
    else:
        resolved.setdefault("href", "#")
    if resolved.get("children"):
        resolved["children"] = [_resolve(child) for child in resolved["children"]]
    return resolved


def header_nav_items(request):
    return {"header_nav_items": [_resolve(item) for item in HEADER_NAV_ITEMS]}


def active_nav(request):
    """Sección del header activa para la página actual, resuelta de forma
    global (namespace/url_name vía `resolver_seccion_activa`) en vez de
    que cada vista la fije manualmente — única fuente de verdad."""
    resolver_match = getattr(request, "resolver_match", None)
    return {"active_nav": resolver_seccion_activa(resolver_match)}
