"""
Planificador determinista de itinerarios (C8). Reúne SOLO candidatos reales
de Viaje Informado (lugares, restaurantes, alojamientos, eventos con fecha
confirmada, platos bandera), los reparte por días y calcula el presupuesto
de forma conservadora: solo costos registrados; lo desconocido se declara
como no incluido. El modelo no aporta candidatos ni precios.

ponytail: reparto secuencial (2 lugares/día, 1 restaurante/día, eventos en
su fecha, 1 alojamiento base). Sin optimización ni distancias: la BD no las
soporta.
"""
import datetime
from decimal import Decimal

from django.utils import timezone

from apps.monedas.models import TipoCambio
from apps.ubicaciones.models import Distrito, Provincia

from . import (
    ArgumentoInvalido,
    decimal_str,
    kwargs_ubicacion,
    resultado_item,
    validar_choice,
    validar_fecha,
    validar_texto,
)
from . import establecimientos as prov_establecimientos
from . import eventos as prov_eventos
from . import gastronomia as prov_gastronomia
from . import turismo as prov_turismo
from .establecimientos import MONEDA_CHOICES, _validar_monto
from .favoritos import ids_favoritos

MAX_DIAS = 14
LUGARES_POR_DIA = 2
MAX_LUGARES = 12
MAX_RESTAURANTES = 10
MAX_ALOJAMIENTOS = 10
MOMENTOS = ("mañana", "tarde")
NO_INCLUIDOS_SIEMPRE = [
    "traslado hacia/desde Huánuco",
    "movilidad local",
    "otras comidas y gastos personales",
]
MOTIVO_FAVORITO = "Guardado en tus favoritos"


def _destino(distrito, provincia):
    if distrito:
        obj = Distrito.objects.filter(slug=distrito).select_related("provincia").first()
        if obj is None:
            raise ArgumentoInvalido("distrito", "no encontrado; resuélvelo con buscar_ubicaciones")
        return obj.nombre_oficial.title()
    if provincia:
        obj = Provincia.objects.filter(slug=provincia).first()
        if obj is None:
            raise ArgumentoInvalido("provincia", "no encontrado; resuélvelo con buscar_ubicaciones")
        return obj.nombre_oficial.title()
    return "Huánuco"


def _candidatos(qs, favoritos, limit):
    """Favoritos compatibles (mismo filtro de ubicación, activos) primero;
    después el orden habitual del catálogo. Nunca se fuerza un favorito
    que no pasa el filtro."""
    favs = [o for o in qs.filter(pk__in=favoritos)] if favoritos else []
    favs.sort(key=lambda o: favoritos.index(o.pk))
    favs = favs[:limit]
    resto = qs.exclude(pk__in=[f.pk for f in favs]).order_by("-destacado", "nombre", "id")[: max(limit - len(favs), 0)]
    return favs + list(resto)


def _presupuesto(presupuesto, moneda):
    """→ (monto original, monto en PEN | None, conversión | None, aviso | None)."""
    monto = _validar_monto(presupuesto, "presupuesto")
    if monto is None:
        return None, None, None, None
    if moneda != "USD":
        return monto, monto, None, None
    tipo_cambio = TipoCambio.vigente()
    if tipo_cambio is None or not tipo_cambio.venta:
        return monto, None, None, (
            "No hay tipo de cambio vigente registrado, así que no puedo verificar el ajuste "
            "del presupuesto en dólares. Si me lo indicas en soles, lo comparo con los costos registrados."
        )
    convertido = (monto * tipo_cambio.venta).quantize(monto)
    return monto, convertido, {
        "moneda": "USD",
        "monto_original": decimal_str(monto),
        "tipo_cambio_venta": decimal_str(tipo_cambio.venta),
        "fecha_tipo_cambio": tipo_cambio.fecha.isoformat(),
    }, None


def _elegir_alojamiento(candidatos, favoritos, presupuesto_pen, noches):
    """Un solo alojamiento base. Con presupuesto: favorito que quepa por
    precio_desde*noches, si no el más barato que quepa; si ninguno cabe, el
    más barato (marcado como que no cabe). Sin presupuesto: favorito o el
    primero del catálogo. → (objeto|None, cabe: bool|None)."""
    if not candidatos:
        return None, None
    if presupuesto_pen is None or not noches:
        favs = [a for a in candidatos if a.pk in favoritos]
        return (favs or candidatos)[0], None
    con_precio = sorted(
        (a for a in candidatos if a.precio_desde is not None), key=lambda a: a.precio_desde
    )
    caben = [a for a in con_precio if a.precio_desde * noches <= presupuesto_pen]
    preferidos = [a for a in caben if a.pk in favoritos] or caben
    if preferidos:
        return preferidos[0], True
    return (con_precio or candidatos)[0], False


def _rango(obj, factor=1):
    """(mínimo, máximo) registrados; máximo = mínimo si no hay precio_hasta."""
    desde = obj.precio_desde
    if desde is None:
        return None, None
    hasta = obj.precio_hasta or desde
    return desde * factor, hasta * factor


def _actividad(momento, tipo, resumen, favorito=False):
    return {
        "momento": momento,
        "tipo": tipo,
        "item": resumen,
        "motivo": MOTIVO_FAVORITO if favorito else None,
    }


def _armar_dias(inicio, dias, lugares, restaurantes, eventos, fav_lugares, fav_establecimientos):
    plan, indice, colocados = [], 0, set()
    for n in range(dias):
        fecha = inicio + datetime.timedelta(days=n)
        actividades = []
        for momento in MOMENTOS:
            if indice < len(lugares):
                lugar = lugares[indice]
                actividades.append(_actividad(momento, "lugar", prov_turismo._resumen(lugar), lugar.pk in fav_lugares))
                indice += 1
        if n < len(restaurantes):
            rest = restaurantes[n]
            actividades.append(_actividad("comida", "restaurante", prov_establecimientos._resumen(rest), rest.pk in fav_establecimientos))
        for evento in eventos:
            ini, fin = evento.get("fecha_inicio"), evento.get("fecha_fin") or evento.get("fecha_inicio")
            if evento["id"] in colocados or not ini or not (ini <= fecha.isoformat() <= fin):
                continue
            actividades.append(_actividad("evento", "evento", evento))
            colocados.add(evento["id"])
        titulo = f"Día {n + 1}"
        if n == 0:
            titulo += " · Llegada"
        elif n == dias - 1 and dias > 1:
            titulo += " · Salida"
        plan.append({"numero": n + 1, "fecha": fecha.isoformat(), "titulo": titulo, "actividades": actividades})
    return plan


def _costos(alojamiento, noches, plan, presupuesto_pen):
    minimo, maximo, detalle, no_incluidos = 0, 0, [], []

    def sumar(concepto, obj, factor=1):
        nonlocal minimo, maximo
        desde, hasta = _rango(obj, factor)
        if desde is None:
            no_incluidos.append(f"{concepto} (sin precio registrado)")
            return
        minimo += desde
        maximo += hasta
        detalle.append({"concepto": concepto, "minimo": decimal_str(desde), "maximo": decimal_str(hasta)})

    if alojamiento is not None and noches:
        sumar(f"Alojamiento: {alojamiento.nombre} ({noches} noche(s))", alojamiento, noches)
    for dia in plan:
        for act in dia["actividades"]:
            item, tipo = act["item"], act["tipo"]
            if tipo == "lugar":
                if item["tipo_costo"] == "pagado" and item["precio_desde"]:
                    sumar(f"Entrada: {item['nombre']}", _Precio(item))
                elif item["tipo_costo"] in ("pagado", "consultar"):
                    no_incluidos.append(f"entrada a {item['nombre']} (por consultar)")
            elif tipo == "restaurante":
                if item["precio_desde"]:
                    sumar(f"Comida: {item['nombre']} (precio mínimo registrado)", _Precio(item))
                else:
                    no_incluidos.append(f"comida en {item['nombre']} (sin precio registrado)")
            elif tipo == "evento":
                if item["tipo_costo"] == "pagado" and item["precio_desde"]:
                    sumar(f"Evento: {item['nombre']}", _Precio(item))
                elif item["tipo_costo"] in ("pagado", "consultar"):
                    no_incluidos.append(f"evento {item['nombre']} (por consultar)")
    margen = None if presupuesto_pen is None else presupuesto_pen - minimo
    return {
        "conocido_minimo": decimal_str(minimo),
        "conocido_maximo": decimal_str(maximo),
        "margen": decimal_str(margen),
        "suficiente": None if margen is None else margen >= 0,
        "detalle": detalle,
        "no_incluidos": no_incluidos + NO_INCLUIDOS_SIEMPRE,
    }


class _Precio:
    """Adapta un resumen dict (precio_desde/hasta como str) a la interfaz de _rango."""

    def __init__(self, item):
        self.precio_desde = Decimal(item["precio_desde"]) if item.get("precio_desde") else None
        self.precio_hasta = Decimal(item["precio_hasta"]) if item.get("precio_hasta") else None


def planificar_itinerario(
    fecha_inicio, fecha_fin, presupuesto=None, moneda=None, distrito=None, provincia=None, *, usuario=None
):
    """
    Itinerario propuesto (no reserva) entre dos fechas con datos internos.
    `usuario` lo inyecta el backend: sus favoritos compatibles se priorizan
    sin dominar el plan. USD se convierte solo con TipoCambio.vigente().
    """
    inicio = validar_fecha(fecha_inicio, "fecha_inicio")
    fin = validar_fecha(fecha_fin, "fecha_fin")
    if inicio is None or fin is None:
        raise ArgumentoInvalido("fecha_inicio", "fecha_inicio y fecha_fin son obligatorias")
    if fin < inicio:
        raise ArgumentoInvalido("fecha_fin", "no puede ser anterior a fecha_inicio")
    if fin < timezone.localdate():
        raise ArgumentoInvalido("fecha_fin", "las fechas ya pasaron; usa la próxima ocurrencia futura")
    noches = (fin - inicio).days
    dias = noches + 1
    if dias > MAX_DIAS:
        raise ArgumentoInvalido("fecha_fin", f"el itinerario admite como máximo {MAX_DIAS} días")
    moneda = validar_choice(moneda, "moneda", MONEDA_CHOICES) or "PEN"
    distrito = validar_texto(distrito, "distrito")
    provincia = validar_texto(provincia, "provincia")
    destino = _destino(distrito, provincia)
    monto, presupuesto_pen, conversion, aviso = _presupuesto(presupuesto, moneda)

    fav_lugares, fav_establecimientos = ids_favoritos(usuario)
    filtros_lugar = kwargs_ubicacion(distrito, provincia)
    filtros_est = kwargs_ubicacion(distrito, provincia, prefijo="sucursales__")
    qs_lugares = prov_turismo._base().filter(**filtros_lugar)
    qs_rest = prov_establecimientos._base("restaurante")
    qs_aloj = prov_establecimientos._base("alojamiento")
    if filtros_est:
        qs_rest = qs_rest.filter(sucursales__activo=True, **filtros_est).distinct()
        qs_aloj = qs_aloj.filter(sucursales__activo=True, **filtros_est).distinct()

    lugares = _candidatos(qs_lugares, fav_lugares, min(MAX_LUGARES, dias * LUGARES_POR_DIA))
    restaurantes = _candidatos(qs_rest, fav_establecimientos, min(MAX_RESTAURANTES, dias))
    alojamientos = _candidatos(qs_aloj, fav_establecimientos, MAX_ALOJAMIENTOS)
    eventos = prov_eventos.buscar_eventos(
        fecha_desde=inicio, fecha_hasta=fin, distrito=distrito, provincia=provincia,
        incluir_aproximados=False, limit=10,
    )["items"]
    platos = prov_gastronomia.buscar_platos(es_plato_bandera=True, limit=3)["items"]

    alojamiento, cabe = _elegir_alojamiento(alojamientos, fav_establecimientos, presupuesto_pen, noches)
    seleccion, ajustes = list(lugares), []
    while True:
        plan = _armar_dias(inicio, dias, seleccion, restaurantes, eventos, fav_lugares, fav_establecimientos)
        costos = _costos(alojamiento, noches, plan, presupuesto_pen)
        if costos["suficiente"] is not False:
            break
        pagados = [l for l in seleccion if l.tipo_costo == "pagado" and l.precio_desde]
        if not pagados:
            break
        # Alternativa real más económica: se retira la última entrada pagada.
        seleccion.remove(pagados[-1])
        ajustes.append(pagados[-1].nombre)

    disponible = bool(seleccion or restaurantes or alojamiento or eventos)
    favoritos_usados = [a["item"]["nombre"] for d in plan for a in d["actividades"] if a["motivo"]]
    if alojamiento is not None and alojamiento.pk in fav_establecimientos:
        favoritos_usados.insert(0, alojamiento.nombre)
    item = {
        "disponible": disponible,
        "destino": destino,
        "fecha_inicio": inicio.isoformat(),
        "fecha_fin": fin.isoformat(),
        "dias": dias,
        "noches": noches,
        "presupuesto": None if monto is None else {
            "monto": decimal_str(monto), "moneda": moneda,
            "monto_pen": decimal_str(presupuesto_pen), "conversion": conversion,
        },
        "aviso_presupuesto": aviso,
        "alojamiento": None if alojamiento is None else {
            **prov_establecimientos._resumen(alojamiento),
            "cabe_en_presupuesto": cabe,
            "motivo": MOTIVO_FAVORITO if alojamiento.pk in fav_establecimientos else None,
        },
        "costos": costos,
        "ajustes_por_presupuesto": ajustes,
        "platos_tipicos": [{"nombre": p["nombre"], "url": p["url_donde_comer"]} for p in platos],
        "favoritos_usados": favoritos_usados,
        "sin_datos": [
            nombre for nombre, datos in (
                ("lugares turísticos", seleccion), ("restaurantes", restaurantes),
                ("alojamientos", alojamiento), ("eventos confirmados", eventos),
            ) if not datos
        ],
        "dias_plan": plan,
    }
    return resultado_item("planificar_itinerario", item)
