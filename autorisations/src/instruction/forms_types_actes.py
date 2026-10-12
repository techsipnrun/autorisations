from django import forms

from autorisations.models.models_documents import DocumentNature


class TypeActeForm(forms.ModelForm):
    """Configuration d'un acte, distincte des autres natures documentaires."""

    class Meta:
        model = DocumentNature
        fields = (
            "nature", "actif", "prefixe_numero", "prefixe_nom_fichier",
            "circuit_signature", "rapport_ca_obligatoire", "mode_publication_raa", "autorise_dm",
        )
        labels = {
            "nature": "Nom du type d’acte", "actif": "Actif",
            "circuit_signature": "Circuit de signature",
            "rapport_ca_obligatoire": "Rapport CA obligatoire", "mode_publication_raa": "Publication au RAA",
            "autorise_dm": "Ce type d'acte peut être déposé sur DM",
        }
        help_texts = {
            "actif": (
                "Oui : proposé lors de la création d’un projet d’acte.\n"
                "Non : retiré des nouveaux choix ; les actes existants restent accessibles et peuvent poursuivre leur traitement."
            ),
            "circuit_signature": (
                "Choisit le circuit de transmission pour la signature :\n"
                "Direction ou Conseil d’administration."
            ),
            "rapport_ca_obligatoire": "Oui : un projet de rapport CA puis un rapport CA signé doivent accompagner l’acte.",
            "mode_publication_raa": (
                "Dans AGIDA : passage par « À publier au RAA ».\n"
                "Déjà réalisée hors AGIDA : classement direct et acte marqué publié.\n"
                "Non requise : classement direct sans marquer l’acte publié."
            ),
            "autorise_dm": "Autorise le dépôt du fichier sur Déclaration Manifestations pour un dossier lié. L’avis favorable ou défavorable dépend toujours de la décision du dossier.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nom in ("prefixe_numero", "prefixe_nom_fichier"):
            self.fields[nom].required = True
        for nom in ("actif", "rapport_ca_obligatoire", "autorise_dm"):
            self.initial[nom] = "true" if getattr(self.instance, nom) else "false"
            self.fields[nom] = forms.TypedChoiceField(
                label=self.fields[nom].label, choices=(("true", "Oui"), ("false", "Non")),
                help_text=self.fields[nom].help_text,
                coerce=lambda valeur: valeur == "true", required=True,
                initial="true" if getattr(self.instance, nom) else "false",
            )
        for champ in self.fields.values():
            champ.widget.attrs["class"] = "back-office-acte-input"
            champ.widget.attrs["required"] = True

    def clean(self):
        donnees = super().clean()
        if donnees.get("rapport_ca_obligatoire"):
            manquants = {"Projet Rapport CA", "Rapport CA"} - set(
                DocumentNature.objects.filter(nature__in=("Projet Rapport CA", "Rapport CA")).values_list("nature", flat=True)
            )
            if manquants:
                raise forms.ValidationError("Références documentaires manquantes : " + ", ".join(sorted(manquants)))
        return donnees
