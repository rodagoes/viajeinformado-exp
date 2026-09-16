from django.urls import reverse

from apps.movilidad.services.como_llegar import (
    obtener_consejos_aereos,
    obtener_consejos_terrestres,
    obtener_rutas_aereas,
    obtener_rutas_terrestres,
)
from apps.movilidad.services.tarifas_taxi import (
    obtener_consejos_movilidad,
    obtener_transportes_con_tarifas,
)

from . import INTERNAL, MIXED, decimal_str, normalizar_limit, resultado_lista, validar_choice

VIA_CHOICES = [("terrestre", "Terrestre"), ("aerea", "Aérea")]

_FUENTES_POR_VIA = {
    "terrestre": (obtener_rutas_terrestres, obtener_consejos_terrestres),
    "aerea": (obtener_rutas_aereas, obtener_consejos_aereos),
}


def consultar_tarifas_movilidad():
    items = [
        {
            "nombre": t["nombre"],
            "nombre_alternativo": t["nombre_alternativo"],
            "descripcion": t["descripcion"],
            "tarifa_minima_pen": t["precio_desde_txt"],
            "tarifa_minima_usd": t["precio_usd_txt"],
        }
        for t in obtener_transportes_con_tarifas()
    ]
    # La tarifa es dato propio; el USD sale de TipoCambio (origen externo).
    tipo_fuente = MIXED if any(i["tarifa_minima_usd"] for i in items) else INTERNAL
    return resultado_lista(
        "consultar_tarifas_movilidad",
        items,
        tipo_fuente,
        consejos=obtener_consejos_movilidad(),
        url=reverse("movilidad:tarifas_taxi"),
    )


def _punto(texto, localidad, distrito):
    if texto:
        return texto
    if localidad:
        return localidad.nombre
    if distrito:
        return distrito.nombre_oficial
    return None


def _ruta(ruta, via):
    return {
        "via": via,
        "nombre": ruta.nombre,
        "slug": ruta.slug,
        "descripcion_corta": ruta.descripcion_corta,
        "origen": _punto(ruta.origen_texto, ruta.origen_localidad, ruta.origen_distrito),
        "destino": _punto(ruta.destino_texto, ruta.destino_localidad, ruta.destino_distrito),
        "punto_partida": ruta.punto_partida,
        "punto_llegada": ruta.punto_llegada,
        "indicaciones": ruta.indicaciones,
        "duracion_estimada": ruta.duracion_estimada,
        "duracion_bus": ruta.duracion_bus,
        "duracion_automovil": ruta.duracion_automovil,
        "distancia_km": decimal_str(ruta.distancia_km),
        "frecuencia": ruta.frecuencia,
        "horario_referencial": ruta.horario_referencial,
        "tipo_costo": ruta.tipo_costo,
        "precio_desde": decimal_str(ruta.precio_desde),
        "precio_hasta": decimal_str(ruta.precio_hasta),
        "recomendaciones": ruta.recomendaciones,
        "advertencias": ruta.advertencias,
        "operador": ruta.operador.nombre if ruta.operador_id else None,
    }


def consultar_como_llegar(via=None, limit=None):
    via = validar_choice(via, "via", VIA_CHOICES)
    limit = normalizar_limit(limit)

    items = []
    consejos = {}
    for nombre_via, (obtener_rutas, obtener_consejos) in _FUENTES_POR_VIA.items():
        if via and via != nombre_via:
            continue
        rutas = obtener_rutas().select_related(
            "operador",
            "origen_distrito", "origen_localidad",
            "destino_distrito", "destino_localidad",
        )[:limit]
        items.extend(_ruta(r, nombre_via) for r in rutas)
        consejos[nombre_via] = obtener_consejos()

    return resultado_lista(
        "consultar_como_llegar",
        items,
        consejos=consejos,
        url=reverse("movilidad:como_llegar"),
    )
