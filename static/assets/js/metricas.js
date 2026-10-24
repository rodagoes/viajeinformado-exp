/**
 * metricas.js — Viaje Informado
 *
 * Registra interacciones EXPLÍCITAS del usuario (un clic en un control concreto) enviándolas a
 * POST /metricas/evento/. No mide impresiones, scroll, hover ni cargas de listados.
 *
 * Contrato en el HTML (todo opcional salvo `evento`):
 *   data-metrica-evento        tipo: lugar_detalle_click | restaurante_detalle_click | alojamiento_detalle_click |
 *                              evento_detalle_click | gastronomia_donde_comer_click | ubicacion_click
 *   data-metrica-via           de dónde viene el clic (listado, favoritos, como_llegar, …)
 *   data-metrica-entidad-id    id de la entidad  (o data-metrica-entidad-slug)
 *   data-metrica-entidad-tipo  solo ubicacion_click: lugar | establecimiento | servicio
 *   data-metrica-modo-desde    solo ubicacion_click con via=iniciar_ruta: valor "travelmode". El modo (a_pie | auto) se
 *                              lee en el instante del clic del `travelmode` del href del propio enlace, que es la ruta
 *                              que realmente se abre (el componente de mapa lo fija según el modo activo). No hay un
 *                              segundo estado que pueda quedar desincronizado.
 * La entidad (y su tipo) puede estar en el propio control o en un ancestro: se busca con closest().
 * El servidor valida todo; aquí no se envía ningún dato personal.
 *
 * Además: enlaces del chatbot (#pcbot-root) a fichas de lugares/restaurantes/alojamientos (via=chatbot) y la
 * API window.ViMetricas.registrar() para código que ya conoce el momento exacto de la acción (modal de eventos).
 *
 * Seguro por diseño: nunca bloquea ni cambia el comportamiento del enlace/botón y nunca lanza errores visibles.
 * Sin JavaScript no se registran estas interacciones (la página vista sí se mide en el servidor).
 */
(function () {
    'use strict';

    var script = document.currentScript;
    var ENDPOINT = script && script.dataset.endpoint;
    if (!ENDPOINT) return;

    var VENTANA_DEDUP_MS = 1500; // doble clic involuntario = 1 interacción; un clic posterior vuelve a contar
    var recientes = {};

    function obtenerCookie(nombre) {
        var partes = document.cookie ? document.cookie.split('; ') : [];
        for (var i = 0; i < partes.length; i++) {
            if (partes[i].indexOf(nombre + '=') === 0) return decodeURIComponent(partes[i].slice(nombre.length + 1));
        }
        return '';
    }

    function tokenCsrf() {
        return (script && script.dataset.csrf) || obtenerCookie('csrftoken');
    }

    function nuevoUuid() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
        var bytes = new Uint8Array(16);
        (window.crypto || window.msCrypto).getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        var hex = Array.prototype.map.call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
        return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-' + hex.slice(16, 20) + '-' + hex.slice(20);
    }

    function duplicado(clave) {
        var ahora = Date.now();
        if (recientes[clave] && ahora - recientes[clave] < VENTANA_DEDUP_MS) return true;
        recientes[clave] = ahora;
        return false;
    }

    function enviar(datos) {
        var cuerpo = new URLSearchParams();
        Object.keys(datos).forEach(function (clave) {
            if (datos[clave] !== undefined && datos[clave] !== null && datos[clave] !== '') cuerpo.append(clave, datos[clave]);
        });
        cuerpo.append('csrfmiddlewaretoken', tokenCsrf());
        try {
            // sendBeacon no admite cabeceras: el token CSRF viaja en el cuerpo, que Django también valida.
            if (navigator.sendBeacon) {
                var blob = new Blob([cuerpo.toString()], { type: 'application/x-www-form-urlencoded;charset=UTF-8' });
                if (navigator.sendBeacon(ENDPOINT, blob)) return;
            }
            fetch(ENDPOINT, {
                method: 'POST',
                keepalive: true,
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'X-CSRFToken': tokenCsrf() },
                body: cuerpo.toString(),
            }).catch(function () { /* las métricas nunca molestan al usuario */ });
        } catch (error) { /* idem */ }
    }

    function registrar(evento, opciones) {
        try {
            opciones = opciones || {};
            var clave = [evento, opciones.entidadTipo || '', opciones.entidadId || opciones.entidadSlug || '', opciones.via || '', opciones.modo || ''].join('|');
            if (!evento || duplicado(clave)) return;
            enviar({
                tipo: evento,
                via: opciones.via,
                modo: opciones.modo,
                entidad_tipo: opciones.entidadTipo,
                entidad_id: opciones.entidadId,
                entidad_slug: opciones.entidadSlug,
                click_id: nuevoUuid(),
            });
        } catch (error) { /* idem */ }
    }

    // travelmode de Google Maps -> modo de la métrica. Otros valores (bicycling, transit…) no se mapean: no se envía modo.
    var MODOS_TRAVELMODE = { walking: 'a_pie', driving: 'auto' };

    function modoDeRuta(control) {
        try {
            var modo = new URL(control.href, window.location.href).searchParams.get('travelmode');
            return Object.prototype.hasOwnProperty.call(MODOS_TRAVELMODE, modo) ? MODOS_TRAVELMODE[modo] : undefined;
        } catch (error) { return undefined; }
    }

    function datosDeControl(control) {
        var contenedor = control.closest('[data-metrica-entidad-id], [data-metrica-entidad-slug]');
        var tipoEntidad = control.closest('[data-metrica-entidad-tipo]');
        return {
            via: control.dataset.metricaVia,
            modo: control.dataset.metricaModoDesde === 'travelmode' ? modoDeRuta(control) : undefined,
            entidadId: control.dataset.metricaEntidadId || (contenedor && contenedor.dataset.metricaEntidadId),
            entidadSlug: control.dataset.metricaEntidadSlug || (contenedor && contenedor.dataset.metricaEntidadSlug),
            entidadTipo: control.dataset.metricaEntidadTipo || (tipoEntidad && tipoEntidad.dataset.metricaEntidadTipo),
        };
    }

    // Enlaces del chatbot a fichas de contenido: /lugares-turisticos/<slug>/, /restaurantes/<slug>/, /alojamientos/<slug>/
    var FICHAS = [
        { patron: /^\/lugares-turisticos\/([-\w]+)\/?$/, evento: 'lugar_detalle_click' },
        { patron: /^\/restaurantes\/([-\w]+)\/?$/, evento: 'restaurante_detalle_click' },
        { patron: /^\/alojamientos\/([-\w]+)\/?$/, evento: 'alojamiento_detalle_click' },
    ];

    function registrarEnlaceChatbot(enlace) {
        var ruta;
        try { ruta = new URL(enlace.href, window.location.href); } catch (error) { return; }
        if (ruta.origin !== window.location.origin) return;
        for (var i = 0; i < FICHAS.length; i++) {
            var coincide = FICHAS[i].patron.exec(ruta.pathname);
            if (coincide) {
                registrar(FICHAS[i].evento, { via: 'chatbot', entidadSlug: coincide[1] });
                return;
            }
        }
    }

    function alHacerClic(event) {
        try {
            if (event.type === 'auxclick' && event.button !== 1) return; // solo clic central además del clic normal
            var objetivo = event.target;
            if (!objetivo || !objetivo.closest) return;
            var control = objetivo.closest('[data-metrica-evento]');
            if (control) {
                var datos = datosDeControl(control);
                datos.via = datos.via || undefined;
                registrar(control.dataset.metricaEvento, datos);
            }
            var enlaceChat = objetivo.closest('#pcbot-root a[href]');
            if (enlaceChat) registrarEnlaceChatbot(enlaceChat);
        } catch (error) { /* nunca romper la interacción */ }
    }

    document.addEventListener('click', alHacerClic);
    document.addEventListener('auxclick', alHacerClic);

    window.ViMetricas = { registrar: registrar };

    // ------------------------------------------------------------------------------------------------------------
    // Tiempo visible (duración de la sesión). Solo si la plantilla declara data-duracion (seguimiento activo y no staff).
    //
    // Se acumula únicamente el tiempo con la pestaña VISIBLE y con alguna interacción reciente, y se reporta en
    // incrementos pequeños (segundos enteros, nunca marcas de tiempo): cada 30 s mientras la pestaña está visible, al
    // ocultarla y en pagehide. El servidor es quien acota el valor (máximo por envío, reloj real y tope por sesión).
    //  - Una pestaña olvidada: tras INACTIVIDAD_MS sin interacción deja de sumar hasta la siguiente acción.
    //  - Oculta/minimizada: no suma; al volver se reinicia el punto de control.
    //  - pagehide no es fiable en todos los móviles; por eso existe el heartbeat. No se usa beforeunload.
    //  - No hay doble envío: cada envío descuenta lo enviado del acumulado pendiente.
    //  - Si el servidor responde 410 (sin sesión vigente) se detienen los heartbeats de esa página.
    // ------------------------------------------------------------------------------------------------------------
    var DURACION_URL = script.dataset.duracion;
    if (DURACION_URL) iniciarTiempoVisible(DURACION_URL);

    function iniciarTiempoVisible(url) {
        var HEARTBEAT_MS = 30000;
        var INACTIVIDAD_MS = 5 * 60 * 1000;
        var MAX_ENVIO_S = 60; // el servidor rechaza más de esto por envío
        var visibleDesde = document.visibilityState === 'visible' ? Date.now() : null;
        var ultimaAccion = Date.now();
        var pendienteMs = 0;
        var temporizador = null;
        var activo = true;

        function acumular(ahora) {
            if (visibleDesde === null) return;
            var hasta = Math.min(ahora, ultimaAccion + INACTIVIDAD_MS); // sin interacción reciente no se suma
            if (hasta > visibleDesde) pendienteMs += hasta - visibleDesde;
            visibleDesde = ahora;
        }

        function detener() {
            activo = false;
            if (temporizador !== null) { clearInterval(temporizador); temporizador = null; }
        }

        function enviarTiempo(conBeacon) {
            if (!activo) return;
            acumular(Date.now());
            var segundos = Math.floor(pendienteMs / 1000);
            if (segundos < 1) return;
            segundos = Math.min(segundos, MAX_ENVIO_S);
            pendienteMs = Math.min(pendienteMs - segundos * 1000, MAX_ENVIO_S * 1000);
            var cuerpo = new URLSearchParams({ segundos: String(segundos), csrfmiddlewaretoken: tokenCsrf() }).toString();
            try {
                if (conBeacon && navigator.sendBeacon) {
                    var blob = new Blob([cuerpo], { type: 'application/x-www-form-urlencoded;charset=UTF-8' });
                    if (navigator.sendBeacon(url, blob)) return;
                }
                fetch(url, {
                    method: 'POST',
                    keepalive: true,
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'X-CSRFToken': tokenCsrf() },
                    body: cuerpo,
                }).then(function (respuesta) { if (respuesta && respuesta.status === 410) detener(); })
                  .catch(function () { /* las métricas nunca molestan al usuario */ });
            } catch (error) { /* idem */ }
        }

        function alInteractuar() {
            var ahora = Date.now();
            acumular(ahora);   // cierra el tramo anterior con el límite de inactividad vigente
            ultimaAccion = ahora;
        }

        function alCambiarVisibilidad() {
            var ahora = Date.now();
            if (document.visibilityState === 'hidden') {
                enviarTiempo(true);          // lo pendiente sale antes de que el navegador congele la pestaña
                visibleDesde = null;
            } else {
                visibleDesde = ahora;        // el tiempo oculto nunca se suma
                ultimaAccion = ahora;
            }
        }

        ['pointerdown', 'keydown', 'scroll', 'touchstart'].forEach(function (tipo) {
            document.addEventListener(tipo, alInteractuar, { passive: true, capture: true });
        });
        document.addEventListener('visibilitychange', alCambiarVisibilidad);
        window.addEventListener('pagehide', function () { enviarTiempo(true); });
        window.addEventListener('pageshow', function (evento) {
            if (evento && evento.persisted) { visibleDesde = Date.now(); ultimaAccion = visibleDesde; }  // vuelta desde bfcache
        });
        temporizador = setInterval(function () {
            if (document.visibilityState === 'visible') enviarTiempo(false);
        }, HEARTBEAT_MS);
    }
})();
