from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.metricas.models import PeriodoEvaluacion
from apps.metricas.services.previsualizacion import lineas_previsualizacion
from apps.metricas.services.simulacion import (
    DatasetInvalido,
    DatosSimuladosExistentes,
    SimulacionError,
    contar_datos_simulados,
    persistir_dataset,
    simular_periodo,
    validar_dataset,
)


class Command(BaseCommand):
    help = (
        "Genera el dataset SIMULADO de un periodo (metas mensuales exactas, reproducible por semilla). "
        "--dry-run solo previsualiza y no escribe nada. Sin --reemplazar aborta si el periodo ya tiene datos SIMULADOS."
    )

    def add_arguments(self, parser):
        parser.add_argument("--periodo", required=True, help="ID o nombre exacto del PeriodoEvaluacion.")
        parser.add_argument("--seed", type=int, required=True, help="Semilla (entera) del generador.")
        parser.add_argument("--dry-run", action="store_true", help="Genera, valida y muestra el resumen sin escribir.")
        parser.add_argument(
            "--reemplazar", action="store_true",
            help="Borra SOLO los datos SIMULADOS de este periodo y los reemplaza (REAL, GA4 y otros periodos no se tocan).",
        )
        parser.add_argument("--usuario", help="Username (staff) que queda registrado en la auditoría.")
        parser.add_argument("--dias", action="store_true", help="Incluye el detalle diario en la previsualización.")

    def _periodo(self, valor):
        filtro = {"pk": int(valor)} if valor.isdigit() else {"nombre": valor}
        encontrados = list(PeriodoEvaluacion.objects.filter(**filtro))
        if len(encontrados) != 1:
            raise CommandError(f"El periodo '{valor}' {'no existe' if not encontrados else 'es ambiguo; use el ID'}.")
        return encontrados[0]

    def handle(self, *args, **opciones):
        periodo = self._periodo(opciones["periodo"])
        usuario = None
        if opciones["usuario"]:
            usuario = get_user_model().objects.filter(username=opciones["usuario"]).first()
            if usuario is None:
                raise CommandError(f"No existe el usuario '{opciones['usuario']}'.")

        existentes = contar_datos_simulados(periodo)
        hay_datos = any(existentes.values())
        if hay_datos and not opciones["dry_run"] and not opciones["reemplazar"]:
            raise CommandError(
                f"El periodo ya tiene datos SIMULADOS ({existentes['metricas_diarias']} métricas diarias, "
                f"{existentes['interacciones']} interacciones, {existentes['unicos']} únicos). "
                "No se modificó nada; use --reemplazar para sustituirlos."
            )

        try:
            dataset = simular_periodo(periodo, opciones["seed"])
        except SimulacionError as exc:
            raise CommandError(str(exc))
        errores = validar_dataset(dataset)
        if errores:
            raise CommandError("El dataset generado no es válido; no se escribió nada:\n - " + "\n - ".join(errores[:10]))

        for linea in lineas_previsualizacion(dataset, con_dias=opciones["dias"]):
            self.stdout.write(linea)

        if opciones["dry_run"]:
            if hay_datos:
                self.stdout.write(self.style.WARNING(
                    f"\nADVERTENCIA: el periodo ya tiene datos SIMULADOS ({existentes['metricas_diarias']} métricas "
                    f"diarias, {existentes['interacciones']} interacciones, {existentes['unicos']} únicos)."
                    + (" Con --reemplazar serían eliminados y sustituidos." if opciones["reemplazar"] else "")
                ))
            self.stdout.write(self.style.SUCCESS("\nDRY-RUN: no se escribió nada."))
            return

        try:
            generacion = persistir_dataset(dataset, reemplazar=opciones["reemplazar"], usuario=usuario)
        except DatosSimuladosExistentes as exc:
            raise CommandError(f"El periodo ya tiene datos SIMULADOS {exc.conteos}. No se modificó nada.")
        except DatasetInvalido as exc:
            raise CommandError("No se escribió nada: " + "; ".join(exc.errores[:5]))
        self.stdout.write(self.style.SUCCESS(
            f"\nDataset SIMULADO guardado (generación {generacion.pk}, huella {generacion.huella_inicial[:12]}…)."
        ))
