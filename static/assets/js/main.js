document.addEventListener("DOMContentLoaded", function() {
    // Set current year in footer
    const yearSpan = document.getElementById('current-year');
    if(yearSpan) {
        yearSpan.textContent = new Date().getFullYear();
    }

    // Toasts globales (mensajes de Django fuera de las pantallas de auth)
    document.querySelectorAll('[data-vi-toast]').forEach(function(toast) {
        const dismissAfter = parseInt(toast.dataset.autoDismiss, 10) || 3000;

        const hide = function() {
            if (toast.classList.contains('is-hiding')) return;
            toast.classList.add('is-hiding');
            setTimeout(function() { toast.remove(); }, 200);
        };

        const timer = setTimeout(hide, dismissAfter);
        const closeBtn = toast.querySelector('[data-vi-toast-close]');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                clearTimeout(timer);
                hide();
            });
        }
    });
});
