(function () {
    "use strict";

    var MENSAJE_COPIADO = "Número copiado";
    var ETIQUETA_DEFECTO = "Copiar número";
    var DURACION_ESTADO_MS = 1800;

    var anunciador = document.getElementById("emergencias-anuncio");

    function anunciar(mensaje) {
        if (!anunciador) return;
        anunciador.textContent = "";
        window.setTimeout(function () {
            anunciador.textContent = mensaje;
        }, 0);
    }

    function marcarComoCopiado(boton) {
        var etiqueta = boton.querySelector("[data-copiar-etiqueta]");
        var icono = boton.querySelector("[data-copiar-icono]");

        if (boton.dataset.timeoutId) {
            window.clearTimeout(Number(boton.dataset.timeoutId));
        }

        boton.dataset.estado = "copiado";
        if (etiqueta) etiqueta.textContent = MENSAJE_COPIADO;
        if (icono) icono.className = "bi bi-check-lg";

        var timeoutId = window.setTimeout(function () {
            boton.dataset.estado = "";
            if (etiqueta) etiqueta.textContent = ETIQUETA_DEFECTO;
            if (icono) icono.className = "bi bi-clipboard";
        }, DURACION_ESTADO_MS);

        boton.dataset.timeoutId = String(timeoutId);
    }

    function copiarConFallback(texto, boton) {
        var textarea = document.createElement("textarea");
        textarea.value = texto;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand("copy");
            marcarComoCopiado(boton);
            anunciar(MENSAJE_COPIADO);
        } catch (error) {
            anunciar("No se pudo copiar el número");
        }
        document.body.removeChild(textarea);
    }

    function copiarNumero(numero, boton) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(numero).then(
                function () {
                    marcarComoCopiado(boton);
                    anunciar(MENSAJE_COPIADO);
                },
                function () {
                    copiarConFallback(numero, boton);
                }
            );
        } else {
            copiarConFallback(numero, boton);
        }
    }

    document.addEventListener("click", function (event) {
        var boton = event.target.closest("[data-copiar-numero]");
        if (!boton) return;
        copiarNumero(boton.getAttribute("data-copiar-numero"), boton);
    });

    document.querySelectorAll(".emergencias-idioma-switch").forEach(function (grupo) {
        var contenedor = grupo.closest(".emergencias-extranjeros__texto");
        if (!contenedor) return;
        var tituloEs = contenedor.querySelector(
            ".emergencias-extranjeros__title-es"
        );
        var tituloEn = contenedor.querySelector(
            ".emergencias-extranjeros__title-en"
        );
        var es = contenedor.querySelector(
            ".emergencias-extranjeros__es"
        );
        var en = contenedor.querySelector(
            ".emergencias-extranjeros__en"
        );
        if (!tituloEs || !tituloEn || !es || !en) return;
        grupo.addEventListener("click", function (event) {
            var boton = event.target.closest("[data-idioma]");
            if (!boton) return;
            var esEspanol = boton.dataset.idioma === "es";
            grupo.querySelectorAll("[data-idioma]").forEach(function (b) {
                var activo = b === boton;
                b.classList.toggle("is-active", activo);
                b.setAttribute("aria-pressed", String(activo));
            });
            // Cambiar título
            tituloEs.hidden = !esEspanol;
            tituloEn.hidden = esEspanol;
            // Cambiar descripción
            es.hidden = !esEspanol;
            en.hidden = esEspanol;
        });
    });

    var modal = document.getElementById("reportar-problema-modal");
    if (modal) {
        var form = document.getElementById("reportar-problema-form");
        var dialogo = modal.querySelector(".emergencias-modal__dialogo");
        var estado = form.querySelector("[data-estado-envio]");
        var botonEnviar = form.querySelector(".emergencias-modal__btn--enviar");
        var ultimoFoco = null;
        var scrollBloqueado = 0;

        // overflow:hidden en <body> no evita el scroll táctil en iOS; fijar
        // la posición y restaurarla al cerrar sí bloquea el scroll de
        // verdad (y evita el "temblor" de tener dos scrolls compitiendo).
        function bloquearScroll() {
            scrollBloqueado = window.scrollY;
            document.body.style.position = "fixed";
            document.body.style.top = "-" + scrollBloqueado + "px";
            document.body.style.left = "0";
            document.body.style.right = "0";
        }

        function desbloquearScroll() {
            document.body.style.position = "";
            document.body.style.top = "";
            document.body.style.left = "";
            document.body.style.right = "";
            // "behavior: instant" evita que el navegador anime el salto de
            // vuelta a la posición guardada (se veía como un scroll rápido
            // de arriba hacia abajo al cerrar el modal).
            window.scrollTo({ top: scrollBloqueado, left: 0, behavior: "instant" });
        }

        function abrirModal() {
            ultimoFoco = document.activeElement;
            modal.hidden = false;
            bloquearScroll();
            // No enfocar el input de texto: hacerlo abriría el teclado del
            // celular a la vez que entra la animación del modal, que es
            // justo lo que causaba el temblor visual. Se enfoca el diálogo
            // (sin abrir teclado) y el usuario toca el campo cuando quiera.
            if (dialogo) dialogo.focus({ preventScroll: true });
        }

        function cerrarModal() {
            modal.hidden = true;
            desbloquearScroll();
            estado.textContent = "";
            estado.removeAttribute("data-tipo");
            form.reset();
            // preventScroll: ya restauramos la posición nosotros mismos;
            // sin esto el navegador vuelve a hacer scroll (animado) hasta
            // el botón "Reportar", que suele estar al fondo de la página.
            if (ultimoFoco && typeof ultimoFoco.focus === "function") {
                ultimoFoco.focus({ preventScroll: true });
            }
        }

        document.querySelectorAll('[data-abrir-modal="reportar-problema"]').forEach(function (boton) {
            boton.addEventListener("click", abrirModal);
        });

        modal.querySelectorAll("[data-cerrar-modal]").forEach(function (boton) {
            boton.addEventListener("click", cerrarModal);
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && !modal.hidden) cerrarModal();
        });

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            botonEnviar.disabled = true;
            estado.removeAttribute("data-tipo");
            estado.textContent = "Enviando...";

            fetch(form.dataset.actionUrl, {
                method: "POST",
                body: new FormData(form),
            })
                .then(function (response) {
                    return response.json().catch(function () {
                        return { ok: false };
                    });
                })
                .then(function (data) {
                    if (data.ok) {
                        estado.dataset.tipo = "exito";
                        estado.textContent = "¡Gracias! Tu reporte fue enviado.";
                        window.setTimeout(cerrarModal, 1600);
                    } else {
                        estado.dataset.tipo = "error";
                        estado.textContent = "No se pudo enviar el reporte. Revisa los campos e intenta de nuevo.";
                    }
                })
                .catch(function () {
                    estado.dataset.tipo = "error";
                    estado.textContent = "No se pudo enviar el reporte. Intenta de nuevo más tarde.";
                })
                .finally(function () {
                    botonEnviar.disabled = false;
                });
        });
    }
})();
