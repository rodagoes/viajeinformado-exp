from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.metricas import formatos
from apps.metricas.choices import DispositivoAcceso, FuenteTrafico, TipoInteraccion
from apps.metricas.models import PeriodoEvaluacion
from apps.metricas.services.consolidacion_real import reconstruir_metricas_reales


def _fecha(valor):
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise CommandError(f"Fecha inválida '{valor}': use AAAA-MM-DD.")


class Command(BaseCommand):
    help = (
        "Reconstruye los agregados REAL (métricas diarias, desgloses, interacciones y únicos semanales/mensuales) de un "
        "periodo a partir de visitantes, sesiones y eventos REAL. Por seguridad solo CALCULA y muestra el plan (dry-run); "
        "use --aplicar para escribir. Nunca toca SIMULADO ni GA4."
    )

    def add_arguments(self, parser):
        parser.add_argument("--periodo", required=True, help="ID o nombre exacto del PeriodoEvaluacion.")
        parser.add_argument("--desde", help="Inicio del rango (AAAA-MM-DD). Por defecto, el inicio del periodo.")
        parser.add_argument("--hasta", help="Fin del rango (AAAA-MM-DD). Por defecto, hoy o el fin del periodo.")
        parser.add_argument("--aplicar", action="store_true", help="Escribe los agregados (sin esto solo se muestra el plan).")

    def _periodo(self, valor):
        filtro = {"pk": int(valor)} if valor.isdigit() else {"nombre": valor}
        encontrados = list(PeriodoEvaluacion.objects.filter(**filtro))
        if len(encontrados) != 1:
            raise CommandError(f"El periodo '{valor}' {'no existe' if not encontrados else 'es ambiguo; use el ID'}.")
        return encontrados[0]

    def handle(self, *args, periodo, desde, hasta, aplicar, **opciones):
        obj = self._periodo(periodo)
        try:
            resultado = reconstruir_metricas_reales(
                obj, _fecha(desde) if desde else None, _fecha(hasta) if hasta else None, dry_run=not aplicar,
            )
        except ValueError as exc:
            raise CommandError(str(exc))
        a, t = resultado.agregados, resultado.agregados.totales
        w = self.stdout.write
        w(f"=== Agregados REAL de «{obj.nombre}» ({obj.get_alcance_display()}) ===")
        w(f"Rango:          {a.desde:%d/%m/%Y} – {a.hasta:%d/%m/%Y} ({len(a.diarias)} días)")
        w(f"Sesiones:       {t['sesiones']}")
        w(f"Páginas vistas: {t['paginas_vistas']}  ·  por sesión: {formatos.num(t['paginas_vistas'] / t['sesiones'] if t['sesiones'] else None)}")
        w(f"Duración media: {formatos.duracion(t['duracion_total_seg'] / t['sesiones'] if t['sesiones'] else None)}")
        w(f"Tasa de rebote: {formatos.pct(t['sesiones_rebote'] / t['sesiones'] * 100 if t['sesiones'] else None)}")
        w(f"Usuarios nuevos (suma diaria): {t['usuarios_nuevos']}  ·  interacciones: {t['interacciones']}")
        for titulo, opciones_, atributo in (("Fuente", FuenteTrafico, "fuentes"), ("Dispositivo", DispositivoAcceso, "dispositivos")):
            partes = []
            for codigo, nombre in opciones_.choices:
                n = sum(getattr(f, atributo).get(codigo, 0) for f in a.diarias)
                if n:
                    partes.append(f"{nombre} {n}")
            w(f"{titulo + ':':<15} " + (", ".join(partes) or "—"))
        por_tipo = {}
        for _, tipo, n in a.interacciones:
            por_tipo[tipo] = por_tipo.get(tipo, 0) + n
        w("Interacciones:  " + (", ".join(f"{nombre} {por_tipo[c]}" for c, nombre in TipoInteraccion.choices if c in por_tipo) or "—"))
        w(f"Únicos:         {sum(1 for u in a.unicos if u.granularidad == 'SEMANA')} semanas y "
          f"{sum(1 for u in a.unicos if u.granularidad == 'MES')} meses; "
          f"recurrentes semanales {[u.usuarios_recurrentes for u in a.unicos if u.granularidad == 'SEMANA']}")
        f = resultado.filas
        w(f"Filas a escribir: {f['metricas_diarias']} diarias, {f['fuentes']} de fuente, {f['dispositivos']} de dispositivo, "
          f"{f['interacciones']} de interacciones, {f['unicos']} de únicos.")
        e = resultado.existentes
        w(f"Filas REAL del rango que se reemplazan: {e['metricas_diarias']} diarias, {e['interacciones']} interacciones, {e['unicos']} únicos.")
        if not aplicar:
            w(self.style.WARNING("DRY-RUN: no se escribió nada. Repita con --aplicar para guardar."))
            return
        v = resultado.validacion
        w(self.style.SUCCESS(f"Agregados REAL guardados. Validación del periodo (REAL): {v.estado}. {v.mensaje_estado}"))
        for aviso in v.errores:
            w(self.style.ERROR(f"  ERROR: {aviso}"))
        for aviso in v.advertencias[:8]:
            w(f"  · {aviso}")
