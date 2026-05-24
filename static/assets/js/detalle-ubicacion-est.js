(function () {
    "use strict";

    /* ─── Utilidades ─── */

    function text(value) {
        return value ? String(value).trim() : "";
    }

    function normaliseCoord(value) {
        return text(value).replace(",", ".");
    }

    function buildUrls(query) {
        var q = text(query);
        if (!q) return { open: "", route: "", embed: "" };

        var enc = encodeURIComponent(q);

        return {
            open: "https://www.google.com/maps/search/?api=1&query=" + enc,
            route: "https://www.google.com/maps/dir/?api=1&destination=" + enc,
            embed: "https://www.google.com/maps?q=" + enc + "&z=17&hl=es&output=embed",
        };
    }

    function buildLocationData(source) {
        var d = source.dataset || {};
        var lat = normaliseCoord(d.lat);
        var lng = normaliseCoord(d.lng);
        var direccion = text(d.direccion);
        var query = lat && lng ? lat + "," + lng : direccion;
        var fallback = buildUrls(query);

        return {
            nombre: text(d.nombre) || "Local principal",
            label: text(d.label) || (d.esPrincipal === "true" ? "Local principal" : "Sucursal"),
            direccion: direccion,
            referencia: text(d.referencia),
            horario: text(d.horario),
            esPrincipal: d.esPrincipal === "true",
            openUrl: text(d.openUrl) || fallback.open,
            routeUrl: text(d.routeUrl) || fallback.route,
            embedUrl: text(d.embedUrl) || fallback.embed,
        };
    }

    /* ─── DOM helpers ─── */

    function qs(root, sel) {
        return root.querySelector(sel);
    }

    function qsa(root, sel) {
        return Array.prototype.slice.call(root.querySelectorAll(sel));
    }

    function setText(root, sel, val) {
        qsa(root, sel).forEach(function (el) {
            el.textContent = val;
        });
    }

    function toggleRow(root, name, value) {
        qsa(root, '[data-detalle-ubicacion-row="' + name + '"]').forEach(function (row) {
            row.classList.toggle("is-empty", !value);
        });
    }

    /* ─── Google Maps ─── */

    function updateMap(root, data) {
        var iframe = qs(root, "[data-detalle-ubicacion-map]");
        if (iframe && data.embedUrl && iframe.src !== data.embedUrl) {
            iframe.src = data.embedUrl;
        }
    }

    function updateLinks(root, data) {
        qsa(root, "[data-detalle-ubicacion-open]").forEach(function (el) {
            el.href = data.openUrl || "#";
        });

        qsa(root, "[data-detalle-ubicacion-route]").forEach(function (el) {
            el.href = data.routeUrl || "#";
        });
    }

    function refreshRouteLink(root, baseRouteUrl) {
        var link = qs(root, "[data-du-route-link]");
        var modeBtn = qs(root, ".du-mode.is-active");

        if (!link || !baseRouteUrl) return;

        var mode = modeBtn ? (modeBtn.dataset.duMode || "walking") : "walking";
        var url = baseRouteUrl.replace(/&travelmode=[^&]*/g, "");

        link.href = url + "&travelmode=" + mode;
    }

    /* ─── Actualizar contenido ─── */

    function updateLocation(root, data) {
        var dir = data.direccion || "Dirección no registrada";
        var ref = data.referencia || "";
        var hor = data.horario || "";

        setText(root, "[data-detalle-ubicacion-badge]", data.label);
        setText(root, "[data-detalle-ubicacion-panel-direccion]", dir);

        setText(root, "[data-detalle-ubicacion-nombre]", data.nombre);
        setText(root, "[data-detalle-ubicacion-direccion]", dir);
        setText(root, "[data-detalle-ubicacion-referencia]", ref);
        setText(root, "[data-detalle-ubicacion-horario]", hor);

        var pill = qs(root, "[data-du-branch-pill]");
        if (pill) {
            if (data.esPrincipal) {
                pill.removeAttribute("hidden");
            } else {
                pill.setAttribute("hidden", "");
            }
        }

        toggleRow(root, "direccion", data.direccion);
        toggleRow(root, "referencia", data.referencia);
        toggleRow(root, "horario", data.horario);

        var destInput = qs(root, "[data-du-dest]");
        if (destInput) {
            destInput.value = dir;
        }

        updateMap(root, data);
        updateLinks(root, data);
        refreshRouteLink(root, data.routeUrl);
    }

    /* ─── Panel desplegable de ruta ─── */

    function openDirections(root) {
        var ctaDefault = qs(root, "[data-du-cta-default]");
        var dirPanel = qs(root, "[data-du-directions]");

        if (ctaDefault) {
            ctaDefault.setAttribute("hidden", "");
        }

        if (dirPanel) {
            dirPanel.removeAttribute("hidden");
        }

        root.classList.add("is-route-open");
    }

    function closeDirections(root) {
        var ctaDefault = qs(root, "[data-du-cta-default]");
        var dirPanel = qs(root, "[data-du-directions]");

        if (dirPanel) {
            dirPanel.setAttribute("hidden", "");
        }

        if (ctaDefault) {
            ctaDefault.removeAttribute("hidden");
        }

        root.classList.remove("is-route-open");
    }

    function initDirectionsPanel(root, getRouteUrl) {
        var showBtn = qs(root, "[data-du-show-dir]");
        var hideBtn = qs(root, "[data-du-hide-dir]");
        var modeBtns = qsa(root, ".du-mode");

        if (!showBtn || !hideBtn) return;

        showBtn.addEventListener("click", function () {
            openDirections(root);
            refreshRouteLink(root, getRouteUrl());
        });

        hideBtn.addEventListener("click", function () {
            closeDirections(root);
        });

        modeBtns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                modeBtns.forEach(function (b) {
                    b.classList.remove("is-active");
                });

                btn.classList.add("is-active");
                refreshRouteLink(root, getRouteUrl());
            });
        });
    }

    /* ─── Tabs de sucursales ─── */

    function setActiveTab(tabs, selected) {
        tabs.forEach(function (tab) {
            var active = tab === selected;
            tab.classList.toggle("is-active", active);
            tab.setAttribute("aria-pressed", active ? "true" : "false");
        });
    }

    /* ─── Inicialización ─── */

    function initSection(root) {
        var currentRouteUrl = root.dataset.routeUrl || "";

        var tabs = qsa(root, "[data-detalle-ubicacion-sucursal]");
        var activeTab = tabs.find(function (t) {
            return t.classList.contains("is-active");
        });

        var initData = buildLocationData(activeTab || root);
        currentRouteUrl = initData.routeUrl;
        updateLocation(root, initData);

        tabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                setActiveTab(tabs, tab);

                var data = buildLocationData(tab);
                currentRouteUrl = data.routeUrl;

                updateLocation(root, data);
                closeDirections(root);
            });
        });

        initDirectionsPanel(root, function () {
            return currentRouteUrl;
        });
    }

    function init() {
        qsa(document, "[data-detalle-ubicacion]").forEach(initSection);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();