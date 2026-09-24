"""Carga OFFLINE las traducciones EN del contenido dinámico desde un JSON versionable.

    python manage.py importar_traducciones_en --dry-run
    python manage.py importar_traducciones_en
    python manage.py importar_traducciones_en --archivo ruta/otro.json

No llama a Gemini ni a ninguna API. Idempotente; nunca sobrescribe un `_en` existente.
Ver apps/base/traducciones_en.py.
"""
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.base import traducciones_en as t


class Command(BaseCommand):
    help = "Carga offline las traducciones EN desde un archivo JSON (idempotente, sin sobrescribir)."

    def add_arguments(self, parser):
        parser.add_argument("--archivo", default=None, help=f"Ruta del JSON (por defecto {t.RUTA_POR_DEFECTO} dentro del proyecto).")
        parser.add_argument("--dry-run", action="store_true", help="Valida y resume; no escribe nada.")

    def handle(self, *args, archivo=None, dry_run=False, **options):
        ruta = archivo or str(settings.BASE_DIR / t.RUTA_POR_DEFECTO)
        try:
            datos = t.cargar_archivo(ruta)
        except t.ArchivoInvalido as exc:
            raise CommandError(str(exc)) from exc

        errores = t.validar_estructura(datos)
        if errores:
            self.stdout.write(self.style.ERROR(f"Archivo inválido ({len(errores)} problema(s)); no se escribió nada:"))
            for e in errores[:50]:
                self.stdout.write(self.style.ERROR(f"  - {e}"))
            raise CommandError("El archivo de traducciones no es válido.")

        res = t.importar(datos, dry_run=dry_run)

        self.stdout.write(f"{'[DRY-RUN] ' if dry_run else ''}Archivo: {ruta}")
        self.stdout.write(f"Registros en el archivo: {res.registros}")
        if dry_run:
            self.stdout.write(f"Campos que se cargarían: {res.a_cargar} (No se escribió nada.)")
        else:
            self.stdout.write(f"Campos cargados: {res.cargados}")
        self.stdout.write(f"Ya traducidos (no se sobrescriben): {res.ya_traducidos}")
        if res.es_corregidos:
            self.stdout.write(f"Correcciones del ES fuente {'previstas' if dry_run else 'aplicadas'}: {res.es_corregidos}")
        self.stdout.write(f"No encontrados en este entorno (no aplica, no es error): {len(res.no_encontrados)}")
        for donde, motivo in res.no_encontrados:
            self.stdout.write(f"  · [no_encontrado] {donde}: {motivo}")
        self.stdout.write(f"Errores: {len(res.errores)}")
        por_tipo = Counter(tipo for _, tipo, _ in res.errores)
        for tipo, n in por_tipo.items():
            self.stdout.write(f"  · {tipo}: {n}")
        for donde, tipo, mensaje in res.errores:
            self.stdout.write(self.style.ERROR(f"  - [{tipo}] {donde}: {mensaje}"))
