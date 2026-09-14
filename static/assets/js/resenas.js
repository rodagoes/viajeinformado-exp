/**
 * resenas.js — Viaje Informado
 *
 * El formulario de reseña (.vi-resena-form) se envía con un POST tradicional
 * a la misma página de detalle (sin fetch). Este archivo se encarga de:
 *
 * 1. Mover el/los modal(es) de "Eliminar reseña" a <body>. Bootstrap crea su
 *    .modal-backdrop como hijo directo de <body>, pero el propio .modal vive
 *    donde lo puso el template — anidado dentro de .vi-resenas. En mobile,
 *    .detalle-contenido gana position:relative;z-index:1 (ver
 *    detalle-establecimiento.css), lo que atrapa al modal en un stacking
 *    context de valor bajo: el backdrop (hijo directo de body, z-index:1050)
 *    termina pintando por encima y bloquea los clics aunque el modal se vea.
 *    Sacarlo a body evita depender de cualquier ancestro presente o futuro.
 * 2. Bloquear el scroll de fondo mientras el modal de eliminar está abierto.
 *    Bootstrap ya agrega `.modal-open`/`overflow:hidden` al body, pero eso no
 *    alcanza en iOS Safari: el "rubber-band" táctil sigue moviendo la página
 *    por debajo del backdrop pese al overflow:hidden (bug histórico de
 *    WebKit, independiente de este proyecto). El fix estándar es fijar el
 *    body en su posición de scroll actual mientras el modal está visible.
 * 3. Abrir/cerrar el compositor solo mediante "Editar" (nunca queda visible
 *    y poblado automáticamente tras publicar).
 * 4. Habilitar/deshabilitar "Publicar reseña"/"Guardar cambios" según si hay
 *    una valoración marcada (la validación real sigue siendo server-side).
 * 5. Contador de caracteres del comentario.
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

    document.querySelectorAll('.vi-resenas .modal').forEach(function (modal) {
        document.body.appendChild(modal);
    });

    var SCROLL_LOCK_CLASS = 'vi-modal-scroll-lock';
    var scrollLockY = 0;

    document.querySelectorAll('[id$="-modal-eliminar"]').forEach(function (modal) {
        modal.addEventListener('show.bs.modal', function () {
            scrollLockY = window.scrollY;
            document.body.style.top = (-scrollLockY) + 'px';
            document.body.classList.add(SCROLL_LOCK_CLASS);
        });
        modal.addEventListener('hidden.bs.modal', function () {
            document.body.classList.remove(SCROLL_LOCK_CLASS);
            document.body.style.top = '';
            window.scrollTo(0, scrollLockY);
        });
    });

    var form = document.querySelector('.vi-resena-form');
    if (!form) return;

    var compose = document.querySelector('[data-resena-compose]');
    var submitBtn = form.querySelector('[data-resena-submit]');
    var cancelarBtn = form.querySelector('[data-resena-cancelar]');
    var snapshotOriginal = null;

    function actualizarContador() {
        var textarea = form.querySelector('textarea[name="comentario"]');
        var contador = form.querySelector('[data-resena-contador]');
        if (!textarea || !contador) return;
        var max = Number(form.dataset.maxCaracteres) || textarea.getAttribute('maxlength') || 500;
        contador.textContent = textarea.value.length + '/' + max;
    }

    function actualizarBotonSubmit() {
        if (!submitBtn) return;
        submitBtn.disabled = !form.querySelector('input[name="valoracion"]:checked');
    }

    function leerValores() {
        var estrella = form.querySelector('input[name="valoracion"]:checked');
        var textarea = form.querySelector('textarea[name="comentario"]');
        return { valoracion: estrella ? estrella.value : '', comentario: textarea ? textarea.value : '' };
    }

    function aplicarValores(datos) {
        form.querySelectorAll('input[name="valoracion"]').forEach(function (r) {
            r.checked = r.value === datos.valoracion;
        });
        var textarea = form.querySelector('textarea[name="comentario"]');
        if (textarea) textarea.value = datos.comentario;
        var botonQuitar = form.querySelector('[data-rating-quitar]');
        if (botonQuitar) botonQuitar.hidden = !datos.valoracion;
        actualizarContador();
        actualizarBotonSubmit();
    }

    if (compose && !compose.hidden) snapshotOriginal = leerValores();

    document.querySelectorAll('[data-resena-editar]').forEach(function (link) {
        link.addEventListener('click', function (event) {
            event.preventDefault();
            if (!compose) return;
            snapshotOriginal = leerValores();
            compose.hidden = false;
            compose.scrollIntoView({ behavior: 'smooth', block: 'start' });
            var foco = form.querySelector('input[name="valoracion"]:checked') || form.querySelector('input[name="valoracion"]');
            if (foco) foco.focus();
        });
    });

    if (cancelarBtn) {
        cancelarBtn.addEventListener('click', function () {
            if (snapshotOriginal) aplicarValores(snapshotOriginal);
            if (compose) compose.hidden = true;
        });
    }

    form.addEventListener('input', function (event) {
        if (event.target.matches('textarea[name="comentario"]')) actualizarContador();
    });

    actualizarContador();
    actualizarBotonSubmit();

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

        grupo.addEventListener('change', function () {
            actualizarBotonQuitar();
            actualizarBotonSubmit();
        });
        botonQuitar.addEventListener('click', function () {
            radiosValoracion.forEach(function (r) { r.checked = false; });
            actualizarBotonQuitar();
            actualizarBotonSubmit();
        });

        actualizarBotonQuitar();
    });
})();
