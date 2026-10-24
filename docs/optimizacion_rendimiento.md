# Optimización de rendimiento, accesibilidad y SEO (rama `optimizacion-v1`)

Medido con Lighthouse 12 (móvil, throttling simulado) contra `runserver` local. El servidor de desarrollo no comprime
ni cachea, así que los números absolutos de CSS/JS son más pesados que en producción; lo comparable es antes/después.

## Causas encontradas

| Hallazgo | Causa real | Solución aplicada |
|---|---|---|
| LCP móvil 10,9 s | El LCP es la primera imagen del hero: un PNG de 2,9 MB (`media/home/hero/*.png`). Ya llevaba `fetchpriority="high"` y sin `lazy`; el problema era el peso | `HomeHeroSlide.save()` convierte las imágenes subidas a WebP (≤1600 px, ~250 KB). Ver «Hero» |
| Imágenes pesadas en chrome del sitio | Logo del header (PNG 600 KB para 162 px), `pillcobot.webp` (186 KB para ≤92 px) y `logo-footer.webp` (167 KB para ≤190 px) | Reescalados a ~2-3× del tamaño de render (WebP). Footer con `width`/`height` y `loading="lazy"` |
| Lottie | `base.html` cargaba `lottie-player@latest` desde UNPKG en todas las páginas (100 KB sin usar en la mayoría) y competía con el LCP. `static/assets/js/lottie-player.js` era HTML de UNPKG guardado como `.js`, sin ninguna referencia | Archivo eliminado. Versión fija `2.0.12` (jsDelivr, mismo origen que Bootstrap) en `partials/lottie_js.html`, incluido solo en las 6 páginas que usan `<lottie-player>` y cargado tras el evento `load` |
| Animate.css (CDN) | 4 páginas lo cargaban solo para `animate__animated` + `animate__fadeInUp`; el proyecto ya redefinía el keyframe | Eliminado el CDN; las 2 reglas viven en `animaciones-entrada.css` |
| A11y: `tablist` sin `tab` | Los bullets del hero y los puntos del carrusel 3D son botones de navegación, no tabs/tabpanels | `role="group"` (cada botón conserva `aria-label` y `aria-current`) |
| A11y: salto de encabezado | «Pillco Bot» del mockup era `<h5>` sin ser estructural | `<p class="h5 …">` + `font-family` en `home.css` (mismo aspecto) |
| A11y: `role="group"` en `<form>` | ARIA no permitido en `form` | El `role` + `aria-labelledby` pasan a un `<div>` interior (misma clase CSS) |
| A11y (listados/detalle) | `<select>` sin nombre, estrellas `span` con `aria-label` sin rol, `tablist` en carrusel 3D, `h3` sin `h2` | `aria-label` con msgids existentes, `role="img"`, `role="group"`, `<h2 class="visually-hidden">Resultados</h2>` |
| SEO: sin meta description | No existía | `{% block meta_description %}` en `base.html` (fallback traducido). Cada página reutiliza el texto de su hero (ya traducido); detalles usan `descripcion_corta`/`descripcion` truncada a 155 |
| SEO: títulos genéricos | Listados y detalles heredaban «Viaje Informado • Huánuco» | Título con el nombre/título de la página |
| Consola: 404 | No había favicon (`/favicon.ico`) | `favicon.png` (96 px) enlazado en `base.html` |

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
