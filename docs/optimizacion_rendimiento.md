# Optimización de rendimiento, accesibilidad y SEO (rama `optimizacion-v1`)

Medido con Lighthouse 12 (móvil, throttling simulado) contra `runserver` local. El servidor de desarrollo no comprime
ni cachea, así que los números absolutos de CSS/JS son más pesados que en producción; lo comparable es antes/después.

## Causas encontradas

| Hallazgo | Causa real | Solución aplicada |
|---|---|---|
| LCP móvil 10,9 s | El LCP es la primera imagen del hero: un PNG de 2,9 MB (`media/home/hero/*.png`). Ya llevaba `fetchpriority="high"` y sin `lazy`; el problema era el peso | `HomeHeroSlide.save()` convierte las imágenes subidas a WebP (≤2000 px, q85, ~370 KB). Ver «Hero» |
| Imágenes pesadas en chrome del sitio | Logo del header (PNG 600 KB para 162 px), `pillcobot.webp` (186 KB para ≤92 px) y `logo-footer.webp` (167 KB para ≤190 px) | Reescalados a ~2-3× del tamaño de render (WebP). Footer con `width`/`height` y `loading="lazy"` |
| Lottie | `base.html` cargaba `lottie-player@latest` desde UNPKG en todas las páginas (100 KB sin usar en la mayoría) y competía con el LCP. `static/assets/js/lottie-player.js` era HTML de UNPKG guardado como `.js`, sin ninguna referencia | Archivo eliminado. Versión fija `2.0.12` (jsDelivr, mismo origen que Bootstrap) en `partials/lottie_js.html`, incluido solo en las 6 páginas que usan `<lottie-player>` y cargado tras el evento `load` |
| Animate.css (CDN) | 4 páginas lo cargaban solo para `animate__animated` + `animate__fadeInUp`; el proyecto ya redefinía el keyframe | Eliminado el CDN; las 2 reglas viven en `animaciones-entrada.css` |
| A11y: `tablist` sin `tab` | Los bullets del hero y los puntos del carrusel 3D son botones de navegación, no tabs/tabpanels | `role="group"` (cada botón conserva `aria-label` y `aria-current`) |
| A11y: salto de encabezado | «Pillco Bot» del mockup era `<h5>` sin ser estructural | `<p class="h5 …">` + `font-family` en `home.css` (mismo aspecto) |
| A11y: `role="group"` en `<form>` | ARIA no permitido en `form` | El `role` + `aria-labelledby` pasan a un `<div>` interior (misma clase CSS) |
| A11y (listados/detalle) | `<select>` sin nombre, estrellas `span` con `aria-label` sin rol, `tablist` en carrusel 3D, `h3` sin `h2` | `aria-label` con msgids existentes, `role="img"`, `role="group"`, `<h2 class="visually-hidden">Resultados</h2>` |
| SEO: sin meta description | No existía | `{% block meta_description %}` en `base.html` (fallback traducido). Cada página reutiliza el texto de su hero (ya traducido); detalles usan `descripcion_corta`/`descripcion` truncada a 155 |
| SEO: títulos genéricos | Listados y detalles heredaban «Viaje Informado • Huánuco» | Título con el nombre/título de la página |
| Consola: 404 | No había favicon (`/favicon.ico`) | `favicon-viaje-informado.ico` enlazado en `base.html` |

## Hero

`apps/base/models.py` → `_a_webp()` se ejecuta solo para `tipo_archivo == 'image'` y archivos recién subidos. Reduce, nunca
amplía. Los GIF y videos no se tocan. Si Pillow no puede leer el archivo se conserva el original.

Los slides ya existentes **no se convierten solos**: en producción hay que volver a guardar cada slide desde el Admin
(re-subir la imagen) o ejecutar una vez un `shell` equivalente al de la sección siguiente. Los originales no se borran.

```python
from django.core.files import File
from apps.base.models import HomeHeroSlide
for s in HomeHeroSlide.objects.filter(tipo_archivo="image"):
    with open(s.archivo.path, "rb") as f:
        s.archivo = File(f, name=s.archivo.name.split("/")[-1])
        s.save()
```

## Caché (propuesta — NO aplicada)

Los ~1384 KiB «sin caché eficiente» de PageSpeed son los archivos propios de `/static/` (logos, `pillcobot.*`, CSS/JS) servidos
sin `Cache-Control` largo. No se tocó Nginx ni `settings`:

- `/static/` **no tiene nombres versionados** (`StaticFilesStorage` por defecto): `immutable` serviría CSS/JS obsoletos tras
  cada despliegue. Con la configuración actual lo máximo prudente es `expires 7d; add_header Cache-Control "public";`.
- Opción robusta: `ManifestStaticFilesStorage` en `production.py` + `expires 1y; Cache-Control "public, immutable"`. Probado en
  local: `collectstatic` funciona, pero con `DEBUG=False` el manifest estricto falla donde el código llama a `static()` con
  nombres que no existen (p. ej. `assets/img/eventos/reco-programacion.svg`, `apps/eventos/views.py`) y varios tests comparan
  nombres exactos. Hay que corregir eso (o usar una subclase con `manifest_strict = False`) antes de activarlo.
- `/media/`: Django nunca sobrescribe un archivo (añade sufijo), así que la URL cambia al re-subir; admite `expires 30d`.

## Descartado (no justifica la complejidad)

- Self-hosting de Bootstrap/Bootstrap Icons/Google Fonts: añade ~600 KB de vendor al repo; no se pudo medir de forma justa
  sin compresión en el servidor de desarrollo. Reevaluar si se acepta mantener esos archivos.
- Cargar la hoja de Google Fonts de forma no bloqueante: medido, sin mejora (el cuello está en Bootstrap/iconos).
- Minificar CSS/JS propio (~28 KiB + 25 KiB sin comprimir): exige una cadena de build; con gzip en Nginx el ahorro real es ~10 KiB.
- Eliminar CSS/JS «sin usar» (Bootstrap, `pillcobot.*`, `header.css`): se usa en modales, offcanvas, chatbot y páginas que
  Lighthouse no ve en una sola carga.
- `defer` en `pillcobot.js`/`main.js`: cambia el orden de ejecución respecto a scripts de página; ganancia mínima.
- Animación no compuesta: es `stroke-dashoffset` del anillo de progreso (SVG, 18 px). No se puede componer y cambiarla
  implicaría rediseñar el control.
- Redistribución forzada (`animaciones-scroll.js:29`, `home.js` `offsetWidth`): lecturas puntuales necesarias (≈1-55 ms); no hay
  patrón lectura/escritura intercalado en bucle.
- `srcset`/`picture` en el hero: la imagen de 1448 px en WebP pesa ~250 KB; varias variantes obligarían a guardar más archivos
  por slide.
- `hreflang`: el idioma se elige por cookie/POST (`set_language`), no por URL; no hay URLs alternativas que anunciar.
- Contraste de color en varias páginas (eyebrows, chips, precios), `target-size` de los puntos del carrusel 3D y
  `label-content-name-mismatch`: requieren decisión de diseño, el diseño está aprobado.

## V2 (rama `optimizacion-v2`)

- **Destello gris del hero:** los slides 2+ son `loading="lazy"` (para no competir con el LCP). Al iniciar el crossfade la
  imagen entrante aún no se había pedido; cuando el saliente pasaba a `opacity: 0` se veía el fondo de la página (`#f7f8fa`).
  Bootstrap `carousel-fade` ya hace un crossfade correcto (el saliente se queda en 1 hasta que el entrante llega a 1).
  `home.js` → `precargar()` pide el siguiente slide tras `load` y en cada cambio (con `decode()`), sin precargar todos.
  Salto manual (puntos/flechas) a un slide aún no descargado: el handler de `slide.bs.carousel` cancela la transición,
  espera a `decode()` de esa imagen y reanuda con `carousel.to()`; si el usuario elige otro destino mientras tanto, gana el último.
- **Nitidez:** WebP q75 suavizaba la textura fina (ladrillos, melena) y los móviles amplían la imagen ~1,7×. Ahora q85,
  filtro Lanczos y ancho máx. 2000 px. Los slides ya subidos **no se reprocesan**: hay que re-subir los originales.
  Las fuentes originales miden 1448 px (vi1/vi2) y 1974 px (vi3): más resolución en móvil exige originales mayores.
- **Lottie:** el script solo se pide cuando un `<lottie-player>` está a ≤300 px de verse (antes, tras `load`).
- **Logo/bot:** logo 450×150 (29 KB), `pillcobot.webp` 192 px (16 KB).
- **Techo móvil (Lighthouse simulado):** con un hero artificialmente de ~100 KB el Home sólo llega a ~91 (FCP 2,3 s lo fija
  la cadena Bootstrap/Icons/Google Fonts en CDN). Con hero de calidad (~370 KB) el rango es 80-85 local. 97+ exigiría
  degradar el hero o rehacer la entrega de CSS/fuentes.
- **Self-hosting de Bootstrap, Icons y fuentes:** probado con un proxy gzip local: no mejoró (FCP 2,6-2,9 s vs 2,3 s,
  LCP 5,8 s vs 4,4 s). Descartado.
- **Favicon `.ico`:** pesa ~122 KB (capas PNG grandes); se carga tras `load`, no afecta al LCP, pero conviene regenerarlo
  (16/32/48 px ≈ 15 KB).

## V3 (rama `optimizacion-v3`)

Medido con un proxy de medición local **HTTP/2 + gzip** (emula Nginx; no es parte del proyecto) y Lighthouse 12 móvil.
Mediana de 3-5 corridas; la dispersión del LCP simulado es ±0,5 s entre corridas (bimodal 3,1 / 4,0 s).

**Desglose del LCP (local sin throttling):** TTFB 20 ms, load delay 17 ms, load duration 58 ms, **render delay 863 ms**.
La imagen llega a los ~95 ms; el primer pintado espera al CSS de Google Fonts (el último bloqueante, ~780 ms).
Con throttling simulado el LCP es FCP + descarga del hero (~1,5 s de ancho de banda compartido con CSS/JS/logos).
`fetchpriority="high"` funciona (Prioridad High, pedido a los ~50 ms, sin preload redundante); `decoding="async"` no
cambia nada (3 corridas sin él: igual).

| Cambio | Resultado (mediana) |
|---|---|
| Base (V2, h2) | perf 78, FCP 2,2 s, LCP 5,2 s |
| + recorte móvil del hero (`<picture>`) | perf 88, FCP 2,2 s, LCP 3,5 s |
| + Google Fonts sin bloquear el render | perf 92, FCP 1,9 s, LCP 3,1 s |

- **Hero móvil:** `HomeHeroSlide.archivo_movil` (no editable, se genera sola al subir) = recorte central de aspecto 0,65
  (altura ≤1500 px, WebP q85). Son los mismos píxeles que `object-fit: cover; object-position: center` ya muestra en <576 px,
  así que no pierde nitidez: 365→164 KB, 389→186 KB, 361→107 KB. ≥576 px y escritorio siguen con la imagen completa.
  Imágenes ya casi verticales no generan recorte. Si la imagen subida ya es WebP, el recorte se re-codifica una vez desde ella:
  para la mejor calidad, re-subir el original. Los slides existentes no tienen recorte hasta volver a guardarlos (snippet de «Hero»).
- **Google Fonts:** `media="print" onload` + `<noscript>`. Texto con fuente de reserva hasta que llega la web font
  (`display=swap` ya estaba); CLS sin cambios (0,048).
- **Precarga del slide 2:** se pide tras `load` con prioridad Low (~0,8 s en local, después del LCP). Quitarla no mejoró
  el LCP (3 corridas), así que se deja como está: es lo que evita el flash gris.

**Descartado (medido):**
- Self-hosting de Bootstrap, Icons y fuentes con HTTP/2: perf 86, FCP 2,3 s (sin mejora), LCP 3,8 s y TBT 80 ms (peor que con CDN) y +~600 KB de vendor.
- Bootstrap Icons sin bloquear: FCP 1,9→1,8 s, a cambio de iconos sin estilo en el primer pintado.
- CSS propios no críticos (footer, pillcobot, skeleton) con `media="print"`: sin cambio de FCP.
- `pillcobot.js` bajo demanda: quitarlo por completo no mejoró nada medible (JS al final del body, 11 KB gzip); no justifica el riesgo con métricas/primer clic.
- Minificar / purgar CSS-JS: ≈10 KB con gzip; sin pipeline de build no compensa.

**Techo:** ~92 local (LCP 3,1 s). Lo que queda es ancho de banda: ~300 KB antes del LCP (hero 164 KB + logo, bot, Bootstrap CSS/JS)
a 1,6 Mbps. Bajarlo más exige degradar el hero o quitar Bootstrap de la ruta crítica.

### Caché de producción (propuesta Nginx, NO aplicada)

Solo ayuda a visitas repetidas (los ~988 KiB «sin TTL» ya están descargados); no cambia el LCP de una primera visita.

```nginx
location /static/ { expires 7d; add_header Cache-Control "public"; }   # nombres sin hash: nada de immutable/1y
location /media/  { expires 30d; add_header Cache-Control "public"; }  # Django no sobrescribe: re-subir cambia la URL
```
Terceros (jsDelivr, Google Fonts) ya traen su propio `Cache-Control`.

## V4 (rama `optimizacion-v4`)

Misma metodología que V3 (proxy local HTTP/2 + gzip, Lighthouse 12 móvil), más corridas con `--throttling-method=devtools`
(red real estrangulada, sin simulación) para comprobar que las conclusiones no dependen de Lantern. El LCP simulado oscila
±0,5 s entre corridas idénticas, así que solo cuenta lo que se repite en pares A/B alternados.

**Aplicado: assets pequeños** (-18 KB antes del LCP, sin cambio visual)
- Logo del header 450×150 → 330×110 (29 → 19 KB, WebP q85 desde el PNG original). Se muestra a 126-162×42-54 px: 2× en escritorio, 3× en móviles.
- Icono del botón flotante/avatar del Pillco Bot: nuevo `pillcobot-sm.webp` 120 px (16 → 7,5 KB) en `includes/pillcobot.html` (se muestra a 36-40 px). La mockup del Home sigue usando `pillcobot.webp` (192 px).
- En Lighthouse el efecto no se distingue del ruido (perf 84-92 en ambos lados); el beneficio es de bytes reales en primera carga.

**CSS bloqueante (Home carga 12 hojas):** Bootstrap, Icons (CDN) + main, header, pages, home, footer, responsive, pillcobot,
skeleton, animaciones-entrada (propias, h2, 0,3-22 KB cada una, ≈80 KB sin comprimir en total).

| CSS | Tamaño | Clases usadas en Home | Veredicto |
|---|---:|---:|---|
| main / header / home | 4,7 / 21 / 20 KB | 86 / 90 / 83 % | Críticos (layout inicial, header, hero) |
| pillcobot | 22 KB | 96 % | Botón flotante visible desde el primer pintado |
| footer | 18 KB | 91 % | Below the fold, pero diferirlo no mejora (abajo) |
| skeleton / animaciones-entrada | 1,7 / 3,1 KB | 100 / 62 % | Mínimos |
| pages | 4 KB | 40 % | Se podría mover a otras páginas: -2 KB, no compensa |
| responsive | 0,3 KB | 0 % | Casi vacío |

Prueba de techo: diferir con `media="print" onload` footer, pillcobot, skeleton, pages, responsive, animaciones **e** Icons
a la vez → FCP 2,1-2,6 s vs 2,0-2,3 s de la base (no mejora; con 12 pedidos h2 en paralelo el CSS propio no es el cuello).
Con throttling real, Icons diferido tampoco cambió el LCP (3,5 vs 3,4-3,7 s) y una corrida bajó Best Practices a 96.
Descartado: no hay CSS propio muerto relevante (80-96 % usado) y diferirlo no compensa el riesgo de FOUC.

**Bootstrap Icons:** Home renderiza ~42 iconos distintos (header, footer, Pillco Bot, mockup) más 9 que inyecta
`pillcobot.js`/`home.js`, y el resto del sitio los usa por todas partes (`bi-*` en casi todas las plantillas). Reemplazarlos por
SVG sería una librería casera y una carga condicional es imposible (header y footer son globales). Se mantiene el CDN
(CSS 13 KB + woff2 128 KB); subsetear la fuente exige herramienta de build y regenerar al añadir cada icono.

**Bootstrap CSS:** sin cambios (ver V3: self-hosting HTTP/2 medido peor). **Minificación:** sin herramienta ya disponible en
el proyecto; ~10 KB reales con gzip (30 KB CSS / 27 KB JS son sin comprimir). Exigiría build + archivos duplicados. Descartado.
**`stroke-dashoffset` del anillo del hero:** anillo SVG de 18 px; no es medible en TBT (0-40 ms) ni toca CLS (0,048). Se deja.

**Techo:** ~88-92 local con el simulador; lo que queda es FCP ≈ HTML + Bootstrap CSS desde un origen de CDN (≈2 s simulados)
y ~300 KB de ancho de banda antes del LCP. Bajarlo más exige quitar Bootstrap de la ruta crítica (Critical CSS duplicado o
purga), que es deuda técnica.

### Caché de producción (Nginx) — instrucciones, NO aplicadas

Dentro del `server { ... }` del sitio (los `location` ya existentes de `/static/` y `/media/` deben conservar su `alias`/`root`):

```nginx
location /static/ {
    alias /ruta/a/staticfiles/;        # el que ya tengas
    expires 7d;
    add_header Cache-Control "public";
}
location /media/ {
    alias /ruta/a/media/;              # el que ya tengas
    expires 30d;
    add_header Cache-Control "public";
}
```
1. `sudo nginx -t` y `sudo systemctl reload nginx` (reload, no restart).
2. Verificar: `curl -sI https://DOMINIO/static/assets/css/home.css | grep -i -E "cache-control|expires"` → `max-age=604800`; igual con una imagen de `/media/` → `max-age=2592000`.
3. Rollback: quitar las dos líneas `expires`/`add_header` y `reload`.
- `/static/` no lleva hash en el nombre: sin `immutable` ni 1 año. Tras cada despliegue que cambie CSS/JS, los visitantes recurrentes pueden tardar hasta 7 días en verlo; si es un problema, bajar a `1d` o activar un manifest de estáticos (V3).
- `/media/`: Django no sobrescribe, re-subir un archivo cambia su URL.
- `add_header` dentro de un `location` anula los `add_header` heredados del `server`; repetir allí los de seguridad si los hay.
- Mejora visitas repetidas; no cambia el LCP de una primera visita.
