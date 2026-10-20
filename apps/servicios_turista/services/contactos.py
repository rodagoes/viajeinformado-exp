"""
Contactos de una sede con precedencia inequívoca y sin duplicados.

Orden: contactos de la sede -> teléfono de la sede -> contactos generales de
la entidad -> teléfono de la entidad. Compartido por la vista pública y por
Pillco Bot para que ambos muestren lo mismo.
"""
import re

TELEFONO_LIMPIO_RE = re.compile(r"[^\d+]")


def telefono_tel(telefono):
    """Solo dígitos y '+' inicial, listo para href="tel:...". '' si no hay."""
    if not telefono:
        return ""
    return TELEFONO_LIMPIO_RE.sub("", telefono)


def es_telefonico(valor):
    """Parece teléfono si tiene suficientes dígitos, sin importar el tipo_contacto."""
    return len(re.sub(r"\D", "", valor or "")) >= 6


def clave_dedup(valor):
    """'(062) 512400' y '062512400' son el mismo contacto; correos por texto."""
    if es_telefonico(valor):
        return telefono_tel(valor)
    return (valor or "").strip().lower()


def _ordenados(contactos):
    activos = [c for c in contactos if c.activo]
    return sorted(activos, key=lambda c: (not c.es_principal, c.orden, c.pk))


def contactos_de_sede(sede, incluir_telefonos=True):
    """Lista de {"tipo","etiqueta","valor","valor_tel"} deduplicada.

    Usa los prefetch `contactos` y `servicio__contactos` si existen. Con
    incluir_telefonos=False omite sede.telefono/servicio.telefono (el chatbot
    los expone aparte)."""
    servicio = sede.servicio
    candidatos = [
        (c.tipo_contacto, c.etiqueta, c.valor, False) for c in _ordenados(sede.contactos.all())
    ]
    if incluir_telefonos and (sede.telefono or "").strip():
        candidatos.append(("telefono", "", sede.telefono, True))
    candidatos += [
        (c.tipo_contacto, c.etiqueta, c.valor, False)
        for c in _ordenados(c for c in servicio.contactos.all() if c.sede_id is None)
    ]
    if incluir_telefonos and (servicio.telefono or "").strip():
        candidatos.append(("telefono", "", servicio.telefono, True))

    vistos, resultado = set(), []
    for tipo, etiqueta, valor, es_telefono_suelto in candidatos:
        valor = (valor or "").strip()
        if not valor:
            continue
        clave = clave_dedup(valor)
        if clave in vistos:
            continue
        vistos.add(clave)
        # Los teléfonos sueltos (sede/entidad) siempre son llamables; los contactos, solo si lo parecen.
        llamable = es_telefono_suelto or es_telefonico(valor)
        resultado.append({
            "tipo": tipo,
            "etiqueta": etiqueta,
            "valor": valor,
            "valor_tel": telefono_tel(valor) if llamable else "",
        })
    return resultado


def telefono_llamar(sede):
    """Primer teléfono llamable según la precedencia; '' si no hay."""
    return next((c["valor_tel"] for c in contactos_de_sede(sede) if c["valor_tel"]), "")
