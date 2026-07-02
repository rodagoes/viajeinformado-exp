/**
 * detalle-lugar-turistico.js — Viaje Informado
 *
 * JS propio de la vista Detalle Lugar Turístico: scroll suave interno,
 * botón favorito y botón compartir.
 */
(function () {
  'use strict';

  var root = document.querySelector('.detalle-lugar');
  var lugarNombre = root ? root.dataset.lugarNombre : '';
  var shareText = root ? root.dataset.shareText : '';

  /* ── Scroll suave con duración dinámica según distancia ──
     Curva easeInOutSine: transición más rápida y natural que el
     easeInOutCubic anterior, sin sentirse como salto brusco. */
  function easeInOutSine(t) {
    return -(Math.cos(Math.PI * t) - 1) / 2;
  }

  function desplazarConEasing(destino) {
    var navEl = document.querySelector('header') || document.querySelector('.navbar');
    var altoNavbar = navEl ? navEl.offsetHeight : 0;
    var inicio = window.pageYOffset;
    var objetivo = destino.getBoundingClientRect().top + window.pageYOffset - altoNavbar;
    var diferencia = objetivo - inicio;
    var distanciaAbs = Math.abs(diferencia);
    var duracion = Math.min(680, Math.max(520, distanciaAbs * 0.45));
    var tiempoInicio = null;

    function paso(timestamp) {
      if (!tiempoInicio) tiempoInicio = timestamp;
      var transcurrido = timestamp - tiempoInicio;
      var progreso = Math.min(transcurrido / duracion, 1);
      window.scrollTo(0, inicio + diferencia * easeInOutSine(progreso));
      if (progreso < 1) requestAnimationFrame(paso);
    }

    requestAnimationFrame(paso);
  }

  document.querySelectorAll('.detalle-lugar a[href^="#"]').forEach(function (a) {
    var href = a.getAttribute('href');
    if (!href || href === '#') return;
    a.addEventListener('click', function (e) {
      var target;
      try {
        target = document.querySelector(href);
      } catch (err) {
        return;
      }
      if (!target) return;
      e.preventDefault();
      desplazarConEasing(target);
    });
  });

  document.querySelectorAll('[data-action="favorite"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var active = btn.classList.toggle('is-active');
      btn.querySelectorAll('i').forEach(function (ic) {
        ic.className = active ? 'bi bi-heart-fill' : 'bi bi-heart';
      });
      btn.setAttribute('aria-label', active ? 'Quitar de favoritos' : 'Añadir a favoritos');
    });
  });

  function showToast(msg) {
    var t = document.createElement('div');
    t.setAttribute('role', 'status');
    t.setAttribute('aria-live', 'polite');
    t.textContent = msg;
    t.style.cssText = [
      'position:fixed', 'bottom:90px', 'left:50%',
      'transform:translateX(-50%)', 'background:#002d89',
      'color:#fff', 'padding:10px 24px', 'border-radius:999px',
      'font-size:13px', 'font-weight:600', 'z-index:9999',
      'box-shadow:0 4px 18px rgba(0,45,137,0.35)',
      'transition:opacity .3s', 'font-family:inherit',
      'white-space:nowrap'
    ].join(';');
    document.body.appendChild(t);
    setTimeout(function () {
      t.style.opacity = '0';
      setTimeout(function () { t.remove(); }, 330);
    }, 2600);
  }

  function copiarAlPortapapeles(texto) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(texto);
    }
    return new Promise(function (resolve, reject) {
      var textarea = document.createElement('textarea');
      textarea.value = texto;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      var copiado = false;
      try {
        copiado = document.execCommand('copy');
      } catch (err) {
        copiado = false;
      }
      document.body.removeChild(textarea);
      if (copiado) resolve(); else reject(new Error('No se pudo copiar'));
    });
  }

  function copiarConFeedback(url) {
    copiarAlPortapapeles(url).then(function () {
      showToast('Enlace copiado al portapapeles');
    }).catch(function () {
      showToast('No se pudo compartir el enlace');
    });
  }

  function doShare() {
    var url = window.location.href;
    if (navigator.share) {
      navigator.share({
        title: lugarNombre,
        text: shareText,
        url: url
      }).catch(function () {
        copiarConFeedback(url);
      });
      return;
    }
    copiarConFeedback(url);
  }

  document.querySelectorAll('[data-action="share"]').forEach(function (btn) {
    btn.addEventListener('click', doShare);
  });
})();
