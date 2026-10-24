"""Filtros Año / Mes del Admin de Métricas (reemplazan a date_hierarchy y a "Hoy / 7 días / Este mes").

Se usan en las constantes `<MODELO>_FILTROS_ADMIN` de apps/metricas/admin.py. Cada campo de fecha real tiene su par de
subclases (solo cambia `campo`). Los años salen de los datos del propio listado; los meses son los 12 nombres traducibles.
Año y Mes se combinan entre sí y con el resto de filtros (el Admin conserva q, o y demás parámetros).
"""
from django.contrib import admin
from django.utils.dates import MONTHS


class AnioFilter(admin.SimpleListFilter):
    title = "año"
    parameter_name = "anio"
    campo = "fecha"  # campo DateField del modelo sobre el que filtra

    def lookups(self, request, model_admin):
        anios = model_admin.get_queryset(request).dates(self.campo, "year", order="DESC")
        return [(str(a.year), str(a.year)) for a in anios]

    def queryset(self, request, queryset):
        if self.value() and self.value().isdigit():
            return queryset.filter(**{f"{self.campo}__year": int(self.value())})
        return queryset


class MesFilter(admin.SimpleListFilter):
    title = "mes"
    parameter_name = "mes"
    campo = "fecha"

    def lookups(self, request, model_admin):
        return [(str(n), str(nombre).capitalize()) for n, nombre in MONTHS.items()]

    def queryset(self, request, queryset):
        if self.value() and self.value().isdigit() and 1 <= int(self.value()) <= 12:
            return queryset.filter(**{f"{self.campo}__month": int(self.value())})
        return queryset


# Un par por campo de fecha real (fecha, primera_visita). `fecha` es el valor por defecto de las clases base.
class AnioPrimeraVisitaFilter(AnioFilter):
    campo = "primera_visita"


class MesPrimeraVisitaFilter(MesFilter):
    campo = "primera_visita"


class AgruparPorFilter(admin.SimpleListFilter):
    """"Granularidad" (término técnico) mostrada como "Agrupar por": Semana / Mes. El campo del modelo no cambia."""

    title = "agrupar por"
    parameter_name = "agrupar_por"

    def lookups(self, request, model_admin):
        from .choices import GranularidadUnicos
        return GranularidadUnicos.choices

    def queryset(self, request, queryset):
        return queryset.filter(granularidad=self.value()) if self.value() else queryset
