"""Providers Python contrôlés ; aucune expression issue du back-office."""

from functools import cached_property
from django.utils import timezone
from autorisations.models.models_instruction import DossierAction

from autorisations.models.models_utilisateurs import ContactExterne


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

    @cached_property
    def demandeur_intermediaire(self):
        contacts = list(ContactExterne.objects.filter(
            dossierinterlocuteur__id_dossier=self.dossier,
        ).order_by('pk').distinct()[:2])
        if len(contacts) > 1:
            raise BeneficiaireAmbiguError('Plusieurs demandeurs intermédiaires distincts sont associés à ce dossier.')
        return contacts[0] if contacts else None

    @cached_property
    def historique_dates(self):
        return list(DossierAction.objects.filter(id_dossier=self.dossier,
            id_action__action__in=['Passage en instruction', 'Repassage en instruction', 'Demande de compléments']
        ).order_by('date', 'pk').values_list('id_action__action', 'date'))

    @cached_property
    def annee_courante(self):
        return timezone.localdate().year


def annee_provider(decalage):
    return lambda source: source.annee_courante + decalage


def date_instruction(source, dernier=False, apres_complements=False):
    history = source.historique_dates
    demandes = [date for action, date in history if action == 'Demande de compléments' and date]
    if apres_complements and not demandes:
        return None
    passages = [date for action, date in history if action in ('Passage en instruction', 'Repassage en instruction')
                and date and (not apres_complements or date > demandes[-1])]
    return (passages[-1] if dernier else passages[0]) if passages else (None if apres_complements else source.dossier.date_debut_instruction)


def derniere_demande_complements(source):
    dates = [date for action, date in source.historique_dates if action == 'Demande de compléments' and date]
    return dates[-1] if dates else None


def dossier_demande_complements(source):
    return any(action == 'Demande de compléments' for action, _ in source.historique_dates)


def date_affichee(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%d/%m/%Y')


def intermediaire_prenom_nom(source):
    contact = source.demandeur_intermediaire
    if contact is None:
        return None
    prenom, nom = texte_normalise(contact.prenom), texte_normalise(contact.nom)
    return ' '.join(part for part in (prenom, nom.upper() if nom else None) if part) or None


def intermediaire_raison_sociale(source):
    contact = source.demandeur_intermediaire
    return (texte_normalise(contact.raison_sociale) or texte_normalise(contact.organisation)) if contact else None


def dossier_numero(source):
    return source.dossier.numero


def dossier_nom(source):
    return texte_normalise(source.dossier.nom_dossier)




def beneficiaire_prenom_nom(source):
    prenom = source.identite_beneficiaire('prenom')
    nom = source.identite_beneficiaire('nom')
    return ' '.join(part for part in (prenom, nom.upper() if nom else None) if part) or None


def beneficiaire_raison_sociale(source):
    return source.identite_beneficiaire('raison_sociale') or source.identite_beneficiaire('organisation')


KNOWN_PROVIDERS = {
    "dossier.numero": dossier_numero,
    "dossier.nom": dossier_nom,
}
