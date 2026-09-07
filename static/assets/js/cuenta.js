/**
 * cuenta.js — Viaje Informado
 *
 * JS pequeño para las páginas de Cuenta (email/password/reauth/eliminar):
 * cooldown de reenvío OTP, solo-dígitos en el input de código, y habilitar
 * el botón "Eliminar cuenta" solo cuando el username escrito coincide.
 * La validación real de todo esto sigue siendo server-side.
 */
(function () {
    'use strict';

    // Cooldown de reenvío de OTP
    var btnReenviar = document.getElementById('btn-reenviar-cuenta');
    if (btnReenviar) {
        var restante = parseInt(btnReenviar.dataset.cooldown || '0', 10);
        var label = document.getElementById('cooldown-label-cuenta');
        if (restante > 0) {
            var tick = function () {
                if (restante <= 0) {
                    btnReenviar.disabled = false;
                    if (label) label.textContent = '';
                    return;
                }
                if (label) label.textContent = ' (' + restante + 's)';
                restante -= 1;
                setTimeout(tick, 1000);
            };
            tick();
        }
    }

    // Solo dígitos en el input OTP
    var otp = document.querySelector('.cuenta-otp-input');
    if (otp) {
        otp.addEventListener('input', function () {
            otp.value = otp.value.replace(/\D/g, '').slice(0, 4);
        });
    }

    // Habilitar "Eliminar cuenta" solo cuando el texto coincide con el username.
    var formEliminar = document.getElementById('form-eliminar-cuenta');
    if (formEliminar) {
        var input = formEliminar.querySelector('input[name="confirmacion"]');
        var boton = document.getElementById('btn-eliminar-cuenta');
        var esperado = (formEliminar.dataset.username || '').trim();
        if (input && boton) {
            var actualizar = function () {
                boton.disabled = input.value.trim() !== esperado;
            };
            input.addEventListener('input', actualizar);
            actualizar();
        }
    }
})();
