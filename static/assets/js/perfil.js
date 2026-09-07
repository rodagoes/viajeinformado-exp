/**
 * perfil.js — Viaje Informado
 *
 * Edición progresiva por bloque en /mi-cuenta/perfil/. El guardado es un
 * POST tradicional (PRG); este script solo abre/cierra cada bloque y
 * restaura el valor original al cancelar. Sin fetch.
 */
(function () {
    'use strict';

    function fila(campo) {
        return document.querySelector('.perfil-fila-edicion[data-campo="' + campo + '"]');
    }

    function abrir(campo) {
        var form = fila(campo);
        if (!form) return;
        var lectura = form.previousElementSibling;
        if (lectura) lectura.hidden = true;
        form.hidden = false;
        var input = form.querySelector('input[type="text"]');
        if (input) input.focus();
    }

    function cancelar(campo) {
        var form = fila(campo);
        if (!form) return;
        var input = form.querySelector('input[type="text"]');
        if (input) input.value = form.dataset.valorOriginal || '';
        form.hidden = true;
        var lectura = form.previousElementSibling;
        if (lectura) {
            lectura.hidden = false;
            var btnEditar = lectura.querySelector('[data-abrir="' + campo + '"]');
            if (btnEditar) btnEditar.focus();
        }
    }

    document.addEventListener('click', function (event) {
        var abrirBtn = event.target.closest ? event.target.closest('[data-abrir]') : null;
        if (abrirBtn) {
            abrir(abrirBtn.dataset.abrir);
            return;
        }
        var cancelarBtn = event.target.closest ? event.target.closest('[data-cancelar]') : null;
        if (cancelarBtn) {
            cancelar(cancelarBtn.dataset.cancelar);
        }
    });

    // Si el servidor reabrió un bloque tras un error de validación, mover el
    // foco a su input evita obligar a un segundo clic.
    var formAbierto = document.querySelector('.perfil-fila-edicion:not([hidden])');
    if (formAbierto) {
        var inputAbierto = formAbierto.querySelector('input[type="text"]');
        if (inputAbierto) inputAbierto.focus();
    }
})();
