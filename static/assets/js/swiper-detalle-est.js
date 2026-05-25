document.addEventListener("DOMContentLoaded", function () {
    const AUTOPLAY_DELAY = 4200;

    function swiperElRealCount(swiperEl) {
        if (!swiperEl) return 0;

        const slides = swiperEl.querySelectorAll(".swiper-slide:not(.swiper-slide-duplicate)");
        return slides.length || 1;
    }

    function updateCounter(swiper, counterEl) {
        if (!counterEl) return;

        const totalSlides = swiperElRealCount(swiper.el);
        const currentIndex = swiper.realIndex + 1;
        const numberEl = counterEl.querySelector("span");

        if (numberEl) {
            numberEl.textContent = `${currentIndex} / ${totalSlides}`;
        }
    }

    function getBullets(paginationEl) {
        if (!paginationEl) return [];
        return Array.from(paginationEl.querySelectorAll(".swiper-pagination-bullet"));
    }

    function prepareBullets(paginationEl) {
        getBullets(paginationEl).forEach(function (bullet) {
            let progress = bullet.querySelector(".detalle-bullet-progress");

            if (!progress) {
                progress = document.createElement("span");
                progress.className = "detalle-bullet-progress";
                bullet.appendChild(progress);
            }
        });
    }

    function resetInactiveBullets(paginationEl) {
        getBullets(paginationEl).forEach(function (bullet) {
            const progress = bullet.querySelector(".detalle-bullet-progress");

            if (!bullet.classList.contains("swiper-pagination-bullet-active") && progress) {
                progress.style.width = "0%";
            }
        });
    }

    function setActiveBulletProgress(paginationEl, percentage) {
        const activeBullet = paginationEl
            ? paginationEl.querySelector(".swiper-pagination-bullet-active")
            : null;

        if (!activeBullet) return;

        let progress = activeBullet.querySelector(".detalle-bullet-progress");

        if (!progress) {
            progress = document.createElement("span");
            progress.className = "detalle-bullet-progress";
            activeBullet.appendChild(progress);
        }

        progress.style.width = `${percentage}%`;
    }

    function resetActiveBulletProgress(paginationEl) {
        resetInactiveBullets(paginationEl);
        setActiveBulletProgress(paginationEl, 0);
    }

    function setPausedUI(swiperEl, playButton) {
        const icon = playButton ? playButton.querySelector("i") : null;

        swiperEl.classList.add("is-carousel-paused");

        if (playButton) {
            playButton.classList.add("is-paused");
        }

        if (icon) {
            icon.className = "bi bi-play-fill";
        }
    }

    function setPlayingUI(swiperEl, playButton) {
        const icon = playButton ? playButton.querySelector("i") : null;

        swiperEl.classList.remove("is-carousel-paused");

        if (playButton) {
            playButton.classList.remove("is-paused");
        }

        if (icon) {
            icon.className = "bi bi-pause-fill";
        }
    }

    function initDetalleSwiper(options) {
        const swiperEl = document.querySelector(options.swiperSelector);
        if (!swiperEl || typeof Swiper === "undefined") return;

        const paginationEl = document.querySelector(options.paginationSelector);
        const playButton = document.querySelector(options.playSelector);
        const counterEl = options.counterSelector
            ? document.querySelector(options.counterSelector)
            : null;

        let isPausedByUser = false;
        let isTransitioning = false;
        let rafId = null;
        let progressStartTime = 0;
        let progressElapsed = 0;

        function cancelProgress() {
            if (rafId) {
                window.cancelAnimationFrame(rafId);
                rafId = null;
            }
        }

        function startProgress(swiper, elapsed) {
            cancelProgress();

            if (isPausedByUser || isTransitioning) return;

            progressElapsed = Math.max(0, Math.min(elapsed || 0, AUTOPLAY_DELAY));
            progressStartTime = performance.now() - progressElapsed;

            function tick(now) {
                if (isPausedByUser || isTransitioning) return;

                progressElapsed = now - progressStartTime;

                const percentage = Math.min(100, Math.max(0, (progressElapsed / AUTOPLAY_DELAY) * 100));

                resetInactiveBullets(paginationEl);
                setActiveBulletProgress(paginationEl, percentage);

                if (progressElapsed >= AUTOPLAY_DELAY) {
                    progressElapsed = 0;
                    setActiveBulletProgress(paginationEl, 100);
                    cancelProgress();
                    swiper.slideNext();
                    return;
                }

                rafId = window.requestAnimationFrame(tick);
            }

            rafId = window.requestAnimationFrame(tick);
        }

        function pauseProgress() {
            if (progressStartTime) {
                progressElapsed = Math.max(0, Math.min(performance.now() - progressStartTime, AUTOPLAY_DELAY));
            }

            cancelProgress();

            const percentage = Math.min(100, Math.max(0, (progressElapsed / AUTOPLAY_DELAY) * 100));
            setActiveBulletProgress(paginationEl, percentage);
        }

        function resetProgressForCurrentSlide() {
            progressElapsed = 0;
            prepareBullets(paginationEl);
            resetActiveBulletProgress(paginationEl);
        }

        const swiperConfig = {
            loop: true,
            speed: 850,
            grabCursor: true,
            slidesPerView: 1,
            spaceBetween: 0,
            effect: "slide",

            /*
               Importante:
               No usamos autoplay interno de Swiper.
               El autoplay y progress lo controla este archivo JS.
            */
            autoplay: false,

            pagination: {
                el: options.paginationSelector,
                clickable: true,
                renderBullet: function (index, className) {
                    return `<span class="${className}"><span class="detalle-bullet-progress"></span></span>`;
                },
            },

            on: {
                init: function () {
                    prepareBullets(paginationEl);
                    resetProgressForCurrentSlide();
                    updateCounter(this, counterEl);
                    setPlayingUI(swiperEl, playButton);
                    startProgress(this, 0);
                },

                slideChangeTransitionStart: function () {
                    isTransitioning = true;
                    cancelProgress();

                    /*
                       Si el usuario cambia de imagen estando pausado,
                       vuelve automáticamente a modo reproducción.
                    */
                    if (isPausedByUser) {
                        isPausedByUser = false;
                        setPlayingUI(swiperEl, playButton);
                    }

                    resetProgressForCurrentSlide();
                    updateCounter(this, counterEl);
                },

                slideChangeTransitionEnd: function () {
                    isTransitioning = false;

                    prepareBullets(paginationEl);
                    resetProgressForCurrentSlide();
                    updateCounter(this, counterEl);

                    if (!isPausedByUser) {
                        startProgress(this, 0);
                    }
                },
            },
        };

        if (options.nextSelector && options.prevSelector) {
            swiperConfig.navigation = {
                nextEl: options.nextSelector,
                prevEl: options.prevSelector,
            };
        }

        const swiper = new Swiper(options.swiperSelector, swiperConfig);

        if (playButton) {
            playButton.addEventListener("click", function () {
                if (!isPausedByUser) {
                    isPausedByUser = true;
                    pauseProgress();
                    setPausedUI(swiperEl, playButton);
                } else {
                    isPausedByUser = false;
                    setPlayingUI(swiperEl, playButton);
                    startProgress(swiper, progressElapsed);
                }
            });
        }

        document.addEventListener("visibilitychange", function () {
            if (document.visibilityState === "hidden") {
                if (!isPausedByUser) {
                    pauseProgress();
                }
            }

            if (document.visibilityState === "visible") {
                if (!isPausedByUser && !isTransitioning) {
                    startProgress(swiper, progressElapsed);
                }
            }
        });

        window.addEventListener("pageshow", function () {
            if (!isPausedByUser && !isTransitioning) {
                startProgress(swiper, progressElapsed);
            }
        });
    }

    initDetalleSwiper({
        swiperSelector: ".detalle-swiper",
        paginationSelector: ".detalle-swiper-pagination",
        playSelector: ".detalle-swiper-play",
        nextSelector: ".detalle-swiper-next",
        prevSelector: ".detalle-swiper-prev",
        counterSelector: null,
    });

    initDetalleSwiper({
        swiperSelector: ".detalle-mobile-swiper",
        paginationSelector: ".detalle-mobile-pagination",
        playSelector: ".detalle-mobile-swiper-play",
        nextSelector: null,
        prevSelector: null,
        counterSelector: ".detalle-mobile-counter",
    });
});