/**
 * desplazable-como-llegar.js — Viaje Informado
 *
 * Componente reutilizable "Cómo llegar" compatible con cualquier
 * pantalla del proyecto: Detalle Lugar Turístico, Detalle
 * Establecimiento y futuras páginas.
 *
 * Modo simple   → una sola ubicación, datos en el propio wrapper.
 * Modo sucursales → múltiples tabs [data-sucursal] con datos propios.
 *
 * Wrapper esperado: <elemento data-como-llegar ...>
 *
 * Atributos del wrapper (modo simple):
 *   data-route-url   URL base de ruta de Google Maps
 *   data-embed-url   URL del mapa embebido (iframe)
 *   data-open-url    URL para abrir Google Maps
 *   data-nombre      Nombre del lugar
 *   data-direccion   Dirección del lugar
 *   data-referencia  Referencia (opcional)
 *   data-horario     Horario (opcional)
 *   data-es-principal  "true" | "false"
 *
 * Atributos del wrapper (modo sucursales):
 *   Los datos vienen de cada [data-sucursal] con los mismos
 *   atributos que el wrapper en modo simple.
 *
 * Elementos internos esperados (data-atributos):
 *   [data-cta-default]   Fila con botones "Cómo llegar" y "Abrir mapa"
 *   [data-show-dir]      Botón que abre el panel desplegable
 *   [data-hide-dir]      Botón que cierra el panel desplegable
 *   [data-directions]    Panel desplegable (ocultable con hidden)
 *   [data-destino]       Input "Hasta" (se actualiza al cambiar sucursal)
 *   [data-enlace-ruta]   Enlace "Iniciar ruta en Google Maps"
 *   [data-open-link]     Enlace "Abrir mapa"
 *   [data-mapa]          Iframe del mapa (se actualiza al cambiar sucursal)
 *   .du-mode[data-modo]  Botones de modo de transporte (walking / driving)
 *
 * Elementos de visualización de sucursal (actualizados al cambiar tab):
 *   [data-branch-nombre]     Nombre de la sucursal
 *   [data-branch-direccion]  Dirección
 *   [data-branch-referencia] Referencia
 *   [data-branch-horario]    Horario
 *   [data-branch-pill]       Etiqueta "Sucursal Principal" (show/hide)
 *   [data-branch-fila="x"]   Filas completas (se ocultan si el valor está vacío)
 */
(function () {
    'use strict';

    /* ── Utilidades de texto ── */

    function texto(valor) {
        return valor ? String(valor).trim() : '';
    }

    function normalizarCoord(valor) {
        return texto(valor).replace(',', '.');
    }

    /* Construye URLs de Google Maps a partir de lat/lng o dirección */
    function construirUrls(query) {
        var q = texto(query);
        if (!q) return { open: '', route: '', embed: '' };
        var enc = encodeURIComponent(q);
        return {
            open:  'https://www.google.com/maps/search/?api=1&query=' + enc,
            route: 'https://www.google.com/maps/dir/?api=1&destination=' + enc,
            embed: 'https://www.google.com/maps?q=' + enc + '&z=17&hl=es&output=embed'
        };
    }

    /* Lee todos los datos relevantes de un elemento (wrapper o tab de sucursal) */
    function extraerDatos(origen) {
        var d = origen.dataset || {};
        var lat = normalizarCoord(d.lat);
        var lng = normalizarCoord(d.lng);
        var direccion = texto(d.direccion);
        var query = (lat && lng) ? (lat + ',' + lng) : direccion;
        var fb = construirUrls(query);

        return {
            nombre:      texto(d.nombre) || 'Local principal',
            label:       texto(d.label) || (d.esPrincipal === 'true' ? 'Sucursal principal' : 'Sucursal'),
            direccion:   direccion,
            referencia:  texto(d.referencia),
            horario:     texto(d.horario),
            esPrincipal: d.esPrincipal === 'true',
            openUrl:     texto(d.openUrl)   || fb.open,
            routeUrl:    texto(d.routeUrl)  || fb.route,
            embedUrl:    texto(d.embedUrl)  || fb.embed
        };
    }

    /* ── Selectores internos ── */

    function qs(root, sel)  { return root.querySelector(sel); }

    function qsa(root, sel) {
        return Array.prototype.slice.call(root.querySelectorAll(sel));
    }

    /* ── Actualizar enlace de ruta según modo activo ── */

    function refrescarEnlaceRuta(root, routeUrl) {
        var enlace = qs(root, '[data-enlace-ruta]');
        if (!enlace || !routeUrl) return;

        var modoActivo = qs(root, '.du-mode.is-active');
        var modo = modoActivo ? (modoActivo.dataset.modo || 'walking') : 'walking';
        var urlLimpia = routeUrl.replace(/&travelmode=[^&]*/g, '');
        enlace.href = urlLimpia + '&travelmode=' + modo;
    }

    /* ── Actualizar iframe del mapa ── */

    function actualizarMapa(root, datos) {
        var iframe = qs(root, '[data-mapa]');
        if (iframe && datos.embedUrl && iframe.src !== datos.embedUrl) {
            iframe.src = datos.embedUrl;
        }
    }

    /* ── Actualizar enlaces de apertura del mapa ── */

    function actualizarEnlacesMapa(root, datos) {
        qsa(root, '[data-open-link]').forEach(function (el) {
            el.href = datos.openUrl || '#';
        });
    }

    /* ── Mostrar/ocultar fila de datos si el valor está vacío ── */

    function actualizarFila(root, nombre, valor) {
        qsa(root, '[data-branch-fila="' + nombre + '"]').forEach(function (fila) {
            fila.classList.toggle('is-empty', !valor);
        });
    }

    /* ── Actualizar contenido de la sucursal seleccionada ── */

    function actualizarSucursal(root, datos) {
        /* Textos */
        qsa(root, '[data-branch-nombre]').forEach(function (el) {
            el.textContent = datos.nombre;
        });
        qsa(root, '[data-branch-direccion]').forEach(function (el) {
            el.textContent = datos.direccion || 'Dirección no registrada';
        });
        qsa(root, '[data-branch-referencia]').forEach(function (el) {
            el.textContent = datos.referencia;
        });
        qsa(root, '[data-branch-horario]').forEach(function (el) {
            el.textContent = datos.horario;
        });

        /* Etiqueta "Sucursal Principal" */
        var pill = qs(root, '[data-branch-pill]');
        if (pill) {
            if (datos.esPrincipal) pill.removeAttribute('hidden');
            else pill.setAttribute('hidden', '');
        }

        /* Filas que se ocultan cuando su valor está vacío */
        actualizarFila(root, 'direccion',  datos.direccion);
        actualizarFila(root, 'referencia', datos.referencia);
        actualizarFila(root, 'horario',    datos.horario);

        /* Input "Hasta" del desplegable */
        var inputDestino = qs(root, '[data-destino]');
        if (inputDestino) inputDestino.value = datos.direccion || '';

        /* Mapa y enlace de apertura */
        actualizarMapa(root, datos);
        actualizarEnlacesMapa(root, datos);
    }

    /* ── Panel desplegable: mostrar ── */

    function mostrarDesplegable(root) {
        var cta   = qs(root, '[data-cta-default]');
        var panel = qs(root, '[data-directions]');
        if (cta)   cta.setAttribute('hidden', '');
        if (panel) panel.removeAttribute('hidden');
    }

    /* ── Panel desplegable: ocultar ── */

    function ocultarDesplegable(root) {
        var cta   = qs(root, '[data-cta-default]');
        var panel = qs(root, '[data-directions]');
        if (panel) panel.setAttribute('hidden', '');
        if (cta)   cta.removeAttribute('hidden');
    }

    /* ── Inicializar el panel desplegable de una instancia ── */

    function iniciarPanelDesplegable(root, obtenerRouteUrl) {
        var btnMostrar = qs(root, '[data-show-dir]');
        var btnOcultar = qs(root, '[data-hide-dir]');
        var modos      = qsa(root, '.du-mode');

        if (btnMostrar) {
            btnMostrar.addEventListener('click', function () {
                mostrarDesplegable(root);
                refrescarEnlaceRuta(root, obtenerRouteUrl());
            });
        }

        if (btnOcultar) {
            btnOcultar.addEventListener('click', function () {
                ocultarDesplegable(root);
            });
        }

        modos.forEach(function (btn) {
            btn.addEventListener('click', function () {
                modos.forEach(function (b) { b.classList.remove('is-active'); });
                btn.classList.add('is-active');
                refrescarEnlaceRuta(root, obtenerRouteUrl());
            });
        });
    }

    /* ── Activar tab de sucursal ── */

    function activarTab(tabs, seleccionado) {
        tabs.forEach(function (tab) {
            var activo = tab === seleccionado;
            tab.classList.toggle('is-active', activo);
            tab.setAttribute('aria-pressed', activo ? 'true' : 'false');
        });
    }

    /* ── Inicializar una instancia completa ── */

    function iniciarInstancia(root) {
        var tabs = qsa(root, '[data-sucursal]');

        /* Determinar la fuente de datos inicial:
           - con sucursales: el tab marcado como activo (o el primero)
           - sin sucursales: el propio wrapper */
        var tabInicial = null;
        if (tabs.length > 0) {
            tabInicial = tabs.filter(function (t) {
                return t.classList.contains('is-active');
            })[0] || tabs[0];
        }

        var datosIniciales = extraerDatos(tabInicial || root);
        var routeUrlActual = datosIniciales.routeUrl;

        /* Pintar estado inicial */
        actualizarSucursal(root, datosIniciales);
        refrescarEnlaceRuta(root, routeUrlActual);

        /* Clicks en los tabs de sucursal */
        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                activarTab(tabs, tab);
                var datos = extraerDatos(tab);
                routeUrlActual = datos.routeUrl;
                actualizarSucursal(root, datos);
                ocultarDesplegable(root);
                refrescarEnlaceRuta(root, routeUrlActual);
            });
        });

        /* Panel desplegable */
        iniciarPanelDesplegable(root, function () { return routeUrlActual; });
    }

    /* ── Punto de entrada: soporta múltiples instancias en la misma página ── */

    function iniciar() {
        document.querySelectorAll('[data-como-llegar]').forEach(iniciarInstancia);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
