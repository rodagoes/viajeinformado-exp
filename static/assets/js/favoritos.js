/**
 * favoritos.js — Viaje Informado
 *
 * Toggle de favoritos (corazón) reutilizable en listados, detalles y en
 * /mi-cuenta/favoritos/. Delegación de eventos: funciona con cualquier
 * cantidad de corazones en la página sin volver a consultarlos uno a uno.
 */
(function () {
    'use strict';

    function getToastStack() {
        var stack = document.querySelector('.vi-toast-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.className = 'vi-toast-stack';
            stack.setAttribute('aria-live', 'polite');
            stack.setAttribute('aria-atomic', 'true');
            document.body.appendChild(stack);
        }
        return stack;
    }

    function showToast(mensaje, tag) {
        tag = tag || 'success';
        var iconos = {
            success: 'bi-check-circle-fill',
            error: 'bi-x-circle-fill',
            warning: 'bi-exclamation-circle-fill',
        };
        var toast = document.createElement('div');
        toast.className = 'vi-toast vi-toast--' + tag;
        toast.setAttribute('role', 'status');
        toast.dataset.autoDismiss = '3000';
        toast.innerHTML =
            '<i class="vi-toast__icon bi ' + (iconos[tag] || iconos.success) + '" aria-hidden="true"></i>' +
            '<span class="vi-toast__message"></span>' +
            '<button type="button" class="vi-toast__close" aria-label="Cerrar mensaje"><i class="bi bi-x" aria-hidden="true"></i></button>';
        toast.querySelector('.vi-toast__message').textContent = mensaje;

        var hide = function () {
            if (toast.classList.contains('is-hiding')) return;
            toast.classList.add('is-hiding');
            setTimeout(function () { toast.remove(); }, 200);
        };
        var timer = setTimeout(hide, 3000);
        toast.querySelector('.vi-toast__close').addEventListener('click', function () {
            clearTimeout(timer);
            hide();
        });

        getToastStack().appendChild(toast);
    }

    function setHeartState(btn, activo) {
        btn.classList.toggle('is-active', activo);
        btn.setAttribute('aria-pressed', activo ? 'true' : 'false');
        var icon = btn.querySelector('i');
        if (icon) icon.className = activo ? 'bi bi-heart-fill' : 'bi bi-heart';
        var nombre = btn.dataset.nombreRecurso || '';
        btn.setAttribute('aria-label', (activo ? 'Quitar ' : 'Agregar ') + nombre + (activo ? ' de favoritos' : ' a favoritos'));
        var texto = btn.querySelector('span');
        if (texto) texto.textContent = activo ? 'Guardado' : 'Guardar';
    }

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!form.classList || !form.classList.contains('vi-favorito-form')) return;
        event.preventDefault();
        if (form.dataset.pending === '1') return;

        var btn = form.querySelector('button');
        var estabaActivo = btn.classList.contains('is-active');

        form.dataset.pending = '1';
        btn.disabled = true;
        setHeartState(btn, !estabaActivo);

        fetch(form.dataset.actionUrl, {
            method: 'POST',
            body: new FormData(form),
        })
            .then(function (response) {
                if (response.status === 401) {
                    setHeartState(btn, estabaActivo);
                    abrirPopoverAnonimo(btn);
                    return null;
                }
                if (!response.ok) throw new Error('Respuesta no válida');
                return response.json();
            })
            .then(function (data) {
                if (!data) return;
                setHeartState(btn, data.es_favorito);
                showToast(data.es_favorito ? 'Agregado a tus favoritos.' : 'Eliminado de tus favoritos.');

                var paginaFavoritos = document.querySelector('[data-favoritos-page]');
                if (paginaFavoritos && !data.es_favorito) {
                    var card = btn.closest('.favorito-tarjeta');
                    if (card) {
                        var col = card.closest('.col');
                        var contenedor = col ? col.parentElement : null;
                        (col || card).classList.add('is-removing');
                        setTimeout(function () {
                            (col || card).remove();
                            if (contenedor && !contenedor.querySelector('.favorito-tarjeta')) {
                                window.location.reload();
                            }
                        }, 200);
                    }
                }
            })
            .catch(function () {
                setHeartState(btn, estabaActivo);
                showToast('No pudimos actualizar tus favoritos. Inténtalo nuevamente.', 'error');
            })
            .finally(function () {
                btn.disabled = false;
                form.dataset.pending = '0';
            });
    });

    // --- Prompt de usuario anónimo -----------------------------------------

    var popoverAbierto = null; // { popover, trigger }

    function cerrarPopoverAnonimo(devolverFoco) {
        if (!popoverAbierto) return;
        var trigger = popoverAbierto.trigger;
        popoverAbierto.popover.remove();
        popoverAbierto = null;
        document.removeEventListener('click', onClickFuera, true);
        document.removeEventListener('keydown', onKeydownPopover, true);
        window.removeEventListener('scroll', onScrollPopover, true);
        if (devolverFoco) trigger.focus();
    }

    function onClickFuera(event) {
        if (!popoverAbierto) return;
        if (popoverAbierto.popover.contains(event.target) || popoverAbierto.trigger.contains(event.target)) return;
        cerrarPopoverAnonimo(false);
    }

    function onKeydownPopover(event) {
        if (event.key === 'Escape') cerrarPopoverAnonimo(true);
    }

    function onScrollPopover() {
        cerrarPopoverAnonimo(false);
    }

    function posicionarPopover(popover, btn) {
        var rect = btn.getBoundingClientRect();
        popover.style.top = (rect.bottom + 10) + 'px';
        popover.style.left = Math.max(8, rect.right - popover.offsetWidth) + 'px';
    }

    function abrirPopoverAnonimo(btn) {
        if (popoverAbierto && popoverAbierto.trigger === btn) {
            cerrarPopoverAnonimo(true);
            return;
        }
        cerrarPopoverAnonimo(false);

        var popover = document.createElement('div');
        popover.className = 'vi-favorito-anon-popover';
        popover.setAttribute('role', 'dialog');
        popover.setAttribute('aria-label', 'Inicia sesión para guardar en favoritos');
        popover.setAttribute('tabindex', '-1');
        popover.innerHTML =
            '<p>Inicia sesión para guardar este lugar en tus favoritos.</p>' +
            '<div class="vi-favorito-anon-popover__acciones">' +
            '<a href="' + btn.dataset.loginUrl + '">Iniciar sesión</a>' +
            '<a href="' + btn.dataset.registroUrl + '">Crear cuenta</a>' +
            '</div>';

        document.body.appendChild(popover);
        posicionarPopover(popover, btn);

        popoverAbierto = { popover: popover, trigger: btn };
        document.addEventListener('click', onClickFuera, true);
        document.addEventListener('keydown', onKeydownPopover, true);
        window.addEventListener('scroll', onScrollPopover, true);

        var primerEnlace = popover.querySelector('a');
        // preventScroll: sin esto, el navegador hace scroll-into-view al enfocar,
        // lo que dispara onScrollPopover y cierra el popover recién abierto.
        if (primerEnlace) primerEnlace.focus({ preventScroll: true });
    }

    document.addEventListener('click', function (event) {
        var btn = event.target.closest ? event.target.closest('.vi-favorito-anon') : null;
        if (!btn) return;
        event.preventDefault();
        abrirPopoverAnonimo(btn);
    });

    // Se expone para que otros scripts (p. ej. compartir-establecimiento.js)
    // reutilicen el mismo sistema de toasts en vez de crear uno paralelo.
    window.viToast = showToast;
})();
