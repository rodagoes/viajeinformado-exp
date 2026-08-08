from django import forms


class ReportarProblemaForm(forms.Form):
    titulo = forms.CharField(max_length=140, label="Nombre del problema")
    descripcion = forms.CharField(widget=forms.Textarea, max_length=2000, label="Describa el problema")
    # Honeypot: los bots suelen rellenar todos los campos, las personas nunca ven este.
    sitio_web = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_sitio_web(self):
        valor = self.cleaned_data.get("sitio_web")
        if valor:
            raise forms.ValidationError("Spam detectado.")
        return valor
