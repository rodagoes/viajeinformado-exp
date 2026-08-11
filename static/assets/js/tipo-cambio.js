(() => {
    "use strict";

    const CARACTER_INVALIDO = /[^0-9.,]/;
    const PATRON_EDICION = /^\d+(?:[.,]\d{0,2})?$/;
    const PATRON_FINAL = /^(?:0|[1-9]\d*)(?:[.,]\d{1,2})?$/;
    const TIPOS_INSERCION = [
        "insertText",
        "insertReplacementText",
        "insertFromPaste",
        "insertFromDrop",
        "insertCompositionText",
    ];

    const leerTasa = (id) => {
        const el = document.getElementById(id);
        if (!el) return null;

        try {
            const valor = parseFloat(JSON.parse(el.textContent));
            return Number.isFinite(valor) ? valor : null;
        } catch (error) {
            return null;
        }
    };

    const formatearResultado = (valor) =>
        new Intl.NumberFormat("es-PE", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(valor);

    const construirCandidato = (input, texto) => {
        const inicio = input.selectionStart ?? input.value.length;
        const fin = input.selectionEnd ?? inicio;

        return input.value.slice(0, inicio) + texto + input.value.slice(fin);
    };

    const tieneEstructuraInsertable = (valor) => {
        if (valor === "") return true;
        if (CARACTER_INVALIDO.test(valor)) return false;

        // Exige al menos un dígito antes del separador:
        // ".50" y ",50" se rechazan; "0.50" y "0,50" sí se permiten.
        return PATRON_EDICION.test(valor);
    };

    const normalizarCerosIniciales = (valor) => {
        if (valor === "") return "";

        const separador = valor.includes(",")
            ? ","
            : (valor.includes(".") ? "." : null);

        if (separador === null) {
            return valor.replace(/^0+(?=\d)/, "");
        }

        const [enteroBruto, decimalBruto = ""] = valor.split(separador);
        const entero = enteroBruto.replace(/^0+(?=\d)/, "") || "0";

        return `${entero}${separador}${decimalBruto}`;
    };

    const initTipoCambio = () => {
        const input = document.getElementById("tc-input-envia");
        const resultado = document.getElementById("tc-resultado");
        const swap = document.getElementById("tc-swap");
        const monedaEnvia = document.getElementById("tc-moneda-envia");
        const monedaRecibe = document.getElementById("tc-moneda-recibe");

        if (!input || !resultado || !swap || !monedaEnvia || !monedaRecibe) {
            return;
        }

        const compra = leerTasa("tc-compra");
        const venta = leerTasa("tc-venta");

        if (compra === null || venta === null) {
            return;
        }

        let direccion = "USD_PEN";
        let ultimoValorValido = input.value;

        const restaurarUltimoValor = () => {
            input.value = ultimoValorValido;

            try {
                input.setSelectionRange(
                    ultimoValorValido.length,
                    ultimoValorValido.length
                );
            } catch (error) {
                // La ausencia de selección no afecta el valor ni el cálculo.
            }
        };

        input.addEventListener("beforeinput", (event) => {
            if (!TIPOS_INSERCION.includes(event.inputType)) return;

            const texto = event.data != null
                ? event.data
                : (
                    event.dataTransfer
                        ? event.dataTransfer.getData("text/plain")
                        : ""
                );

            // Algunos navegadores no exponen el texto pegado en beforeinput;
            // el listener "paste" actúa como respaldo.
            if (texto === "" && event.inputType === "insertFromPaste") return;

            if (CARACTER_INVALIDO.test(texto)) {
                event.preventDefault();
                return;
            }

            const candidato = construirCandidato(input, texto);

            if (!tieneEstructuraInsertable(candidato)) {
                event.preventDefault();
            }
        });

        input.addEventListener("paste", (event) => {
            const portapapeles = event.clipboardData || window.clipboardData;
            const texto = portapapeles ? portapapeles.getData("text") : "";

            if (CARACTER_INVALIDO.test(texto)) {
                event.preventDefault();
                return;
            }

            const candidato = construirCandidato(input, texto);

            if (!tieneEstructuraInsertable(candidato)) {
                event.preventDefault();
            }
        });

        const normalizarCampo = () => {
            const crudo = input.value;

            if (crudo === "") {
                ultimoValorValido = "";
                return;
            }

            if (!tieneEstructuraInsertable(crudo)) {
                restaurarUltimoValor();
                return;
            }

            const normalizado = normalizarCerosIniciales(crudo);

            if (!tieneEstructuraInsertable(normalizado)) {
                restaurarUltimoValor();
                return;
            }

            if (normalizado !== crudo) {
                input.value = normalizado;

                try {
                    input.setSelectionRange(
                        normalizado.length,
                        normalizado.length
                    );
                } catch (error) {
                    // Sin acción: no afecta el valor ni el cálculo.
                }
            }

            ultimoValorValido = normalizado;
        };

        const calcular = () => {
            const crudo = input.value;

            if (crudo === "") {
                resultado.textContent = "—";
                return;
            }

            // "5." / "5," / "0." / "0," son estados temporales de edición.
            if (/[.,]$/.test(crudo)) {
                resultado.textContent = "—";
                return;
            }

            if (!PATRON_FINAL.test(crudo)) {
                resultado.textContent = "—";
                return;
            }

            const monto = Number.parseFloat(crudo.replace(",", "."));

            if (!Number.isFinite(monto)) {
                resultado.textContent = "—";
                return;
            }

            const tasa = direccion === "USD_PEN" ? compra : venta;
            const convertido = direccion === "USD_PEN"
                ? monto * tasa
                : monto / tasa;

            resultado.textContent = formatearResultado(convertido);
        };

        const actualizarEtiquetas = () => {
            const [envia, recibe] = direccion === "USD_PEN"
                ? ["USD", "PEN"]
                : ["PEN", "USD"];

            monedaEnvia.textContent = envia;
            monedaRecibe.textContent = recibe;
        };

        input.addEventListener("input", () => {
            normalizarCampo();
            calcular();
        });

        swap.addEventListener("click", () => {
            direccion = direccion === "USD_PEN"
                ? "PEN_USD"
                : "USD_PEN";

            actualizarEtiquetas();
            calcular();
        });

        actualizarEtiquetas();
        normalizarCampo();
        calcular();
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initTipoCambio);
    } else {
        initTipoCambio();
    }
})();
