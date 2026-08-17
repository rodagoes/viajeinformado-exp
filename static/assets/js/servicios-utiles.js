(() => {
    "use strict";

    const modalComoLlegarEl = document.getElementById("su-modal-como-llegar");
    const modalInfoEl = document.getElementById("su-modal-info");

    const CLASE_BLUR = "su-backdrop-blur";
    let scrollBloqueado = 0;
    let siguienteBackdropLlevaBlur = false;

    const bloquearScroll = () => {
        scrollBloqueado = window.scrollY;
        document.body.style.position = "fixed";
        document.body.style.top = "-" + scrollBloqueado + "px";
        document.body.style.left = "0";
        document.body.style.right = "0";
    };

    const desbloquearScroll = () => {
        document.body.style.position = "";
        document.body.style.top = "";
        document.body.style.left = "";
        document.body.style.right = "";
        window.scrollTo({ top: scrollBloqueado, left: 0, behavior: "instant" });
    };

    new MutationObserver((mutaciones) => {
        if (!siguienteBackdropLlevaBlur) return;
        for (const mutacion of mutaciones) {
            for (const nodo of mutacion.addedNodes) {
                if (nodo.nodeType === 1 && nodo.classList.contains("modal-backdrop")) {
                    nodo.classList.add(CLASE_BLUR);
                    siguienteBackdropLlevaBlur = false;
                    return;
                }
            }
        }
    }).observe(document.body, { childList: true });

    [modalInfoEl, modalComoLlegarEl].forEach((modalEl) => {
        if (!modalEl) return;
        modalEl.addEventListener("show.bs.modal", () => {
            bloquearScroll();
            siguienteBackdropLlevaBlur = true;
        });
        modalEl.addEventListener("hidden.bs.modal", desbloquearScroll);
    });

    const obtenerModalBootstrap = (elemento) => {
        if (!elemento || !window.bootstrap) return null;
        return window.bootstrap.Modal.getOrCreateInstance(elemento);
    };

    const abrirComoLlegar = (servicioId) => {
        if (!modalComoLlegarEl) return;

        const proxy = modalComoLlegarEl.querySelector(
            '[data-sucursal][data-servicio-id="' + servicioId + '"]'
        );
        if (proxy) proxy.click();

        // Cada apertura arranca colapsada (mapa + CTA), igual que
        // establecimientos/turismo: el panel Desde/Hasta se expande solo
        // si el usuario hace clic en "Cómo llegar" (data-show-dir).
        const panelDirecciones = modalComoLlegarEl.querySelector("[data-directions]");
        const ctaDefault = modalComoLlegarEl.querySelector("[data-cta-default]");
        if (panelDirecciones) panelDirecciones.hidden = true;
        if (ctaDefault) ctaDefault.hidden = false;

        const modal = obtenerModalBootstrap(modalComoLlegarEl);
        if (modal) modal.show();
    };

    const leerServiciosData = () => {
        const el = document.getElementById("su-servicios-data");
        if (!el) return {};

        try {
            const lista = JSON.parse(el.textContent) || [];
            const porId = {};
            lista.forEach((servicio) => {
                porId[servicio.id] = servicio;
            });
            return porId;
        } catch (error) {
            return {};
        }
    };

    const serviciosPorId = leerServiciosData();

    const mostrarFila = (nombre, valor) => {
        if (!modalInfoEl) return;
        const fila = modalInfoEl.querySelector('[data-info-fila="' + nombre + '"]');
        if (fila) fila.hidden = !valor;
    };

    const ICONOS_ENLACE = {
        sitio_web: "bi-globe2",
        facebook: "bi-facebook",
        instagram: "bi-instagram",
    };

    const pintarContactos = (contactos) => {
        const lista = modalInfoEl.querySelector("[data-info-contactos]");
        lista.replaceChildren();

        (contactos || []).forEach((contacto) => {
            const fila = document.createElement("p");
            fila.className = "su-modal__contacto";

            if (contacto.etiqueta) {
                const etiqueta = document.createElement("strong");
                etiqueta.textContent = contacto.etiqueta + ": ";
                fila.appendChild(etiqueta);
            }

            if (contacto.valor_tel) {
                const enlace = document.createElement("a");
                enlace.href = "tel:" + contacto.valor_tel;
                enlace.textContent = contacto.valor;
                fila.appendChild(enlace);
            } else {
                fila.appendChild(document.createTextNode(contacto.valor));
            }

            lista.appendChild(fila);
        });

        mostrarFila("contactos", (contactos || []).length > 0);
    };

    const pintarEnlaces = (enlaces) => {
        const wrap = modalInfoEl.querySelector("[data-info-enlaces]");
        const lista = modalInfoEl.querySelector("[data-info-enlaces-lista]");
        lista.replaceChildren();

        (enlaces || []).forEach((enlace) => {
            const a = document.createElement("a");
            a.href = enlace.url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.className = "su-modal__enlace";
            a.setAttribute("aria-label", enlace.label);
            a.title = enlace.label;

            const icono = document.createElement("i");
            icono.className = "bi " + (ICONOS_ENLACE[enlace.tipo] || "bi-link-45deg");
            icono.setAttribute("aria-hidden", "true");
            a.appendChild(icono);

            lista.appendChild(a);
        });

        wrap.hidden = !(enlaces && enlaces.length);
    };

    const abrirInfo = (servicioId) => {
        if (!modalInfoEl) return;

        const servicio = serviciosPorId[servicioId];
        if (!servicio) return;

        modalInfoEl.querySelector("[data-info-nombre]").textContent = servicio.nombre || "";

        const imagen = modalInfoEl.querySelector("[data-info-imagen]");
        const imagenFallback = modalInfoEl.querySelector("[data-info-imagen-fallback]");
        if (servicio.imagen_url) {
            imagen.src = servicio.imagen_url;
            imagen.alt = servicio.imagen_alt || servicio.nombre || "";
            imagen.hidden = false;
            imagenFallback.hidden = true;
        } else {
            imagen.removeAttribute("src");
            imagen.hidden = true;
            imagenFallback.hidden = false;
        }

        // Descripción como fila
        modalInfoEl.querySelector("[data-info-descripcion]").textContent = servicio.descripcion_corta || "";
        mostrarFila("descripcion", servicio.descripcion_corta);

        // Dirección
        modalInfoEl.querySelector("[data-info-direccion]").textContent = servicio.direccion || "";
        mostrarFila("direccion", servicio.direccion);

        // Horario
        modalInfoEl.querySelector("[data-info-horario]").textContent = servicio.disponibilidad_texto || "";
        mostrarFila("horario", servicio.disponibilidad_texto);

        // Contactos y enlaces
        pintarContactos(servicio.contactos);
        pintarEnlaces(servicio.enlaces);

        const modal = obtenerModalBootstrap(modalInfoEl);
        if (modal) modal.show();
    };

    document.addEventListener("click", (event) => {
        const btnComoLlegar = event.target.closest("[data-abrir-como-llegar]");
        if (btnComoLlegar) {
            abrirComoLlegar(btnComoLlegar.dataset.servicioId);
            return;
        }

        const btnInfo = event.target.closest("[data-abrir-info]");
        if (btnInfo) {
            abrirInfo(btnInfo.dataset.servicioId);
        }
    });
})();
