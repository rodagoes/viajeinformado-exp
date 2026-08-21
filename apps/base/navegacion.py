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
