"""Providers Python contrôlés ; aucune expression issue du back-office."""

from functools import cached_property

from autorisations.models.models_utilisateurs import ContactExterne
from autorisations.models.models_instruction import Champ, DossierChamp


class BeneficiaireAmbiguError(ValueError):
    """Une balise singulière ne peut pas représenter plusieurs bénéficiaires."""


def texte_normalise(value):
    """Retire les espaces périphériques sans modifier la casse des données."""
    return (value.strip() or None) if value is not None else None


class ResolutionSource:
    """Données partagées pour un rendu, sans cache global entre dossiers."""

    def __init__(self, dossier):
        if dossier.pk is None:
            raise ValueError("Le dossier doit être enregistré avant la résolution.")
        self.dossier = dossier

    @cached_property
    def beneficiaire(self):
        # DISTINCT évite qu'un même contact lié plusieurs fois soit ambigu.
        contacts = list(ContactExterne.objects.filter(
            dossierbeneficiaire__id_dossier_interlocuteur__id_dossier=self.dossier,
        ).order_by("pk").distinct()[:2])
        if len(contacts) > 1:
            raise BeneficiaireAmbiguError(
                f"Le dossier {self.dossier.numero} possède plusieurs bénéficiaires distincts."
            )
        return contacts[0] if contacts else None

    def identite_beneficiaire(self, champ):
        if self.beneficiaire is None:
            return None
        return texte_normalise(getattr(self.beneficiaire, champ))


def dossier_numero(source):
    return source.dossier.numero


def dossier_nom(source):
    return texte_normalise(source.dossier.nom_dossier)


def dossier_commune(source):
    """Champ Commune de la démarche Test ; aucune saisie du dossier n'est modifiée."""
    dossier = source.dossier
    if not dossier.id_demarche_id or (dossier.id_demarche.type or '').strip().casefold() != 'test':
        return None
    fields = list(Champ.objects.filter(id_demarche_id=dossier.id_demarche_id, nom__iexact='Commune')
                  .order_by('pk').values_list('pk', flat=True)[:2])
    if len(fields) > 1:
        raise ValueError("Plusieurs champs Commune existent dans la démarche Test ; la source doit être précisée.")
    if not fields:
        return None
    value = DossierChamp.objects.filter(id_dossier=dossier, id_champ_id=fields[0]).order_by(
        '-date_saisie', '-pk').values_list('valeur', flat=True).first()
    return texte_normalise(value)


def beneficiaire_nom(source):
    return source.identite_beneficiaire("nom")


def beneficiaire_prenom(source):
    return source.identite_beneficiaire("prenom")


def beneficiaire_nom_complet(source):
    return " ".join(filter(None, (
        beneficiaire_prenom(source), beneficiaire_nom(source),
    ))) or None


KNOWN_PROVIDERS = {
    "dossier.numero": dossier_numero,
    "dossier.nom": dossier_nom,
    "dossier.commune": dossier_commune,
    "beneficiaire.nom": beneficiaire_nom,
    "beneficiaire.prenom": beneficiaire_prenom,
    "beneficiaire.nom_complet": beneficiaire_nom_complet,
}
