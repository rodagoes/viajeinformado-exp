document.addEventListener('DOMContentLoaded', function () {
    var carouselEl = document.getElementById('carouselInicioPremium');
    if (!carouselEl || typeof bootstrap === 'undefined') return;

    var carousel = bootstrap.Carousel.getOrCreateInstance(carouselEl);
    var bullets = carouselEl.querySelectorAll('.inicio-hero-bullet');
    var playPauseBtn = carouselEl.querySelector('.inicio-hero-playpause');
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var isPlaying = !reduceMotion;

    function activeIndex() {
        var active = carouselEl.querySelector('.carousel-item.active');
        return Array.prototype.indexOf.call(carouselEl.querySelectorAll('.carousel-item'), active);
    }

    function restartProgress(index) {
        bullets.forEach(function (bullet) {
            var ring = bullet.querySelector('.inicio-hero-bullet__progress');
            if (ring) {
                ring.classList.remove('is-animating');
                ring.style.animationPlayState = '';
            }
        });
        void carouselEl.offsetWidth; // fuerza reflow para reiniciar la animación
        bullets.forEach(function (bullet, i) {
            var active = i === index;
            var ring = bullet.querySelector('.inicio-hero-bullet__progress');
            bullet.classList.toggle('active', active);
            bullet.setAttribute('aria-current', active ? 'true' : 'false');
            if (active && isPlaying && ring) ring.classList.add('is-animating');
        });
    }

    function setProgressPlayState(state) {
        bullets.forEach(function (bullet) {
            var ring = bullet.querySelector('.inicio-hero-bullet__progress');
            if (ring) ring.style.animationPlayState = state;
        });
    }

    function setPlayIcon(playing) {
        if (!playPauseBtn) return;
        playPauseBtn.innerHTML = playing
            ? '<i class="bi bi-pause-fill" aria-hidden="true"></i>'
            : '<i class="bi bi-play-fill" aria-hidden="true"></i>';
        playPauseBtn.setAttribute('aria-label', playing ? ViI18n('home_pausar', 'Pausar presentación') : ViI18n('home_reanudar', 'Reanudar presentación'));
    }

    restartProgress(activeIndex());
    setPlayIcon(isPlaying);
    if (!isPlaying) carousel.pause();

    carouselEl.addEventListener('slide.bs.carousel', function (e) {
        restartProgress(e.to);
    });

    if (playPauseBtn) {
        playPauseBtn.addEventListener('click', function () {
            isPlaying = !isPlaying;
            setPlayIcon(isPlaying);
            if (isPlaying) {
                restartProgress(activeIndex());
                carousel.cycle();
            } else {
                carousel.pause();
                setProgressPlayState('paused');
            }
        });
    }

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            carousel.pause();
            setProgressPlayState('paused');
        } else if (isPlaying) {
            restartProgress(activeIndex());
            carousel.cycle();
        }
    });
});

// Cifras: cuenta de 0 al valor la primera vez que la sección entra en pantalla (el HTML ya trae el valor final).
document.addEventListener('DOMContentLoaded', function () {
    var cifras = document.querySelectorAll('[data-home-metricas] [data-count]');
    if (!cifras.length || !('IntersectionObserver' in window) ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var DURACION = 900;

    function contar(el) {
        var meta = parseInt(el.getAttribute('data-count'), 10);
        var inicio = null;
        function paso(t) {
            if (inicio === null) inicio = t;
            var p = Math.min((t - inicio) / DURACION, 1);
            var ease = 1 - Math.pow(1 - p, 3);
            el.textContent = Math.round(meta * ease).toLocaleString('en-US');
            if (p < 1) requestAnimationFrame(paso);
        }
        el.textContent = '0';
        requestAnimationFrame(paso);
    }

    var observer = new IntersectionObserver(function (entradas, obs) {
        entradas.forEach(function (e) {
            if (!e.isIntersecting) return;
            obs.unobserve(e.target);
            contar(e.target);
        });
    }, { threshold: 0.4 });
    cifras.forEach(function (el) { observer.observe(el); });
});
