/* Django Admin de sedes: el segundo turno de cada bloque de horario aparece solo si se pide
   (o si ya tiene datos / errores). Ocultar no borra nada: los valores se limpian únicamente
   al guardar, según el estado final del bloque. Sin dependencias; no se carga en el sitio público. */
(function () {
    "use strict";

    var BLOQUES = ["lv", "sa", "do"];

    function envoltorio(fila, campo) {
        var caja = fila.querySelector(".fieldBox.field-" + campo);
        return caja ? caja.parentElement : null;
    }

    function entrada(clave, sufijo) {
        return document.getElementById("id_" + clave + "_" + sufijo);
    }

    function mostrar(elemento, visible) {
        if (elemento) elemento.classList.toggle("sede-oculto", !visible);
    }

    function iniciarBloque(clave) {
        var estado = entrada(clave, "estado");
        if (!estado) return null;
        var fila = estado.closest(".form-row");
        var contenedor = fila && fila.querySelector(".form-multiline");
        var d1 = envoltorio(fila, clave + "_d1"), h1 = envoltorio(fila, clave + "_h1");
        var d2 = envoltorio(fila, clave + "_d2"), h2 = envoltorio(fila, clave + "_h2");
        if (!contenedor || !d1 || !h1 || !d2 || !h2) return null;
        fila.classList.add("sede-bloque-horario");

        function conErrores(caja) { return !!caja.querySelector(".errorlist"); }
        var segundo = !!(entrada(clave, "d2").value || entrada(clave, "h2").value || conErrores(d2) || conErrores(h2));

        var contenedorBoton = document.createElement("div");
        var boton = document.createElement("button");
        boton.type = "button";
        boton.className = "sede-turno-boton";
        contenedorBoton.appendChild(boton);
        contenedor.appendChild(contenedorBoton);

        function pintar() {
            var abierto = estado.value === "abierto";
            mostrar(d1, abierto);
            mostrar(h1, abierto);
            mostrar(d2, abierto && segundo);
            mostrar(h2, abierto && segundo);
            mostrar(contenedorBoton, abierto);
            boton.textContent = segundo ? "Quitar segundo turno" : "+ Añadir otro turno";
            boton.setAttribute("aria-expanded", segundo ? "true" : "false");
        }

        boton.addEventListener("click", function () {
            segundo = !segundo;
            pintar();
            if (segundo) entrada(clave, "d2").focus();
        });
        estado.addEventListener("change", pintar);
        pintar();

        // Al guardar: «Sin indicar»/«Cerrado» no llevan horas y un segundo turno quitado se vacía.
        return function limpiarAlGuardar() {
            var abierto = estado.value === "abierto";
            ["d1", "h1"].forEach(function (s) { if (!abierto) entrada(clave, s).value = ""; });
            ["d2", "h2"].forEach(function (s) { if (!abierto || !segundo) entrada(clave, s).value = ""; });
        };
    }

    function iniciar() {
        var limpiezas = BLOQUES.map(iniciarBloque).filter(Boolean);
        if (!limpiezas.length) return;
        var formulario = document.getElementById("id_" + BLOQUES[0] + "_estado").form;
        formulario.addEventListener("submit", function () {
            limpiezas.forEach(function (limpiar) { limpiar(); });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
