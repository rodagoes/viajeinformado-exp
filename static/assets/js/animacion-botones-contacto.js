/**
 * animacion-botones-contacto.js — Viaje Informado
 *
 * Animación de entrada escalonada para los botones de contacto (.dpc-btn)
 * en la pantalla Detalle Establecimiento.
 *
 * Cuando el contenedor .dpc-botones entra en el viewport se agrega la clase
 * .dpc-visible a cada botón con un retardo incremental de 80 ms para
 * producir un efecto cascada.
 *
 * Requiere: estilos .dpc-btn / .dpc-visible en detalle-establecimiento.css
 */
(function () {
    'use strict';

    function iniciarAnimacionContacto() {
        var contenedor = document.querySelector('.dpc-botones');
        if (!contenedor) return;

        var btns = contenedor.querySelectorAll('.dpc-btn');
        if (!btns.length) return;

        /* Fallback: navegadores sin IntersectionObserver */
        if (!('IntersectionObserver' in window)) {
            btns.forEach(function (btn) { btn.classList.add('dpc-visible'); });
            return;
        }

        var observador = new IntersectionObserver(function (entradas) {
            entradas.forEach(function (entrada) {
                if (!entrada.isIntersecting) return;

                var botonesVisibles = entrada.target.querySelectorAll('.dpc-btn');
                botonesVisibles.forEach(function (btn, i) {
                    setTimeout(function () {
                        btn.classList.add('dpc-visible');
                    }, i * 80); /* 80 ms entre cada botón → efecto cascada */
                });

                observador.unobserve(entrada.target);
            });
        }, { threshold: 0.15 });

        observador.observe(contenedor);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciarAnimacionContacto);
    } else {
        iniciarAnimacionContacto();
    }
})();
