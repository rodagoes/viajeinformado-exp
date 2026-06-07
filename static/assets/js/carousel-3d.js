/* ============================================================
   CARRUSEL 3D COVERFLOW — componente reutilizable
   Compatible: img, gif, video mp4, video externo (YouTube/Vimeo)
   ============================================================ */

(function () {
  'use strict';

  var track         = document.getElementById('c3dTrack');
  if (!track) return;

  var prevBtn       = document.getElementById('c3dPrev');
  var nextBtn       = document.getElementById('c3dNext');
  var dotsContainer = document.getElementById('c3dDots');
  var lightbox      = document.getElementById('c3dLightbox');
  var lbContent     = document.getElementById('c3dLbContent');
  var lbClose       = document.getElementById('c3dLbClose');
  var lbPrev        = document.getElementById('c3dLbPrev');
  var lbNext        = document.getElementById('c3dLbNext');
  var lbDotsEl      = document.getElementById('c3dLbDots');
  var lbPeekPrev    = document.getElementById('c3dLbPeekPrev');
  var lbPeekNext    = document.getElementById('c3dLbPeekNext');

  var slides      = Array.from(track.querySelectorAll('.slide'));
  var total       = slides.length;
  var current     = 0;
  var isAnimating = false;
  var ANIM_DELAY  = 580;

  // ── Estado de zoom ──────────────────────────────────────────
  var zoom     = 1;
  var panX     = 0;
  var panY     = 0;
  var zoomEl   = null;   // <img> o <video> al que se aplica el transform
  var MIN_ZOOM = 1;
  var MAX_ZOOM = 5;

  // ── Estado de drag (mouse, desktop) ────────────────────────
  var isDragging  = false;
  var dragX0      = 0;
  var dragY0      = 0;
  var panDragX0   = 0;
  var panDragY0   = 0;
  var dragWrapper = null;

  // Listeners de mousemove/mouseup a nivel de documento (una sola vez)
  document.addEventListener('mousemove', function (e) {
    if (!isDragging || !zoomEl) return;
    panX = panDragX0 + (e.clientX - dragX0) / zoom;
    panY = panDragY0 + (e.clientY - dragY0) / zoom;
    applyTransform();
  });

  document.addEventListener('mouseup', function () {
    if (!isDragging) return;
    isDragging = false;
    if (dragWrapper) dragWrapper.style.cursor = zoom > 1 ? 'move' : 'zoom-in';
    dragWrapper = null;
  });

  var POS_CLASS = {
    '-3': 'pos-far-left',
    '-2': 'pos-n2',
    '-1': 'pos-n1',
     '0': 'pos-0',
     '1': 'pos-1',
     '2': 'pos-2',
     '3': 'pos-far-right',
  };
  var FAR_LEFT  = 'pos-far-left';
  var FAR_RIGHT = 'pos-far-right';
  var HIDDEN    = 'pos-hidden';

  // ── Embed URL ──────────────────────────────────────────────
  function toEmbedUrl(url) {
    var ytMatch = url.match(/(?:youtube\.com\/watch\?(?:.*&)?v=|youtu\.be\/)([^&?/\s]+)/);
    if (ytMatch) return 'https://www.youtube.com/embed/' + ytMatch[1] + '?autoplay=1&rel=0';
    var vmMatch = url.match(/vimeo\.com\/(\d+)/);
    if (vmMatch) return 'https://player.vimeo.com/video/' + vmMatch[1] + '?autoplay=1';
    return url;
  }

  // ── Dots del carrusel ──────────────────────────────────────
  function buildDots() {
    dotsContainer.innerHTML = '';
    slides.forEach(function (_, i) {
      var btn = document.createElement('button');
      btn.className = 'dot' + (i === 0 ? ' active' : '');
      btn.setAttribute('aria-label', 'Ir al slide ' + (i + 1));
      btn.addEventListener('click', function () { goTo(i); });
      dotsContainer.appendChild(btn);
    });
  }

  function updateDots() {
    var dots = dotsContainer.querySelectorAll('.dot');
    dots.forEach(function (d, i) { d.classList.toggle('active', i === current); });
  }

  // ── Dots del lightbox ─────────────────────────────────────
  function buildLightboxDots() {
    if (!lbDotsEl) return;
    lbDotsEl.innerHTML = '';
    slides.forEach(function (_, i) {
      var btn = document.createElement('button');
      btn.className = 'c3d-lb-dot' + (i === current ? ' active' : '');
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-label', 'Imagen ' + (i + 1));
      btn.addEventListener('click', function () { lbGoTo(i); });
      lbDotsEl.appendChild(btn);
    });
  }

  function updateLightboxDots() {
    if (!lbDotsEl) return;
    lbDotsEl.querySelectorAll('.c3d-lb-dot').forEach(function (d, i) {
      d.classList.toggle('active', i === current);
    });
  }

  // ── Render 3D ─────────────────────────────────────────────
  function render() {
    var allPos = Object.values(POS_CLASS).concat([FAR_LEFT, FAR_RIGHT, HIDDEN, 'active']);
    slides.forEach(function (slide, i) {
      allPos.forEach(function (cls) { slide.classList.remove(cls); });
      var offset = i - current;
      if (offset > total / 2)  offset -= total;
      if (offset < -total / 2) offset += total;
      if (offset === 0) {
        slide.classList.add('pos-0', 'active');
      } else if (POS_CLASS[String(offset)]) {
        slide.classList.add(POS_CLASS[String(offset)]);
      } else if (offset > 3) {
        slide.classList.add(Math.abs(offset) > 4 ? HIDDEN : FAR_RIGHT);
      } else if (offset < -3) {
        slide.classList.add(Math.abs(offset) > 4 ? HIDDEN : FAR_LEFT);
      } else {
        slide.classList.add(HIDDEN);
      }
    });
    updateDots();
  }

  // ── Navegación del carrusel ────────────────────────────────
  function goTo(index) {
    if (isAnimating || index === current) return;
    isAnimating = true;
    current = ((index % total) + total) % total;
    render();
    setTimeout(function () { isAnimating = false; }, ANIM_DELAY);
  }

  function prev() { goTo(current - 1); }
  function next() { goTo(current + 1); }

  prevBtn.addEventListener('click', prev);
  nextBtn.addEventListener('click', next);

  slides.forEach(function (slide, i) {
    slide.addEventListener('click', function (e) {
      if (slide.classList.contains('pos-0')) return;
      if (e.target.closest('.fullview-btn')) return;
      goTo(i);
    });
  });

  // ── Teclado ────────────────────────────────────────────────
  document.addEventListener('keydown', function (e) {
    if (lightbox.classList.contains('open')) {
      if (e.key === 'ArrowLeft')  lbNavigate(-1);
      if (e.key === 'ArrowRight') lbNavigate(1);
      if (e.key === 'Escape')     closeLightbox();
      return;
    }
    var active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;
    if (e.key === 'ArrowLeft')  prev();
    if (e.key === 'ArrowRight') next();
  });

  // ── Swipe táctil (carrusel) ────────────────────────────────
  var touchStartX = null;
  track.addEventListener('touchstart', function (e) {
    touchStartX = e.touches[0].clientX;
  }, { passive: true });

  track.addEventListener('touchend', function (e) {
    if (touchStartX === null) return;
    var dx = e.changedTouches[0].clientX - touchStartX;
    if (Math.abs(dx) > 40) { dx < 0 ? next() : prev(); }
    touchStartX = null;
  }, { passive: true });

  // ── Scroll-lock sin position:fixed (evita el bounce al cerrar) ──
  function preventTouchScroll(e) {
    e.preventDefault();
  }

  function lockScroll() {
    document.body.style.overflow = 'hidden';
    document.addEventListener('touchmove', preventTouchScroll, { passive: false });
  }

  function unlockScroll() {
    document.body.style.overflow = '';
    document.removeEventListener('touchmove', preventTouchScroll);
  }

  // ── Zoom helpers ───────────────────────────────────────────
  function applyTransform() {
    if (!zoomEl) return;
    zoomEl.style.transformOrigin = 'center center';
    zoomEl.style.transform = 'scale(' + zoom + ') translate(' + panX + 'px, ' + panY + 'px)';
  }

  function setTransformSmooth(duration) {
    if (!zoomEl) return;
    zoomEl.style.transition = 'transform ' + duration + 'ms ease';
    applyTransform();
    var el = zoomEl;
    setTimeout(function () { if (el) el.style.transition = ''; }, duration);
  }

  function resetZoom() {
    zoom = 1; panX = 0; panY = 0;
    zoomEl = null;
  }

  // ── Zoom listeners por elemento ────────────────────────────
  function attachZoomListeners(wrapper, mediaEl) {
    zoomEl = mediaEl;

    var pinchDist0    = 0;
    var pinchZoom0    = 1;
    var panTouchX0    = 0;
    var panTouchY0    = 0;
    var panX0         = 0;
    var panY0         = 0;
    var lastTap       = 0;

    // ── Touch: pinch-to-zoom + pan ──
    wrapper.addEventListener('touchstart', function (e) {
      if (e.touches.length === 2) {
        pinchDist0 = Math.hypot(
          e.touches[1].clientX - e.touches[0].clientX,
          e.touches[1].clientY - e.touches[0].clientY
        );
        pinchZoom0 = zoom;
      } else if (e.touches.length === 1) {
        panTouchX0 = e.touches[0].clientX;
        panTouchY0 = e.touches[0].clientY;
        panX0      = panX;
        panY0      = panY;
      }
    }, { passive: true });

    wrapper.addEventListener('touchmove', function (e) {
      if (e.touches.length === 2) {
        // Pinch zoom
        var d = Math.hypot(
          e.touches[1].clientX - e.touches[0].clientX,
          e.touches[1].clientY - e.touches[0].clientY
        );
        zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, pinchZoom0 * (d / pinchDist0)));
        wrapper.classList.toggle('is-zoomed', zoom > 1);
        applyTransform();
      } else if (e.touches.length === 1 && zoom > 1) {
        // Pan cuando hay zoom
        panX = panX0 + (e.touches[0].clientX - panTouchX0) / zoom;
        panY = panY0 + (e.touches[0].clientY - panTouchY0) / zoom;
        applyTransform();
      }
    }, { passive: true });

    wrapper.addEventListener('touchend', function (e) {
      // Snap a 1× si el zoom cayó justo por debajo
      if (e.touches.length === 0 && zoom < 1.08) {
        zoom = 1; panX = 0; panY = 0;
        wrapper.classList.remove('is-zoomed');
        setTransformSmooth(200);
      }

      // Doble tap: alterna entre 1× y 2.5×
      if (e.touches.length === 0 && e.changedTouches.length === 1) {
        var now = Date.now();
        if (now - lastTap < 280) {
          if (zoom > 1) {
            zoom = 1; panX = 0; panY = 0;
            wrapper.classList.remove('is-zoomed');
            wrapper.style.cursor = 'zoom-in';
          } else {
            zoom = 2.5;
            wrapper.classList.add('is-zoomed');
            wrapper.style.cursor = 'move';
          }
          setTransformSmooth(280);
          lastTap = 0;
        } else {
          lastTap = now;
        }
      }
    }, { passive: true });

    // ── Wheel: zoom con rueda (desktop) ──
    wrapper.addEventListener('wheel', function (e) {
      e.preventDefault();
      var factor = e.deltaY < 0 ? 1.12 : 0.90;
      zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));
      if (zoom <= 1.02) {
        zoom = 1; panX = 0; panY = 0;
        wrapper.classList.remove('is-zoomed');
        wrapper.style.cursor = 'zoom-in';
      } else {
        wrapper.classList.add('is-zoomed');
        wrapper.style.cursor = 'move';
      }
      setTransformSmooth(100);
    }, { passive: false });

    // ── Mousedown: drag para pan con mouse (desktop) ──
    wrapper.addEventListener('mousedown', function (e) {
      if (zoom <= 1) return;
      e.preventDefault();
      isDragging  = true;
      dragX0      = e.clientX;
      dragY0      = e.clientY;
      panDragX0   = panX;
      panDragY0   = panY;
      dragWrapper = wrapper;
      wrapper.style.cursor = 'grabbing';
    });

    // ── Doble click: alterna zoom (desktop) ──
    wrapper.addEventListener('dblclick', function (e) {
      if (zoom > 1) {
        zoom = 1; panX = 0; panY = 0;
        wrapper.classList.remove('is-zoomed');
        wrapper.style.cursor = 'zoom-in';
      } else {
        zoom = 2.5;
        // Centra el zoom en el punto clicado
        var rect = mediaEl.getBoundingClientRect();
        panX = (rect.width  / 2 - (e.clientX - rect.left)) / zoom;
        panY = (rect.height / 2 - (e.clientY - rect.top))  / zoom;
        wrapper.classList.add('is-zoomed');
        wrapper.style.cursor = 'move';
      }
      setTransformSmooth(280);
    });
  }

  // ── Peeks laterales ────────────────────────────────────────
  function buildPeekMedia(container, slideIndex) {
    if (!container) return;
    container.innerHTML = '';
    var idx = ((slideIndex % total) + total) % total;
    var mediaEl = slides[idx] && slides[idx].querySelector('.media');
    if (!mediaEl || mediaEl.tagName.toLowerCase() !== 'img') return;
    var img = document.createElement('img');
    img.src = mediaEl.getAttribute('src') || '';
    img.alt = '';
    img.setAttribute('aria-hidden', 'true');
    container.appendChild(img);
  }

  function updatePeeks() {
    if (total <= 1) return;
    buildPeekMedia(lbPeekPrev, ((current - 1) + total) % total);
    buildPeekMedia(lbPeekNext, (current + 1) % total);
  }

  // ── Builder de media del lightbox ─────────────────────────
  function getMediaElement(slideEl) {
    return slideEl.querySelector('.media');
  }

  function buildLightboxMedia(mediaEl) {
    lbContent.innerHTML = '';
    resetZoom();
    if (!mediaEl) return;

    var wrap = document.createElement('div');
    wrap.className = 'c3d-lb-zoom-wrapper';

    var cloned;
    var tag = mediaEl.tagName.toLowerCase();

    if (tag === 'video') {
      cloned = document.createElement('video');
      cloned.src        = mediaEl.getAttribute('src') || mediaEl.currentSrc || '';
      cloned.controls   = true;
      cloned.autoplay   = true;
      cloned.loop       = mediaEl.loop;
      cloned.muted      = false;
      cloned.playsInline = true;

    } else if (tag === 'div' && mediaEl.dataset.videoUrl) {
      cloned = document.createElement('iframe');
      cloned.src            = toEmbedUrl(mediaEl.dataset.videoUrl);
      cloned.allow          = 'autoplay; fullscreen; picture-in-picture';
      cloned.allowFullscreen = true;
      cloned.className      = 'c3d-lb-iframe';

    } else {
      // Imagen / GIF
      cloned = document.createElement('img');
      cloned.src = mediaEl.getAttribute('src') || '';
      cloned.alt = mediaEl.alt || '';
    }

    wrap.appendChild(cloned);
    lbContent.appendChild(wrap);

    // Zoom solo para img y video (no para iframes externos)
    if (tag !== 'div') {
      attachZoomListeners(wrap, cloned);
    }
  }

  // ── Navegación interna del lightbox ────────────────────────
  function lbGoTo(index) {
    current = ((index % total) + total) % total;
    render();
    lbContent.style.animation = 'none';
    lbContent.offsetHeight;
    lbContent.style.animation = '';
    buildLightboxMedia(getMediaElement(slides[current]));
    updateLightboxDots();
    updatePeeks();
  }

  function openLightbox(slideIndex) {
    current = ((slideIndex % total) + total) % total;
    render();
    buildLightboxMedia(getMediaElement(slides[current]));
    lbContent.style.animation = 'none';
    lbContent.offsetHeight;
    lbContent.style.animation = '';
    buildLightboxDots();
    updatePeeks();
    lockScroll();
    lightbox.classList.add('open');
  }

  function closeLightbox() {
    lightbox.classList.remove('open');
    resetZoom();
    isDragging = false;

    var vid = lbContent.querySelector('video');
    if (vid) vid.pause();
    var iframe = lbContent.querySelector('iframe');
    if (iframe) iframe.src = '';
    lbContent.innerHTML = '';

    if (lbPeekPrev) lbPeekPrev.innerHTML = '';
    if (lbPeekNext) lbPeekNext.innerHTML = '';

    unlockScroll();
  }

  function lbNavigate(dir) {
    current = ((current + dir + total) % total);
    render();
    lbContent.style.animation = 'none';
    lbContent.offsetHeight;
    lbContent.style.animation = '';
    buildLightboxMedia(getMediaElement(slides[current]));
    updateLightboxDots();
    updatePeeks();
  }

  // ── Botón expandir de cada slide ───────────────────────────
  slides.forEach(function (slide, i) {
    var btn = slide.querySelector('.fullview-btn');
    if (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        openLightbox(i);
      });
    }
  });

  lbClose.addEventListener('click', closeLightbox);
  lbPrev.addEventListener('click', function () { lbNavigate(-1); });
  lbNext.addEventListener('click', function () { lbNavigate(1); });

  // Cerrar al clicar el fondo oscuro
  lightbox.addEventListener('click', function (e) {
    if (e.target === lightbox) closeLightbox();
  });

  // ── Swipe en lightbox (solo cuando zoom = 1) ───────────────
  var lbTouchX = null;

  lightbox.addEventListener('touchstart', function (e) {
    // Solo rastrear si es 1 solo dedo
    lbTouchX = e.touches.length === 1 ? e.touches[0].clientX : null;
  }, { passive: true });

  lightbox.addEventListener('touchend', function (e) {
    if (lbTouchX === null) return;
    // Navegar solo si no hay zoom activo
    if (zoom <= 1) {
      var dx = e.changedTouches[0].clientX - lbTouchX;
      if (Math.abs(dx) > 40) lbNavigate(dx < 0 ? 1 : -1);
    }
    lbTouchX = null;
  }, { passive: true });

  // ── Inicializar ────────────────────────────────────────────
  buildDots();
  render();

})();
