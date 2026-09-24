"""Etiquetas de `choices` de modelos que se muestran al turista.

Los `choices` de los modelos se quedan en español (envolverlos en gettext_lazy
generaría ruido de migraciones). Los templates los traducen con
`{% translate obj.get_campo_display %}`; este módulo solo existe para que
`makemessages` extraiga esos textos al catálogo.
"""
from django.utils.translation import gettext_noop

ETIQUETAS_CHOICES = (
    # turismo.LugarTuristico.dificultad
    gettext_noop("No aplica"),
    gettext_noop("Fácil"),
    gettext_noop("Moderada"),
    gettext_noop("Difícil"),
    # establecimientos.Establecimiento.rango_precio
    gettext_noop("Económico"),
    gettext_noop("Moderado"),
    gettext_noop("Alto"),
    gettext_noop("Consultar"),
    # emergencias.ContactoEmergencia.categoria (respuestas de PillcoBot)
    gettext_noop("Policía"),
    gettext_noop("Bomberos"),
    gettext_noop("Salud"),
    gettext_noop("Policía de Turismo"),
    gettext_noop("Serenazgo"),
    gettext_noop("Municipal"),
    gettext_noop("Otro"),
    # servicios_turista.ServicioTurista.tipo_atencion / disponibilidad
    gettext_noop("Presencial"),
    gettext_noop("Telefónica"),
    gettext_noop("Virtual"),
    gettext_noop("Mixta"),
    gettext_noop("Horario específico"),
    gettext_noop("24 horas"),
    gettext_noop("Emergencia"),
)
