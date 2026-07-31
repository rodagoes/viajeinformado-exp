(() => {
    "use strict";

    const initComoLlegar = () => {
        const selector = document.querySelector("[data-como-llegar-selector]");
        const tabs = selector
            ? Array.from(selector.querySelectorAll('[role="tab"][data-via]'))
            : [];

        const panels = Array.from(
            document.querySelectorAll('.cl-panel[role="tabpanel"]')
        );

        const validVias = new Set(["terrestre", "aerea"]);

        const activateVia = (via, updateUrl = true) => {
            if (!validVias.has(via)) {
                via = "terrestre";
            }

            tabs.forEach((tab) => {
                const isActive = tab.dataset.via === via;

                tab.classList.toggle("is-active", isActive);
                tab.setAttribute("aria-selected", String(isActive));
                tab.tabIndex = isActive ? 0 : -1;
            });

            panels.forEach((panel) => {
                panel.hidden = panel.id !== `cl-panel-${via}`;
            });

            if (updateUrl) {
                const url = new URL(window.location.href);
                url.searchParams.set("via", via);
                window.history.replaceState({}, "", url);
            }
        };

        tabs.forEach((tab, index) => {
            tab.addEventListener("click", () => {
                activateVia(tab.dataset.via);
            });

            tab.addEventListener("keydown", (event) => {
                let nextIndex = null;

                if (event.key === "ArrowRight") {
                    nextIndex = (index + 1) % tabs.length;
                } else if (event.key === "ArrowLeft") {
                    nextIndex = (index - 1 + tabs.length) % tabs.length;
                } else if (event.key === "Home") {
                    nextIndex = 0;
                } else if (event.key === "End") {
                    nextIndex = tabs.length - 1;
                }

                if (nextIndex === null) {
                    return;
                }

                event.preventDefault();

                const nextTab = tabs[nextIndex];
                nextTab.focus();
                activateVia(nextTab.dataset.via);
            });
        });

        const requestedVia = new URLSearchParams(window.location.search).get("via");
        activateVia(validVias.has(requestedVia) ? requestedVia : "terrestre", false);

        /* Mapa: fallback limpio si el recurso no carga. */
        const mapImage = document.querySelector("[data-mapa-accesos]");
        const mapFallback = document.querySelector("[data-mapa-fallback]");

        if (mapImage && mapFallback) {
            const showFallback = () => {
                mapImage.hidden = true;
                mapFallback.hidden = false;
            };

            mapImage.addEventListener("error", showFallback, { once: true });

            if (mapImage.complete && mapImage.naturalWidth === 0) {
                showFallback();
            }
        }

        /* Móvil: mostrar tres rutas y expandir el resto. */
        const routesList = document.querySelector("[data-rutas-list]");
        const routesToggle = document.querySelector("[data-rutas-toggle]");

        if (routesList && routesToggle) {
            const extraRoutes = routesList.querySelectorAll(".cl-ruta--extra");

            if (extraRoutes.length > 0) {
                routesList.classList.add("is-collapsible");
                routesToggle.hidden = false;

                const label = routesToggle.querySelector(
                    "[data-rutas-toggle-label]"
                );

                routesToggle.addEventListener("click", () => {
                    const isExpanded = routesList.classList.toggle("is-expanded");

                    routesToggle.setAttribute(
                        "aria-expanded",
                        String(isExpanded)
                    );

                    if (label) {
                        label.textContent = isExpanded
                            ? "Ver menos rutas"
                            : "Ver todas las rutas";
                    }
                });
            }
        }

        const lottieContainers = document.querySelectorAll(
            "[data-consejo-lottie]"
        );

        if (window.lottie && lottieContainers.length > 0) {
            lottieContainers.forEach((container) => {
                const path = container.dataset.lottieSrc;

                if (!path || container.dataset.lottieReady === "true") {
                    return;
                }

                container.dataset.lottieReady = "true";

                const animation = window.lottie.loadAnimation({
                    container,
                    renderer: "svg",
                    loop: true,
                    autoplay: true,
                    path,
                    rendererSettings: {
                        preserveAspectRatio: "xMidYMid meet",
                    },
                });

                animation.addEventListener("DOMLoaded", () => {
                    container.classList.add("is-ready");
                });
            });
        }

    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initComoLlegar);
    } else {
        initComoLlegar();
    }
})();