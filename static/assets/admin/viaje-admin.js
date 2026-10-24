/* Admin Viaje Informado: solo mejoras visuales. No toca formularios ni guardado. */
document.addEventListener("change", function (e) {
    // Desplegables de filtro: navegan a la URL (query string) que Django ya calculó.
    if (e.target.matches("select[data-vi-nav]")) {
        window.location.search = e.target.value;
    }
});

// En pantallas estrechas el sidebar es un panel superpuesto: arranca cerrado y se abre con el botón ☰.
// No usa (ni modifica) la preferencia de escritorio que Django guarda en localStorage.
(function () {
    var narrow = window.matchMedia("(max-width: 1023px)");
    var main = document.getElementById("main");
    var button = document.getElementById("toggle-nav-sidebar");
    if (!main || !button) return;
    window.addEventListener("load", function () {
        if (narrow.matches) main.classList.remove("shifted");
    });
    button.addEventListener("click", function (e) {
        if (!narrow.matches) return;
        e.stopImmediatePropagation();
        main.classList.toggle("shifted");
        if (window.viSidebarAjustar) window.requestAnimationFrame(window.viSidebarAjustar);
    }, true);
})();

// Tema: Django cicla auto -> claro -> oscuro (con SO oscuro, "oscuro -> auto" no cambia nada y pide 2 clics).
// Aquí un clic alterna claro <-> oscuro según el tema EFECTIVO; usa el mismo almacenamiento nativo (localStorage "theme").
document.addEventListener("click", function (e) {
    if (!e.target.closest(".theme-toggle")) return;
    e.stopImmediatePropagation();
    var root = document.documentElement;
    var actual = root.dataset.theme;
    if (actual !== "light" && actual !== "dark") {
        actual = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    var nuevo = actual === "dark" ? "light" : "dark";
    root.dataset.theme = nuevo;
    try { localStorage.setItem("theme", nuevo); } catch (err) { /* sin almacenamiento: solo esta página */ }
}, true);

// Sidebar superpuesto (<=1023px): se cierra con Escape o al pulsar fuera.
(function () {
    var narrow = window.matchMedia("(max-width: 1023px)");
    var main = document.getElementById("main");
    if (!main) return;
    function cerrar() { if (narrow.matches) main.classList.remove("shifted"); }
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") cerrar(); });
    document.addEventListener("click", function (e) {
        if (!e.target.closest("#nav-sidebar, #toggle-nav-sidebar")) cerrar();
    });
})();

// Filtros del listado: plegables en móvil (<=767px; el CSS los oculta solo ahí).
(function () {
    var panel = document.getElementById("changelist-filter");
    var titulo = panel && panel.querySelector("h2");
    if (!titulo || !window.matchMedia("(max-width: 767px)").matches) return;
    panel.classList.add("vi-filter-collapsed");
    titulo.setAttribute("role", "button");
    titulo.setAttribute("tabindex", "0");
    titulo.setAttribute("aria-expanded", "false");
    function alternar() {
        var cerrado = panel.classList.toggle("vi-filter-collapsed");
        titulo.setAttribute("aria-expanded", cerrado ? "false" : "true");
    }
    titulo.addEventListener("click", alternar);
    titulo.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); alternar(); }
    });
})();

// Sidebar: recuerda el scroll de la lista entre pantallas (sessionStorage) y, si no hay posición válida,
// muestra juntos el encabezado de la app y el modelo activo. Solo posiciona; no toca enlaces ni formularios.
(function () {
    var KEY = "vi_admin_sidebar_scroll";
    var caja = document.getElementById("vi-nav-scroll");
    if (!caja) return;
    var buscador = document.getElementById("nav-filter");

    function visible() { return caja.clientHeight > 0; }
    function top(el) { return el.getBoundingClientRect().top - caja.getBoundingClientRect().top + caja.scrollTop; }
    function activoVisible() {
        var modelo = caja.querySelector("tr.current-model");
        if (!modelo) return true;
        var t = top(modelo);
        return t >= caja.scrollTop && t + modelo.offsetHeight <= caja.scrollTop + caja.clientHeight;
    }
    function aActivo() {
        var modelo = caja.querySelector("tr.current-model");
        var app = modelo ? modelo.closest(".module") : caja.querySelector(".current-app");
        var cab = app && app.querySelector("caption");
        if (!cab) return;
        var arriba = top(cab) - 8;
        var abajo = modelo ? top(modelo) + modelo.offsetHeight : top(cab) + cab.offsetHeight;
        if (top(cab) >= caja.scrollTop && abajo <= caja.scrollTop + caja.clientHeight) return;  // ya se ve: no mover
        if (abajo - arriba > caja.clientHeight) arriba = abajo - caja.clientHeight + 8;  // prioriza el modelo
        caja.scrollTop = Math.max(arriba, 0);
    }
    function ajustar() {
        if (!visible()) return;
        if (buscador && buscador.value) return;  // buscando: no mover
        var guardado = null;
        try { guardado = sessionStorage.getItem(KEY); } catch (e) { /* sin sessionStorage */ }
        if (guardado !== null) caja.scrollTop = parseInt(guardado, 10) || 0;
        if (guardado === null || !activoVisible()) aActivo();
    }
    window.viSidebarAjustar = ajustar;

    caja.addEventListener("scroll", function () {
        if (!visible()) return;
        try { sessionStorage.setItem(KEY, String(caja.scrollTop)); } catch (e) { /* ignorar */ }
    });
    if (buscador) buscador.addEventListener("input", function () {
        if (!buscador.value) window.requestAnimationFrame(aActivo);  // búsqueda limpiada: volver al módulo activo
    });
    var boton = document.getElementById("toggle-nav-sidebar");
    if (boton) boton.addEventListener("click", function () { window.setTimeout(ajustar, 0); });
    window.addEventListener("load", ajustar);
})();

// Tablas del listado: centra (cabecera y celdas) las columnas de booleanos y números cortos.
(function () {
    var tabla = document.getElementById("result_list");
    if (!tabla || !tabla.tHead || !tabla.tBodies[0]) return;
    var filas = Array.prototype.slice.call(tabla.tBodies[0].rows);
    var cabeceras = tabla.tHead.rows[0].cells;
    // las flechas de orden quedan pegadas a continuación del nombre de la columna (solo cambia su posición en el DOM)
    Array.prototype.forEach.call(cabeceras, function (th) {
        var orden = th.querySelector(".sortoptions");
        if (orden) th.appendChild(orden);
    });
    for (var i = 0; i < cabeceras.length; i++) {
        if (cabeceras[i].classList.contains("action-checkbox-column")) continue;
        var vacias = 0, centrables = 0;
        filas.forEach(function (fila) {
            var celda = fila.cells[i];
            if (!celda) return;
            var texto = celda.textContent.trim();
            if (celda.querySelector("img[src*='icon-']") && !texto) centrables++;
            else if (/^[-–—]$|^[\d.,%\s]{1,8}$/.test(texto) && texto) centrables++;
            else if (!texto) vacias++;
        });
        if (centrables && centrables + vacias === filas.length) {
            cabeceras[i].classList.add("vi-center");
            filas.forEach(function (fila) { if (fila.cells[i]) fila.cells[i].classList.add("vi-center"); });
        }
    }
})();

// Filtros: resalta los <select> con un valor distinto del primero ("Todos").
Array.prototype.forEach.call(document.querySelectorAll("#changelist-filter .vi-filter select"), function (sel) {
    if (sel.selectedIndex > 0) sel.closest(".vi-filter").classList.add("is-active");
});
