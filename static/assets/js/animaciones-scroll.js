/**
 * animaciones-scroll.js — Viaje Informado
 *
 * Activa las animaciones de Animate.css SOLO cuando el usuario
 * hace scroll hacia ABAJO. Al scrollear hacia arriba los elementos
 * simplemente aparecen visibles sin ningún efecto de entrada.
 *
 * Comportamiento:
 * - Scroll ↓ + elemento entra en pantalla → animación fadeInUp
 * - Scroll ↑ + elemento entra en pantalla → aparece directo, sin animación
 * - Cada elemento se anima una sola vez y luego se deja de observar
 *   (unobserve), para evitar retriggers/temblor en scroll con inercia.
 *
 * Compatible con desktop y móvil. Funciona con y sin recarga de página.
 *
 * Requiere: Animate.css + animaciones-entrada.css
 */
(function () {
    'use strict';

    /* Porcentaje del elemento visible para activarse */
    var UMBRAL_VISIBILIDAD = 0.15;

    /* Activar un poco antes del borde inferior de la pantalla */
    var MARGEN_INFERIOR = '-30px';

    /* ── Detector de dirección de scroll ──
       Se actualiza en cada evento scroll antes de que el
       IntersectionObserver procese los cambios de visibilidad. */
    var scrollPrevio = window.pageYOffset;
    var scrollHaciaAbajo = true; /* true en carga inicial → los elementos visibles se animan */

    window.addEventListener('scroll', function () {
        var scrollActual = window.pageYOffset;
        if (scrollActual !== scrollPrevio) {
            scrollHaciaAbajo = scrollActual > scrollPrevio;
            scrollPrevio = scrollActual;
        }
    }, { passive: true });

    /* ── Animación completa (scroll hacia abajo) ── */
    function activarAnimacion(elemento) {
        var claseAnimacion = elemento.dataset.animar || 'animate__fadeInUp';
        elemento.classList.add('visible', 'animate__animated', claseAnimacion);
    }

    /* ── Solo visibilidad, sin animación (scroll hacia arriba) ── */
    function mostrarSinAnimacion(elemento) {
        var claseAnimacion = elemento.dataset.animar || 'animate__fadeInUp';
        /* Asegurarse de que no quede ninguna clase de animación activa */
        elemento.classList.remove('animate__animated', claseAnimacion);
        elemento.classList.add('visible');
    }

    /**
     * Inicializa el IntersectionObserver sobre todos los elementos
     * con el atributo [data-animar].
     */
    function iniciarAnimacionesAlScroll() {
        var elementos = document.querySelectorAll('[data-animar]');
        if (!elementos.length) return;

        /* Fallback: navegadores sin IntersectionObserver */
        if (!('IntersectionObserver' in window)) {
            elementos.forEach(activarAnimacion);
            return;
        }

        var observador = new IntersectionObserver(function (entradas) {
            entradas.forEach(function (entrada) {

                if (entrada.isIntersecting) {
                    /* El elemento entró en pantalla: se anima una sola vez
                       y se deja de observar, sin resetear en scrolls futuros
                       (evita retriggers que causan temblor en móvil). */
                    if (scrollHaciaAbajo) {
                        activarAnimacion(entrada.target);   /* ↓ con animación */
                    } else {
                        mostrarSinAnimacion(entrada.target); /* ↑ sin animación */
                    }
                    observador.unobserve(entrada.target);
                }

            });
        }, {
            threshold: UMBRAL_VISIBILIDAD,
            rootMargin: '0px 0px ' + MARGEN_INFERIOR + ' 0px'
        });

        elementos.forEach(function (el) {
            observador.observe(el);
        });
    }

    /* Iniciar cuando el DOM esté listo */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciarAnimacionesAlScroll);
    } else {
        iniciarAnimacionesAlScroll();
    }
})();
