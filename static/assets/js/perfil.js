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

    function restaurarPreviewFoto(form) {
        if (form.dataset.previewUrl) {
            URL.revokeObjectURL(form.dataset.previewUrl);
            delete form.dataset.previewUrl;
        }
        form.querySelectorAll('[data-foto-input]').forEach(function (input) { input.value = ''; });
        var img = form.querySelector('[data-foto-preview]');
        var inicial = form.querySelector('[data-foto-inicial]');
        if (!img) return;
        var original = img.dataset.avatarOriginal || '';
        if (original) {
            img.src = original;
            img.hidden = false;
            if (inicial) inicial.hidden = true;
        } else {
            img.hidden = true;
            if (inicial) inicial.hidden = false;
        }
    }

    function cancelar(campo) {
        var form = fila(campo);
        if (!form) return;
        if (campo === 'foto_perfil') {
            restaurarPreviewFoto(form);
        } else {
            var input = form.querySelector('input[type="text"]');
            if (input) input.value = form.dataset.valorOriginal || '';
        }
        form.hidden = true;
        if (campo !== 'foto_perfil') {
            var lectura = form.previousElementSibling;
            if (lectura) {
                lectura.hidden = false;
                var btnEditar = lectura.querySelector('[data-abrir="' + campo + '"]');
                if (btnEditar) btnEditar.focus();
            }
        } else {
            var lapiz = document.querySelector('.perfil-foto-lapiz');
            if (lapiz) lapiz.focus();
        }
    }

    function previsualizarFoto(input) {
        var form = input.closest('.perfil-fila-edicion');
        if (!form || !input.files || !input.files[0]) return;
        var img = form.querySelector('[data-foto-preview]');
        var inicial = form.querySelector('[data-foto-inicial]');
        if (!img) return;
        if (form.dataset.previewUrl) URL.revokeObjectURL(form.dataset.previewUrl);
        var url = URL.createObjectURL(input.files[0]);
        form.dataset.previewUrl = url;
        img.src = url;
        img.hidden = false;
        if (inicial) inicial.hidden = true;
        form.hidden = false;
    }

    // --- Menú de la foto (lápiz sobre el avatar) ---------------------------
    // Un único input[type=file] oculto: "Cargar una imagen" solo dispara su
    // click programático y deja que el selector nativo del sistema
    // (Photos/Cámara/Archivos en iOS, equivalente en Android, explorador en
    // desktop) resuelva el origen. La app no decide eso por el usuario.
    var menuFoto = document.querySelector('.perfil-foto-menu');

    function cerrarDropdownFoto() {
        if (!menuFoto || !window.bootstrap) return;
        var toggle = menuFoto.querySelector('.perfil-foto-lapiz');
        var instancia = window.bootstrap.Dropdown.getInstance(toggle);
        if (instancia) instancia.hide();
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
            return;
        }
        var cargarBtn = event.target.closest ? event.target.closest('[data-foto-cargar]') : null;
        if (cargarBtn) {
            var input = document.querySelector('[data-foto-input]');
            if (input) input.click();
            cerrarDropdownFoto();
            return;
        }
        var quitarBtn = event.target.closest ? event.target.closest('[data-foto-quitar]') : null;
        if (quitarBtn) {
            cerrarDropdownFoto();
            if (window.confirm('¿Quitar tu foto de perfil?')) {
                var form = fila('foto_perfil');
                var submitOculto = form ? form.querySelector('[data-foto-quitar-submit]') : null;
                if (form && submitOculto) form.requestSubmit(submitOculto);
            }
        }
    });

    document.addEventListener('change', function (event) {
        if (event.target.matches && event.target.matches('[data-foto-input]')) {
            previsualizarFoto(event.target);
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
