(() => {
    "use strict";

    const prefiereReducirMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // ---- Scroll lock + backdrop blur compartido por los 3 modales de
    // Eventos (E7): mismo patrón ya probado en Historia
    // (his-himno-modal/historia.js) — guardar scrollY, fijar el body en esa
    // posición con `position:fixed` + `top` negativo (evita el salto/scroll
    // de fondo que un simple `overflow:hidden` no bloquea de forma
    // confiable en iOS Safari) y restaurar el scroll exacto al cerrar.
    // Único helper para los 3 (`#ev-modal-info`, `#ev-modal-promocionar`,
    // `#ev-modal-reportar`) en vez de repetirlo por modal, con un contador
    // para que cerrar uno mientras "en teoría" hay otro abierto no
    // desbloquee el body de más (E37) — Bootstrap solo permite un modal
    // visible a la vez, pero el contador lo deja a prueba de ese caso igual.
    let modalesEventosAbiertos = 0;
    let scrollAlAbrirModal = 0;

    const bloquearScrollFondo = () => {
        scrollAlAbrirModal = window.scrollY;
        document.body.style.position = "fixed";
        document.body.style.top = "-" + scrollAlAbrirModal + "px";
        document.body.style.left = "0";
        document.body.style.right = "0";
    };

    const desbloquearScrollFondo = () => {
        document.body.style.position = "";
        document.body.style.top = "";
        document.body.style.left = "";
        document.body.style.right = "";
        window.scrollTo({ top: scrollAlAbrirModal, left: 0, behavior: "instant" });
    };

    // `body.ev-modal-abierto` (E38) activa el blur del backdrop en CSS
    // (agenda-eventos.css) sin tocar `.modal-backdrop` de otros módulos —
    // se agrega en `show.bs.modal`, ANTES de que Bootstrap inserte el
    // `.modal-backdrop` en el DOM, así el selector CSS ya lo alcanza desde
    // que aparece (sin MutationObserver ni clase inyectada por elemento).
    document.querySelectorAll("#ev-modal-info, #ev-modal-promocionar, #ev-modal-reportar").forEach((modalEl) => {
        modalEl.addEventListener("show.bs.modal", () => {
            if (modalesEventosAbiertos === 0) bloquearScrollFondo();
            modalesEventosAbiertos += 1;
            document.body.classList.add("ev-modal-abierto");
        });
        modalEl.addEventListener("hidden.bs.modal", () => {
            modalesEventosAbiertos = Math.max(0, modalesEventosAbiertos - 1);
            if (modalesEventosAbiertos === 0) {
                desbloquearScrollFondo();
                document.body.classList.remove("ev-modal-abierto");
            }
        });
    });

    // El día activo del selector debe verse sin necesidad de hacer scroll
    // manual — se aplica siempre, incluso sin eventos en la página (estado
    // vacío), por eso vive fuera del guard del modal.
    const enfocarDiaActivo = () => {
        const diaActivo = document.querySelector(".ev-selector-dias__dia.is-activo");
        if (!diaActivo) return;
        diaActivo.scrollIntoView({
            inline: "center",
            block: "nearest",
            behavior: prefiereReducirMovimiento ? "auto" : "smooth",
        });
    };

    // Flechas del selector de días (B2): navegación visual pura del
    // calendario, NUNCA un filtro. Antes disparaban un fetch + replaceState
    // que igual pegaba al backend y ensuciaba la URL con `semana=`. Ahora
    // desplazan la ventana de 14 días 100% en cliente: sin request, sin
    // tocar la URL, sin generar `semana` — mutan en el sitio los mismos 14
    // <a> ya renderizados por Django (mismo DOM, no se recrean) para no
    // perder la posición de scroll de la lista.
    const DIAS_VENTANA = 14;
    const NOMBRES_DIA_SEMANA = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"];
    const NOMBRES_MES_ABREV = ["", "ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"];

    // Fechas civiles (YYYY-MM-DD) tratadas siempre en UTC epoch, nunca con
    // `new Date("YYYY-MM-DD")` ni getters locales: evita que un usuario en
    // UTC-5 (Perú) o cualquier otro huso vea el día correrse ±1 (R igual
    // que en el backend, que trabaja con `datetime.date` sin hora/TZ).
    const fechaISOaEpochUTC = (iso) => {
        const [anio, mes, dia] = iso.split("-").map(Number);
        return Date.UTC(anio, mes - 1, dia);
    };
    const epochUTCaFechaISO = (epoch) => {
        const d = new Date(epoch);
        const anio = d.getUTCFullYear();
        const mes = String(d.getUTCMonth() + 1).padStart(2, "0");
        const dia = String(d.getUTCDate()).padStart(2, "0");
        return `${anio}-${mes}-${dia}`;
    };
    const sumarDiasUTC = (epoch, n) => epoch + n * 86400000;

    const inicializarSelectorDias = () => {
        const selectorEl = document.querySelector(".ev-selector-dias");
        if (!selectorEl) return;

        const listaEl = selectorEl.querySelector(".ev-selector-dias__lista");
        const diasEl = Array.from(listaEl.querySelectorAll(".ev-selector-dias__dia"));
        const tituloEl = document.querySelector(".ev-selector-dias__mes");
        const hoyISO = selectorEl.dataset.hoy;
        const fechaActivaISO = selectorEl.dataset.fechaActiva || "";
        const baseQuery = selectorEl.dataset.baseQuery || "";
        let anclaEpoch = fechaISOaEpochUTC(selectorEl.dataset.ancla);

        const construirHref = (iso) => "?" + (baseQuery ? baseQuery + "&fecha=" + iso : "fecha=" + iso);

        const pintarVentana = () => {
            const conteoPorAnio = {};
            const ordenAnios = [];

            for (let i = 0; i < DIAS_VENTANA; i++) {
                const epoch = sumarDiasUTC(anclaEpoch, i);
                const iso = epochUTCaFechaISO(epoch);
                const fecha = new Date(epoch);
                const anio = fecha.getUTCFullYear();
                const mes = fecha.getUTCMonth() + 1;
                const numero = fecha.getUTCDate();
                const diaSemanaPy = (fecha.getUTCDay() + 6) % 7; // JS 0=dom..6=sáb -> Python 0=lun..6=dom

                if (!(anio in conteoPorAnio)) ordenAnios.push(anio);
                conteoPorAnio[anio] = (conteoPorAnio[anio] || 0) + 1;

                const enlace = diasEl[i];
                enlace.href = construirHref(iso);
                enlace.dataset.date = iso;
                enlace.querySelector(".ev-selector-dias__mesdia").textContent = NOMBRES_MES_ABREV[mes];
                enlace.querySelector(".ev-selector-dias__nombre").textContent = NOMBRES_DIA_SEMANA[diaSemanaPy];
                enlace.querySelector(".ev-selector-dias__numero").textContent = String(numero);

                const esHoy = iso === hoyISO;
                const esActivo = Boolean(fechaActivaISO) && iso === fechaActivaISO;
                enlace.classList.toggle("is-hoy", esHoy);
                enlace.classList.toggle("is-activo", esActivo);
                if (esActivo) enlace.setAttribute("aria-current", "date");
                else enlace.removeAttribute("aria-current");
            }

            // Año dominante de la ventana visible, con el mismo criterio que
            // `Counter.most_common(1)` en el backend: mayor conteo, y en
            // empate el primero que apareció en la ventana.
            let anioDominante = ordenAnios[0];
            let maxConteo = 0;
            ordenAnios.forEach((anio) => {
                if (conteoPorAnio[anio] > maxConteo) {
                    maxConteo = conteoPorAnio[anio];
                    anioDominante = anio;
                }
            });
            if (tituloEl) tituloEl.textContent = `Calendario - ${anioDominante}`;
        };

        selectorEl.querySelectorAll(".ev-selector-dias__flecha").forEach((flecha) => {
            flecha.addEventListener("click", () => {
                anclaEpoch = sumarDiasUTC(anclaEpoch, flecha.dataset.direccion === "siguiente" ? 1 : -1);
                pintarVentana();
            });
        });
    };

    document.addEventListener("DOMContentLoaded", () => {
        enfocarDiaActivo();
        inicializarSelectorDias();
    });

    // "Elegir fecha" (B1.1): en iOS/iPadOS el picker nativo de <input
    // type="date"> dispara `change` en cada ajuste de rueda (mes/año/día),
    // no solo al confirmar — a diferencia de Android (diálogo modal real) y
    // desktop, donde `change` sí se dispara únicamente al comprometer el
    // valor final. Ahí, `change` seguía provocando un submit prematuro con
    // un valor todavía provisional (incluso el auto-relleno con "hoy" que
    // iOS aplica al abrir un campo vacío).
    //
    // En iOS/iPadOS, `change` pasa a solo marcar el cambio como pendiente;
    // el envío real espera a que el input pierda el foco (`blur`), que es
    // cuando el picker realmente se cierra — con o sin botón "Done"/check
    // visible según la versión de iOS, nunca se depende de ese control
    // nativo en sí. Sin timeouts, sin leer coordenadas ni el propio ✓.
    // En el resto de plataformas se conserva cambiar+enviar de una sola vez
    // (ahí `change` ya se comporta como el "commit" final).
    const esIOSoIPadOS = () => (
        /iPad|iPhone|iPod/.test(navigator.userAgent)
        || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
    );

    const inputFecha = document.getElementById("ev-fecha-input");
    if (inputFecha) {
        let valorAlEnfocar = inputFecha.value;
        let cambioPendiente = false;
        let enviandoFecha = false;

        const enviarFecha = () => {
            if (enviandoFecha) return;
            enviandoFecha = true;
            inputFecha.form.requestSubmit();
        };

        inputFecha.addEventListener("focus", () => {
            valorAlEnfocar = inputFecha.value;
            cambioPendiente = false;
        });

        if (esIOSoIPadOS()) {
            inputFecha.addEventListener("change", () => {
                // Recalculado en cada ajuste (no solo el primero): si el
                // usuario cambia y vuelve al valor original antes de cerrar
                // el picker, el último `change` deja esto en `false` y el
                // blur de abajo no envía nada (R17 del encargo).
                cambioPendiente = inputFecha.value !== valorAlEnfocar;
            });
            inputFecha.addEventListener("blur", () => {
                if (cambioPendiente) enviarFecha();
            });
        } else {
            inputFecha.addEventListener("change", enviarFecha);
        }
    }

    // CTA "Promociona tu evento" / "Reportar un problema": envío normal por
    // POST (sin fetch, ver R20/R21 — el navegador ya hace todo el trabajo,
    // incluida la validación HTML5 antes de llegar al servidor). Único
    // aporte de JS aquí es la mejora progresiva de deshabilitar el botón
    // para evitar doble envío mientras la página navega (R26).
    document.querySelectorAll(".ev-form-modal__form").forEach((form) => {
        form.addEventListener("submit", () => {
            const boton = form.querySelector('button[type="submit"]');
            if (!boton) return;
            boton.disabled = true;
            boton.textContent = "Enviando…";
        });
    });

    // Distrito dependiente de Provincia (R1.1): la lista de distritos vino de
    // Django ya agrupada por provincia (json_script, sin AJAX). Aquí solo se
    // repintan las <option> del <select> nativo; el backend sigue siendo la
    // autoridad final si llega una combinación incompatible por URL manual.
    const selectProvincia = document.getElementById("ev-filtro-provincia");
    const selectDistrito = document.getElementById("ev-filtro-distrito");
    const distritosDataEl = document.getElementById("ev-distritos-data");

    if (selectProvincia && selectDistrito && distritosDataEl) {
        let distritosPorProvincia = {};
        try {
            distritosPorProvincia = JSON.parse(distritosDataEl.textContent) || {};
        } catch (error) {
            distritosPorProvincia = {};
        }

        const pintarDistritos = (provinciaSlug, distritoPreferido) => {
            const opciones = distritosPorProvincia[provinciaSlug || "__todos__"] || [];
            selectDistrito.replaceChildren();

            const optTodos = document.createElement("option");
            optTodos.value = "";
            optTodos.textContent = "Todos";
            selectDistrito.appendChild(optTodos);

            opciones.forEach((distrito) => {
                const opt = document.createElement("option");
                opt.value = distrito.slug;
                opt.textContent = distrito.nombre;
                if (distrito.slug === distritoPreferido) opt.selected = true;
                selectDistrito.appendChild(opt);
            });
        };

        // Repinta ya en la carga: el <select> vino del servidor con TODOS los
        // distritos (fallback sin JS), así que aquí se acota de inmediato a
        // los de la provincia activa, conservando el distrito ya elegido
        // (el backend garantiza que si llegó hasta aquí es compatible).
        pintarDistritos(selectProvincia.value, selectDistrito.value);

        selectProvincia.addEventListener("change", () => {
            // Nueva provincia: el distrito ya elegido casi nunca pertenece a
            // ella, así que se resetea a "Todos" antes de repintar (E5). Ya
            // no se auto-envía el form (R29): en desktop ahora el turista
            // confirma toda la selección con el botón "Aplicar filtros".
            pintarDistritos(selectProvincia.value, "");
        });
    }

    const modalInfoEl = document.getElementById("ev-modal-info");
    if (!modalInfoEl) return; // sin eventos en la página, no hay modal que preparar

    let swiperInstance = null;

    // ---- Autoplay + bullets con progreso/timer (R74, sección 17-19) ----
    // Mismo patrón ya consolidado en Establecimientos (swiper-detalle-est.js,
    // `initDetalleSwiper`): autoplay propio por rAF en vez del módulo
    // `autoplay` de Swiper (así el progreso se puede pausar/reanudar exacto
    // donde quedó, sin reiniciar el temporizador), con el progreso pintado
    // dentro del bullet activo (`.ev-modal-bullet-progress`, creado por
    // `renderBullet` en `inicializarSwiperGaleria`). No se reimplementa "a
    // ojo": mismos nombres de fase (iniciar/pausar/resetear progreso),
    // adaptados a la convención de nombres en español de este módulo.
    // `prefiereReducirMovimiento` (sección 20): con reduced motion, el
    // autoplay nunca arranca y el botón play/pause queda oculto — la
    // navegación manual (swipe/flechas/bullets) sigue intacta.
    const AUTOPLAY_DELAY_MS = 4200;
    const playBtn = modalInfoEl.querySelector("[data-info-swiper-play]");
    const paginationEl = modalInfoEl.querySelector("[data-info-swiper-pagination]");

    let autoplayPausadoPorUsuario = false;
    let enTransicion = false;
    let rafProgresoId = null;
    let progresoInicioMs = 0;
    let progresoTranscurridoMs = 0;

    const cancelarProgreso = () => {
        if (rafProgresoId) {
            window.cancelAnimationFrame(rafProgresoId);
            rafProgresoId = null;
        }
    };

    const fijarProgresoBulletActivo = (porcentaje) => {
        const activo = paginationEl.querySelector(".swiper-pagination-bullet-active");
        const barra = activo && activo.querySelector(".ev-modal-bullet-progress");
        if (barra) barra.style.width = porcentaje + "%";
    };

    const resetearBulletsInactivos = () => {
        paginationEl.querySelectorAll(".swiper-pagination-bullet").forEach((bullet) => {
            if (bullet.classList.contains("swiper-pagination-bullet-active")) return;
            const barra = bullet.querySelector(".ev-modal-bullet-progress");
            if (barra) barra.style.width = "0%";
        });
    };

    const resetearProgresoSlideActual = () => {
        progresoTranscurridoMs = 0;
        resetearBulletsInactivos();
        fijarProgresoBulletActivo(0);
    };

    const marcarReproduciendo = () => {
        if (!playBtn) return;
        playBtn.classList.remove("is-paused");
        const icono = playBtn.querySelector("i");
        if (icono) icono.className = "bi bi-pause-fill";
        playBtn.setAttribute("aria-label", "Pausar carrusel");
    };

    const marcarPausado = () => {
        if (!playBtn) return;
        playBtn.classList.add("is-paused");
        const icono = playBtn.querySelector("i");
        if (icono) icono.className = "bi bi-play-fill";
        playBtn.setAttribute("aria-label", "Reanudar carrusel");
    };

    const iniciarProgreso = (swiper, transcurridoPrevio) => {
        cancelarProgreso();
        if (autoplayPausadoPorUsuario || enTransicion || prefiereReducirMovimiento) return;
        if (!swiper || swiper.slides.length <= 1) return;

        progresoTranscurridoMs = Math.max(0, Math.min(transcurridoPrevio || 0, AUTOPLAY_DELAY_MS));
        progresoInicioMs = performance.now() - progresoTranscurridoMs;

        const tick = (ahora) => {
            if (autoplayPausadoPorUsuario || enTransicion) return;
            progresoTranscurridoMs = ahora - progresoInicioMs;
            const porcentaje = Math.min(100, Math.max(0, (progresoTranscurridoMs / AUTOPLAY_DELAY_MS) * 100));
            resetearBulletsInactivos();
            fijarProgresoBulletActivo(porcentaje);

            if (progresoTranscurridoMs >= AUTOPLAY_DELAY_MS) {
                progresoTranscurridoMs = 0;
                cancelarProgreso();
                swiper.slideNext();
                return;
            }
            rafProgresoId = window.requestAnimationFrame(tick);
        };
        rafProgresoId = window.requestAnimationFrame(tick);
    };

    const pausarProgreso = () => {
        if (progresoInicioMs) {
            progresoTranscurridoMs = Math.max(0, Math.min(performance.now() - progresoInicioMs, AUTOPLAY_DELAY_MS));
        }
        cancelarProgreso();
        fijarProgresoBulletActivo(Math.min(100, Math.max(0, (progresoTranscurridoMs / AUTOPLAY_DELAY_MS) * 100)));
    };

    // Un único listener (no dentro de inicializarSwiperGaleria, que se llama
    // en cada apertura del modal): el botón es el mismo nodo del DOM en
    // todas las aperturas, así que registrarlo ahí acumularía listeners
    // duplicados en cada evento abierto (R74, sección 52).
    if (playBtn) {
        playBtn.addEventListener("click", () => {
            if (autoplayPausadoPorUsuario) {
                autoplayPausadoPorUsuario = false;
                marcarReproduciendo();
                iniciarProgreso(swiperInstance, progresoTranscurridoMs);
            } else {
                autoplayPausadoPorUsuario = true;
                pausarProgreso();
                marcarPausado();
            }
        });
    }

    // Lightbox de la galería (botón glass "ver en grande"): overlay simple
    // sin librería nueva — usa el índice activo del propio swiperInstance
    // como única fuente de verdad, sin duplicar estado de navegación. El
    // overlay cubre toda la pantalla, así que el carrusel de fondo queda
    // inalcanzable mientras está abierto (no hace falta re-sincronizarlo).
    const lightboxEl = document.getElementById("ev-lightbox");
    const cerrarLightbox = () => {
        if (lightboxEl) lightboxEl.hidden = true;
    };

    if (lightboxEl) {
        const lightboxImg = lightboxEl.querySelector("[data-lightbox-img]");
        const lightboxPrev = lightboxEl.querySelector("[data-lightbox-prev]");
        const lightboxNext = lightboxEl.querySelector("[data-lightbox-next]");

        const actualizarLightbox = () => {
            if (!swiperInstance) return;
            const slideActivo = swiperInstance.slides[swiperInstance.activeIndex];
            const img = slideActivo && slideActivo.querySelector("img");
            if (img) {
                lightboxImg.src = img.src;
                lightboxImg.alt = img.alt;
            }
            const haySoloUna = swiperInstance.slides.length <= 1;
            lightboxPrev.hidden = haySoloUna;
            lightboxNext.hidden = haySoloUna;
        };

        modalInfoEl.addEventListener("click", (event) => {
            if (event.target.closest("[data-info-swiper-zoom]")) {
                actualizarLightbox();
                lightboxEl.hidden = false;
            }
        });
        lightboxEl.querySelector("[data-lightbox-cerrar]").addEventListener("click", cerrarLightbox);
        lightboxEl.addEventListener("click", (event) => {
            if (event.target === lightboxEl) cerrarLightbox();
        });
        lightboxPrev.addEventListener("click", () => {
            if (swiperInstance) swiperInstance.slidePrev();
            actualizarLightbox();
        });
        lightboxNext.addEventListener("click", () => {
            if (swiperInstance) swiperInstance.slideNext();
            actualizarLightbox();
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !lightboxEl.hidden) cerrarLightbox();
        });
    }

    // El scroll lock + blur del backdrop ya quedaron enganchados arriba
    // (bloque compartido con los otros 2 modales de Eventos); aquí solo
    // queda lo específico de este modal: única responsabilidad de destroy
    // del carrusel (ver `inicializarSwiperGaleria`, que es la única que
    // construye) — se quita `is-ready` para que la próxima apertura no
    // reutilice por un instante el estado "listo" de la sesión anterior con
    // slides todavía viejas.
    modalInfoEl.addEventListener("hidden.bs.modal", () => {
        cerrarLightbox();
        galeriaPendiente = false;
        cancelarProgreso();
        autoplayPausadoPorUsuario = false;
        enTransicion = false;
        modalInfoEl.querySelector("[data-info-swiper]").classList.remove("is-ready");
        modalInfoEl.querySelector("[data-info-swiper-pagination]").classList.remove("is-ready");
        if (swiperInstance) {
            swiperInstance.destroy(true, true);
            swiperInstance = null;
        }
    });

    // Swiper mide el ancho/alto real del contenedor al construirse — con el
    // modal todavía `display:none` esa primera medición sale mal (0 o el
    // tamaño de un frame previo) y el carrusel queda descuadrado hasta el
    // primer resize manual. `shown.bs.modal` es el momento en que Bootstrap
    // garantiza que el modal ya terminó de mostrarse con su tamaño final,
    // así que es el único punto donde se instancia Swiper (ver
    // `inicializarSwiperGaleria`).
    modalInfoEl.addEventListener("shown.bs.modal", () => {
        inicializarSwiperGaleria();
    });

    const obtenerModalBootstrap = (elemento) => {
        if (!elemento || !window.bootstrap) return null;
        return window.bootstrap.Modal.getOrCreateInstance(elemento);
    };

    const leerEventosData = () => {
        const el = document.getElementById("ev-eventos-data");
        if (!el) return {};

        try {
            const lista = JSON.parse(el.textContent) || [];
            const porId = {};
            lista.forEach((evento) => {
                porId[evento.id] = evento;
            });
            return porId;
        } catch (error) {
            return {};
        }
    };

    const eventosPorId = leerEventosData();

    const mostrarFila = (nombre, valor) => {
        const fila = modalInfoEl.querySelector('[data-info-fila="' + nombre + '"]');
        if (fila) fila.hidden = !valor;
    };

    const soloDigitos = (texto) => (texto || "").replace(/\D/g, "");

    const ICONOS_ENLACE = {
        telefono: "bi-telephone-fill",
        whatsapp: "bi-whatsapp",
        correo: "bi-envelope-fill",
        sitio_web: "bi-globe2",
        facebook: "bi-facebook",
        instagram: "bi-instagram",
    };

    const construirEnlacesContacto = (evento) => {
        const enlaces = [];
        if (evento.telefono) enlaces.push({ tipo: "telefono", url: "tel:" + evento.telefono, label: "Llamar" });
        if (evento.whatsapp) enlaces.push({ tipo: "whatsapp", url: "https://wa.me/" + soloDigitos(evento.whatsapp), label: "WhatsApp" });
        if (evento.correo) enlaces.push({ tipo: "correo", url: "mailto:" + evento.correo, label: "Correo" });
        if (evento.sitio_web) enlaces.push({ tipo: "sitio_web", url: evento.sitio_web, label: "Sitio web" });
        if (evento.facebook) enlaces.push({ tipo: "facebook", url: evento.facebook, label: "Facebook" });
        if (evento.instagram) enlaces.push({ tipo: "instagram", url: evento.instagram, label: "Instagram" });
        return enlaces;
    };

    const pintarTags = (tags) => {
        const contenedor = modalInfoEl.querySelector("[data-info-tags]");
        contenedor.replaceChildren();

        // Iconos oficiales del módulo (R74, sección 22-23): sin mapa
        // hardcodeado en JS — el backend ya resuelve icono_archivo con el
        // mismo mapeo que usan los filtros (ICONOS_EXPERIENCIA + static()).
        // Prioridad 1: archivo propio; prioridad 2: Bootstrap Icon.
        (tags || []).forEach((tag) => {
            const chip = document.createElement("span");
            chip.className = "ev-chip ev-chip--info";

            if (tag.icono_archivo) {
                const img = document.createElement("img");
                img.src = tag.icono_archivo;
                img.alt = "";
                img.className = "ev-chip__icono";
                img.setAttribute("aria-hidden", "true");
                chip.appendChild(img);
            } else if (tag.icono_bootstrap) {
                const icono = document.createElement("i");
                // .className nunca interpreta el valor como HTML (a diferencia de
                // innerHTML): un icono_bootstrap con caracteres inesperados solo
                // produce una clase inválida/sin efecto, nunca inyección.
                icono.className = "bi " + tag.icono_bootstrap;
                icono.setAttribute("aria-hidden", "true");
                chip.appendChild(icono);
            }

            chip.appendChild(document.createTextNode(tag.nombre));
            contenedor.appendChild(chip);
        });
    };

    const pintarRecomendaciones = (evento) => {
        const contenedor = modalInfoEl.querySelector("[data-info-recomendaciones]");
        contenedor.replaceChildren();

        const items = evento.recomendaciones_items || [];

        // Estructuradas (R74, sección 41-49): card con icono/título/descripción,
        // mismo patrón que Turismo (dl-reco-item). Sin parsear texto legado
        // (nunca `.split("\n")`): si no hay ninguna activa, se cae al texto
        // libre tal cual (fallback, sección 46).
        if (items.length > 0) {
            items.forEach((item) => {
                const articulo = document.createElement("article");
                articulo.className = "ev-reco-item";

                // Prioridad de icono (R6-R8 del encargo V3): SVG propio primero,
                // Bootstrap Icon como fallback, icono neutro si ambos faltan.
                // Nunca un mapa título->icono hardcodeado aquí: el icono siempre
                // viene del payload (datos_modal_para en views.py).
                const iconoWrap = document.createElement("span");
                iconoWrap.className = "ev-reco-icon";
                iconoWrap.setAttribute("aria-hidden", "true");
                if (item.icono_archivo) {
                    const img = document.createElement("img");
                    img.src = item.icono_archivo;
                    img.alt = "";
                    img.loading = "lazy";
                    iconoWrap.appendChild(img);
                } else {
                    const icono = document.createElement("i");
                    icono.className = item.icono_bootstrap || "bi bi-lightbulb";
                    iconoWrap.appendChild(icono);
                }
                articulo.appendChild(iconoWrap);

                // Sin wrapper <div> a propósito (V3.1): título y descripción son
                // hijos DIRECTOS del grid de `.ev-reco-item` (no anidados), porque
                // `grid-column`/`grid-row` en CSS solo puede posicionar hijos
                // directos de un grid container — así la descripción puede
                // ocupar el ancho completo en su propia fila en mobile
                // (agenda-eventos.css) sin quedar encajonada en la columna
                // estrecha del texto junto al icono.
                const titulo = document.createElement("h4");
                titulo.textContent = item.titulo;
                articulo.appendChild(titulo);

                const descripcion = document.createElement("p");
                descripcion.textContent = item.descripcion;
                articulo.appendChild(descripcion);

                contenedor.appendChild(articulo);
            });
            return;
        }

        if (evento.recomendaciones) {
            const parrafo = document.createElement("p");
            parrafo.className = "ev-modal__texto";
            parrafo.textContent = evento.recomendaciones;
            contenedor.appendChild(parrafo);
        }
    };

    const pintarEnlaces = (enlaces) => {
        const lista = modalInfoEl.querySelector("[data-info-enlaces]");
        lista.replaceChildren();

        enlaces.forEach((enlace) => {
            const a = document.createElement("a");
            a.href = enlace.url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.title = enlace.label;

            const icono = document.createElement("i");
            icono.className = "bi " + (ICONOS_ENLACE[enlace.tipo] || "bi-link-45deg");
            icono.setAttribute("aria-hidden", "true");
            a.appendChild(icono);
            a.appendChild(document.createTextNode(" " + enlace.label));

            lista.appendChild(a);
        });
    };

    const construirSlides = (evento) => {
        const imagenes = [];
        if (evento.imagen_principal) {
            imagenes.push({ src: evento.imagen_principal, alt: evento.texto_alt_imagen || evento.nombre, lazy: false });
        }
        (evento.galeria || []).forEach((img) => {
            imagenes.push({ src: img.imagen, alt: img.texto_alt || evento.nombre, lazy: true });
        });
        return imagenes;
    };

    const actualizarContador = (swiper) => {
        const contadorEl = modalInfoEl.querySelector("[data-info-contador]");
        if (!contadorEl) return;
        // Con 1 sola imagen "1/1" no aporta información (R74, sección 8):
        // se oculta igual que con 0 imágenes.
        contadorEl.hidden = swiper.slides.length <= 1;
        contadorEl.textContent = `${swiper.activeIndex + 1}/${swiper.slides.length}`;
    };

    // Lifecycle del carrusel, en dos funciones con una sola responsabilidad
    // cada una (nunca se construye Swiper con el modal oculto):
    //   pintarGaleria()         → solo DOM: wrapper, slides, fallback,
    //                             flechas/paginación mostradas u ocultas.
    //   inicializarSwiperGaleria() → solo Swiper: se llama exclusivamente
    //                             desde `shown.bs.modal`, cuando el modal ya
    //                             tiene su tamaño final. Antes de este punto
    //                             `.ev-modal-swiper`/`.ev-modal-swiper-pagination`
    //                             están en `visibility:hidden` (CSS, clase
    //                             `is-ready`) para que el usuario nunca vea
    //                             el wrapper sin inicializar.
    // El destroy vive únicamente en `hidden.bs.modal`.
    let galeriaPendiente = false;

    const pintarGaleria = (evento) => {
        const wrapper = modalInfoEl.querySelector("[data-info-swiper-wrapper]");
        const fallback = modalInfoEl.querySelector("[data-info-imagen-fallback]");
        const swiperEl = modalInfoEl.querySelector("[data-info-swiper]");
        const prevBtn = modalInfoEl.querySelector("[data-info-swiper-prev]");
        const nextBtn = modalInfoEl.querySelector("[data-info-swiper-next]");
        const zoomBtn = modalInfoEl.querySelector("[data-info-swiper-zoom]");
        const contadorEl = modalInfoEl.querySelector("[data-info-contador]");

        galeriaPendiente = false;
        wrapper.replaceChildren();

        const imagenes = construirSlides(evento);

        if (imagenes.length === 0) {
            swiperEl.hidden = true;
            prevBtn.hidden = true;
            nextBtn.hidden = true;
            paginationEl.hidden = true;
            if (playBtn) playBtn.hidden = true;
            zoomBtn.hidden = true;
            contadorEl.hidden = true;
            fallback.hidden = false;
            return;
        }

        fallback.hidden = true;
        swiperEl.hidden = false;
        zoomBtn.hidden = false;

        imagenes.forEach((imagen) => {
            const slide = document.createElement("div");
            slide.className = "swiper-slide";
            const img = document.createElement("img");
            img.src = imagen.src;
            img.alt = imagen.alt;
            if (imagen.lazy) img.loading = "lazy";
            slide.appendChild(img);
            wrapper.appendChild(slide);
        });

        // Contador (R74, sección 8): con una sola imagen, sin dos+ imágenes no
        // aporta información — se oculta (ya lo hacía actualizarContador). Con
        // 1 sola imagen tampoco hay nada que reproducir/pausar ni bullets que
        // mostrar: mismo criterio que antes para prev/next/pagination.
        const haySoloUna = imagenes.length === 1;
        prevBtn.hidden = haySoloUna;
        nextBtn.hidden = haySoloUna;
        paginationEl.hidden = haySoloUna;
        if (playBtn) playBtn.hidden = haySoloUna || prefiereReducirMovimiento;

        galeriaPendiente = true;
    };

    const inicializarSwiperGaleria = () => {
        if (!galeriaPendiente || typeof Swiper === "undefined") return;
        galeriaPendiente = false;

        const swiperEl = modalInfoEl.querySelector("[data-info-swiper]");
        const prevBtn = modalInfoEl.querySelector("[data-info-swiper-prev]");
        const nextBtn = modalInfoEl.querySelector("[data-info-swiper-next]");

        const marcarListo = (swiper) => {
            swiperEl.classList.add("is-ready");
            paginationEl.classList.add("is-ready");
            actualizarContador(swiper);
        };

        autoplayPausadoPorUsuario = false;
        enTransicion = false;

        swiperInstance = new Swiper(swiperEl, {
            loop: false,
            // Carrusel apilado tipo "card deck" (R74, sección 9-10): la
            // imagen activa al frente, las siguientes ligeramente detrás con
            // offset/rotación sutiles. `slideShadows: false` porque la
            // profundidad ya la aporta el box-shadow propio de cada slide
            // (agenda-eventos.css), sin duplicar sombra.
            effect: "cards",
            cardsEffect: {
                perSlideOffset: 8,
                perSlideRotate: 1.5,
                rotate: true,
                slideShadows: false,
            },
            grabCursor: true,
            slidesPerView: 1,
            spaceBetween: 0,
            speed: prefiereReducirMovimiento ? 0 : 400,
            keyboard: { enabled: true },
            a11y: {
                prevSlideMessage: "Imagen anterior",
                nextSlideMessage: "Imagen siguiente",
                paginationBulletMessage: "Ir a la imagen {{index}}",
            },
            // Siempre se configuran (nunca `undefined`): Swiper espera un objeto
            // real para estos módulos y falla al destruirse si se le pasa
            // `undefined` en vez de omitir la clave. La visibilidad de los
            // controles ya se controla arriba con `hidden` cuando hay 1 sola imagen.
            navigation: { nextEl: nextBtn, prevEl: prevBtn },
            // Bullets con progreso/timer (R74, sección 17): `renderBullet`
            // inyecta la barra de progreso propia en cada bullet — mismo
            // recurso que `.detalle-swiper-pagination` en Establecimientos,
            // adaptado al namespace `ev-` en vez de duplicar el CSS/JS ahí.
            pagination: {
                el: paginationEl,
                clickable: true,
                renderBullet: (index, className) =>
                    `<span class="${className}"><span class="ev-modal-bullet-progress"></span></span>`,
            },
            on: {
                init: (swiper) => {
                    marcarListo(swiper);
                    marcarReproduciendo();
                    iniciarProgreso(swiper, 0);
                },
                slideChange: actualizarContador,
                slideChangeTransitionStart: () => {
                    enTransicion = true;
                    cancelarProgreso();
                },
                slideChangeTransitionEnd: (swiper) => {
                    enTransicion = false;
                    resetearProgresoSlideActual();
                    if (!autoplayPausadoPorUsuario) iniciarProgreso(swiper, 0);
                },
            },
        });
    };

    // Accordion exclusivo: al abrir una sección, las demás se pliegan solas
    // (comportamiento nativo de <details> es independiente por elemento, así
    // que el "solo una abierta a la vez" se agrega con un listener por
    // sección). Se registra una sola vez — los <details> son los mismos
    // nodos del DOM en cada apertura del modal, solo cambia su contenido.
    const accordionItems = Array.from(modalInfoEl.querySelectorAll(".ev-accordion__item"));
    accordionItems.forEach((item) => {
        item.addEventListener("toggle", () => {
            if (!item.open) return;
            accordionItems.forEach((otro) => {
                if (otro !== item) otro.open = false;
            });
        });
    });

    const abrirEvento = (eventoId) => {
        const evento = eventosPorId[eventoId];
        if (!evento) return;

        // Todas las secciones plegadas cada vez que se abre el modal (para
        // el evento que sea): un acordeón que quedó abierto en la visita
        // anterior no debe seguir abierto al mirar otro evento.
        accordionItems.forEach((item) => { item.open = false; });

        modalInfoEl.querySelector("[data-info-nombre]").textContent = evento.nombre || "";
        modalInfoEl.querySelector("[data-info-categoria]").textContent = evento.categoria || "";

        pintarGaleria(evento);

        const fechaTexto = evento.fecha_detalle || "";
        modalInfoEl.querySelector("[data-info-fecha]").textContent = fechaTexto;
        mostrarFila("fecha", fechaTexto);

        modalInfoEl.querySelector("[data-info-ubicacion]").textContent = evento.ubicacion || "";
        mostrarFila("ubicacion", evento.ubicacion);

        modalInfoEl.querySelector("[data-info-costo]").textContent = evento.costo || "";
        mostrarFila("costo", evento.costo);

        const tags = evento.tags || [];
        pintarTags(tags);
        mostrarFila("tags", tags.length > 0);

        modalInfoEl.querySelector("[data-info-descripcion]").textContent = evento.descripcion || "";
        mostrarFila("descripcion", evento.descripcion);

        modalInfoEl.querySelector("[data-info-contexto]").textContent = evento.contexto_cultural || "";
        mostrarFila("contexto", evento.contexto_cultural);

        pintarRecomendaciones(evento);
        const hayRecomendaciones = (evento.recomendaciones_items || []).length > 0 || Boolean(evento.recomendaciones);
        mostrarFila("recomendaciones", hayRecomendaciones);

        modalInfoEl.querySelector("[data-info-organizador]").textContent = evento.organizador || "";
        const enlaces = construirEnlacesContacto(evento);
        pintarEnlaces(enlaces);
        mostrarFila("organizador", Boolean(evento.organizador) || enlaces.length > 0);

        const modal = obtenerModalBootstrap(modalInfoEl);
        if (modal) modal.show();
    };

    document.addEventListener("click", (event) => {
        const boton = event.target.closest("[data-abrir-evento]");
        if (boton) {
            abrirEvento(boton.dataset.eventoId);
        }
    });
})();
