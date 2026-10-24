// Pruebas de comportamiento (Node, sin dependencias) del tiempo visible de metricas.js (heartbeat, visibilitychange, pagehide).
// Ejecuta el código REAL de static/assets/js/metricas.js con relojes, temporizadores y eventos simulados.
// Lanzado desde Django por apps/metricas/test_real_duracion.py (se omite si Node no está instalado).
'use strict';
const fs = require('fs');
const path = require('path');

const RAIZ = path.resolve(__dirname, '..', '..', '..');
// METRICAS_JS permite probar otra versión del archivo (para comprobar que estas pruebas detectan regresiones).
const CODIGO = fs.readFileSync(process.env.METRICAS_JS || path.join(RAIZ, 'static/assets/js/metricas.js'), 'utf8');
const URL_DURACION = '/metricas/duracion/';

let ahora, temporizadores, escuchasDoc, escuchasVentana, enviados, visibilidad, beaconAcepta, respuestaFetch;

function montar({ conDuracion = true } = {}) {
  ahora = 1_000_000; temporizadores = []; escuchasDoc = {}; escuchasVentana = {}; enviados = []; visibilidad = 'visible';
  beaconAcepta = true; respuestaFetch = () => Promise.resolve({ status: 204 });
  const documento = {
    currentScript: { dataset: { endpoint: '/metricas/evento/', csrf: 'TOKEN', ...(conDuracion ? { duracion: URL_DURACION } : {}) } },
    cookie: '',
    get visibilityState() { return visibilidad; },
    addEventListener: (t, f) => { (escuchasDoc[t] = escuchasDoc[t] || []).push(f); },
  };
  const ventana = {
    location: { href: 'http://localhost/x/', origin: 'http://localhost' }, crypto: { randomUUID: () => 'u' },
    addEventListener: (t, f) => { (escuchasVentana[t] = escuchasVentana[t] || []).push(f); },
  };
  const navegador = {
    sendBeacon: (url, blob) => { if (!beaconAcepta) return false; enviados.push({ via: 'beacon', url, ...Object.fromEntries(new URLSearchParams(blob.texto)) }); return true; },
  };
  class Blob { constructor(p) { this.texto = p.join(''); } }
  const fetchFalso = (url, op) => { enviados.push({ via: 'fetch', url, keepalive: op.keepalive, ...Object.fromEntries(new URLSearchParams(op.body)) }); return respuestaFetch(); };
  const setIntervalFalso = (f, ms) => { const t = { f, ms, proximo: ahora + ms, activo: true }; temporizadores.push(t); return t; };
  const clearIntervalFalso = (t) => { if (t) t.activo = false; };
  new Function('document', 'window', 'navigator', 'URLSearchParams', 'URL', 'Date', 'Blob', 'fetch', 'setInterval', 'clearInterval', CODIGO)(
    documento, ventana, navegador, URLSearchParams, URL, { now: () => ahora }, Blob, fetchFalso, setIntervalFalso, clearIntervalFalso);
}

// Avanza el reloj ejecutando los temporizadores que venzan (como lo haría el navegador).
function pasar(ms) {
  const meta = ahora + ms;
  for (;;) {
    const vivos = temporizadores.filter((t) => t.activo && t.proximo <= meta);
    if (!vivos.length) break;
    const t = vivos.sort((a, b) => a.proximo - b.proximo)[0];
    ahora = t.proximo; t.proximo += t.ms; t.f();
  }
  ahora = meta;
}
const tick = () => temporizadores.filter((t) => t.activo).forEach((t) => t.f());
const disparar = (donde, tipo, evento = {}) => ((donde === 'doc' ? escuchasDoc : escuchasVentana)[tipo] || []).forEach((f) => f(evento));
const cambiarVisibilidad = (estado) => { visibilidad = estado; disparar('doc', 'visibilitychange'); };
const interactuar = () => disparar('doc', 'pointerdown');
const segundos = () => enviados.map((e) => Number(e.segundos));
const suma = () => segundos().reduce((a, b) => a + b, 0);

let total = 0, fallos = 0;
async function prueba(nombre, f) {
  total++;
  try { await f(); console.log('ok   ' + nombre); } catch (e) { fallos++; console.log('FALLA ' + nombre + ' -> ' + e.message); }
}
function igual(real, esperado, mensaje) {
  if (JSON.stringify(real) !== JSON.stringify(esperado)) throw new Error((mensaje || '') + ' esperado=' + JSON.stringify(esperado) + ' real=' + JSON.stringify(real));
}

(async () => {
  await prueba('heartbeat cada 30 s con la pestaña visible: incrementos pequeños en segundos enteros', () => {
    montar(); interactuar();
    pasar(30000); pasar(30000); pasar(30000);
    igual(segundos(), [30, 30, 30], 'incrementos');
    igual(enviados.every((e) => e.url === URL_DURACION && e.csrfmiddlewaretoken === 'TOKEN' && e.keepalive === true), true, 'url, csrf y keepalive');
    igual(Object.keys(enviados[0]).sort(), ['csrfmiddlewaretoken', 'keepalive', 'segundos', 'url', 'via'], 'solo segundos y csrf (sin ids ni marcas de tiempo)');
  });

  await prueba('ocultar la pestaña envía lo pendiente (beacon) y el tiempo oculto no se suma', () => {
    montar(); interactuar();
    pasar(30000);                 // heartbeat: 30 s
    pasar(15000);                 // 15 s más visibles sin enviar
    cambiarVisibilidad('hidden'); // al ocultar sale lo pendiente
    igual(enviados.map((e) => [e.via, Number(e.segundos)]), [['fetch', 30], ['beacon', 15]], 'al ocultar');
    pasar(10 * 60 * 1000);        // 10 min oculta: ni heartbeat ni suma
    igual(enviados.length, 2, 'oculta no envía');
    cambiarVisibilidad('visible'); // vuelve: se reinicia el punto de control
    pasar(15000);
    igual(suma(), 30 + 15 + 15, 'solo tiempo visible (45 s antes + 15 s después), no los 10 min ocultos');
  });

  await prueba('pagehide envía lo pendiente y no hay doble envío', () => {
    montar(); interactuar();
    pasar(12000);
    disparar('ventana', 'pagehide');
    igual(enviados.map((e) => [e.via, Number(e.segundos)]), [['beacon', 12]], 'pagehide');
    disparar('ventana', 'pagehide'); cambiarVisibilidad('hidden'); disparar('ventana', 'pagehide');
    igual(enviados.length, 1, 'sin reenvío de la misma ventana');
  });

  await prueba('si sendBeacon rechaza el envío se usa fetch keepalive', () => {
    montar(); interactuar(); beaconAcepta = false;
    pasar(8000); disparar('ventana', 'pagehide');
    igual(enviados.map((e) => [e.via, Number(e.segundos), e.keepalive]), [['fetch', 8, true]], 'respaldo');
  });

  await prueba('el heartbeat no envía mientras la pestaña está oculta', () => {
    montar(); interactuar(); cambiarVisibilidad('hidden');
    pasar(5 * 60 * 1000);
    igual(enviados, [], 'sin envíos');
  });

  await prueba('una pestaña olvidada deja de sumar tras 5 minutos sin interacción y se reanuda con la siguiente', () => {
    montar();                    // sin interacción posterior al inicio
    pasar(15 * 60 * 1000);       // 15 min visible pero inactiva
    igual(suma(), 300, 'solo los primeros 5 min');
    interactuar(); pasar(30000);
    igual(suma(), 330, 'tras interactuar vuelve a sumar');
  });

  await prueba('con interacciones periódicas la sesión visible suma todo el tiempo', () => {
    montar();
    for (let i = 0; i < 5; i++) { pasar(120000); interactuar(); }
    igual(suma(), 600, 'diez minutos activos');
  });

  await prueba('mostrar la pestaña cuenta como interacción (no hereda una inactividad previa)', () => {
    montar(); pasar(30000);
    cambiarVisibilidad('hidden'); pasar(20 * 60 * 1000); cambiarVisibilidad('visible');
    pasar(30000);
    igual(suma(), 60, '30 s antes + 30 s después');
  });

  await prueba('el envío nunca supera el máximo por solicitud (60 s) y el resto acumulado está acotado', () => {
    montar(); interactuar();
    ahora += 200000;             // 200 s sin que corra ningún temporizador (p. ej. suspensión del equipo)
    tick(); tick(); tick();
    igual(segundos(), [60, 60], 'máx. 60 s por envío; lo que excede el tope no se acumula sin límite');
  });

  await prueba('respuesta 410 (sin sesión vigente): se detienen los heartbeats de la página', async () => {
    montar(); interactuar();
    respuestaFetch = () => Promise.resolve({ status: 410 });
    pasar(30000);
    await Promise.resolve(); await Promise.resolve();
    igual(enviados.length, 1, 'primer heartbeat');
    pasar(5 * 60 * 1000);
    igual(enviados.length, 1, 'no vuelve a enviar');
  });

  await prueba('un fallo de red no genera errores visibles ni detiene la medición', async () => {
    montar(); interactuar();
    respuestaFetch = () => Promise.reject(new Error('sin red'));
    pasar(30000); await Promise.resolve(); await Promise.resolve();
    respuestaFetch = () => Promise.resolve({ status: 204 });
    pasar(30000);
    igual(segundos(), [30, 30], 'sigue enviando');
  });

  await prueba('sin data-duracion (seguimiento apagado) no hay temporizadores, listeners de tiempo ni envíos', () => {
    montar({ conDuracion: false });
    igual(temporizadores.length, 0, 'temporizadores');
    igual(['visibilitychange', 'pointerdown', 'keydown', 'scroll', 'touchstart'].every((t) => !escuchasDoc[t]), true, 'listeners del documento');
    igual(!escuchasVentana.pagehide && !escuchasVentana.pageshow, true, 'listeners de ventana');
    cambiarVisibilidad('hidden'); pasar(60000);
    igual(enviados, [], 'sin envíos');
  });

  console.log((fallos ? 'FALLARON ' + fallos + ' de ' : 'OK ') + total + ' pruebas');
  process.exit(fallos ? 1 : 0);
})();
