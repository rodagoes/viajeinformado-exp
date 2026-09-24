/* Skeleton global — Viaje Informado.
 *
 * Marca un contenedor con `.vi-skel` SOLO si el recurso de su interior está
 * realmente pendiente, y lo retira cuando el navegador lo confirma
 * (load / error). No hay temporizadores: si la imagen ya está en caché o
 * el recurso no existe en la página, no se hace nada.
 *
 *   ViSkeleton.watch(img|iframe, contenedor?)  // contenedor = padre por defecto
 *   ViSkeleton.watchAll(raiz?)                 // envolturas conocidas + [data-skel]
 *   ViSkeleton.start(caja) / ViSkeleton.stop(caja)  // p. ej. alrededor de un fetch
 */
(function () {
    'use strict';

    var CLASE = 'vi-skel';

    // Envolturas de imagen ya existentes en las cards/galerías del sitio.
    var ENVOLTURAS = [
        '.ev-card__media', '.ev-modal__galeria',
        '.lugar-imagen-contenedor', '.est-imagen-contenedor', '.pt-card__image',
        '.favorito-imagen-contenedor', '.dl-feature-media',
        '.detalle-swiper-slide', '.detalle-mobile-slide', '.detalle-gallery-slide',
        '.detalle-imagen-estatica', '[data-skel]'
    ].join(',');

    function start(caja) {
        if (!caja) return;
        caja.classList.add(CLASE);
        caja.setAttribute('aria-busy', 'true');
    }

    function stop(caja) {
        if (!caja) return;
        caja.classList.remove(CLASE);
        caja.removeAttribute('aria-busy');
    }

    function watch(recurso, caja) {
        if (!recurso || !recurso.tagName) return;
        caja = caja || recurso.parentElement;
        if (!caja) return;

        var tag = recurso.tagName;
        if (tag === 'IMG') {
            // complete = ya cargó (caché) o ya falló: no hay nada que esperar.
            if (recurso.complete) return;
        } else if (tag === 'IFRAME') {
            // Un iframe no lazy ya cargado no vuelve a emitir `load`.
            if (document.readyState === 'complete' && recurso.loading !== 'lazy') return;
        } else {
            return;
        }

        start(caja);
        var terminar = function () { stop(caja); };
        recurso.addEventListener('load', terminar, { once: true });
        recurso.addEventListener('error', terminar, { once: true });
    }

    function watchAll(raiz) {
        raiz = raiz || document;
        raiz.querySelectorAll(ENVOLTURAS).forEach(function (caja) {
            caja.querySelectorAll('img').forEach(function (img) { watch(img, caja); });
        });
        // Mapas y otros iframes diferidos: el contenedor directo hace de caja.
        raiz.querySelectorAll('iframe[loading="lazy"], iframe[data-skel-iframe]').forEach(function (frame) {
            watch(frame);
        });
    }

    // Volver con "atrás" (bfcache) no debe dejar cajas atascadas.
    window.addEventListener('pageshow', function (evento) {
        if (!evento.persisted) return;
        document.querySelectorAll('.' + CLASE).forEach(stop);
    });

    document.addEventListener('DOMContentLoaded', function () { watchAll(document); });

    window.ViSkeleton = { watch: watch, watchAll: watchAll, start: start, stop: stop };
})();
