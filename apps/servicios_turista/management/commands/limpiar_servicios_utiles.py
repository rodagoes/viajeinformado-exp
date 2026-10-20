"""
Limpieza selectiva de Servicios útiles para reinicializar el directorio con la
estructura entidad + sedes.

Borra SOLO: imágenes de galería, contactos, sedes y entidades (ServicioTurista,
con sus categorías secundarias). NO toca categorías, otras apps, el esquema,
django_migrations ni archivos de media/.

Por defecto es una simulación. Para borrar de verdad hay que repetir el nombre
de la base de datos en --confirmar, para no ejecutarlo en el entorno equivocado.

    python manage.py limpiar_servicios_utiles                      # simulación
    python manage.py limpiar_servicios_utiles --confirmar NOMBRE_BD
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.servicios_turista.models import (
    ContactoServicioTurista,
    ImagenServicioTurista,
    SedeServicioTurista,
    ServicioTurista,
)

# Orden de borrado: primero los dependientes.
MODELOS = (ImagenServicioTurista, ContactoServicioTurista, SedeServicioTurista, ServicioTurista)


class Command(BaseCommand):
    help = "Simula (por defecto) o ejecuta la limpieza selectiva de Servicios útiles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar", metavar="NOMBRE_BD",
            help="Nombre exacto de la base de datos actual; sin él solo se simula.",
        )

    def _conteos(self):
        through = ServicioTurista.categorias_secundarias.through
        conteos = [(m._meta.label, m.objects.count()) for m in MODELOS]
        conteos.append((f"{through._meta.label} (categorías secundarias)", through.objects.count()))
        return conteos

    def _archivos_media(self):
        rutas = set(
            ServicioTurista.objects.exclude(imagen_principal="").values_list("imagen_principal", flat=True)
        )
        rutas |= set(ImagenServicioTurista.objects.exclude(imagen="").values_list("imagen", flat=True))
        return sorted(rutas)

    def handle(self, *args, **options):
        nombre_bd = connection.settings_dict["NAME"]
        confirmar = options["confirmar"]
        simulacion = confirmar is None

        self.stdout.write(f"Base de datos: {nombre_bd} @ {connection.settings_dict['HOST'] or 'local'}")
        self.stdout.write("Modo: SIMULACIÓN (no se borra nada)" if simulacion else "Modo: BORRADO REAL")
        self.stdout.write("Filas afectadas:")
        for etiqueta, n in self._conteos():
            self.stdout.write(f"  {etiqueta}: {n}")
        archivos = self._archivos_media()
        self.stdout.write(f"Archivos de media que quedarían sin referencia (NO se borran): {len(archivos)}")
        for ruta in archivos:
            self.stdout.write(f"  {ruta}")
        self.stdout.write("No se tocan: categorías, otras apps, migraciones ni esquema.")

        if simulacion:
            self.stdout.write(self.style.WARNING(
                f"Simulación terminada. Para borrar: --confirmar {nombre_bd}"
            ))
            return

        if confirmar != nombre_bd:
            raise CommandError(
                f"--confirmar no coincide con la base de datos actual ({nombre_bd}). No se borró nada."
            )

        with transaction.atomic():
            for modelo in MODELOS:
                modelo.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Limpieza completada. Filas restantes:"))
        for etiqueta, n in self._conteos():
            self.stdout.write(f"  {etiqueta}: {n}")
