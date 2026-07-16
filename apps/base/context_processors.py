from django.urls import NoReverseMatch, reverse

from .navegacion import HEADER_NAV_ITEMS


def _resolve(item):
    resolved = dict(item)
    url_name = resolved.pop("url_name", None)
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
