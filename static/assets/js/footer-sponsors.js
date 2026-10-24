/* Franja de sponsors del footer: carrusel circular de uno en uno, solo si hay más sponsors que los visibles.
   Cantidad visible y pausa: atributos data-max-desktop / data-max-movil / data-intervalo en templates/partials/footer.html.
   Sin librerías. Con prefers-reduced-motion no hay carrusel (el CSS muestra todos los logos). */
(function () {
    var raiz = document.querySelector("[data-vi-sponsors]");
    if (!raiz || !window.matchMedia) return;

    var pista = raiz.querySelector(".vi-sponsors__track");
    var originales = Array.prototype.slice.call(pista.children);
    var total = originales.length;
    var maxDesktop = parseInt(raiz.dataset.maxDesktop, 10) || 5;
    var maxMovil = parseInt(raiz.dataset.maxMovil, 10) || 3;
    var intervalo = parseInt(raiz.dataset.intervalo, 10) || 3500;
    var movil = window.matchMedia("(max-width: 599px)");
    var sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)");

    var posicion = 0;
    var temporizador = null;
    var pausado = false;
    var clones = [];

    function visibles() { return movil.matches ? maxMovil : maxDesktop; }
    function activo() { return total > visibles() && !sinMovimiento.matches; }

    function paso() {
        if (originales.length < 2) return 0;
        return originales[1].getBoundingClientRect().left - originales[0].getBoundingClientRect().left;
    }

    function mover(conTransicion) {
        pista.style.transition = conTransicion ? "" : "none";
        pista.style.transform = "translateX(" + (-posicion * paso()) + "px)";
    }

    function quitarClones() {
        clones.forEach(function (c) { c.remove(); });
        clones = [];
    }

    function detener() {
        if (temporizador) { window.clearInterval(temporizador); temporizador = null; }
    }

    function reiniciar() {
        posicion = 0;
        mover(false);
        void pista.offsetWidth;  // fuerza el reflujo antes de restaurar la transición
        pista.style.transition = "";
    }

    function avanzar() {
        // Si el paso anterior terminó sobre los clones (idénticos a los primeros), se vuelve al inicio sin animar.
        // Así el bucle no depende solo de `transitionend` (que no se dispara si la pestaña está en segundo plano).
        if (posicion >= total) reiniciar();
        posicion += 1;
        mover(true);
    }

    function preparar() {
        detener();
        quitarClones();
        posicion = 0;
        pista.style.transition = "none";
        pista.style.transform = "";
        raiz.classList.remove("is-carrusel");
        if (!activo()) return;

        raiz.classList.add("is-carrusel");
        // clones de los primeros N: el final enlaza con el principio sin salto visible (bucle circular)
        for (var i = 0; i < visibles(); i++) {
            var clon = originales[i % total].cloneNode(true);
            clon.setAttribute("aria-hidden", "true");
            Array.prototype.forEach.call(clon.querySelectorAll("a"), function (a) { a.setAttribute("tabindex", "-1"); });
            pista.appendChild(clon);
            clones.push(clon);
        }
        temporizador = window.setInterval(function () {
            if (!pausado && !document.hidden) avanzar();
        }, intervalo);
    }

    pista.addEventListener("transitionend", function () {
        if (posicion >= total) reiniciar();  // estamos sobre los clones: volver al inicio real sin animar
    });

    raiz.addEventListener("mouseenter", function () { pausado = true; });
    raiz.addEventListener("mouseleave", function () { pausado = false; });
    raiz.addEventListener("focusin", function () { pausado = true; });
    raiz.addEventListener("focusout", function () { pausado = false; });

    function alCambiar() { preparar(); }
    [movil, sinMovimiento].forEach(function (mq) {
        if (mq.addEventListener) mq.addEventListener("change", alCambiar); else mq.addListener(alCambiar);
    });
    var redimension = null;
    window.addEventListener("resize", function () {
        window.clearTimeout(redimension);
        redimension = window.setTimeout(function () { if (activo()) mover(false); }, 150);
    });

    preparar();
})();
