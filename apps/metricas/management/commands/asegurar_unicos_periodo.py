from django.core.management.base import BaseCommand, CommandError

from apps.metricas.choices import OrigenDato
from apps.metricas.models import PeriodoEvaluacion
from apps.metricas.services.unicos import asegurar_intervalos_unicos


class Command(BaseCommand):
    help = (
        "Crea las filas de UnicosPeriodo (una por semana y mes) que falten para un periodo SIMULADO, "
        "con usuarios_recurrentes = 0. Idempotente: no modifica ni borra filas existentes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--periodo", type=int, required=True, help="ID del PeriodoEvaluacion.")

    def handle(self, *args, periodo, **options):
        try:
            obj = PeriodoEvaluacion.objects.get(pk=periodo)
        except PeriodoEvaluacion.DoesNotExist:
            raise CommandError(f"No existe el periodo {periodo}.")
        resultado = asegurar_intervalos_unicos(obj, OrigenDato.SIMULADO)
        self.stdout.write(f"{obj}: {resultado.creados} creados, {resultado.existentes} ya existían.")
        for fila in resultado.inconsistentes:
            self.stderr.write(f"Inconsistente (no se modificó): {fila} termina el {fila.fin}.")
