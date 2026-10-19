"""Validation commune aux demandes, brouillons et imports d'avis."""
from django import forms

from instruction.utils.avis_formulaires import CHOIX_IMPORT, FICHIERS, evaluer_configuration


class ImportAvisCSForm(forms.Form):
    numero_avis_externe = forms.CharField(max_length=100, required=False, label="Numéro de l'avis CS importé")
    publication_raa = forms.ChoiceField(choices=(
        ("a_publier", "À publier"), ("deja_publie", "Déjà publié"), ("non_requise", "Publication non requise"),
    ), label="Publication au RAA")


class DemandeAvisForm(forms.Form):
    def __init__(self, data, files, *, configuration, etat, variables, avis=None, brouillon=False, thematiques_autorisees=None):
        self.effectifs = evaluer_configuration(configuration, etat, variables)
        self.avis = avis
        self.etat = etat
        self.brouillon = brouillon
        self.thematiques_autorisees = thematiques_autorisees
        data = data.copy()
        self.fichiers_actifs = files.copy()
        for code, champ in self.effectifs.items():
            if code in FICHIERS:
                if not champ["visible"]:
                    self.fichiers_actifs.pop(code, None)
                continue
            if not champ["visible"]:
                # Ignorer les données forgées de champs masqués, sans effacer un brouillon.
                attribut = {"note_demandeur": "note", "formulation_avis": "formulation", "destinataire": "destinataire"}.get(code)
                data[code] = str(getattr(avis, attribut, "") or "") if avis and attribut else ""
            elif not data.get(code, "").strip() and champ["defaut"]:
                data[code] = champ["defaut"]
        # Un expert invisible ne doit jamais rester envoyé avec l'expert sélectionné.
        for code in ("expert_interne", "expert_externe"):
            if not self.effectifs[code]["visible"]:
                data[code] = ""
        super().__init__(data, self.fichiers_actifs)
        self.donnees = data
        if not self.effectifs["pj_lie_avis"]["visible"]:
            for cle in list(self.fichiers_actifs):
                if cle.startswith("remplacer_pj_"):
                    self.fichiers_actifs.pop(cle)
        obligation = "requis_brouillon" if brouillon else "requis_envoi"
        for code, champ in self.effectifs.items():
            if code not in FICHIERS:
                options = {"label": champ["libelle"], "required": champ["visible"] and champ[obligation]}
                if code in CHOIX_IMPORT:
                    self.fields[code] = forms.ChoiceField(choices=CHOIX_IMPORT[code], **options)
                elif code in {"date_demande_avis", "date_reponse_avis"}:
                    self.fields[code] = forms.DateTimeField(**options)
                elif code == "numero_avis_externe":
                    self.fields[code] = forms.CharField(max_length=100, **options)
                else:
                    self.fields[code] = forms.CharField(**options)

    def clean(self):
        donnees = super().clean()
        obligation = "requis_brouillon" if self.brouillon else "requis_envoi"
        for code, champ in self.effectifs.items():
            if champ["visible"] and champ[obligation] and code in FICHIERS:
                attribut = FICHIERS[code]
                existe = bool(self.avis and attribut and getattr(self.avis, attribut + "_id", None))
                if code == "pj_lie_avis" and self.avis:
                    existe = self.avis.avisdocument_set.exclude(id_document__id_nature__nature="Avis instance").exists()
                if not self.fichiers_actifs.getlist(code) and not existe:
                    raise forms.ValidationError(f"{champ['libelle']} : joignez le document requis.")
        if self.etat["nature_type"] not in {"interne", "instance"}:
            raise forms.ValidationError("Sélectionnez une nature d'avis autorisée.")
        if bool(donnees.get("expert_interne")) == bool(donnees.get("expert_externe")):
            raise forms.ValidationError("Sélectionnez un seul expert correspondant à la nature de l'avis.")
        if donnees.get("destinataire") and donnees["destinataire"] not in {"CS", "BCS"}:
            self.add_error("destinataire", "Choisissez CS ou BCS.")
        choix = self.thematiques_autorisees
        if choix is not None and donnees.get("thematique") and donnees["thematique"] not in choix:
            self.add_error("thematique", "Choisissez une thématique autorisée pour cette démarche.")
        return donnees
