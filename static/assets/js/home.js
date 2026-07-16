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
        playPauseBtn.setAttribute('aria-label', playing ? 'Pausar presentación' : 'Reanudar presentación');
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
