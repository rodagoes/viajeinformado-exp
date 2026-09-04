"""
Estructura centralizada del menú del header (desktop + móvil).

Cada item soporta:
    key             identificador único, usado para resaltar el activo
    label           texto visible
    icon            clase de Bootstrap Icons (sin el prefijo "bi-")
    url_name        nombre de ruta Django a resolver con reverse()
    href            enlace directo (usar "#" si la ruta todavía no existe)
    dropdown_title  título del panel desplegable (solo si tiene children)
    description     texto corto opcional para el desplegable
    children        lista de sub-items con la misma forma

Para agregar "Tradiciones", "Cultura" o "Danzas" en el futuro basta con
añadir nuevos diccionarios a la lista "children" del item EXPLORAR, sin
tocar ningún template.
"""

HEADER_NAV_ITEMS = [
    {
        "key": "inicio",
        "label": "INICIO",
        "icon": "house",
        "url_name": "base:home",
    },
    {
        "key": "explorar",
        "label": "EXPLORAR",
        "icon": "map",
        "dropdown_title": "Explorar",
        "children": [
            {
                "key": "lugares-turisticos",
                "label": "Lugares turísticos",
                "icon": "camera",
                "url_name": "turismo:listado_lugares",
                "description": "Atractivos naturales, arqueológicos y culturales.",
            },
            {
                "key": "historia",
                "label": "Historia",
                "icon": "book",
                "url_name": "base:historia",
                "description": "El pasado histórico de Huánuco.",
            },
        ],
    },
    {
        "key": "gastronomia",
        "label": "GASTRONOMÍA Y ALOJAMIENTO",
        "icon": "shop",
        "dropdown_title": "Gastronomía y alojamiento",
        "children": [
            {
                "key": "restaurantes",
                "label": "Restaurantes",
                "icon": "cup-hot",
                "url_name": "establecimientos:listado_restaurantes",
                "description": "Restaurantes recomendados en la ciudad.",
            },
            {
                "key": "platos-tipicos",
                "label": "Platos típicos",
                "icon": "egg-fried",
                "url_name": "gastronomia:platos_tipicos",
                "description": "Sabores tradicionales de Huánuco.",
            },
            {
                "key": "alojamientos",
                "label": "Alojamientos",
                "icon": "house-door",
                "url_name": "establecimientos:listado_alojamientos",
                "description": "Hoteles y hospedajes para tu estadía.",
            },
        ],
    },
    {
        "key": "planifica",
        "label": "PLANIFICA",
        "icon": "journal-text",
        "dropdown_title": "Planifica tu viaje",
        "children": [
            {
                "key": "transporte-tarifas",
                "label": "Transporte y tarifas",
                "icon": "car-front",
                "url_name": "movilidad:tarifas_taxi",
                "description": "Medios de transporte locales y tarifas referenciales.",
            },
            {
                "key": "como-llegar",
                "label": "Cómo llegar",
                "icon": "signpost-split",
                "url_name": "movilidad:como_llegar",
                "description": "Rutas, tiempos y medios de transporte para su llegada.",
            },
            {
                "key": "clima-temporadas",
                "label": "Clima y temporadas",
                "icon": "cloud-sun",
                "url_name": "clima:clima_temporadas",
                "description": "Clima actual, temporadas y recomendaciones.",
            },
            {
                "key": "tipo-cambio",
                "label": "Tipo de cambio",
                "icon": "currency-exchange",
                "url_name": "monedas:tipo_cambio",
                "description": "Convierte soles y dólares con la tasa referencial vigente.",
            },
            {
                "key": "servicios-utiles",
                "label": "Servicios útiles",
                "icon": "info-circle",
                "url_name": "servicios_turista:servicios_utiles",
                "description": "Salud, seguridad, bancos, transporte e información turística.",
            },
            {
                "key": "emergencias",
                "label": "Emergencias",
                "icon": "telephone",
                "url_name": "emergencias:emergencias",
                "description": "Contactos nacionales y locales para tu seguridad.",
            },
        ],
    },
    {
        "key": "eventos",
        "label": "EVENTOS",
        "icon": "calendar-event",
        "url_name": "eventos:listado_eventos",
    },
]


def _namespace_de(url_name):
    return url_name.split(":", 1)[0] if url_name and ":" in url_name else None


def _construir_mapas_seccion():
    """Deriva, a partir de HEADER_NAV_ITEMS (única fuente de verdad), los
    dos mapas que resuelven qué item del header debe verse activo para
    cualquier página del sitio:

    - por url_name exacto: cada entrada del menú apunta a su sección (la
      del padre, si es hijo de un dropdown) — cubre las páginas listado.
    - por namespace de app: cualquier OTRA página de esa misma app (un
      detalle, un formulario...) hereda la sección, siempre que TODAS las
      entradas del menú de ese namespace apunten a la misma sección. Un
      namespace que aparece en más de una sección (como "base": home ->
      inicio, historia -> explorar) queda fuera de este segundo mapa a
      propósito: no hay una única sección "por defecto" válida para el
      resto de sus páginas (privacidad, términos, contacto...), así que
      esas quedan sin sección activa en vez de heredar una equivocada.
    """
    por_url_name = {}
    secciones_por_namespace = {}

    def registrar(url_name, seccion):
        if not url_name:
            return
        por_url_name[url_name] = seccion
        namespace = _namespace_de(url_name)
        if namespace:
            secciones_por_namespace.setdefault(namespace, set()).add(seccion)

    for item in HEADER_NAV_ITEMS:
        registrar(item.get("url_name"), item["key"])
        for child in item.get("children", []):
            registrar(child.get("url_name"), item["key"])

    por_namespace = {
        namespace: next(iter(secciones))
        for namespace, secciones in secciones_por_namespace.items()
        if len(secciones) == 1
    }
    return por_url_name, por_namespace


SECCION_POR_URL_NAME, SECCION_POR_NAMESPACE = _construir_mapas_seccion()


def resolver_seccion_activa(resolver_match):
    """Determina la sección del header (`item.key`) activa para la URL
    actual, a partir de un `request.resolver_match`. Namespace/app_name es
    la fuente principal (cubre páginas presentes y futuras de cada app sin
    tocar esta función); url_name exacto es solo la excepción puntual para
    namespaces ambiguos. Nunca compara `request.path`."""
    if resolver_match is None:
        return None
    namespace = resolver_match.namespace or ""
    url_name = resolver_match.url_name or ""
    url_name_calificado = f"{namespace}:{url_name}" if namespace else url_name
    if url_name_calificado in SECCION_POR_URL_NAME:
        return SECCION_POR_URL_NAME[url_name_calificado]
    return SECCION_POR_NAMESPACE.get(namespace)
