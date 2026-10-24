"""Vistas de consulta (solo lectura) colgadas del Admin de PeriodoEvaluacion.

No hay modelos "falsos": son URLs propias del ModelAdmin, protegidas por admin_view (staff) y por
el permiso de ver periodos. Ninguna vista escribe en la BD.
"""
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .choices import OrigenDato
from .models import PeriodoEvaluacion
from .services import presentacion
from .services.datos import cargar_datos
from .services.resumenes import resumen_mensual, resumen_semanal, resumen_total
from .services.validacion import validar_periodo_metricas

VISTAS = (
    ("semanal", "Resumen semanal"),
    ("mensual", "Resumen mensual"),
    ("total", "Resumen total y validación"),
)


class ResumenesAdminMixin:
    def _nombre(self, vista):
        meta = self.model._meta
        return f"{meta.app_label}_{meta.model_name}_resumen_{vista}"

    def get_urls(self):
        propias = [
            path(f"resumen/{vista}/", self.admin_site.admin_view(getattr(self, f"vista_{vista}")), name=self._nombre(vista))
            for vista, _ in VISTAS
        ]
        return propias + super().get_urls()  # antes del comodín <object_id>

    def enlaces_resumen(self, periodo, origen=OrigenDato.SIMULADO):
        consulta = f"?periodo={periodo.pk}&origen={origen}"
        return [
            (titulo, reverse(f"admin:{self._nombre(vista)}") + consulta, vista) for vista, titulo in VISTAS
        ]

    def _seleccion(self, request):
        periodos = list(PeriodoEvaluacion.objects.order_by("-activo", "-fecha_inicio"))
        pedido = request.GET.get("periodo", "")
        periodo = next((p for p in periodos if str(p.pk) == pedido), None) or (periodos[0] if periodos else None)
        origen = request.GET.get("origen")
        return periodos, periodo, origen if origen in OrigenDato.values else OrigenDato.SIMULADO

    def _responder(self, request, vista, construir):
        if not self.has_view_permission(request):
            raise PermissionDenied
        periodos, periodo, origen = self._seleccion(request)
        titulo = dict(VISTAS)[vista]
        contexto = {
            **self.admin_site.each_context(request),
            "title": titulo, "opts": self.model._meta, "vista": vista, "periodos": periodos, "periodo": periodo,
            "origen": origen, "origenes": OrigenDato.choices,
            "pestanas": [
                {"titulo": t, "url": reverse(f"admin:{self._nombre(v)}") + (
                    f"?periodo={periodo.pk}&origen={origen}" if periodo else ""), "activa": v == vista}
                for v, t in VISTAS
            ],
        }
        if periodo is not None:
            contexto.update(construir(request, periodo, origen))
        return TemplateResponse(request, "admin/metricas/resumen.html", contexto)

    def vista_semanal(self, request):
        return self._responder(request, "semanal", lambda r, p, o: {
            "tablas": presentacion.tablas_intervalos(resumen_semanal(p, o), presentacion.etiqueta_semanal),
        })

    def vista_mensual(self, request):
        return self._responder(request, "mensual", lambda r, p, o: {
            "tablas": presentacion.tablas_intervalos(resumen_mensual(p, o), presentacion.etiqueta_mensual, mensual=True),
        })

    def vista_total(self, request):
        def construir(request, periodo, origen):
            datos = cargar_datos(periodo, origen)  # una sola carga para el resumen y la validación
            validacion = validar_periodo_metricas(periodo, origen, datos=datos)
            return {
                "tablas": presentacion.tablas_total(resumen_total(periodo, origen, datos=datos)),
                "validacion": validacion,
                "mostrar_validacion": request.GET.get("validar") == "1",
                "url_validar": reverse(f"admin:{self._nombre('total')}")
                + f"?periodo={periodo.pk}&origen={origen}&validar=1",
            }
        return self._responder(request, "total", construir)
