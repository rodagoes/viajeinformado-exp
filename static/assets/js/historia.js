(() => {
    "use strict";

    const lista = document.querySelector('[data-provincias-lista]');
    const mapa = document.querySelector('[data-provincias-mapa]');
    const flip = document.querySelector('[data-mapa-flip]');
    const infoBtn = document.querySelector('[data-info-btn]');
    const backBtn = document.querySelector('[data-back-btn]');
    const infoPanel = document.querySelector('[data-mapa-info]');
    if (!lista || !mapa) return;

    const cache = {};

    const activeSlug = () => {
        const activo = lista.querySelector('button.is-active');
        return activo ? activo.dataset.provincia : null;
    };

    const activeNombre = () => {
        const activo = lista.querySelector('button.is-active');
        return activo ? activo.textContent.trim() : '';
    };

    lista.addEventListener('click', (event) => {
        const btn = event.target.closest('button[data-provincia]');
        if (!btn) return;
        const slug = btn.dataset.provincia;

        lista.querySelectorAll('button').forEach((b) => {
            const active = b === btn;
            b.classList.toggle('is-active', active);
            b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        mapa.querySelectorAll('.mapa-provincia').forEach((path) => {
            path.classList.toggle('is-active', path.dataset.provincia === slug);
        });

        if (flip) {
            flip.classList.remove('is-flipped');
        }
    });

    if (flip && infoBtn && backBtn && infoPanel) {
        infoBtn.addEventListener('click', () => {
            const slug = activeSlug();
            if (!slug) return;
            flip.classList.add('is-flipped');
            renderInfo(slug, activeNombre());
        });

        backBtn.addEventListener('click', () => {
            flip.classList.remove('is-flipped');
        });
    }

    function renderInfo(slug, nombre) {
        if (cache[slug]) {
            paintInfo(cache[slug], nombre);
            return;
        }

        // Skeleton mientras la petición REAL está en vuelo; se retira en `finally`
        // (éxito o error). Sin temporizadores.
        infoPanel.innerHTML =
            '<span class="vi-skel-line vi-skel-line--titulo" aria-hidden="true"></span>' +
            '<span class="vi-skel-line" aria-hidden="true"></span>' +
            '<span class="vi-skel-line" aria-hidden="true"></span>' +
            '<span class="vi-skel-line vi-skel-line--corta" aria-hidden="true"></span>';
        infoPanel.setAttribute('aria-busy', 'true');

        fetch('/ubicaciones/provincia/' + slug + '/')
            .then((res) => {
                if (!res.ok) throw new Error('No disponible');
                return res.json();
            })
            .then((data) => {
                cache[slug] = data;
                paintInfo(data, nombre);
            })
            .catch(() => {
                infoPanel.innerHTML = '<p class="his-mapa-info__error">' + ViI18n('his_error', 'No se pudo cargar la información de esta provincia.') + '</p>';
            })
            .finally(() => {
                infoPanel.removeAttribute('aria-busy');
            });
    }

    // Formato numérico según el idioma activo de la interfaz.
    const LOCALE = (document.documentElement.lang || 'es').startsWith('en') ? 'en-US' : 'es-PE';

    function titleCase(texto) {
        return texto.toLowerCase().replace(/^\S|\s\S/g, (c) => c.toUpperCase());
    }

    function paintInfo(data, nombre) {
        const superficie = data.superficie_km2
            ? Number(data.superficie_km2).toLocaleString(LOCALE) + ' km²'
            : '—';
        const altitud = data.altitud_m
            ? Number(data.altitud_m).toLocaleString(LOCALE) + ' ' + ViI18n('his_msnm', 'm s. n. m.')
            : '—';
        const capital = data.capital || '—';

        const distritosHtml = data.distritos.map((d) => '<li>' + titleCase(d) + '</li>').join('');

        infoPanel.innerHTML =
            '<h3 class="his-mapa-info__titulo">' + nombre + '</h3>' +
            '<dl class="his-mapa-info__datos">' +
                '<div class="his-mapa-info__dato"><i class="bi bi-flag-fill" aria-hidden="true"></i><dt>' + ViI18n('his_capital', 'Capital') + '</dt><dd>' + capital + '</dd></div>' +
                '<div class="his-mapa-info__dato"><i class="bi bi-bounding-box" aria-hidden="true"></i><dt>' + ViI18n('his_superficie', 'Superficie') + '</dt><dd>' + superficie + '</dd></div>' +
                '<div class="his-mapa-info__dato"><i class="bi bi-triangle-fill" aria-hidden="true"></i><dt>' + ViI18n('his_altitud', 'Altitud') + '</dt><dd>' + altitud + '</dd></div>' +
            '</dl>' +
            '<div class="his-mapa-info__distritos">' +
                '<h4>' + ViI18n('his_distritos', 'Distritos') + ' (' + data.distritos.length + ')</h4>' +
                '<ul>' + distritosHtml + '</ul>' +
            '</div>';
    }

    const himnoModal = document.querySelector('[data-himno-modal]');
    const himnoAbrirBtn = document.querySelector('[data-himno-abrir]');

    if (himnoModal && himnoAbrirBtn) {
        let scrollBloqueado = 0;
        let overflowAnterior = '';

        const abrirHimno = () => {
            scrollBloqueado = window.scrollY;
            overflowAnterior = document.body.style.overflow;
            document.body.style.position = 'fixed';
            document.body.style.top = '-' + scrollBloqueado + 'px';
            document.body.style.left = '0';
            document.body.style.right = '0';
            document.body.style.overflow = 'hidden';
            himnoModal.hidden = false;
        };

        const cerrarHimno = () => {
            himnoModal.hidden = true;
            document.body.style.position = '';
            document.body.style.top = '';
            document.body.style.left = '';
            document.body.style.right = '';
            document.body.style.overflow = overflowAnterior;
            window.scrollTo({ top: scrollBloqueado, left: 0, behavior: 'instant' });
        };

        himnoAbrirBtn.addEventListener('click', abrirHimno);

        himnoModal.querySelectorAll('[data-himno-cerrar]').forEach((el) => {
            el.addEventListener('click', cerrarHimno);
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !himnoModal.hidden) {
                cerrarHimno();
            }
        });
    }
})();
