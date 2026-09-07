/**
 * compartir-establecimiento.js — Viaje Informado
 *
 * Botón "Compartir" del detalle de restaurantes y alojamientos (misma
 * plantilla para ambos). navigator.share() cuando el navegador lo soporta;
 * si no, copia la URL actual al portapapeles con feedback vía el sistema de
 * toasts de favoritos.js (window.viToast).
 */
(function () {
    'use strict';

    function toast(mensaje, tag) {
        if (window.viToast) {
            window.viToast(mensaje, tag);
        }
    }

    function copiarAlPortapapeles(texto) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(texto);
        }
        return new Promise(function (resolve, reject) {
            var textarea = document.createElement('textarea');
            textarea.value = texto;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            var copiado = false;
            try {
                copiado = document.execCommand('copy');
            } catch (error) {
                copiado = false;
            }
            document.body.removeChild(textarea);
            if (copiado) resolve(); else reject(new Error('No se pudo copiar'));
        });
    }

    function copiarConFeedback(url) {
        copiarAlPortapapeles(url).then(function () {
            toast('Enlace copiado', 'success');
        }).catch(function () {
            toast('No se pudo compartir el enlace.', 'error');
        });
    }

    document.querySelectorAll('[data-action="compartir-establecimiento"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var url = window.location.href;
            var nombre = btn.dataset.compartirNombre || document.title;

            if (navigator.share) {
                navigator.share({
                    title: nombre,
                    text: 'Mira este lugar en Viaje Informado',
                    url: url,
                }).catch(function (error) {
                    if (error && error.name === 'AbortError') return; // cancelación normal
                    toast('No se pudo compartir el enlace.', 'error');
                });
                return;
            }

            copiarConFeedback(url);
        });
    });
})();
