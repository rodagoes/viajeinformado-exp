from decimal import Decimal

from django.db.models import Prefetch, Q

from apps.establecimientos.models import (
    CategoriaEstablecimiento,
    Establecimiento,
    RecomendacionEstablecimiento,
    ServicioEstablecimiento,
    SucursalEstablecimiento,
)
from apps.gastronomia.models import PlatoTipico
from apps.monedas.models import TipoCambio

from . import (
    ArgumentoInvalido,
    decimal_str,
    kwargs_ubicacion,
    normalizar_limit,
    resultado_item,
    resultado_lista,
    ubicacion_de,
    validar_bool,
    validar_choice,
    validar_texto,
    validar_texto_obligatorio,
)

MONEDA_CHOICES = [("PEN", "Soles"), ("USD", "Dólares")]


def _validar_monto(valor, campo):
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        raise ArgumentoInvalido(campo, "debe ser un número en soles o dólares")
    monto = Decimal(str(valor))
    if monto <= 0:
        raise ArgumentoInvalido(campo, "debe ser mayor que 0")
    return monto.quantize(Decimal("0.01"))


def _presupuesto_pen(precio_max, moneda):
    """→ (precio_max en PEN, info de conversión | None). USD usa solo el tipo de
    cambio vigente registrado (venta); sin tipo de cambio no se convierte."""
    if precio_max is None or moneda != "USD":
        return precio_max, None
    tipo_cambio = TipoCambio.vigente()
    if tipo_cambio is None or not tipo_cambio.venta:
        raise ArgumentoInvalido(
            "moneda", "no hay tipo de cambio vigente para convertir dólares; pide el presupuesto en soles"
        )
    convertido = (precio_max * tipo_cambio.venta).quantize(Decimal("0.01"))
    return convertido, {
        "moneda": "USD",
        "monto_original": decimal_str(precio_max),
        "tipo_cambio_venta": decimal_str(tipo_cambio.venta),
        "fecha_tipo_cambio": tipo_cambio.fecha.isoformat(),
    }


def _sucursales_prefetch():
    # Principal primero: la primera sucursal prefetched es la representativa
    return Prefetch(
        "sucursales",
        queryset=SucursalEstablecimiento.objects.filter(activo=True)
        .select_related("distrito__provincia", "localidad")
        .order_by("-es_principal", "id"),
    )


def _base(tipo=None):
    qs = Establecimiento.objects.filter(activo=True)
    if tipo:
        qs = qs.filter(tipo=tipo)
    return qs.select_related("categoria_principal").prefetch_related(
        _sucursales_prefetch(),
        Prefetch(
            "categorias_secundarias",
            queryset=CategoriaEstablecimiento.objects.filter(activo=True),
        ),
    )


def _sucursal_resumen(sucursal):
    if sucursal is None:
        return None
    return {
        "nombre": sucursal.nombre,
        "es_principal": sucursal.es_principal,
        "direccion": sucursal.direccion,
        "horario_atencion": sucursal.horario_atencion,
        **ubicacion_de(sucursal.distrito, sucursal.localidad),
    }


def _sucursal_detalle(sucursal):
    return {
        **_sucursal_resumen(sucursal),
        "referencia": sucursal.referencia,
        "telefono": sucursal.telefono,
        "whatsapp": sucursal.whatsapp,
        "correo": sucursal.correo,
        "latitud": decimal_str(sucursal.latitud),
        "longitud": decimal_str(sucursal.longitud),
        "maps_url": sucursal.maps_url,
    }


def _resumen(establecimiento):
    sucursales = list(establecimiento.sucursales.all())
    return {
        "id": establecimiento.pk,
        "nombre": establecimiento.nombre,
        "slug": establecimiento.slug,
        "tipo": establecimiento.tipo,
        "descripcion_corta": establecimiento.descripcion_corta,
        "categoria": establecimiento.categoria_principal.nombre,
        "categoria_slug": establecimiento.categoria_principal.slug,
        "rango_precio": establecimiento.rango_precio,
        "precio_desde": decimal_str(establecimiento.precio_desde),
        "precio_hasta": decimal_str(establecimiento.precio_hasta),
        "especialidades": [c.nombre for c in establecimiento.categorias_secundarias.all()],
        "destacado": establecimiento.destacado,
        "sucursal": _sucursal_resumen(sucursales[0] if sucursales else None),
        "url": establecimiento.get_absolute_url(),
    }


def _buscar(
    tool, tipo, q, categoria, distrito, provincia, rango_precio, servicio, destacado,
    precio_max, moneda, limit,
):
    limit = normalizar_limit(limit)
    q = validar_texto(q, "q")
    categoria = validar_texto(categoria, "categoria")
    servicio = validar_texto(servicio, "servicio")
    rango_precio = validar_choice(
        rango_precio, "rango_precio", Establecimiento.RANGO_PRECIO_CHOICES
    )
    destacado = validar_bool(destacado, "destacado")
    moneda = validar_choice(moneda, "moneda", MONEDA_CHOICES) or "PEN"
    precio_max, conversion = _presupuesto_pen(_validar_monto(precio_max, "precio_max"), moneda)
    filtros_ubicacion = kwargs_ubicacion(distrito, provincia, prefijo="sucursales__")

    qs = _base(tipo)
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(descripcion_corta__icontains=q))
    if categoria:
        # Slug exacto o nombre parcial ("parrillas" → "Pollería / Parrillas"):
        # el modelo no conoce los slugs reales del catálogo.
        qs = qs.filter(
            Q(categoria_principal__slug=categoria) | Q(categorias_secundarias__slug=categoria)
            | Q(categoria_principal__nombre__icontains=categoria)
            | Q(categorias_secundarias__nombre__icontains=categoria)
        )
    if filtros_ubicacion:
        qs = qs.filter(sucursales__activo=True, **filtros_ubicacion)
    if rango_precio:
        qs = qs.filter(rango_precio=rango_precio)
    if servicio:
        qs = qs.filter(servicios__slug=servicio)
    if destacado is not None:
        qs = qs.filter(destacado=destacado)
    if precio_max is not None:
        # Solo garantiza que el precio mínimo registrado no supera el presupuesto;
        # el rango real viaja en cada item para que el turista decida.
        qs = qs.filter(precio_desde__isnull=False, precio_desde__lte=precio_max)

    qs = qs.distinct().order_by("-destacado", "nombre", "id")[:limit]
    extra = {}
    if precio_max is not None:
        extra["presupuesto"] = {"precio_max_pen": decimal_str(precio_max), "conversion": conversion}
    return resultado_lista(tool, [_resumen(e) for e in qs], **extra)


def buscar_restaurantes(
    q=None,
    categoria=None,
    distrito=None,
    provincia=None,
    rango_precio=None,
    servicio=None,
    destacado=None,
    precio_max=None,
    moneda=None,
    limit=None,
):
    return _buscar(
        "buscar_restaurantes", "restaurante",
        q, categoria, distrito, provincia, rango_precio, servicio, destacado, precio_max, moneda, limit,
    )


def buscar_alojamientos(
    q=None,
    categoria=None,
    distrito=None,
    provincia=None,
    rango_precio=None,
    servicio=None,
    destacado=None,
    precio_max=None,
    moneda=None,
    limit=None,
):
    return _buscar(
        "buscar_alojamientos", "alojamiento",
        q, categoria, distrito, provincia, rango_precio, servicio, destacado, precio_max, moneda, limit,
    )


def obtener_establecimiento(slug):
    slug = validar_texto_obligatorio(slug, "slug")
    establecimiento = (
        _base()
        .prefetch_related(
            Prefetch("servicios", queryset=ServicioEstablecimiento.objects.filter(activo=True)),
            Prefetch(
                "recomendaciones",
                queryset=RecomendacionEstablecimiento.objects.filter(activo=True)
                .select_related("plato_tipico")
                .order_by("orden"),
            ),
        )
        .filter(slug=slug)
        .first()
    )
    if establecimiento is None:
        return resultado_item("obtener_establecimiento", None)

    item = _resumen(establecimiento)
    item.update(
        {
            "descripcion": establecimiento.descripcion,
            "categorias_secundarias": [
                c.nombre for c in establecimiento.categorias_secundarias.all()
            ],
            "servicios": [s.nombre for s in establecimiento.servicios.all()],
            "recomendaciones": [
                {
                    "nombre": r.nombre,
                    "plato_tipico_slug": r.plato_tipico.slug if r.plato_tipico else None,
                }
                for r in establecimiento.recomendaciones.all()
            ],
            "telefono": establecimiento.telefono,
            "whatsapp": establecimiento.whatsapp,
            "correo": establecimiento.correo,
            "sitio_web": establecimiento.sitio_web,
            "carta_url": establecimiento.carta_url,
            "sucursales": [_sucursal_detalle(s) for s in establecimiento.sucursales.all()],
        }
    )
    return resultado_item("obtener_establecimiento", item)


def _resolver_plato(texto):
    """slug exacto → nombre exacto → nombre parcial (primero por orden del catálogo)."""
    activos = PlatoTipico.objects.filter(activo=True)
    return (
        activos.filter(slug=texto).first()
        or activos.filter(nombre__iexact=texto).first()
        or activos.filter(nombre__icontains=texto).order_by("orden", "nombre").first()
    )


def buscar_restaurantes_por_plato(plato, distrito=None, provincia=None, limit=None):
    plato = validar_texto_obligatorio(plato, "plato")
    limit = normalizar_limit(limit)
    filtros_ubicacion = kwargs_ubicacion(distrito, provincia, prefijo="sucursales__")

    plato_obj = _resolver_plato(plato)
    if plato_obj is None:
        return resultado_lista("buscar_restaurantes_por_plato", [], plato=None)

    qs = _base("restaurante").filter(
        platos_disponibles__plato=plato_obj, platos_disponibles__activo=True
    )
    if filtros_ubicacion:
        qs = qs.filter(sucursales__activo=True, **filtros_ubicacion)
    qs = qs.distinct().order_by("-destacado", "nombre", "id")[:limit]

    return resultado_lista(
        "buscar_restaurantes_por_plato",
        [_resumen(e) for e in qs],
        plato={"id": plato_obj.pk, "nombre": plato_obj.nombre, "slug": plato_obj.slug},
    )
