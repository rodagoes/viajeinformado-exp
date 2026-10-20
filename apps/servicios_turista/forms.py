"""Formulario de la sede en el Admin: horario por bloques y copia desde otra sede.

Los campos de horario del formulario NO son columnas: se convierten en
SedeServicioTurista.horario (JSON) y el modelo genera el texto ES/EN. Un horario es
*estructurado* (bloques) o *personalizado* (texto ES/EN); nunca se mezclan en silencio.
"""
import copy
import datetime

from django import forms

from .models import SedeServicioTurista
from .services import horarios

BLOQUES_FORM = (("lv", "Lunes a viernes"), ("sa", "Sábados"), ("do", "Domingos"))
ESTADOS = [("", "Sin indicar"), ("abierto", "Abierto"), ("cerrado", "Cerrado")]
TEXTOS = ("horario_atencion_es", "horario_atencion_en")
AYUDA_COPIAR = "Copia el horario completo (bloques o texto) y la disponibilidad de otra sede de esta misma entidad."


def _campos_horario():
    campos = {}
    for clave, nombre in BLOQUES_FORM:
        campos[f"{clave}_estado"] = forms.ChoiceField(label=nombre, choices=ESTADOS, required=False)
        for sufijo, etiqueta in (("d1", "Desde"), ("h1", "Hasta"), ("d2", "Desde (2.º tramo)"), ("h2", "Hasta (2.º tramo)")):
            campos[f"{clave}_{sufijo}"] = forms.TimeField(
                label=etiqueta, required=False, input_formats=["%H:%M", "%H:%M:%S"],
                widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            )
    campos["copiar_horario_de"] = forms.ModelChoiceField(
        queryset=SedeServicioTurista.objects.none(), required=False,
        label="Copiar horario de otra sede", help_text=AYUDA_COPIAR,
    )
    return campos


class _SedeFormBase(forms.ModelForm):
    class Meta:
        model = SedeServicioTurista
        fields = "__all__"
        widgets = {
            "maps_url": forms.Textarea(attrs={"rows": 3, "spellcheck": "false", "autocomplete": "off"}),
            "embed_maps": forms.Textarea(attrs={"rows": 6, "spellcheck": "false", "autocomplete": "off"}),
        }

    class Media:
        # CSS/JS solo del Admin de sedes (ancho de los campos de Maps y turno 2 plegable).
        css = {"all": ("assets/admin/sedes-admin.css",)}
        js = ("assets/admin/sedes-admin.js",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configurar_mapas()
        self._configurar_horario()

    def _configurar_mapas(self):
        ayudas = {
            "maps_url": (
                "URL de la ficha de Google Maps (recomendado)",
                "Abra esta sede exacta en Google Maps y copie la URL de la barra de direcciones (https://www.google.com/maps/place/…).",
            ),
            "embed_maps": (
                "Código de inserción (iframe)",
                "En la misma ficha: Compartir → Insertar un mapa → Copiar HTML. Pegue el código completo.",
            ),
            "latitud": ("Latitud del pin", "Opcional. Para una ruta exacta: clic derecho sobre el pin en Google Maps y copie los dos números."),
            "longitud": ("Longitud del pin", "Opcional, junto con la latitud."),
        }
        for nombre, (etiqueta, ayuda) in ayudas.items():
            if nombre in self.fields:
                self.fields[nombre].label, self.fields[nombre].help_text = etiqueta, ayuda

    def _configurar_horario(self):
        sede = self.instance
        estructurado = bool(sede.pk and sede.horario)
        if estructurado:
            for clave, _nombre in BLOQUES_FORM:
                if clave not in sede.horario:
                    continue
                tramos = sede.horario[clave]
                self.initial[f"{clave}_estado"] = "abierto" if tramos else "cerrado"
                for i, (desde, hasta) in enumerate(tramos[:2], 1):
                    self.initial[f"{clave}_d{i}"] = datetime.time.fromisoformat(desde)
                    self.initial[f"{clave}_h{i}"] = datetime.time.fromisoformat(hasta)
            for nombre in TEXTOS:
                if nombre in self.fields:
                    # En modo por bloques el texto lo genera el sistema: se muestra solo en la vista previa.
                    self.fields[nombre].disabled = True
                    self.fields[nombre].widget = forms.HiddenInput()
        campo = self.fields["copiar_horario_de"]
        if sede.pk:
            hermanas = SedeServicioTurista.objects.filter(servicio_id=sede.servicio_id).exclude(pk=sede.pk)
            ids = [
                h.pk for h in hermanas
                if h.horario or h.horario_atencion_es or h.horario_atencion_en or h.disponibilidad != "consultar"
            ]
            campo.queryset = SedeServicioTurista.objects.filter(pk__in=ids)
            campo.label_from_instance = lambda h: f"{h.nombre or '(sede sin nombre)'}: {h.horario_atencion_es or h.get_disponibilidad_display()}"
        else:
            campo.disabled = True
            campo.help_text = "Disponible al editar la sede, una vez guardada. " + AYUDA_COPIAR

    def clean(self):
        datos = super().clean()
        estructura, usa_bloques = {}, False
        for clave, nombre in BLOQUES_FORM:
            estado = datos.get(f"{clave}_estado") or ""
            pares = [(datos.get(f"{clave}_d1"), datos.get(f"{clave}_h1")), (datos.get(f"{clave}_d2"), datos.get(f"{clave}_h2"))]
            hay_horas = any(x is not None for par in pares for x in par)
            if not estado:
                if hay_horas:
                    self.add_error(f"{clave}_estado", f"{nombre}: marque «Abierto» o «Cerrado» (hay horas escritas).")
                continue
            usa_bloques = True
            if estado == "cerrado":
                if hay_horas:
                    self.add_error(f"{clave}_estado", f"{nombre}: «Cerrado» no lleva horas.")
                else:
                    estructura[clave] = []
                continue
            tramos, con_error = [], False
            for i, (desde, hasta) in enumerate(pares, 1):
                if desde is None and hasta is None:
                    continue
                if desde is None or hasta is None:
                    self.add_error(f"{clave}_{'d' if desde is None else 'h'}{i}", "Complete la hora de inicio y la de fin.")
                    con_error = True
                    continue
                tramos.append([desde.strftime("%H:%M"), hasta.strftime("%H:%M")])
            if pares[0] == (None, None) and pares[1] != (None, None):
                self.add_error(f"{clave}_d1", "Complete primero el tramo 1.")
            elif not tramos and not con_error:
                self.add_error(f"{clave}_estado", f"{nombre}: «Abierto» necesita al menos un tramo.")
            else:
                estructura[clave] = tramos
        if not self._errors:
            for problema in horarios.validar_estructura(estructura):
                self.add_error(None, problema)

        origen = datos.get("copiar_horario_de")
        textos_editados = [t for t in TEXTOS if t in self.changed_data]
        if origen:
            servicio = datos.get("servicio")
            servicio_id = servicio.pk if servicio else self.instance.servicio_id
            if usa_bloques or textos_editados:
                self.add_error("copiar_horario_de", "Elija una sola cosa: copiar el horario de otra sede o editar el de esta (bloques o texto).")
            elif origen.servicio_id != servicio_id:
                self.add_error("copiar_horario_de", "La sede elegida no pertenece a esta entidad.")
            else:
                datos["disponibilidad"] = origen.disponibilidad
                datos["horario_atencion_es"] = origen.horario_atencion_es or ""
                datos["horario_atencion_en"] = origen.horario_atencion_en or ""
                self.instance.horario = copy.deepcopy(origen.horario)  # copia independiente
        elif usa_bloques:
            if textos_editados:
                self.add_error(None, "Use bloques o un texto personalizado, no ambos: se editó el texto y también los bloques.")
            self.instance.horario = estructura
        elif self.instance.pk and self.instance.horario:
            self.instance.horario = {}  # pasó a texto personalizado; el último texto generado se conserva
        return datos


SedeAdminForm = type("SedeAdminForm", (_SedeFormBase,), _campos_horario())
