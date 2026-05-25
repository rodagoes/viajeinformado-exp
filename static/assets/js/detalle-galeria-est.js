(function () {
    "use strict";

    let gallerySwiper = null;
    let initialIndex = 0;
    let lockedScrollY = 0;
    function blurActiveGalleryControl() {
        const activeElement = document.activeElement;

        if (activeElement && typeof activeElement.blur === "function") {
            activeElement.blur();
        }

        document.querySelectorAll("[data-detalle-gallery-open], .detalle-gallery-close").forEach((control) => {
            if (typeof control.blur === "function") {
                control.blur();
            }
        });
    }

    function normaliseIndex(index, totalSlides) {
        if (!Number.isFinite(index) || totalSlides <= 0) {
            return 0;
        }

        const safeIndex = index % totalSlides;
        return safeIndex < 0 ? safeIndex + totalSlides : safeIndex;
    }

    function getVisibleSourceSwiper() {
        const isTabletOrMobile = window.matchMedia("(max-width: 1199.98px)").matches;
        const mobileSwiper = document.querySelector(".detalle-mobile-swiper");
        const desktopSwiper = document.querySelector(".detalle-swiper");

        if (isTabletOrMobile && mobileSwiper) {
            return mobileSwiper;
        }

        if (!isTabletOrMobile && desktopSwiper) {
            return desktopSwiper;
        }

        return mobileSwiper || desktopSwiper;
    }

    function getActiveSlideIndex() {
        const sourceSwiper = getVisibleSourceSwiper();

        if (!sourceSwiper) {
            return 0;
        }

        const wrapper = sourceSwiper.querySelector(".swiper-wrapper");
        const originalSlides = wrapper
            ? Array.from(wrapper.children).filter((slide) => {
                return slide.classList.contains("swiper-slide") && !slide.classList.contains("swiper-slide-duplicate");
            })
            : [];

        const totalSlides = originalSlides.length;

        if (sourceSwiper.swiper && typeof sourceSwiper.swiper.realIndex === "number") {
            return normaliseIndex(sourceSwiper.swiper.realIndex, totalSlides || 1);
        }

        const activeSlide = sourceSwiper.querySelector(".swiper-slide-active");

        if (!activeSlide || !wrapper) {
            return 0;
        }

        const dataIndex = activeSlide.getAttribute("data-swiper-slide-index");

        if (dataIndex !== null && dataIndex !== "") {
            return normaliseIndex(parseInt(dataIndex, 10), totalSlides || 1);
        }

        const domIndex = originalSlides.indexOf(activeSlide);
        return domIndex >= 0 ? domIndex : 0;
    }

    function storeCurrentIndex() {
        initialIndex = getActiveSlideIndex();
    }

    function preventModalScroll(event) {
        // En iOS/Safari evita que al deslizar verticalmente dentro de la galería se mueva toda la página.
        event.preventDefault();
    }

    function lockPageScroll() {
        lockedScrollY = window.scrollY || window.pageYOffset || 0;
        document.body.classList.add("detalle-gallery-locked");
        document.body.style.top = `-${lockedScrollY}px`;
        document.body.style.left = "0";
        document.body.style.right = "0";
    }

    function unlockPageScroll() {
        document.body.classList.remove("detalle-gallery-locked");
        document.body.style.removeProperty("top");
        document.body.style.removeProperty("left");
        document.body.style.removeProperty("right");
        window.scrollTo(0, lockedScrollY);
    }

    function initGalleryModal() {
        const modalElement = document.getElementById("detalleGaleriaModal");

        if (!modalElement || typeof Swiper === "undefined") {
            return;
        }

        document.querySelectorAll("[data-detalle-gallery-open]").forEach((button) => {
            button.addEventListener("pointerdown", storeCurrentIndex);
            button.addEventListener("touchstart", storeCurrentIndex, { passive: true });
            button.addEventListener("click", function () {
                storeCurrentIndex();
                window.setTimeout(blurActiveGalleryControl, 80);
            });
        });

        modalElement.addEventListener("show.bs.modal", function () {
            lockPageScroll();
            modalElement.addEventListener("touchmove", preventModalScroll, { passive: false });
        });

        modalElement.addEventListener("shown.bs.modal", function () {
            if (!gallerySwiper) {
                gallerySwiper = new Swiper(".detalle-gallery-swiper", {
                    slidesPerView: 1,
                    spaceBetween: 18,
                    speed: 450,
                    loop: false,
                    keyboard: {
                        enabled: true,
                        onlyInViewport: false,
                    },
                    navigation: {
                        nextEl: ".detalle-gallery-next",
                        prevEl: ".detalle-gallery-prev",
                    },
                    pagination: {
                        el: ".detalle-gallery-pagination",
                        clickable: true,
                    },
                    touchRatio: 1,
                    simulateTouch: true,
                    allowTouchMove: true,
                    resistanceRatio: 0.65,
                });
            }

            gallerySwiper.update();
            gallerySwiper.slideTo(initialIndex, 0, false);
        });

        modalElement.addEventListener("hidden.bs.modal", function () {
            modalElement.removeEventListener("touchmove", preventModalScroll);
            unlockPageScroll();
            window.setTimeout(blurActiveGalleryControl, 80);
        });
    }

    function updateMarqueeState(item) {
        const marquee = item.querySelector(".detalle-marquee");
        const track = item.querySelector(".detalle-marquee-track");
        const firstText = track ? track.querySelector("span:not([aria-hidden='true'])") : null;

        if (!marquee || !track || !firstText) {
            return;
        }

        item.classList.remove("is-overflowing");
        track.style.removeProperty("animation-duration");

        const visibleWidth = marquee.clientWidth;
        const textWidth = firstText.scrollWidth;
        const shouldAnimate = textWidth > visibleWidth + 4;

        if (!shouldAnimate) {
            return;
        }

        item.classList.add("is-overflowing");

        const duration = Math.max(10, Math.min(30, Math.round(textWidth / 16)));
        track.style.setProperty("animation-duration", `${duration}s`);
    }

    function initAddressMarquees() {
        const items = Array.from(document.querySelectorAll(".detalle-marquee-item"));

        if (!items.length) {
            return;
        }

        const refresh = function () {
            items.forEach(updateMarqueeState);
        };

        refresh();
        window.requestAnimationFrame(refresh);
        window.setTimeout(refresh, 250);
        window.setTimeout(refresh, 900);

        window.addEventListener("load", refresh);
        window.addEventListener("resize", refresh);
        window.addEventListener("orientationchange", function () {
            window.setTimeout(refresh, 250);
            window.setTimeout(refresh, 900);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            initGalleryModal();
            initAddressMarquees();
        });
    } else {
        initGalleryModal();
        initAddressMarquees();
    }
})();
