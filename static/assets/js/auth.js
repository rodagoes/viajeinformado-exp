/* Auth: toggle de contraseña, checklist en vivo y cooldown de reenvío OTP. */
(function () {
  'use strict';

  // Mostrar / ocultar contraseña
  document.querySelectorAll('.vi-auth-toggle-pass').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = btn.parentElement.querySelector('input');
      var icon = btn.querySelector('i');
      var visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      icon.className = visible ? 'bi bi-eye' : 'bi bi-eye-slash';
    });
  });

  // Checklist de contraseña (solo registro)
  var checklist = document.getElementById('password-checklist');
  if (checklist) {
    var pass1 = document.getElementById('id_password1');
    var pass2 = document.getElementById('id_password2');
    var reglas = {
      len: function (v) { return v.length >= 8; },
      upper: function (v) { return /[A-ZÁÉÍÓÚÑ]/.test(v); },
      lower: function (v) { return /[a-záéíóúñ]/.test(v); },
      digit: function (v) { return /\d/.test(v); },
      symbol: function (v) { return /[^A-Za-z0-9ÁÉÍÓÚÑáéíóúñ\s]/.test(v); },
      match: function (v) { return v.length > 0 && pass2 && v === pass2.value; }
    };
    var actualizar = function () {
      var v = pass1 ? pass1.value : '';
      checklist.querySelectorAll('li').forEach(function (li) {
        li.classList.toggle('ok', reglas[li.dataset.check](v));
      });
    };
    if (pass1) pass1.addEventListener('input', actualizar);
    if (pass2) pass2.addEventListener('input', actualizar);
  }

  // Cooldown de reenvío de OTP
  var btnReenviar = document.getElementById('btn-reenviar');
  if (btnReenviar) {
    var restante = parseInt(btnReenviar.dataset.cooldown || '0', 10);
    var label = document.getElementById('cooldown-label');
    if (restante > 0) {
      var tick = function () {
        if (restante <= 0) {
          btnReenviar.disabled = false;
          label.textContent = '';
          return;
        }
        label.textContent = ' (' + restante + 's)';
        restante -= 1;
        setTimeout(tick, 1000);
      };
      tick();
    }
  }

  // Solo dígitos en el input OTP
  var otp = document.querySelector('.vi-auth-otp-input');
  if (otp) {
    otp.addEventListener('input', function () {
      otp.value = otp.value.replace(/\D/g, '').slice(0, 4);
    });
  }

  // Cuenta regresiva y redirección tras verificar OTP correctamente
  var otpSuccess = document.getElementById('otp-success');
  if (otpSuccess) {
    var restanteRedirect = parseInt(otpSuccess.dataset.redirectSeconds || '4', 10);
    var destino = otpSuccess.dataset.redirectUrl;
    var countdownEl = document.getElementById('otp-success-countdown');
    var tickRedirect = function () {
      if (restanteRedirect <= 0) {
        window.location.href = destino;
        return;
      }
      if (countdownEl) countdownEl.textContent = restanteRedirect;
      restanteRedirect -= 1;
      setTimeout(tickRedirect, 1000);
    };
    tickRedirect();
  }
})();
