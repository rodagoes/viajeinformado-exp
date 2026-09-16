"""Servicios útiles, emergencias, clima y tipo de cambio."""
from django.db.models import Prefetch, Q
from django.urls import reverse

from apps.clima.services.clima_actual import obtener_clima_actual
from apps.clima.ubicaciones import CIUDAD_PREDETERMINADA, listar_ciudades
from apps.emergencias.models import ContactoEmergencia, ZonaAtencionEmergencia
from apps.monedas.models import TipoCambio
from apps.servicios_turista.models import ContactoServicioTurista, ServicioTurista
from apps.servicios_turista.services.zonas import nombre_publico_zona

from . import (
    EXTERNAL_TRUSTED,
    INTERNAL,
    MAX_LIMIT,
    ArgumentoInvalido,
    decimal_str,
    fecha_iso,
    kwargs_ubicacion,
    normalizar_limit,
    resultado_item,
    resultado_lista,
    ubicacion_de,
    validar_bool,
    validar_choice,
    validar_texto,
)


# --- Servicios útiles -------------------------------------------------------

def _servicio(servicio):
    return {
        "id": servicio.pk,
        "nombre": servicio.nombre,
        "slug": servicio.slug,
        "categoria": servicio.categoria_principal.nombre,
        "categoria_slug": servicio.categoria_principal.slug,
        "descripcion_corta": servicio.descripcion_corta,
        "tipo_atencion": servicio.tipo_atencion,
        "disponibilidad": servicio.disponibilidad,
        "horario_atencion": servicio.horario_atencion,
        "direccion": servicio.direccion,
        "referencia": servicio.referencia,
        "zona": nombre_publico_zona(servicio.distrito) if servicio.distrito_id else None,
        **ubicacion_de(servicio.distrito, servicio.localidad),
        "telefono": servicio.telefono,
        "whatsapp": servicio.whatsapp,
        "correo": servicio.correo,
        "sitio_web": servicio.sitio_web,
        "contactos": [
            {"tipo": c.tipo_contacto, "etiqueta": c.etiqueta, "valor": c.valor}
            for c in servicio.contactos.all()
        ],
        "recomendaciones": servicio.recomendaciones,
        "url": reverse("servicios_turista:servicios_utiles"),
    }


def consultar_servicios_utiles(
    q=None,
    categoria=None,
    tipo_atencion=None,
    disponibilidad=None,
    distrito=None,
    provincia=None,
    limit=None,
):
    limit = normalizar_limit(limit)
    q = validar_texto(q, "q")
    categoria = validar_texto(categoria, "categoria")
    tipo_atencion = validar_choice(tipo_atencion, "tipo_atencion", ServicioTurista.TIPO_ATENCION_CHOICES)
    disponibilidad = validar_choice(disponibilidad, "disponibilidad", ServicioTurista.DISPONIBILIDAD_CHOICES)
    filtros_ubicacion = kwargs_ubicacion(distrito, provincia)

    qs = (
        ServicioTurista.objects.filter(activo=True)
        .select_related("categoria_principal", "distrito__provincia", "localidad")
        .prefetch_related(
            Prefetch(
                "contactos",
                queryset=ContactoServicioTurista.objects.filter(activo=True).order_by("orden", "id"),
            )
        )
    )
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(descripcion_corta__icontains=q))
    if categoria:
        qs = qs.filter(
            Q(categoria_principal__slug=categoria) | Q(categorias_secundarias__slug=categoria)
        ).distinct()
    if tipo_atencion:
        qs = qs.filter(tipo_atencion=tipo_atencion)
    if disponibilidad:
        qs = qs.filter(disponibilidad=disponibilidad)
    if filtros_ubicacion:
        qs = qs.filter(**filtros_ubicacion)

    qs = qs.order_by("-destacado", "categoria_principal__nombre", "nombre", "id")[:limit]
    return resultado_lista("consultar_servicios_utiles", [_servicio(s) for s in qs])


# --- Emergencias ------------------------------------------------------------

def _contacto_emergencia(contacto):
    return {
        "id": contacto.pk,
        "nombre": contacto.nombre,
        "categoria": contacto.categoria,
        "ambito": contacto.ambito,
        "descripcion": contacto.descripcion,
        "numero": contacto.numero_visible,
        "numero_tel": contacto.numero_tel,
        "es_24_horas": contacto.es_24_horas,
        "horario": contacto.horario_texto,
        "zonas": [z.nombre_visible for z in contacto.zonas.all()],
        "numeros_adicionales": [
            {"etiqueta": n.etiqueta, "numero": n.numero_visible, "numero_tel": n.numero_tel}
            for n in contacto.numeros_adicionales.all()
        ],
        "url": reverse("emergencias:emergencias"),
    }


def consultar_emergencias(
    categoria=None, ambito=None, distrito=None, solo_24_horas=None, limit=None
):
    limit = normalizar_limit(limit, default=MAX_LIMIT)
    categoria = validar_choice(categoria, "categoria", ContactoEmergencia.CATEGORIAS)
    ambito = validar_choice(ambito, "ambito", ContactoEmergencia.AMBITOS)
    distrito = validar_texto(distrito, "distrito")
    solo_24_horas = validar_bool(solo_24_horas, "solo_24_horas")

    qs = ContactoEmergencia.objects.filter(activo=True).prefetch_related(
        "numeros_adicionales",
        Prefetch(
            "zonas",
            queryset=ZonaAtencionEmergencia.objects.filter(activo=True).select_related("distrito"),
        ),
    )
    if categoria:
        qs = qs.filter(categoria=categoria)
    if solo_24_horas:
        qs = qs.filter(es_24_horas=True)

    if distrito:
        locales = Q(
            ambito=ContactoEmergencia.AMBITO_LOCAL,
            zonas__distrito__slug=distrito,
            zonas__activo=True,
        )
        nacionales = Q(ambito=ContactoEmergencia.AMBITO_NACIONAL)
        if ambito == ContactoEmergencia.AMBITO_LOCAL:
            qs = qs.filter(locales)
        elif ambito == ContactoEmergencia.AMBITO_NACIONAL:
            qs = qs.filter(nacionales)
        else:
            qs = qs.filter(nacionales | locales)
        qs = qs.distinct()
    elif ambito:
        qs = qs.filter(ambito=ambito)

    qs = qs.order_by("orden", "nombre", "id")[:limit]
    return resultado_lista("consultar_emergencias", [_contacto_emergencia(c) for c in qs])


# --- Clima (Open-Meteo vía apps.clima) --------------------------------------

CAMPOS_CLIMA = (
    "ciudad_slug", "ubicacion", "disponible", "es_respaldo",
    "temperatura_c", "sensacion_c", "humedad_pct", "viento_kph",
    "probabilidad_lluvia_pct", "precipitacion_mm", "nubosidad_pct",
    "estado_texto", "es_dia", "hora_dato", "fuente",
)


def consultar_clima(ciudad=None):
    ciudad = validar_texto(ciudad, "ciudad") or CIUDAD_PREDETERMINADA
    slugs = [c["slug"] for c in listar_ciudades()]
    if ciudad not in slugs:
        raise ArgumentoInvalido("ciudad", f"valores permitidos: {', '.join(slugs)}")

    datos = obtener_clima_actual(ciudad)
    item = {campo: datos.get(campo) for campo in CAMPOS_CLIMA}
    item["url"] = reverse("clima:clima_temporadas")
    return resultado_item("consultar_clima", item, EXTERNAL_TRUSTED)


# --- Tipo de cambio ---------------------------------------------------------

def consultar_tipo_cambio():
    tipo_cambio = TipoCambio.vigente()
    if tipo_cambio is None:
        return resultado_item("consultar_tipo_cambio", None)

    # El registro es editable en admin: solo se afirma origen externo cuando
    # conserva la respuesta de la API (lo que siempre guarda el comando de actualización).
    tipo_fuente = EXTERNAL_TRUSTED if tipo_cambio.respuesta_api else INTERNAL
    item = {
        "fecha": fecha_iso(tipo_cambio.fecha),
        "moneda_origen": tipo_cambio.moneda_origen,
        "moneda_destino": tipo_cambio.moneda_destino,
        "compra": decimal_str(tipo_cambio.compra),
        "venta": decimal_str(tipo_cambio.venta),
        "fuente": tipo_cambio.fuente,
        "url": reverse("monedas:tipo_cambio"),
    }
    return resultado_item("consultar_tipo_cambio", item, tipo_fuente)
