from django import forms
from django.core.exceptions import ValidationError

from .choices import DispositivoAcceso, FuenteTrafico, OrigenDato
from .models import InteraccionDiaria, MetaMuestraMensual, MetricaDiaria, UnicosPeriodo
from .services.unicos import evaluar_fila_unicos
from .services.validaciones import errores_recurrentes_diarios


class OrigenSimuladoFormMixin:
    """Alta manual orientada a SIMULADO.

    En el alta, `origen` se muestra deshabilitado y fijo en SIMULADO: un campo
    deshabilitado ignora lo que llegue por POST y usa solo el inicial, así que no
    puede forzarse REAL/GA4 ni por querystring (?origen=REAL) ni manipulando el
    formulario. Sigue siendo parte del formulario para que la validación de
    unicidad (periodo, origen, fecha…) funcione. Tras crear, el origen pasa a
    solo lectura (lo decide el ModelAdmin).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields.get("origen")
        if campo is not None:
            campo.choices = [(OrigenDato.SIMULADO.value, OrigenDato.SIMULADO.label)]
            campo.initial = OrigenDato.SIMULADO.value
            campo.disabled = True
            self.initial["origen"] = OrigenDato.SIMULADO.value


class MetricaDiariaForm(OrigenSimuladoFormMixin, forms.ModelForm):
    class Meta:
        model = MetricaDiaria
        fields = "__all__"

    def _valor(self, campo):
        """Valor del formulario o, si el campo es solo lectura (edición), el de la instancia."""
        if campo in self.cleaned_data:
            return self.cleaned_data[campo]
        if campo in self.fields:
            return None  # el campo está en el formulario pero no validó
        return getattr(self.instance, campo, None)

    def clean(self):
        datos = super().clean()
        periodo, origen, fecha = self._valor("periodo"), self._valor("origen"), self._valor("fecha")
        nuevos, recurrentes = datos.get("usuarios_nuevos"), datos.get("usuarios_recurrentes")
        if None in (periodo, origen, fecha, nuevos, recurrentes):
            return datos
        errores = errores_recurrentes_diarios(
            periodo=periodo, origen=origen, fecha=fecha, nuevos=nuevos, recurrentes=recurrentes,
            excluir_pk=self.instance.pk,
        )
        if errores:
            raise ValidationError(errores)
        return datos


class InteraccionDiariaForm(OrigenSimuladoFormMixin, forms.ModelForm):
    class Meta:
        model = InteraccionDiaria
        fields = "__all__"


class UnicosPeriodoForm(forms.ModelForm):
    """Solo `usuarios_recurrentes` es editable. Las cotas respecto de las métricas diarias
    rechazan el guardado; lo no concluyente (faltan días) se informa como advertencia.
    Nunca se reajusta el valor automáticamente.
    """

    class Meta:
        model = UnicosPeriodo
        fields = "__all__"

    advertencias = ()

    def clean(self):
        datos = super().clean()
        recurrentes = datos.get("usuarios_recurrentes")
        if recurrentes is None or self.instance.pk is None:
            return datos
        errores, self.advertencias = evaluar_fila_unicos(self.instance, recurrentes=recurrentes)
        if errores:
            raise ValidationError(errores)
        return datos


class DesgloseBaseFormSet(forms.BaseInlineFormSet):
    """Fuente/dispositivo de una fila diaria: el CONJUNTO debe sumar las sesiones del día.

    - Al crear (o al faltar categorías) se ofrecen en la misma pantalla las
      categorías que aún no existen, con 0 sesiones: solo se guardan las que se
      completan; una categoría ausente equivale a 0.
    - La regla de suma no se relaja: se valida en cada guardado, incluso si solo
      cambió `sesiones` en el formulario padre.
    """

    campo = None  # nombre del campo categoría
    opciones = None  # TextChoices con las categorías
    etiqueta = ""  # texto para los mensajes

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        if not kwargs.get("initial"):
            existentes = set()
            if instance is not None and instance.pk:
                existentes = set(self.model.objects.filter(metrica_diaria=instance).values_list(self.campo, flat=True))
            kwargs["initial"] = [
                {self.campo: valor, "sesiones": 0} for valor, _ in self.opciones.choices if valor not in existentes
            ]
        super().__init__(*args, **kwargs)

    def clean(self):
        if any(self.errors):
            return  # primero se corrigen los errores de cada fila
        vistos, total = set(), 0
        for form in self.forms:
            datos = getattr(form, "cleaned_data", None)
            if not datos or datos.get("DELETE"):
                continue
            categoria = datos.get(self.campo)
            if categoria in vistos:
                raise ValidationError(f"Hay más de una fila para la misma categoría de {self.etiqueta}.")
            vistos.add(categoria)
            total += datos.get("sesiones") or 0
        esperado = self.instance.sesiones or 0
        if total != esperado:
            raise ValidationError(
                f"La suma de sesiones por {self.etiqueta} ({total}) debe ser igual a las sesiones del día ({esperado})."
            )
        super().clean()


class FuenteFormSet(DesgloseBaseFormSet):
    campo = "fuente"
    opciones = FuenteTrafico
    etiqueta = "fuente de tráfico"


class DispositivoFormSet(DesgloseBaseFormSet):
    campo = "dispositivo"
    opciones = DispositivoAcceso
    etiqueta = "dispositivo"


class MetasFormSet(forms.BaseInlineFormSet):
    """Metas mensuales de un periodo.

    Valida con las fechas del periodo tal como quedan en este mismo envío (también
    en el alta, donde el periodo aún no tiene pk y el modelo no puede hacerlo).
    Las metas pueden cargarse de forma incremental (suma < tamaño es válida), pero
    la suma nunca puede superar el tamaño de la muestra.
    """

    def clean(self):
        if any(self.errors):
            return
        periodo = self.instance
        vistos, total = set(), 0
        for form in self.forms:
            datos = getattr(form, "cleaned_data", None)
            if not datos or datos.get("DELETE"):
                continue
            anio, mes = datos.get("anio"), datos.get("mes")
            if (anio, mes) in vistos:
                raise ValidationError(f"El mes {mes:02d}/{anio} está repetido.")
            vistos.add((anio, mes))
            if periodo.fecha_inicio and periodo.fecha_fin and not MetaMuestraMensual.mes_intersecta(
                anio, mes, periodo.fecha_inicio, periodo.fecha_fin,
            ):
                raise ValidationError(f"El mes {mes:02d}/{anio} no intersecta el periodo de evaluación.")
            total += datos.get("nuevos_objetivo") or 0
        if periodo.tamano_muestra is not None and total > periodo.tamano_muestra:
            raise ValidationError(
                f"Las metas mensuales suman {total}, más que el tamaño de la muestra ({periodo.tamano_muestra})."
            )
        super().clean()
