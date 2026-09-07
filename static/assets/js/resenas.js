/**
 * resenas.js — Viaje Informado
 *
 * El formulario de reseña (.vi-resena-form) está siempre visible y se envía
 * con un POST tradicional a la misma página de detalle (sin fetch). Este
 * archivo se encarga de tres cosas independientes:
 *
 * 1. Contador de caracteres del comentario.
 * 2. Gate de sesión: si el usuario no está autenticado
 *    (data-autenticado="false"), intercepta el submit, guarda un borrador
 *    (estrella + comentario) en sessionStorage y muestra un SweetAlert que
 *    lleva al login con `next` de vuelta a esta misma página (#resenas).
 * 3. Restaurar ese borrador si existe al volver a cargar la página (tras
 *    completar el login/registro/OAuth).
 *
 * También corrige la navegación por flechas del selector Uiverse: verificado
 * en navegador que `flex-direction: row-reverse` (DOM 5→4→3→2→1, visual
 * 1→2→3→4→5) invierte el sentido nativo de ArrowRight/ArrowLeft del
 * navegador (que navegan por orden del DOM, no por posición visual). Este
 * manejador es exclusivo de .vi-rating: no toca Tab ni Space (nativos) ni
 * ningún otro grupo de radios de la página.
 */
(function () {
    'use strict';

    var form = document.querySelector('.vi-resena-form');
    if (!form) return;

    var BORRADOR_KEY = 'vi-resena-borrador:' + window.location.pathname;

    function actualizarContador() {
        var textarea = form.querySelector('textarea[name="comentario"]');
        var contador = form.querySelector('[data-resena-contador]');
        if (!textarea || !contador) return;
        var max = Number(form.dataset.maxCaracteres) || textarea.getAttribute('maxlength') || 500;
        contador.textContent = textarea.value.length + '/' + max;
    }

    function leerFormulario() {
        var estrella = form.querySelector('input[name="valoracion"]:checked');
        var textarea = form.querySelector('textarea[name="comentario"]');
        return {
            valoracion: estrella ? estrella.value : '',
            comentario: textarea ? textarea.value : '',
        };
    }

    function aplicarFormulario(datos) {
        if (datos.valoracion) {
            var input = form.querySelector('input[name="valoracion"][value="' + datos.valoracion + '"]');
            if (input) input.checked = true;
        }
        var textarea = form.querySelector('textarea[name="comentario"]');
        if (textarea && datos.comentario) textarea.value = datos.comentario;
        actualizarContador();
    }

    function restaurarBorrador() {
        var guardado;
        try {
            guardado = sessionStorage.getItem(BORRADOR_KEY);
        } catch (error) {
            return;
        }
        if (!guardado) return;
        try {
            sessionStorage.removeItem(BORRADOR_KEY);
            aplicarFormulario(JSON.parse(guardado));
        } catch (error) {
            /* borrador corrupto: se ignora */
        }
    }

    form.addEventListener('input', function (event) {
        if (event.target.matches('textarea[name="comentario"]')) actualizarContador();
    });

    form.addEventListener('submit', function (event) {
        if (form.dataset.autenticado === 'true') return;
        event.preventDefault();

        try {
            sessionStorage.setItem(BORRADOR_KEY, JSON.stringify(leerFormulario()));
        } catch (error) {
            /* almacenamiento no disponible: se continúa igual, solo se pierde el borrador */
        }

        var loginUrl = form.dataset.loginUrl;
        if (!window.Swal) {
            window.location.href = loginUrl;
            return;
        }

        Swal.fire({
            icon: 'warning',
            title: 'Necesitas una cuenta para poder dejar tu reseña',
            showCancelButton: true,
            confirmButtonText: 'Iniciar sesión',
            cancelButtonText: 'Cancelar',
            confirmButtonColor: '#007FFF',
            cancelButtonColor: '#dc2626',
        }).then(function (resultado) {
            if (resultado.isConfirmed) window.location.href = loginUrl;
        });
    });

    actualizarContador();
    restaurarBorrador();

    document.querySelectorAll('.vi-resenas-dist-fill[data-porcentaje]').forEach(function (barra) {
        barra.style.width = barra.dataset.porcentaje + '%';
    });

    document.querySelectorAll('.vi-rating').forEach(function (grupo) {
        grupo.addEventListener('keydown', function (evento) {
            if (evento.key !== 'ArrowRight' && evento.key !== 'ArrowLeft') return;

            var radios = Array.from(grupo.querySelectorAll('input[name="valoracion"]'))
                .sort(function (a, b) { return Number(a.value) - Number(b.value); });
            var actual = radios.indexOf(document.activeElement);
            if (actual === -1) return;

            var siguiente = evento.key === 'ArrowRight'
                ? Math.min(actual + 1, radios.length - 1)
                : Math.max(actual - 1, 0);
            if (siguiente === actual) return;

            evento.preventDefault();
            radios[siguiente].checked = true;
            radios[siguiente].focus();
            radios[siguiente].dispatchEvent(new Event('change', { bubbles: true }));
        });

        // "Quitar valoración": visible solo cuando hay una estrella marcada.
        // Vive dentro del mismo <fieldset> que el grupo de estrellas.
        var fieldset = grupo.closest('fieldset');
        var botonQuitar = fieldset ? fieldset.querySelector('[data-rating-quitar]') : null;
        if (!botonQuitar) return;

        var radiosValoracion = grupo.querySelectorAll('input[name="valoracion"]');

        function actualizarBotonQuitar() {
            var hayMarcada = Array.prototype.some.call(radiosValoracion, function (r) { return r.checked; });
            botonQuitar.hidden = !hayMarcada;
        }

        grupo.addEventListener('change', actualizarBotonQuitar);
        botonQuitar.addEventListener('click', function () {
            radiosValoracion.forEach(function (r) { r.checked = false; });
            actualizarBotonQuitar();
        });

        actualizarBotonQuitar();
    });
})();
