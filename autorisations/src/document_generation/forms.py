"""Édition des métadonnées du template ; aucune saisie des balises détectées."""

from django import forms

from autorisations.models.models_generation import Balise, DocumentTemplate
from .services.context_utils import set_nested_value
from .services.validation import valeur_vide
from .repeated_fields import RepeatedTextField, RepeatedTextWidget


class DocumentTemplateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destination_relative"].required = True
        self.fields["nom_fichier"].required = True

    def clean(self):
        cleaned = super().clean()
        for name in ("destination_relative", "nom_fichier"):
            if name in cleaned:
                cleaned[name] = cleaned[name].replace("{num_doss}", "{dossier.numero}")
        return cleaned

    class Meta:
        model = DocumentTemplate
        fields = ("nom", "id_nature", "chemin_relatif", "actif", "demarches", "destination_relative", "nom_fichier")


class BaliseConfigurationForm(forms.ModelForm):
    class Meta:
        model = Balise
        fields = ("code", "libelle", "source", "source_propriete", "type", "libelle_element", "required", "help_text", "actif")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services.catalogue_sources import PROPERTY_LABELS, AVAILABLE_PROPERTIES
        self.fields['source'].required = True
        self.fields['source_propriete'] = forms.ChoiceField(required=False, choices=[('', 'Choisir une information')]
            + [(code, PROPERTY_LABELS.get(code, code)) for code in AVAILABLE_PROPERTIES if code != 'dossier.commune'])
        self.fields['type'].choices = [(value, label) for value, label in Balise.Type.choices
                                      if value not in (Balise.Type.SELECT, Balise.Type.MULTISELECT)]
        if self.instance.pk:
            self.fields['code'].disabled = True

    def clean(self):
        data = super().clean()
        source = data.get('source')
        self.instance.mode = Balise.Mode.A_RENSEIGNER if source == Balise.Source.MANUELLE else Balise.Mode.CONNUE
        self.instance.allow_blank = not data.get('required', False)
        if source == Balise.Source.AGIDA and not data.get('source_propriete'):
            self.add_error('source_propriete', 'Choisissez une information AGIDA.')
        if source != Balise.Source.AGIDA:
            data['source_propriete'] = ''
        if data.get('type') == Balise.Type.LIST:
            if source != Balise.Source.MANUELLE:
                self.add_error('source', 'Une liste répétable doit être renseignée par l’instructeur.')
            if not data.get('libelle_element', '').strip():
                self.add_error('libelle_element', 'Indiquez le libellé de chaque ligne de la liste, par exemple Nom.')
        return data


class DynamicDocumentForm(forms.Form):
    def __init__(self, *args, balises=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.balise_map = {}
        for balise in balises or []:
            if balise.pk is None:
                raise ValueError("Une balise du formulaire doit avoir un identifiant catalogue.")
            name = f"balise_{balise.pk}"
            if name in self.balise_map:
                raise ValueError("Balise dupliquée dans le formulaire.")
            self.balise_map[name] = balise
            self.fields[name] = self.build_field(balise)
            self.fields[name].balise_code = balise.code

    @staticmethod
    def build_field(balise):
        options = dict(label=balise.libelle or balise.code,
                       required=balise.required,
                       help_text=balise.help_text)
        if balise.type == Balise.Type.TEXT:
            return forms.CharField(**options)
        if balise.type == Balise.Type.LIST:
            return RepeatedTextField(widget=RepeatedTextWidget(balise.libelle_element), **options)
        if balise.type == Balise.Type.TEXTAREA:
            return forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), **options)
        if balise.type == Balise.Type.INTEGER:
            return forms.IntegerField(**options)
        if balise.type == Balise.Type.DECIMAL:
            return forms.DecimalField(**options)
        if balise.type == Balise.Type.DATE:
            return forms.DateField(input_formats=["%Y-%m-%d"],
                                   widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), **options)
        if balise.type == Balise.Type.BOOLEAN:
            return forms.TypedChoiceField(
                choices=(("", "Choisir…"), ("true", "Oui"), ("false", "Non")),
                coerce=lambda value: value == "true", empty_value=None, **options,
            )
        raise ValueError(f"Type de saisie non pris en charge : {balise.type} ({balise.code}).")

    def clean(self):
        cleaned = super().clean()
        for name, balise in self.balise_map.items():
            if name not in cleaned:
                continue
            if balise.required and self.add_prefix(name) not in self.data:
                self.add_error(name, "Ce champ doit être renseigné.")
                continue
            raw = self.data.get(self.add_prefix(name))
            # Un contrôle facultatif laissé vide est une absence de saisie.
            # Une valeur vide n'est interdite que pour un champ obligatoire.
            if balise.required and valeur_vide(cleaned[name]) and raw:
                self.add_error(name, "La valeur saisie ne peut pas être vide.")
        return cleaned

    def to_manual_values(self):
        if not self.is_valid():
            raise ValueError("Le formulaire doit être valide avant de construire son contexte.")
        values = {}
        for name, balise in self.balise_map.items():
            value = self.cleaned_data[name]
            if balise.type == Balise.Type.LIST:
                values[balise.code] = value
                continue
            if not balise.required and valeur_vide(value) and not self.data.get(self.add_prefix(name)):
                continue
            values[balise.code] = value
        return values

    def to_context(self):
        context = {}
        for code, value in self.to_manual_values().items():
            set_nested_value(context, code, value)
        return context
