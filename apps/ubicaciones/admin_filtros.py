"""Filtros del Admin: Provincia -> Distrito dependientes.

Se usan en `list_filter` como `("<ruta>__provincia", ProvinciaDependienteFilter)` y `("<ruta>", DistritoDependienteFilter)`,
una al lado de la otra. Reutilizan `RelatedFieldListFilter` de Django: mismas URLs, mismos parámetros GET.

- Provincia = Todo     -> Distrito lista todos los distritos.
- Provincia = X        -> Distrito lista solo los distritos de X (las opciones se construyen en el servidor).
- Elegir otra provincia -> las URLs de Provincia ya no arrastran el distrito anterior (vuelve a "Todo").
- GET incoherente (Provincia A + Distrito de B, p. ej. una URL editada a mano) -> el distrito se ignora, sin error.

Etiquetas: solo cambia el texto visible (el valor de cada opción sigue siendo el id real). Se muestra el nombre limpio
("Ambo", "Cayna") y solo se añade contexto si el nombre se repite entre las opciones ("San Pedro (Ambo)"). El `__str__` de
los modelos no se toca. Para cambiar el texto visible: `etiqueta_provincia`, `etiqueta_distrito` y `_etiquetas`.
"""
from collections import Counter
from urllib.parse import parse_qsl, urlencode

from django.contrib.admin.filters import RelatedFieldListFilter


def _sin_parametros(query_string, claves):
    """`?a=1&b=2` sin las claves indicadas (conserva el resto: q, o, otros filtros)."""
    pares = [(k, v) for k, v in parse_qsl(query_string.lstrip("?"), keep_blank_values=True) if k not in claves]
    return "?" + urlencode(pares)


def etiqueta_provincia(provincia):
    """Contexto que desambigua dos provincias con el mismo nombre."""
    return provincia.departamento.nombre_oficial


def etiqueta_distrito(distrito):
    """Contexto que desambigua dos distritos con el mismo nombre."""
    return distrito.provincia.nombre_oficial


def _etiquetas(objetos, contexto):
    """[(id, texto)]: nombre limpio; con contexto entre paréntesis solo si el nombre se repite."""
    objetos = list(objetos)
    repetidos = Counter(o.nombre_oficial for o in objetos)
    return [
        (o.pk, f"{o.nombre_oficial} ({contexto(o)})" if repetidos[o.nombre_oficial] > 1 else o.nombre_oficial)
        for o in objetos
    ]


def _con_texto_todo(opciones, texto):
    """Solo cambia el texto de la primera opción ("Todo" -> "Todas"/"Todos")."""
    for i, opcion in enumerate(opciones):
        if i == 0:
            opcion["display"] = texto
        yield opcion


class ProvinciaDependienteFilter(RelatedFieldListFilter):
    """Provincia: al elegir una, se descarta el distrito seleccionado (podría pertenecer a otra provincia)."""

    def _param_distrito(self):
        # "distrito__provincia" -> "distrito__id__exact"; "sucursales__distrito__provincia" -> "sucursales__distrito__id__exact"
        return self.field_path[: -len("provincia")] + "id__exact"

    def field_choices(self, field, request, model_admin):
        provincias = field.remote_field.model._default_manager.select_related("departamento")
        return _etiquetas(provincias.order_by("nombre_oficial"), etiqueta_provincia)

    def choices(self, changelist):
        descartar = {self._param_distrito()}
        opciones = super().choices(changelist)
        for i, opcion in enumerate(_con_texto_todo(opciones, "Todas")):
            if i:  # la primera opción es "Todas": conserva el distrito (sigue siendo coherente)
                opcion["query_string"] = _sin_parametros(opcion["query_string"], descartar)
            yield opcion


class DistritoDependienteFilter(RelatedFieldListFilter):
    """Distrito: opciones limitadas a la provincia activa (si la hay) y distrito incoherente ignorado."""

    def _param_provincia(self):
        return f"{self.field_path}__provincia__id__exact"

    def _provincia_activa(self, request):
        valor = request.GET.get(self._param_provincia(), "")
        return valor if valor.isdigit() else None

    def field_choices(self, field, request, model_admin):
        distritos = field.remote_field.model._default_manager.select_related("provincia")
        provincia = self._provincia_activa(request)
        if provincia:
            distritos = distritos.filter(provincia_id=provincia)
        return _etiquetas(distritos.order_by("nombre_oficial", "provincia__nombre_oficial"), etiqueta_distrito)

    def choices(self, changelist):
        return _con_texto_todo(super().choices(changelist), "Todos")

    def has_output(self):
        return bool(self.lookup_choices)  # una provincia con un solo distrito también muestra el filtro

    def queryset(self, request, queryset):
        validos = {str(pk) for pk, _ in self.lookup_choices}
        pedidos = self.lookup_val if isinstance(self.lookup_val, (list, tuple)) else [self.lookup_val]
        if any(v and str(v) not in validos for v in pedidos):
            return queryset  # distrito de otra provincia: se ignora
        return super().queryset(request, queryset)
