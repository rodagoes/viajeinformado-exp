// Pruebas de comportamiento (Node, sin dependencias) del modo de ruta de `ubicacion_click`.
// Ejecuta el código REAL de static/assets/js/metricas.js y de desplazable-como-llegar.js sobre un DOM mínimo simulado.
// Lanzado desde Django por apps/metricas/test_real_frontend.py (se omite si Node no está instalado).
'use strict';
const fs = require('fs');
const path = require('path');

const RAIZ = path.resolve(__dirname, '..', '..', '..');
// METRICAS_JS permite probar otra versión del archivo (p. ej. para demostrar que estas pruebas detectan el bug de F.1).
const CODIGO_METRICAS = fs.readFileSync(process.env.METRICAS_JS || path.join(RAIZ, 'static/assets/js/metricas.js'), 'utf8');
const CODIGO_COMPONENTE = fs.readFileSync(path.join(RAIZ, 'static/assets/js/desplazable-como-llegar.js'), 'utf8');

// ---------------------------------------------------------------- DOM mínimo
const kebab = (k) => k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());

class Nodo {
  constructor(etiqueta, attrs = {}, clases = [], hijos = []) {
    this.etiqueta = etiqueta; this.attrs = { ...attrs }; this.clases = new Set(clases);
    this.hijos = []; this.padre = null; this.escuchas = {};
    this.dataset = new Proxy({}, {
      get: (_, k) => this.attrs['data-' + kebab(String(k))],
      set: (_, k, v) => { this.attrs['data-' + kebab(String(k))] = String(v); return true; },
    });
    this.classList = {
      add: (c) => this.clases.add(c), remove: (c) => this.clases.delete(c), contains: (c) => this.clases.has(c),
      toggle: (c, f) => (f ? this.clases.add(c) : this.clases.delete(c)),
    };
    hijos.forEach((h) => this.agregar(h));
  }
  agregar(h) { h.padre = this; this.hijos.push(h); return h; }
  get href() { return this.attrs.href || ''; }
  set href(v) { this.attrs.href = v; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  getAttribute(k) { return this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  addEventListener(tipo, f) { (this.escuchas[tipo] = this.escuchas[tipo] || []).push(f); }
  coincide(selector) {
    return selector.split(',').some((parte) => {
      parte = parte.trim();
      if (parte === '#pcbot-root a[href]') return this.etiqueta === 'a' && this.hasAttribute('href') && this.ancestros().some((n) => n.attrs.id === 'pcbot-root');
      const atributos = [...parte.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
      const clases = [...parte.matchAll(/\.([\w-]+)/g)].map((m) => m[1]);
      if (!atributos.length && !clases.length) return false;
      return atributos.every((m) => (m[2] === undefined ? m[1] in this.attrs : this.attrs[m[1]] === m[2])) && clases.every((c) => this.clases.has(c));
    });
  }
  ancestros() { const r = []; for (let n = this.padre; n; n = n.padre) r.push(n); return r; }
  closest(selector) { for (let n = this; n; n = n.padre) if (n.coincide(selector)) return n; return null; }
  descendientes() { return this.hijos.flatMap((h) => [h, ...h.descendientes()]); }
  querySelectorAll(selector) { return this.descendientes().filter((n) => n.coincide(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  click() { clic(this); }
}

let ahora = 1_000_000;
let enviados = [];
let escuchasDocumento = {};
let raices = [];

function clic(objetivo, tipo = 'click') {
  const evento = { type: tipo, target: objetivo, button: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  for (let n = objetivo; n; n = n.padre) (n.escuchas[tipo] || []).forEach((f) => f(evento));  // burbujeo hasta el documento
  (escuchasDocumento[tipo] || []).forEach((f) => f(evento));
  return evento;
}
const avanzar = (ms = 2000) => { ahora += ms; };  // fuera de la ventana anti doble clic (1,5 s)

function montar({ conComponente = true, htmlHijos }) {
  enviados = []; escuchasDocumento = {}; raices = htmlHijos;
  const documento = {
    currentScript: { dataset: { endpoint: '/metricas/evento/', csrf: 'TOKEN' } }, cookie: '', readyState: 'complete',
    addEventListener: (t, f) => { (escuchasDocumento[t] = escuchasDocumento[t] || []).push(f); },
    querySelectorAll: (s) => raices.flatMap((r) => [r, ...r.descendientes()]).filter((n) => n.coincide(s)),
  };
  const ventana = { location: { href: 'http://localhost/x/', origin: 'http://localhost' }, crypto: { randomUUID: () => 'uuid-' + enviados.length + '-' + ahora } };
  const navegador = { sendBeacon: (url, blob) => { enviados.push(Object.fromEntries(new URLSearchParams(blob.texto))); return true; } };
  class Blob { constructor(p) { this.texto = p.join(''); } }
  const FechaFalsa = { now: () => ahora };
  const ejecutar = (codigo, extra = {}) => new Function('document', 'window', 'navigator', 'URLSearchParams', 'URL', 'Date', 'Blob', 'fetch', 'ViI18n', codigo)(
    documento, ventana, navegador, URLSearchParams, URL, FechaFalsa, Blob, () => Promise.resolve(), (k, f) => f);
  if (conComponente) ejecutar(CODIGO_COMPONENTE);
  ejecutar(CODIGO_METRICAS);
  return { documento };
}

// Bloque "Cómo llegar" tal como lo renderizan las plantillas (lugar / establecimiento / servicio).
const RUTA = 'https://www.google.com/maps/dir/?api=1&destination=-9.93%2C-76.24';
function bloque({ entidadTipo = 'lugar', entidadId = '7', extraEnlace = {} } = {}) {
  const enlace = new Nodo('a', {
    href: RUTA + '&travelmode=walking', target: '_blank', 'data-enlace-ruta': '', 'data-metrica-evento': 'ubicacion_click',
    'data-metrica-via': 'iniciar_ruta', 'data-metrica-modo-desde': 'travelmode', ...extraEnlace,
  });
  const aPie = new Nodo('button', { 'data-modo': 'walking' }, ['du-mode', 'is-active']);
  const auto = new Nodo('button', { 'data-modo': 'driving' }, ['du-mode']);
  const mostrar = new Nodo('button', { 'data-show-dir': '', 'data-metrica-evento': 'ubicacion_click', 'data-metrica-via': 'como_llegar' });
  const abrirMapa = new Nodo('a', { href: RUTA + '&travelmode=driving', 'data-open-link': '', 'data-metrica-evento': 'ubicacion_click', 'data-metrica-via': 'abrir_mapa' });
  const raiz = new Nodo('section', {
    'data-como-llegar': '', 'data-route-url': RUTA, 'data-metrica-entidad-tipo': entidadTipo, 'data-metrica-entidad-id': entidadId,
  }, [], [mostrar, abrirMapa, aPie, auto, enlace]);
  return { raiz, enlace, aPie, auto, mostrar, abrirMapa };
}

// ---------------------------------------------------------------- pruebas
let total = 0, fallos = 0;
function prueba(nombre, f) {
  total++;
  try { f(); console.log('ok   ' + nombre); } catch (e) { fallos++; console.log('FALLA ' + nombre + ' -> ' + e.message); }
}
function igual(real, esperado, mensaje) {
  if (JSON.stringify(real) !== JSON.stringify(esperado)) throw new Error((mensaje || '') + ' esperado=' + JSON.stringify(esperado) + ' real=' + JSON.stringify(real));
}

prueba('flujo completo: a pie -> auto -> a pie usando el componente real y metricas.js reales', () => {
  const b = bloque();
  montar({ htmlHijos: [b.raiz] });
  b.enlace.click();                                    // modo inicial: a pie
  avanzar(); b.auto.click();                           // el usuario elige En auto (el componente reconstruye el href)
  igual(b.enlace.href.split('&').pop(), 'travelmode=driving', 'href tras elegir auto');
  b.enlace.click();                                    // Iniciar ruta
  avanzar(); b.aPie.click(); b.enlace.click();         // vuelve a A pie
  igual(b.enlace.href.split('&').pop(), 'travelmode=walking', 'href tras volver a pie');
  igual(enviados.map((e) => [e.tipo, e.via, e.modo]), [
    ['ubicacion_click', 'iniciar_ruta', 'a_pie'], ['ubicacion_click', 'iniciar_ruta', 'auto'], ['ubicacion_click', 'iniciar_ruta', 'a_pie'],
  ], 'payloads');
  igual(new Set(enviados.map((e) => e.click_id)).size, 3, 'click_id distintos');
  igual([enviados[1].entidad_tipo, enviados[1].entidad_id], ['lugar', '7'], 'entidad heredada del contenedor');
});

prueba('un atributo fijo obsoleto (el bug de F.1) ya no influye: manda el travelmode real', () => {
  const b = bloque({ extraEnlace: { 'data-metrica-modo': 'a_pie' } });  // el valor fijo que causaba el error
  montar({ htmlHijos: [b.raiz] });
  b.auto.click();
  b.enlace.click();
  igual(enviados[0].modo, 'auto', 'modo con atributo fijo a_pie presente');
});

prueba('sin depender de la versión del componente: el modo sigue al href en cada clic (sin caché)', () => {
  const b = bloque();
  montar({ conComponente: false, htmlHijos: [b.raiz] });   // un navegador con otro componente / sin él
  b.enlace.href = RUTA + '&travelmode=driving'; b.enlace.click();
  avanzar(); b.enlace.href = RUTA + '&travelmode=walking'; b.enlace.click();
  avanzar(); b.enlace.href = RUTA + '&travelmode=driving'; b.enlace.click();
  igual(enviados.map((e) => e.modo), ['auto', 'a_pie', 'auto'], 'modos');
});

prueba('modos no mapeados o ausentes no envían modo; como_llegar y abrir_mapa nunca lo envían', () => {
  const b = bloque();
  montar({ conComponente: false, htmlHijos: [b.raiz] });
  b.enlace.href = RUTA + '&travelmode=bicycling'; b.enlace.click();
  avanzar(); b.enlace.href = RUTA; b.enlace.click();
  avanzar(); b.enlace.href = 'no es una url ::::'; b.enlace.click();
  avanzar(); b.mostrar.click();
  avanzar(); b.abrirMapa.click();   // su href lleva travelmode=driving, pero no declara data-metrica-modo-desde
  igual(enviados.map((e) => [e.via, 'modo' in e]), [
    ['iniciar_ruta', false], ['iniciar_ruta', false], ['iniciar_ruta', false], ['como_llegar', false], ['abrir_mapa', false],
  ], 'envíos');
});

prueba('varias instancias: cada enlace usa su propio href y su propia entidad', () => {
  const a = bloque({ entidadTipo: 'lugar', entidadId: '1' });
  const e = bloque({ entidadTipo: 'establecimiento', entidadId: '2' });
  montar({ conComponente: false, htmlHijos: [a.raiz, e.raiz] });
  a.enlace.href = RUTA + '&travelmode=driving';
  e.enlace.href = RUTA + '&travelmode=walking';
  a.enlace.click(); e.enlace.click();
  igual(enviados.map((x) => [x.entidad_tipo, x.entidad_id, x.modo]), [['lugar', '1', 'auto'], ['establecimiento', '2', 'a_pie']], 'instancias');
});

prueba('modal único de Servicios útiles: el servicio abierto y su modo se leen al hacer clic', () => {
  const b = bloque({ entidadTipo: 'servicio', entidadId: undefined });
  delete b.raiz.attrs['data-metrica-entidad-id'];
  montar({ htmlHijos: [b.raiz] });
  b.raiz.dataset.metricaEntidadId = '11'; b.auto.click(); b.enlace.click();        // se abre el servicio 11 y se elige auto
  avanzar(); b.raiz.dataset.metricaEntidadId = '12'; b.aPie.click(); b.enlace.click();  // luego el servicio 12 a pie
  igual(enviados.map((x) => [x.entidad_id, x.modo]), [['11', 'auto'], ['12', 'a_pie']], 'servicios');
});

prueba('anti doble clic: el mismo modo dentro de la ventana cuenta una vez; cambiar de modo cuenta aparte', () => {
  const b = bloque();
  montar({ htmlHijos: [b.raiz] });
  b.enlace.click(); b.enlace.click();                  // doble clic involuntario a pie
  igual(enviados.length, 1, 'doble clic');
  b.auto.click(); b.enlace.click();                    // cambia de modo de inmediato: es otra acción explícita
  igual(enviados.map((e) => e.modo), ['a_pie', 'auto'], 'modos');
  avanzar(); b.enlace.click();                         // pasada la ventana, el mismo clic vuelve a contar
  igual(enviados.length, 3, 'clic posterior');
});

prueba('no altera el comportamiento del enlace', () => {
  const b = bloque();
  montar({ htmlHijos: [b.raiz] });
  const evento = clic(b.enlace);
  igual(evento.defaultPrevented, false, 'preventDefault no llamado');
});

console.log((fallos ? 'FALLARON ' + fallos + ' de ' : 'OK ') + total + ' pruebas');
process.exit(fallos ? 1 : 0);
