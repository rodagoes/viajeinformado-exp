from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.metricas import formatos
from apps.metricas.models import PeriodoEvaluacion
from apps.metricas.services import consolidacion_real
from apps.metricas.services.periodo_operativo import (
    asegurar_periodo_operativo,
    buscar_periodo_operativo,
    nombre_periodo_operativo,
)


class Command(BaseCommand):
    help = (
        "Actualiza los agregados REAL de producción: asegura el periodo operativo del año actual ('Producción AAAA') y "
        "reconstruye sus métricas diarias, interacciones y únicos con la lógica de reconstruir_metricas_reales. "
        "Idempotente y pensado para ejecutarse periódicamente (cron/systemd). Solo toca datos REAL de ese periodo. "
        "Con --dry-run solo calcula y muestra el plan."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Calcula y muestra el resumen sin escribir nada.")

    def handle(self, *args, dry_run, **opciones):
        w = self.stdout.write
        if not getattr(settings, "METRICAS_REAL_HABILITADAS", False):
            w(self.style.WARNING(
                "Aviso: METRICAS_REAL_HABILITADAS está apagado; no se están registrando hechos nuevos "
                "(se consolidan los ya existentes)."))
        hoy = consolidacion_real.hoy()
        if dry_run:
            periodo = buscar_periodo_operativo(hoy)
            if periodo is None:
                w(f"DRY-RUN: se crearía el periodo «{nombre_periodo_operativo(hoy.year)}» (01/01–31/12, Todos los visitantes). "
                  "No se escribió nada.")
                return
            creado = False
        else:
            periodo, creado = asegurar_periodo_operativo(hoy)
        w(f"Periodo operativo: «{periodo.nombre}» ({periodo.fecha_inicio:%d/%m/%Y}–{periodo.fecha_fin:%d/%m/%Y}), "
          f"{'creado ahora' if creado else 'ya existía'}.")

        try:
            with transaction.atomic():
                if not dry_run:
                    # Serializa ejecuciones solapadas del mismo periodo (el segundo proceso espera al primero).
                    PeriodoEvaluacion.objects.select_for_update().get(pk=periodo.pk)
                resultado = consolidacion_real.reconstruir_metricas_reales(periodo, dry_run=dry_run)
        except ValueError as exc:
            raise CommandError(str(exc))

        t, f, e = resultado.agregados.totales, resultado.filas, resultado.existentes
        sesiones = t["sesiones"]
        w(f"Rango:          {resultado.agregados.desde:%d/%m/%Y} – {resultado.agregados.hasta:%d/%m/%Y}")
        w(f"Sesiones:       {sesiones}  ·  páginas vistas: {t['paginas_vistas']}  ·  interacciones: {t['interacciones']}")
        w(f"Duración media: {formatos.duracion(t['duracion_total_seg'] / sesiones if sesiones else None)}"
          f"  ·  rebote: {formatos.pct(t['sesiones_rebote'] / sesiones * 100 if sesiones else None)}")
        w(f"Filas REAL escritas/previstas: {f['metricas_diarias']} diarias, {f['interacciones']} de interacciones, "
          f"{f['unicos']} de únicos (reemplazan {e['metricas_diarias']}/{e['interacciones']}/{e['unicos']}).")
        if dry_run:
            w(self.style.WARNING("DRY-RUN: no se escribió nada."))
            return
        v = resultado.validacion
        if v is not None and v.errores:
            for aviso in v.errores:
                self.stderr.write(self.style.ERROR(f"  ERROR de validación: {aviso}"))
            raise CommandError("La validación del periodo reportó errores (ver arriba).")
        w(self.style.SUCCESS(f"Agregados REAL actualizados. Validación: {v.estado}."))
