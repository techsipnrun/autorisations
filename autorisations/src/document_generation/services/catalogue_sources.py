"""Sources configurables contrôlées : propriétés autorisées ou champ identifié."""

from datetime import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date
from autorisations.models.models_generation import Balise
from autorisations.models.models_instruction import DossierChamp
from .providers import KNOWN_PROVIDERS

AVAILABLE_PROPERTIES = {**KNOWN_PROVIDERS,
                        'document.numero': lambda source: getattr(source.dossier, '_generation_number', None),
                        "beneficiaire.raison_sociale": lambda source: source.identite_beneficiaire('raison_sociale')}


PROPERTY_LABELS = {
    'document.numero': 'Numéro du document (réservation système)',
    "dossier.numero": "Numéro du dossier", "dossier.nom": "Nom du dossier",
    "beneficiaire.nom": "Nom du bénéficiaire", "beneficiaire.prenom": "Prénom du bénéficiaire",
    "beneficiaire.nom_complet": "Nom complet du bénéficiaire", "dossier.commune": "Commune du dossier (Test)",
    "beneficiaire.raison_sociale": "Raison sociale du bénéficiaire",
}


def source_errors(balise):
    if balise.code == 'document.numero' and (not balise.required or balise.type != Balise.Type.TEXT or balise.mode != Balise.Mode.CONNUE
        or balise.source not in ('', Balise.Source.AGIDA)
        or balise.source_propriete not in ('', 'document.numero')):
        return ['document.numero est une balise système réservée, résolue depuis une réservation BDD.']
    if balise.source_propriete == 'document.numero' and balise.code != 'document.numero':
        return ['Utilisez le code système document.numero pour cette source.']
    if balise.type == Balise.Type.LIST and balise.mode != Balise.Mode.A_RENSEIGNER:
        return ["La liste répétable doit être renseignée par l'instructeur."]
    source = balise.source
    if not source:
        return [] if balise.mode != Balise.Mode.CONNUE or balise.code in KNOWN_PROVIDERS else ["Aucune source connue configurée."]
    if source not in Balise.Source.values:
        return ["Origine de la valeur invalide."]
    if (source == Balise.Source.MANUELLE) != (balise.mode == Balise.Mode.A_RENSEIGNER):
        return ["Le mode et l'origine de la valeur sont incohérents."]
    if source == Balise.Source.AGIDA:
        return [] if balise.source_propriete in AVAILABLE_PROPERTIES else ["Information AGIDA non disponible."]
    if source == Balise.Source.FORMULAIRE:
        mappings = list(balise.sources_champs.all())
        if not mappings:
            return ["Aucun champ de formulaire configuré."]
        if any(item.id_champ.id_demarche_id != item.id_demarche_id for item in mappings):
            return ["Un champ source n'appartient pas à sa démarche."]
    return []


def _convert(value, balise):
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        if balise.type == Balise.Type.INTEGER:
            return int(text)
        if balise.type == Balise.Type.DECIMAL:
            result = Decimal(text.replace(',', '.'))
            if not result.is_finite():
                raise ValueError
            return result
        if balise.type == Balise.Type.BOOLEAN:
            if text.casefold() not in ('oui', 'non', 'true', 'false', '1', '0'):
                raise ValueError
            return text.casefold() in ('oui', 'true', '1')
        if balise.type == Balise.Type.DATE:
            return parse_date(text) or datetime.strptime(text, '%d/%m/%Y').date()
        if balise.type not in (Balise.Type.TEXT, Balise.Type.TEXTAREA):
            raise ValueError
        return text
    except (ValueError, ArithmeticError, ValidationError) as exc:
        raise ValueError(f"La réponse du formulaire pour {balise.code} ne correspond pas au type {balise.type}.") from exc


def resolve_catalogue_source(balise, source):
    errors = source_errors(balise)
    if errors:
        raise ValueError(f"{balise.code} : {' '.join(errors)}")
    if not balise.source or balise.source == Balise.Source.AGIDA:
        return AVAILABLE_PROPERTIES[balise.source_propriete or balise.code](source)
    if balise.source == Balise.Source.FORMULAIRE:
        matches = [item for item in balise.sources_champs.all() if item.id_demarche_id == source.dossier.id_demarche_id]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError(f"Source de formulaire ambiguë pour {balise.code}.")
        value = DossierChamp.objects.filter(id_dossier=source.dossier, id_champ_id=matches[0].id_champ_id).order_by(
            '-date_saisie', '-pk').values_list('valeur', flat=True).first()
        return _convert(value, balise)
    raise ValueError(f"La balise {balise.code} doit être saisie par l'instructeur.")
