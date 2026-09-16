/**
 * pillcobot.js — Viaje Informado
 *
 * Widget de chat de PillcoBot: abrir/cerrar, quick actions, envío de
 * mensajes contra POST /chatbot/mensaje/, render de texto/mini cards/fuentes
 * oficiales y estados de carga/error. Sin frameworks, sin streaming.
 */
(function () {
    'use strict';

    var root = document.getElementById('pcbot-root');
    if (!root) return;

    var endpoint = root.dataset.endpoint;
    var fab = document.getElementById('pcbot-fab');
    var backdrop = document.getElementById('pcbot-backdrop');
    var panel = document.getElementById('pcbot-panel');
    var messagesEl = document.getElementById('pcbot-messages');
    var form = document.getElementById('pcbot-form');
    var input = document.getElementById('pcbot-input');
    var sendBtn = document.getElementById('pcbot-send');
    var closeBtn = document.getElementById('pcbot-close');
    var minimizeBtn = document.getElementById('pcbot-minimize');
    var dragHandle = document.getElementById('pcbot-draghandle');

    var CTA_LINEA = /^(Ver[^:]+):\s*(\S+)$/;
    // Nombres de ciudad tal como los produce response_renderers.renderizar_clima
    // ("Clima actual en <ubicacion>") — ver apps/clima/ubicaciones.py.
    var CIUDADES_CLIMA = {
        'huánuco (ciudad)': { slug: 'huanuco', nombre: 'Huánuco' },
        'tingo maría (ciudad)': { slug: 'tingo-maria', nombre: 'Tingo María' },
    };

    var QUICK_ACTIONS = [
        { id: 'clima_huanuco', label: 'Clima en Huánuco', icon: 'bi-cloud-sun' },
        { id: 'clima_tingo_maria', label: 'Clima en Tingo María', icon: 'bi-cloud-sun' },
        { id: 'eventos_proximos', label: 'Eventos próximos', icon: 'bi-calendar-event' },
        { id: 'platos_tipicos', label: 'Platos típicos', icon: 'bi-egg-fried' },
        { id: 'lugares_destacados', label: 'Lugares destacados', icon: 'bi-geo-alt' },
        { id: 'tarifas_movilidad', label: 'Tarifas de movilidad', icon: 'bi-taxi-front-fill' },
        { id: 'tipo_cambio', label: 'Tipo de cambio', icon: 'bi-currency-exchange' },
        { id: 'emergencias', label: 'Emergencias', icon: 'bi-shield-exclamation' },
    ];

    var MENSAJE_INDISPONIBLE = 'PillcoBot no está disponible temporalmente. Inténtalo nuevamente en unos momentos.';
    var MENSAJE_ERROR_GENERICO = 'No pude responder en este momento. Vuelve a intentarlo, por favor.';
    var ERRORES = {
        chatbot_no_disponible: MENSAJE_INDISPONIBLE,
        proveedor_ia_timeout: MENSAJE_INDISPONIBLE,
        proveedor_ia_error: MENSAJE_INDISPONIBLE,
        error_interno: MENSAJE_ERROR_GENERICO,
        json_invalido: MENSAJE_ERROR_GENERICO,
        payload_invalido: MENSAJE_ERROR_GENERICO,
        accion_invalida: MENSAJE_ERROR_GENERICO,
        mensaje_invalido: MENSAJE_ERROR_GENERICO,
        mensaje_vacio: MENSAJE_ERROR_GENERICO,
        mensaje_demasiado_largo: 'Tu mensaje es demasiado largo. Intenta resumirlo un poco.',
        demasiadas_solicitudes: 'Has enviado varios mensajes en poco tiempo. Inténtalo nuevamente en un momento.',
    };

    var estado = { abierto: false, iniciado: false, enviando: false };

    function getCookie(nombre) {
        var partes = document.cookie.split(';');
        for (var i = 0; i < partes.length; i++) {
            var parte = partes[i].trim();
            if (parte.indexOf(nombre + '=') === 0) {
                return decodeURIComponent(parte.slice(nombre.length + 1));
            }
        }
        return null;
    }

    function esMovil() {
        return window.matchMedia('(max-width: 576px)').matches;
    }

    function autoscroll() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // ---------- Render ----------

    function crearFila(rol, extraClase) {
        var fila = document.createElement('div');
        fila.className = 'pcbot-row pcbot-row--' + rol + (extraClase ? ' ' + extraClase : '');
        if (rol === 'bot') {
            var avatar = document.createElement('img');
            avatar.className = 'pcbot-avatar';
            avatar.alt = '';
            avatar.src = fab.querySelector('img').src;
            fila.appendChild(avatar);
        }
        return fila;
    }

    function crearBurbuja(texto) {
        var burbuja = document.createElement('div');
        burbuja.className = 'pcbot-bubble';
        burbuja.textContent = texto;
        return burbuja;
    }

    function detectarSugerenciaClima(cuerpo) {
        var primeraLinea = (cuerpo.split('\n')[0] || '').match(/^Clima actual en (.+)$/);
        if (!primeraLinea) return null;
        var ciudad = CIUDADES_CLIMA[primeraLinea[1].trim().toLowerCase()];
        if (!ciudad) return null;
        return {
            texto: 'Conoce las temporadas de ' + ciudad.nombre,
            url: '/planifica/clima-temporadas/?ciudad=' + ciudad.slug,
        };
    }

    /**
     * Intenta separar el texto en: cuerpo principal, bloque de "Fuentes
     * oficiales" (formato fijo de external_search.formatear_respuesta), una
     * lista de tarjetas si es un listado con líneas "- ..." (formato fijo de
     * response_renderers._lista) y/o un CTA final "Etiqueta: <url>" (formato
     * fijo de response_renderers._enlace). Una ruta interna nunca se muestra
     * como texto: siempre se convierte en botón o se omite. Si nada encaja,
     * se deja todo como texto plano — nunca se rompe una respuesta por
     * intentar forzar estructura.
     */
    function analizarRespuesta(texto) {
        var resultado = { cuerpo: texto, fuentes: [], cards: null, tituloCards: null, cta: null, climaSugerencia: null };
        try {
            var conFuentes = texto.match(/^([\s\S]*?)\n\nFuentes oficiales:\n([\s\S]+)$/);
            var cuerpo = texto;
            if (conFuentes) {
                cuerpo = conFuentes[1];
                resultado.fuentes = conFuentes[2].split('\n').filter(Boolean).map(function (linea) {
                    var m = linea.match(/^-\s*(.+?)\s+—\s+(https:\/\/\S+)$/);
                    return m ? { titulo: m[1], url: m[2] } : null;
                }).filter(Boolean);
            }

            var conLista = cuerpo.match(/^([^\n]+:)\n((?:-\s.+(?:\n|$))+)$/);
            if (conLista) {
                var lineas = conLista[2].split('\n').filter(Boolean);
                var cards = lineas.map(function (linea) {
                    var segmentos = linea.replace(/^-\s*/, '').split(' — ');
                    var cta = null;
                    var meta = [];
                    segmentos.slice(1).forEach(function (seg) {
                        var enlace = seg.match(CTA_LINEA);
                        if (enlace) cta = { etiqueta: enlace[1], url: enlace[2] }; else meta.push(seg);
                    });
                    return { titulo: segmentos[0], meta: meta, cta: cta };
                });
                if (cards.length && cards.length <= 10) {
                    resultado.tituloCards = conLista[1];
                    resultado.cards = cards;
                    resultado.cuerpo = null;
                    return resultado;
                }
            }

            var lineasCuerpo = cuerpo.split('\n');
            var ctaFinal = (lineasCuerpo[lineasCuerpo.length - 1] || '').match(CTA_LINEA);
            if (ctaFinal) {
                resultado.cta = { etiqueta: ctaFinal[1], url: ctaFinal[2] };
                lineasCuerpo = lineasCuerpo.slice(0, -1);
                while (lineasCuerpo.length && lineasCuerpo[lineasCuerpo.length - 1].trim() === '') {
                    lineasCuerpo.pop();
                }
                cuerpo = lineasCuerpo.join('\n');
            }

            resultado.cuerpo = cuerpo;
            resultado.climaSugerencia = detectarSugerenciaClima(cuerpo);
        } catch (e) {
            resultado.cuerpo = texto;
            resultado.fuentes = [];
            resultado.cards = null;
            resultado.cta = null;
            resultado.climaSugerencia = null;
        }
        return resultado;
    }

    function crearBloqueFuentes(fuentes) {
        var bloque = document.createElement('div');
        bloque.className = 'pcbot-sources';
        var titulo = document.createElement('span');
        titulo.className = 'pcbot-sources__title';
        titulo.textContent = 'Fuentes oficiales';
        bloque.appendChild(titulo);
        fuentes.forEach(function (fuente) {
            var enlace = document.createElement('a');
            enlace.href = fuente.url;
            enlace.target = '_blank';
            enlace.rel = 'noopener noreferrer nofollow';
            enlace.textContent = fuente.titulo;
            bloque.appendChild(enlace);
        });
        return bloque;
    }

    function esUrlExterna(url) {
        return /^https?:\/\//.test(url);
    }

    function crearCta(etiqueta, url) {
        var enlace = document.createElement('a');
        enlace.className = 'pcbot-cta';
        enlace.href = url;
        if (esUrlExterna(url)) {
            enlace.target = '_blank';
            enlace.rel = 'noopener noreferrer nofollow';
        }
        enlace.textContent = etiqueta + ' →';
        return enlace;
    }

    function crearSugerenciaClima(sugerencia) {
        var bloque = document.createElement('div');
        bloque.className = 'pcbot-suggestion';
        var label = document.createElement('span');
        label.className = 'pcbot-suggestion__label';
        label.textContent = sugerencia.titulo || 'También te puede interesar';
        var texto = document.createElement('span');
        texto.className = 'pcbot-suggestion__text';
        texto.textContent = sugerencia.texto;
        bloque.appendChild(label);
        bloque.appendChild(texto);
        bloque.appendChild(crearCta(sugerencia.label || 'Ver más', sugerencia.url));
        return bloque;
    }

    function telHref(numeroTel) {
        return 'tel:' + String(numeroTel || '').replace(/[^\d+]/g, '');
    }

    // ---------- Renderers por presentacion.tipo (C6.2) ----------
    // Construyen DOM directamente desde datos estructurados del backend: no
    // dependen de parsear párrafos. Cualquier tipo desconocido o payload
    // incompleto cae al texto plano (ver despacharPresentacion).

    function renderClima(p) {
        var frag = document.createDocumentFragment();
        var card = document.createElement('div');
        card.className = 'pcbot-weather';

        var titulo = document.createElement('div');
        titulo.className = 'pcbot-weather__titulo';
        titulo.textContent = 'Clima actual en ' + p.ciudad;
        card.appendChild(titulo);

        var principal = document.createElement('div');
        principal.className = 'pcbot-weather__principal';
        var temp = document.createElement('span');
        temp.className = 'pcbot-weather__temp';
        temp.textContent = p.temperatura + ' °C';
        principal.appendChild(temp);
        if (p.estado) {
            var estadoEl = document.createElement('span');
            estadoEl.className = 'pcbot-weather__estado';
            estadoEl.textContent = p.estado;
            principal.appendChild(estadoEl);
        }
        card.appendChild(principal);

        var filas = [
            ['Sensación térmica', p.sensacion != null ? p.sensacion + ' °C' : null],
            ['Humedad', p.humedad != null ? p.humedad + ' %' : null],
            ['Viento', p.viento != null ? p.viento + ' km/h' : null],
            ['Prob. de lluvia', p.lluvia != null ? p.lluvia + ' %' : null],
        ];
        var tabla = document.createElement('div');
        tabla.className = 'pcbot-weather__detalles';
        filas.forEach(function (par) {
            if (par[1] == null) return;
            var fila = document.createElement('div');
            fila.className = 'pcbot-weather__fila';
            var etiqueta = document.createElement('span');
            etiqueta.textContent = par[0];
            var valor = document.createElement('span');
            valor.textContent = par[1];
            fila.appendChild(etiqueta);
            fila.appendChild(valor);
            tabla.appendChild(fila);
        });
        card.appendChild(tabla);
        if (p.respaldo) {
            var nota = document.createElement('div');
            nota.className = 'pcbot-weather__nota';
            nota.textContent = 'Dato de respaldo, puede no estar actualizado.';
            card.appendChild(nota);
        }
        frag.appendChild(card);
        if (p.cta) frag.appendChild(crearSugerenciaClima(p.cta));
        return frag;
    }

    function crearContactoCard(contacto) {
        var card = document.createElement('div');
        card.className = 'pcbot-emg-card';
        var nombre = document.createElement('div');
        nombre.className = 'pcbot-emg-card__nombre';
        nombre.textContent = contacto.nombre;
        card.appendChild(nombre);
        var numero = document.createElement('div');
        numero.className = 'pcbot-emg-card__numero';
        numero.textContent = contacto.numero;
        card.appendChild(numero);
        if (contacto.horario) {
            var horario = document.createElement('div');
            horario.className = 'pcbot-emg-card__meta';
            horario.textContent = contacto.horario;
            card.appendChild(horario);
        }
        if (contacto.zonas && contacto.zonas.length) {
            var zonas = document.createElement('div');
            zonas.className = 'pcbot-emg-card__meta';
            zonas.textContent = contacto.zonas.join(', ');
            card.appendChild(zonas);
        }
        var llamar = document.createElement('a');
        llamar.className = 'pcbot-emg-card__llamar';
        llamar.href = telHref(contacto.numero_tel);
        llamar.textContent = 'Llamar';
        card.appendChild(llamar);
        return card;
    }

    function renderEmergenciasNacionales(p) {
        var frag = document.createDocumentFragment();
        if (p.titulo) {
            var titulo = document.createElement('div');
            titulo.className = 'pcbot-cards-title';
            titulo.textContent = p.titulo;
            frag.appendChild(titulo);
        }
        var grid = document.createElement('div');
        grid.className = 'pcbot-emg-grid';
        p.items.forEach(function (c) { grid.appendChild(crearContactoCard(c)); });
        frag.appendChild(grid);

        if (p.zona_prompt) {
            var prompt = document.createElement('div');
            prompt.className = 'pcbot-bubble pcbot-emg-prompt';
            prompt.textContent = p.zona_prompt;
            frag.appendChild(prompt);
        }
        if (p.zonas && p.zonas.length) {
            var chips = document.createElement('div');
            chips.className = 'pcbot-quick pcbot-quick--zonas';
            p.zonas.forEach(function (zona) {
                var chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'pcbot-chip';
                chip.textContent = zona.nombre;
                chip.addEventListener('click', function () { enviar({ mensaje: zona.mensaje }, zona.mensaje); });
                chips.appendChild(chip);
            });
            frag.appendChild(chips);
        }
        return frag;
    }

    function renderEmergenciasLocales(p) {
        var frag = document.createDocumentFragment();
        var titulo = document.createElement('div');
        titulo.className = 'pcbot-cards-title';
        titulo.textContent = p.titulo;
        frag.appendChild(titulo);
        var lista = document.createElement('div');
        lista.className = 'pcbot-cards';
        (p.items || []).forEach(function (c) { lista.appendChild(crearContactoCard(c)); });
        frag.appendChild(lista);
        return frag;
    }

    function renderEventos(p) {
        var frag = document.createDocumentFragment();
        var titulo = document.createElement('div');
        titulo.className = 'pcbot-cards-title';
        titulo.textContent = p.titulo;
        frag.appendChild(titulo);
        var lista = document.createElement('div');
        lista.className = 'pcbot-cards';
        p.items.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'pcbot-event-card';
            if (item.fecha) {
                var fecha = document.createElement('span');
                fecha.className = 'pcbot-event-card__fecha';
                fecha.textContent = item.fecha;
                card.appendChild(fecha);
            }
            var nombre = document.createElement('div');
            nombre.className = 'pcbot-card__title';
            nombre.textContent = item.nombre;
            card.appendChild(nombre);
            if (item.estado_especial) {
                var estado = document.createElement('span');
                estado.className = 'pcbot-event-card__estado';
                estado.textContent = item.estado_especial;
                card.appendChild(estado);
            }
            [item.ubicacion, item.costo].forEach(function (linea) {
                if (!linea) return;
                var meta = document.createElement('div');
                meta.className = 'pcbot-card__meta';
                meta.textContent = linea;
                card.appendChild(meta);
            });
            if (item.url) card.appendChild(crearCta(item.cta_label || 'Ver evento', item.url));
            lista.appendChild(card);
        });
        frag.appendChild(lista);
        return frag;
    }

    function renderPlatosTipicos(p) {
        var frag = document.createDocumentFragment();
        var titulo = document.createElement('div');
        titulo.className = 'pcbot-cards-title';
        titulo.textContent = p.titulo;
        frag.appendChild(titulo);
        var lista = document.createElement('div');
        lista.className = 'pcbot-plato-list';
        p.items.forEach(function (item) {
            var fila = document.createElement('div');
            fila.className = 'pcbot-plato-row';
            var nombre = document.createElement('span');
            nombre.className = 'pcbot-plato-row__nombre';
            nombre.textContent = item.nombre;
            fila.appendChild(nombre);
            if (item.url) fila.appendChild(crearCta(item.cta_label || 'Ver dónde comer', item.url));
            lista.appendChild(fila);
        });
        frag.appendChild(lista);
        return frag;
    }

    function renderLugares(p) {
        var frag = document.createDocumentFragment();
        var lista = document.createElement('div');
        lista.className = 'pcbot-cards';
        p.items.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'pcbot-place-card';
            var nombre = document.createElement('div');
            nombre.className = 'pcbot-card__title';
            nombre.textContent = item.nombre;
            card.appendChild(nombre);
            var metaSup = [item.categoria, item.ubicacion].filter(Boolean).join(' · ');
            if (metaSup) {
                var sup = document.createElement('div');
                sup.className = 'pcbot-card__meta';
                sup.textContent = metaSup;
                card.appendChild(sup);
            }
            if (item.descripcion) {
                var desc = document.createElement('div');
                desc.className = 'pcbot-place-card__descripcion';
                desc.textContent = item.descripcion;
                card.appendChild(desc);
            }
            [item.entrada, item.horario].forEach(function (linea) {
                if (!linea) return;
                var meta = document.createElement('div');
                meta.className = 'pcbot-card__meta';
                meta.textContent = linea;
                card.appendChild(meta);
            });
            if (item.url) card.appendChild(crearCta(item.cta_label || 'Ver lugar', item.url));
            lista.appendChild(card);
        });
        frag.appendChild(lista);
        return frag;
    }

    // C6.3: alojamientos y restaurantes — misma card que lugares, 1 por fila.
    function renderEstablecimientos(p) {
        var frag = document.createDocumentFragment();
        if (p.titulo) {
            var titulo = document.createElement('div');
            titulo.className = 'pcbot-cards-title';
            titulo.textContent = p.titulo;
            frag.appendChild(titulo);
        }
        var lista = document.createElement('div');
        lista.className = 'pcbot-cards';
        p.items.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'pcbot-place-card';
            var nombre = document.createElement('div');
            nombre.className = 'pcbot-card__title';
            nombre.textContent = item.nombre;
            card.appendChild(nombre);
            var especialidades = (item.especialidades || []).join(', ');
            var lineas = [
                [item.categoria, item.ubicacion].filter(Boolean).join(' · '),
                especialidades ? 'Especialidades: ' + especialidades : '',
                item.precio ? item.precio + (item.excede_presupuesto ? ' (puede superar tu presupuesto)' : '') : '',
                item.horario ? 'Horario registrado: ' + item.horario : '',
                item.motivo || '',
            ];
            lineas.forEach(function (linea) {
                if (!linea) return;
                var meta = document.createElement('div');
                meta.className = 'pcbot-card__meta';
                meta.textContent = linea;
                card.appendChild(meta);
            });
            if (item.url) card.appendChild(crearCta(item.cta_label || 'Ver más', item.url));
            lista.appendChild(card);
        });
        frag.appendChild(lista);
        if (p.nota) {
            var nota = document.createElement('div');
            nota.className = 'pcbot-bubble pcbot-emg-prompt';
            nota.textContent = p.nota;
            frag.appendChild(nota);
        }
        return frag;
    }

    function renderMovilidad(p) {
        var frag = document.createDocumentFragment();
        var titulo = document.createElement('div');
        titulo.className = 'pcbot-cards-title';
        titulo.textContent = p.titulo;
        frag.appendChild(titulo);
        var lista = document.createElement('div');
        lista.className = 'pcbot-cards';
        p.items.forEach(function (item) {
            var card = document.createElement('div');
            card.className = 'pcbot-mobility-card';
            var tipo = document.createElement('div');
            tipo.className = 'pcbot-card__title';
            tipo.textContent = item.tipo;
            card.appendChild(tipo);
            if (item.descripcion) {
                var desc = document.createElement('div');
                desc.className = 'pcbot-card__meta';
                desc.textContent = item.descripcion;
                card.appendChild(desc);
            }
            var pen = document.createElement('div');
            pen.className = 'pcbot-mobility-card__pen';
            pen.textContent = 'Desde S/ ' + item.pen;
            card.appendChild(pen);
            if (item.usd) {
                var usd = document.createElement('div');
                usd.className = 'pcbot-mobility-card__usd';
                usd.textContent = 'Aprox. US$ ' + item.usd;
                card.appendChild(usd);
            }
            lista.appendChild(card);
        });
        frag.appendChild(lista);

        if (p.recomendaciones && p.recomendaciones.length) {
            var pregunta = document.createElement('div');
            pregunta.className = 'pcbot-bubble';
            pregunta.textContent = '¿Quieres algunos consejos para movilizarte?';
            frag.appendChild(pregunta);

            var tips = document.createElement('div');
            tips.className = 'pcbot-mobility-tips';
            tips.hidden = true;
            p.recomendaciones.forEach(function (tip) {
                var fila = document.createElement('div');
                fila.className = 'pcbot-mobility-tip';
                var icono = document.createElement('span');
                icono.className = 'pcbot-mobility-tip__icono';
                icono.textContent = tip.icono || '💡';
                var texto = document.createElement('span');
                texto.textContent = tip.texto;
                fila.appendChild(icono);
                fila.appendChild(texto);
                tips.appendChild(fila);
            });

            var boton = document.createElement('button');
            boton.type = 'button';
            boton.className = 'pcbot-toggle';
            boton.textContent = 'Recomendaciones';
            boton.addEventListener('click', function () {
                tips.hidden = !tips.hidden;
                autoscroll();
            });
            frag.appendChild(boton);
            frag.appendChild(tips);
        }
        return frag;
    }

    // C8: favoritos — misma card que establecimientos; el tipo va en la meta.
    function renderFavoritos(p) {
        var conTipo = function (item) {
            var copia = {};
            Object.keys(item).forEach(function (k) { copia[k] = item[k]; });
            copia.categoria = [item.tipo, item.categoria].filter(Boolean).join(' · ');
            return copia;
        };
        var frag = document.createDocumentFragment();
        frag.appendChild(renderEstablecimientos({ titulo: p.titulo, items: p.items.map(conTipo) }));
        if (p.sugerencias && p.sugerencias.length) {
            frag.appendChild(renderEstablecimientos({ titulo: p.titulo_sugerencias, items: p.sugerencias.map(conTipo) }));
        }
        return frag;
    }

    function crearMeta(texto) {
        var meta = document.createElement('div');
        meta.className = 'pcbot-card__meta';
        meta.textContent = texto;
        return meta;
    }

    // C8: itinerario — resumen, alojamiento base y un bloque por día.
    function renderItinerario(p) {
        var frag = document.createDocumentFragment();
        var r = p.resumen;
        var resumen = document.createElement('div');
        resumen.className = 'pcbot-place-card';
        var titulo = document.createElement('div');
        titulo.className = 'pcbot-card__title';
        titulo.textContent = 'Itinerario propuesto · ' + r.destino;
        resumen.appendChild(titulo);
        [
            r.fechas_texto,
            r.presupuesto ? 'Presupuesto: ' + r.presupuesto : '',
            r.estimado,
            r.margen,
            r.favoritos && r.favoritos.length ? 'Prioricé tus favoritos: ' + r.favoritos.join(', ') : '',
            r.nota_presupuesto,
        ].forEach(function (linea) { if (linea) resumen.appendChild(crearMeta(linea)); });
        frag.appendChild(resumen);

        if (p.alojamiento) {
            var a = p.alojamiento;
            var aloj = document.createElement('div');
            aloj.className = 'pcbot-place-card';
            var at = document.createElement('div');
            at.className = 'pcbot-card__title';
            at.textContent = 'Alojamiento base: ' + a.nombre;
            aloj.appendChild(at);
            [
                [a.categoria, a.ubicacion].filter(Boolean).join(' · '),
                a.precio + (a.cabe_en_presupuesto === false ? ' (supera tu presupuesto para toda la estadía)' : ''),
                a.motivo || '',
            ].forEach(function (linea) { if (linea) aloj.appendChild(crearMeta(linea)); });
            if (a.url) aloj.appendChild(crearCta(a.cta_label || 'Ver alojamiento', a.url));
            frag.appendChild(aloj);
        }

        p.dias_plan.forEach(function (dia) {
            var cabecera = document.createElement('div');
            cabecera.className = 'pcbot-cards-title';
            cabecera.textContent = dia.titulo + ' · ' + dia.fecha_texto;
            frag.appendChild(cabecera);
            var card = document.createElement('div');
            card.className = 'pcbot-place-card';
            if (!dia.actividades.length) card.appendChild(crearMeta('Sin actividades registradas para este día.'));
            dia.actividades.forEach(function (act) {
                var fila = document.createElement('div');
                fila.className = 'pcbot-itin-act';
                var momento = document.createElement('div');
                momento.className = 'pcbot-itin-act__momento';
                momento.textContent = act.momento;
                fila.appendChild(momento);
                var nombre = document.createElement('div');
                nombre.className = 'pcbot-card__title';
                nombre.textContent = act.nombre;
                fila.appendChild(nombre);
                if (act.detalle) fila.appendChild(crearMeta(act.detalle));
                if (act.motivo) fila.appendChild(crearMeta(act.motivo));
                if (act.url) fila.appendChild(crearCta(act.cta_label || 'Ver más', act.url));
                card.appendChild(fila);
            });
            frag.appendChild(card);
        });

        if (p.platos && p.platos.length) {
            var platos = document.createElement('div');
            platos.className = 'pcbot-bubble pcbot-emg-prompt';
            platos.textContent = 'Prueba también: ' + p.platos.map(function (x) { return x.nombre; }).join(', ') + '.';
            frag.appendChild(platos);
        }
        return frag;
    }

    var RENDERERS_PRESENTACION = {
        clima: renderClima,
        emergencias_nacionales: renderEmergenciasNacionales,
        emergencias_locales: renderEmergenciasLocales,
        eventos: renderEventos,
        platos_tipicos: renderPlatosTipicos,
        lugares: renderLugares,
        movilidad: renderMovilidad,
        alojamientos: renderEstablecimientos,
        restaurantes: renderEstablecimientos,
        favoritos: renderFavoritos,
        itinerario: renderItinerario,
    };

    function crearCards(titulo, cards) {
        var envoltorio = document.createElement('div');
        if (titulo) {
            var h = document.createElement('div');
            h.className = 'pcbot-cards-title';
            h.textContent = titulo;
            envoltorio.appendChild(h);
        }
        var fila = document.createElement('div');
        fila.className = 'pcbot-cards';
        cards.forEach(function (card) {
            var el = document.createElement('div');
            el.className = 'pcbot-card';
            var t = document.createElement('div');
            t.className = 'pcbot-card__title';
            t.textContent = card.titulo;
            el.appendChild(t);
            card.meta.slice(0, 3).forEach(function (linea) {
                var m = document.createElement('div');
                m.className = 'pcbot-card__meta';
                m.textContent = linea;
                el.appendChild(m);
            });
            if (card.cta) {
                var a = document.createElement('a');
                a.className = 'pcbot-card__cta';
                a.href = card.cta.url;
                if (esUrlExterna(card.cta.url)) {
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer nofollow';
                }
                a.textContent = card.cta.etiqueta + ' →';
                el.appendChild(a);
            }
            fila.appendChild(el);
        });
        envoltorio.appendChild(fila);
        return envoltorio;
    }

    function agregarMensajeUsuario(texto) {
        var fila = crearFila('user');
        fila.appendChild(crearBurbuja(texto));
        messagesEl.appendChild(fila);
        autoscroll();
    }

    function agregarMensajeBot(texto, opciones) {
        opciones = opciones || {};
        var fila = crearFila('bot', opciones.esError ? 'pcbot-row--error' : '');

        // C6.2: si el backend ya envió una presentación estructurada para un
        // tipo conocido, se usa directamente — nunca se reconstruye desde el
        // texto. Un tipo desconocido o payload incompleto cae al texto plano.
        var renderer = opciones.presentacion && RENDERERS_PRESENTACION[opciones.presentacion.tipo];
        if (renderer) {
            try {
                // Envoltorio sin estilo propio (mismo patrón que crearCards):
                // sin él, un fragmento con hijos de ancho porcentual (ej.
                // .pcbot-emg-grid al 100%) queda como hijo directo de la fila
                // flex, cuyo ancho es indefinido, y el porcentaje colapsa a
                // casi 0 en vez de resolverse contra el ancho real del mensaje.
                var envoltorio = document.createElement('div');
                envoltorio.appendChild(renderer(opciones.presentacion));
                fila.appendChild(envoltorio);
                messagesEl.appendChild(fila);
                autoscroll();
                return;
            } catch (e) {
                fila = crearFila('bot', opciones.esError ? 'pcbot-row--error' : '');
            }
        }

        var analisis = opciones.estructurado
            ? analizarRespuesta(texto)
            : { cuerpo: texto, fuentes: [], cards: null, cta: null, climaSugerencia: null };

        var contenedorPrincipal;
        if (analisis.cards) {
            contenedorPrincipal = crearCards(analisis.tituloCards, analisis.cards);
        } else {
            contenedorPrincipal = crearBurbuja(analisis.cuerpo);
            if (analisis.cta) contenedorPrincipal.appendChild(crearCta(analisis.cta.etiqueta, analisis.cta.url));
        }
        fila.appendChild(contenedorPrincipal);

        if (analisis.fuentes && analisis.fuentes.length) {
            (analisis.cards ? fila : contenedorPrincipal).appendChild(crearBloqueFuentes(analisis.fuentes));
        }
        if (analisis.climaSugerencia) {
            fila.appendChild(crearSugerenciaClima(analisis.climaSugerencia));
        }
        messagesEl.appendChild(fila);
        autoscroll();
    }

    function agregarQuickActions() {
        var fila = document.createElement('div');
        fila.className = 'pcbot-quick';
        QUICK_ACTIONS.forEach(function (accion) {
            var chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'pcbot-chip';
            chip.dataset.accion = accion.id;
            chip.innerHTML = '<i class="bi ' + accion.icon + '" aria-hidden="true"></i><span>' + accion.label + '</span>';
            chip.addEventListener('click', function () { enviarAccion(accion.id, accion.label); });
            fila.appendChild(chip);
        });
        messagesEl.appendChild(fila);
        autoscroll();
    }

    var indicadorEscribiendo = null;

    function mostrarEscribiendo() {
        indicadorEscribiendo = crearFila('bot');
        var burbuja = document.createElement('div');
        burbuja.className = 'pcbot-bubble';
        burbuja.innerHTML = '<span class="pcbot-typing"><span></span><span></span><span></span></span>';
        indicadorEscribiendo.appendChild(burbuja);
        messagesEl.appendChild(indicadorEscribiendo);
        autoscroll();
    }

    function ocultarEscribiendo() {
        if (indicadorEscribiendo && indicadorEscribiendo.parentNode) {
            indicadorEscribiendo.parentNode.removeChild(indicadorEscribiendo);
        }
        indicadorEscribiendo = null;
    }

    // ---------- Red ----------

    function fijarEnviando(valor) {
        estado.enviando = valor;
        sendBtn.disabled = valor;
        input.disabled = valor;
        messagesEl.querySelectorAll('.pcbot-chip').forEach(function (chip) { chip.disabled = valor; });
    }

    function enviar(payload, etiquetaUsuario) {
        if (estado.enviando) return;
        agregarMensajeUsuario(etiquetaUsuario);
        fijarEnviando(true);
        mostrarEscribiendo();

        fetch(endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken') || '',
            },
            body: JSON.stringify(payload),
        })
            .then(function (respuesta) {
                return respuesta.json().catch(function () { return null; }).then(function (datos) {
                    return { status: respuesta.status, datos: datos };
                });
            })
            .then(function (resultado) {
                ocultarEscribiendo();
                var datos = resultado.datos;
                if (datos && datos.ok) {
                    agregarMensajeBot(datos.respuesta.contenido, {
                        estructurado: true,
                        presentacion: datos.respuesta.presentacion || null,
                    });
                } else {
                    var codigo = datos && datos.error;
                    agregarMensajeBot(ERRORES[codigo] || MENSAJE_ERROR_GENERICO, { esError: true });
                }
            })
            .catch(function () {
                ocultarEscribiendo();
                agregarMensajeBot(MENSAJE_ERROR_GENERICO, { esError: true });
            })
            .finally(function () {
                fijarEnviando(false);
                input.focus();
            });
    }

    function enviarAccion(id, label) {
        enviar({ accion: id }, label);
    }

    form.addEventListener('submit', function (event) {
        event.preventDefault();
        var texto = input.value.trim();
        if (!texto || estado.enviando) return;
        input.value = '';
        enviar({ mensaje: texto }, texto);
    });

    // ---------- Apertura / cierre ----------

    function iniciarConversacion() {
        if (estado.iniciado) return;
        estado.iniciado = true;
        agregarMensajeBot(
            '¡Hola! Soy PillcoBot, tu guía virtual de Viaje Informado.\n\n' +
            'Estoy aquí para ayudarte a descubrir Huánuco: lugares turísticos, gastronomía, eventos, clima, ' +
            'transporte y consejos útiles para tu viaje.\n\n¿Qué te gustaría conocer hoy?'
        );
        agregarQuickActions();
    }

    // ---------- Móvil: modo teclado (VisualViewport) ----------
    // Dos estados, una sola fuente de verdad:
    //  - teclado cerrado: el CSS manda (bottom sheet ~86%); sin estilos inline.
    //  - teclado abierto: el panel ocupa el 100% del VisualViewport (alto y
    //    offsetTop), nunca el 86% del viewport reducido. Solo .pcbot-messages
    //    scrollea; el documento no se mueve (scroll lock).
    // Teclado abierto = composer con foco + alto visible reducido de forma
    // significativa respecto al alto base capturado sin teclado (evita falsos
    // positivos por barras del navegador o pequeños resize de Safari).
    var UMBRAL_TECLADO = 0.75;
    var alturaBase = 0;
    var anchoBase = 0;
    var tecladoAbierto = false;
    var rafAjuste = 0;

    function tecladoDetectado(vv) {
        if (document.activeElement !== input || !alturaBase) return false;
        return vv.height < alturaBase * UMBRAL_TECLADO;
    }

    function aplicarModoTeclado() {
        rafAjuste = 0;
        var vv = window.visualViewport;
        if (!vv || !estado.abierto || !esMovil()) {
            salirModoTeclado();
            return;
        }
        if (vv.width !== anchoBase) {
            // Rotación: el alto base anterior ya no sirve.
            anchoBase = vv.width;
            alturaBase = vv.height;
        } else if (document.activeElement !== input && vv.height > alturaBase) {
            // Sin foco no hay teclado: solo se acepta un alto base MAYOR (barra
            // del navegador oculta). Nunca menor: en iOS el blur llega antes de
            // que el viewport recupere su alto y lo dejaría contaminado.
            alturaBase = vv.height;
        }
        if (!tecladoDetectado(vv)) {
            salirModoTeclado();
            return;
        }
        tecladoAbierto = true;
        panel.classList.add('pcbot-panel--keyboard');
        panel.style.top = Math.round(vv.offsetTop) + 'px';
        panel.style.height = Math.round(vv.height) + 'px';
        autoscroll();
    }

    function salirModoTeclado() {
        if (!tecladoAbierto && !panel.style.height) return;
        tecladoAbierto = false;
        panel.classList.remove('pcbot-panel--keyboard');
        panel.style.removeProperty('top');
        panel.style.removeProperty('height');
    }

    function ajustarAlturaMovil() {
        if (rafAjuste) return;
        rafAjuste = window.requestAnimationFrame(aplicarModoTeclado);
    }

    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', ajustarAlturaMovil);
        window.visualViewport.addEventListener('scroll', ajustarAlturaMovil);
        input.addEventListener('focus', ajustarAlturaMovil);
        input.addEventListener('blur', ajustarAlturaMovil);
    }

    // ---------- Scroll lock real (móvil) ----------
    // El fondo debe quedar TOTALMENTE congelado (patrón tipo app de
    // mensajería): se fija <body> en su posición actual con position:fixed
    // (no basta overflow-x:hidden, que no bloquea el scroll vertical ni el
    // "rubber-band" de Safari) y se restaura exactamente el scrollY al cerrar.
    var bloqueoScroll = null;

    function bloquearScroll() {
        if (bloqueoScroll || !esMovil()) return;
        var scrollY = window.scrollY || window.pageYOffset || 0;
        bloqueoScroll = { scrollY: scrollY };
        document.documentElement.classList.add('pcbot-lock-scroll');
        document.body.classList.add('pcbot-lock-scroll');
        document.body.style.top = (-scrollY) + 'px';
    }

    function desbloquearScroll() {
        if (!bloqueoScroll) return;
        var scrollY = bloqueoScroll.scrollY;
        bloqueoScroll = null;
        document.documentElement.classList.remove('pcbot-lock-scroll');
        document.body.classList.remove('pcbot-lock-scroll');
        document.body.style.removeProperty('top');
        window.scrollTo(0, scrollY);
    }

    function abrir() {
        if (estado.abierto) return;
        estado.abierto = true;
        root.classList.add('is-open');
        panel.hidden = false;
        fab.setAttribute('aria-expanded', 'true');
        if (esMovil()) {
            backdrop.hidden = false;
            bloquearScroll();
        }
        iniciarConversacion();
        if (window.visualViewport) {
            alturaBase = window.visualViewport.height;
            anchoBase = window.visualViewport.width;
        }
        ajustarAlturaMovil();
        window.setTimeout(function () { input.focus(); }, 50);
    }

    function cerrar() {
        if (!estado.abierto) return;
        estado.abierto = false;
        root.classList.remove('is-open');
        fab.setAttribute('aria-expanded', 'false');
        input.blur();
        salirModoTeclado();
        desbloquearScroll();
        window.setTimeout(function () {
            panel.hidden = true;
            backdrop.hidden = true;
        }, 220);
        fab.focus();
    }

    fab.addEventListener('click', function () { estado.abierto ? cerrar() : abrir(); });
    closeBtn.addEventListener('click', cerrar);
    minimizeBtn.addEventListener('click', cerrar);
    backdrop.addEventListener('click', cerrar);
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && estado.abierto) cerrar();
    });

    // ---------- Drag-to-close (bottom sheet, solo desde el handle) ----------

    var arrastre = null;

    dragHandle.addEventListener('pointerdown', function (event) {
        if (!esMovil() || !estado.abierto) return;
        arrastre = { inicioY: event.clientY, actual: 0 };
        panel.classList.add('is-dragging');
        try { dragHandle.setPointerCapture(event.pointerId); } catch (e) { /* no soportado, se ignora */ }
    });

    dragHandle.addEventListener('pointermove', function (event) {
        if (!arrastre) return;
        arrastre.actual = Math.max(0, event.clientY - arrastre.inicioY);
        panel.style.transform = 'translateY(' + arrastre.actual + 'px)';
    });

    function finalizarArrastre() {
        if (!arrastre) return;
        var desplazamiento = arrastre.actual;
        var umbral = panel.offsetHeight * 0.22;
        arrastre = null;
        panel.classList.remove('is-dragging');
        panel.style.transform = '';
        if (desplazamiento > umbral) cerrar();
    }

    dragHandle.addEventListener('pointerup', finalizarArrastre);
    dragHandle.addEventListener('pointercancel', finalizarArrastre);
})();
