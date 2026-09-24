from django.urls import NoReverseMatch, reverse

from .navegacion import HEADER_NAV_ITEMS, resolver_seccion_activa


def _resolve(item):
    resolved = dict(item)
    # `url_name` se conserva (no se descarta) para que el template pueda
    # comparar el link exacto del dropdown contra la página actual y
    # marcarlo como "item actual" dentro del submenú (ver header.html).
    url_name = resolved.get("url_name")
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


def active_nav(request):
    """Sección del header activa para la página actual, resuelta de forma
    global (namespace/url_name vía `resolver_seccion_activa`) en vez de
    que cada vista la fije manualmente — única fuente de verdad."""
    resolver_match = getattr(request, "resolver_match", None)
    return {"active_nav": resolver_seccion_activa(resolver_match)}


def js_i18n(request):
    """Cadenas de UI que crea JavaScript (textos dinámicos), ya traducidas al
    idioma activo. Se emiten en base.html con json_script (`vi-i18n`) y las
    lee `ViI18n(clave, fallback)` de main.js. Sin llamadas externas."""
    from django.utils.dates import MONTHS_3, WEEKDAYS_ABBR
    from django.utils.translation import gettext as _

    return {
        "vi_i18n": {
            "enviando": _("Enviando…"),
            "todos": _("Todos"),
            "pausar_carrusel": _("Pausar carrusel"),
            "reanudar_carrusel": _("Reanudar carrusel"),
            "llamar": _("Llamar"),
            "correo": _("Correo"),
            "sitio_web": _("Sitio web"),
            "pcb_clima_huanuco": _("Clima en Huánuco"),
            "pcb_clima_tingo": _("Clima en Tingo María"),
            "pcb_eventos": _("Eventos próximos"),
            "pcb_platos": _("Platos típicos"),
            "pcb_lugares": _("Lugares destacados"),
            "pcb_tarifas": _("Tarifas de movilidad"),
            "pcb_cambio": _("Tipo de cambio"),
            "pcb_emergencias": _("Emergencias"),
            "pcb_indisponible": _("PillcoBot no está disponible temporalmente. Inténtalo nuevamente en unos momentos."),
            "pcb_error": _("No pude responder en este momento. Vuelve a intentarlo, por favor."),
            "pcb_largo": _("Tu mensaje es demasiado largo. Intenta resumirlo un poco."),
            "pcb_muchas": _("Has enviado varios mensajes en poco tiempo. Inténtalo nuevamente en un momento."),
            "pcb_fuentes": _("Fuentes oficiales"),
            "pcb_interesar": _("También te puede interesar"),
            "pcb_ver_mas": _("Ver más"),
            "pcb_respaldo": _("Dato de respaldo, puede no estar actualizado."),
            # Los marcadores %s los sustituye pillcobot.js (fmt).
            "pcb_clima_actual": _("Clima actual en %s"),
            "pcb_temporadas": _("Conoce las temporadas de %s"),
            "pcb_sensacion": _("Sensación térmica"),
            "pcb_humedad": _("Humedad"),
            "pcb_viento": _("Viento"),
            "pcb_lluvia": _("Prob. de lluvia"),
            "pcb_ver_evento": _("Ver evento"),
            "pcb_ver_comer": _("Ver dónde comer"),
            "pcb_ver_lugar": _("Ver lugar"),
            "pcb_ver_aloj": _("Ver alojamiento"),
            "pcb_especialidades": _("Especialidades: %s"),
            "pcb_excede": _("(puede superar tu presupuesto)"),
            "pcb_horario": _("Horario registrado: %s"),
            "pcb_desde": _("Desde S/ %s"),
            "pcb_aprox_usd": _("Aprox. US$ %s"),
            "pcb_consejos": _("¿Quieres algunos consejos para movilizarte?"),
            "pcb_recomendaciones": _("Recomendaciones"),
            "pcb_itinerario": _("Itinerario propuesto · %s"),
            "pcb_presupuesto": _("Presupuesto: %s"),
            "pcb_priorice": _("Prioricé tus favoritos: %s"),
            "pcb_aloj_base": _("Alojamiento base: %s"),
            "pcb_excede_estadia": _("(supera tu presupuesto para toda la estadía)"),
            "pcb_sin_actividades": _("Sin actividades registradas para este día."),
            "pcb_prueba": _("Prueba también: %s."),
            "pcb_bienvenida": _(
                "¡Hola! Soy PillcoBot, tu guía virtual de Viaje Informado.\n\n"
                "Estoy aquí para ayudarte a descubrir Huánuco: lugares turísticos, gastronomía, eventos, clima, "
                "transporte y consejos útiles para tu viaje.\n\n¿Qué te gustaría conocer hoy?"
            ),
            "em_gracias": _("¡Gracias! Tu reporte fue enviado."),
            "em_revisa": _("No se pudo enviar el reporte. Revisa los campos e intenta de nuevo."),
            "em_tarde": _("No se pudo enviar el reporte. Intenta de nuevo más tarde."),
            "fav_cerrar": _("Cerrar mensaje"),
            "fav_quitar": _("Quitar %(nombre)s de favoritos"),
            "fav_agregar": _("Agregar %(nombre)s a favoritos"),
            "fav_guardado": _("Guardado"),
            "fav_guardar": _("Guardar"),
            "fav_login": _("Inicia sesión para guardar en favoritos"),
            "his_msnm": _("m s. n. m."),
            "his_capital": _("Capital"),
            "his_superficie": _("Superficie"),
            "his_altitud": _("Altitud"),
            "his_distritos": _("Distritos"),
            "his_error": _("No se pudo cargar la información de esta provincia."),
            "cal_titulo": _("Elegir fechas"),
            "cal_anio": _("Año"),
            "cal_elegir_anio": _("Elegir año"),
            "cal_anio_actual": _("Año actual"),
            "cal_decada_ant": _("Década anterior"),
            "cal_decada_sig": _("Década siguiente"),
            "cal_fin": _("Elige la fecha de fin"),
            "cal_cerrar": _("Cerrar calendario"),
            "cal_limpiar": _("Limpiar"),
            "cal_listo": _("Listo"),
            "img_anterior": _("Imagen anterior"),
            "img_siguiente": _("Imagen siguiente"),
            "img_ir": _("Ir a la imagen {{index}}"),
            "slide_ir": _("Ir al slide %s"),
            "imagen_n": _("Imagen %s"),
            "rutas_menos": _("Ver menos rutas"),
            "rutas_todas": _("Ver todas las rutas"),
            "enlace_copiado": _("Enlace copiado"),
            "enlace_copiado_portapapeles": _("Enlace copiado al portapapeles"),
            "enlace_error_punto": _("No se pudo compartir el enlace."),
            "enlace_error": _("No se pudo compartir el enlace"),
            "mira_lugar": _("Mira este lugar en Viaje Informado"),
            "local_principal": _("Local principal"),
            "em_copiado": _("Número copiado"),
            "em_copiar": _("Copiar número"),
            "em_no_copiar": _("No se pudo copiar el número"),
            "fav_agregado": _("Agregado a tus favoritos."),
            "fav_eliminado": _("Eliminado de tus favoritos."),
            "fav_error": _("No pudimos actualizar tus favoritos. Inténtalo nuevamente."),
            "fav_popover": _("Inicia sesión para guardar este lugar en tus favoritos."),
            "fav_iniciar": _("Iniciar sesión"),
            "fav_crear": _("Crear cuenta"),
            "home_pausar": _("Pausar presentación"),
            "home_reanudar": _("Reanudar presentación"),
            "perfil_quitar_foto": _("¿Quitar tu foto de perfil?"),
            "sucursal_principal": _("Sucursal principal"),
            "sucursal": _("Sucursal"),
            "sin_direccion": _("Dirección no registrada"),
            # Placeholder %(anio)s: lo sustituye el JS al repintar la ventana de días.
            "calendario": _("Calendario - %(anio)s"),
            "dias_abrev": [str(WEEKDAYS_ABBR[i]).upper() for i in range(7)],
            "meses_abrev": [""] + [str(MONTHS_3[i]).upper() for i in range(1, 13)],
        }
    }
