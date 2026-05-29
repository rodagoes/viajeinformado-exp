from django.core.management.base import BaseCommand, CommandError

from apps.monedas.services import (
    TipoCambioAPIError,
    actualizar_tipo_cambio_sunat,
)


class Command(BaseCommand):
    help = "Actualiza el tipo de cambio SUNAT/SBS USD-PEN desde Decolecta / apis.net.pe."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            type=str,
            default=None,
            help="Fecha específica en formato YYYY-MM-DD. Si se omite, consulta el tipo de cambio actual.",
        )

    def handle(self, *args, **options):
        fecha = options.get("fecha")

        try:
            tipo_cambio = actualizar_tipo_cambio_sunat(fecha=fecha)
        except TipoCambioAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Tipo de cambio actualizado: {tipo_cambio.fecha} | "
                f"Compra S/. {tipo_cambio.compra} | Venta S/. {tipo_cambio.venta}"
            )
        )
