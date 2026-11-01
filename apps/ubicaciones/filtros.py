"""Filtro territorial (provincia → distrito) compartido por los listados públicos.

Solo ofrece distritos con datos reales: el llamador pasa los ids que tienen
contenido activo. El valor llega por ?distrito=<id>; uno inválido o sin
datos se ignora sin error.
"""
from itertools import groupby

from .models import Distrito


def filtro_distrito(request, distrito_ids):
    """Devuelve (distrito_id_seleccionado | None, grupos_para_el_select)."""
    distritos = list(
        Distrito.objects.filter(pk__in=set(distrito_ids))
        .select_related("provincia")
        .order_by("provincia__nombre_oficial", "nombre_oficial")
    )
    valor = request.GET.get("distrito", "").strip()
    seleccionado = int(valor) if valor.isdigit() and int(valor) in {d.pk for d in distritos} else None
    grupos = [
        {
            "provincia": provincia.nombre_oficial,
            "distritos": [
                {"id": d.pk, "nombre": d.nombre_oficial, "selected": d.pk == seleccionado} for d in items
            ],
        }
        for provincia, items in groupby(distritos, key=lambda d: d.provincia)
    ]
    return seleccionado, grupos
