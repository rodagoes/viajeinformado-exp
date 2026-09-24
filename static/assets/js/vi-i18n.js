// Cadenas de UI traducidas por Django (json_script "vi-i18n" en base.html).
// Uso: ViI18n('enviando', 'Enviando…') -> texto en el idioma activo o el fallback.
(function () {
    var textos = {};
    try {
        var nodo = document.getElementById('vi-i18n');
        if (nodo) textos = JSON.parse(nodo.textContent) || {};
    } catch (e) { textos = {}; }
    window.ViI18n = function (clave, respaldo) {
        return textos[clave] || respaldo || clave;
    };
})();
