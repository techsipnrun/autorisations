"""Sources configurables contrôlées : propriétés autorisées ou champ identifié."""

from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date
from autorisations.models.models_generation import Balise
from autorisations.models.models_instruction import DossierChamp
from .providers import KNOWN_PROVIDERS, dossier_numero, dossier_nom, beneficiaire_prenom_nom, beneficiaire_raison_sociale
from .providers import (annee_provider, date_instruction, derniere_demande_complements,
                        date_affichee, intermediaire_prenom_nom, intermediaire_raison_sociale)
from .providers import dossier_demande_complements

@dataclass(frozen=True)
class AgidaProperty:
    label: str
    description: str
    category: str
    resolve: Callable


# Une seule définition par information : identité, aide, catégorie et résolution.
AGIDA_PROPERTIES = {
    'annee.n_plus_0': AgidaProperty(
        'Année en cours',
        'Année courante dans le fuseau horaire de l’application, augmentée de 0 an(s).',
        'Année', annee_provider(0),
    ),
    'annee.n_plus_1': AgidaProperty(
        'Année N+1',
        'Année courante dans le fuseau horaire de l’application, augmentée de 1 an(s).',
        'Année', annee_provider(1),
    ),
    'annee.n_plus_2': AgidaProperty(
        'Année N+2',
        'Année courante dans le fuseau horaire de l’application, augmentée de 2 an(s).',
        'Année', annee_provider(2),
    ),
    'annee.n_plus_3': AgidaProperty(
        'Année N+3',
        'Année courante dans le fuseau horaire de l’application, augmentée de 3 an(s).',
        'Année', annee_provider(3),
    ),
    'annee.n_plus_4': AgidaProperty(
        'Année N+4',
        'Année courante dans le fuseau horaire de l’application, augmentée de 4 an(s).',
        'Année', annee_provider(4),
    ),
    'annee.n_plus_5': AgidaProperty(
        'Année N+5',
        'Année courante dans le fuseau horaire de l’application, augmentée de 5 an(s).',
        'Année', annee_provider(5),
    ),
    'date.premier_passage_instruction': AgidaProperty(
        'Date du premier passage en instruction',
        'Premier passage ou repassage en instruction enregistré dans l’historique. À défaut, date de début d’instruction du dossier. Format JJ/MM/AAAA.',
        'Date', lambda s: date_affichee(date_instruction(s)),
    ),
    'date.dernier_passage_instruction': AgidaProperty(
        'Date du dernier passage en instruction',
        'Dernier passage ou repassage en instruction enregistré dans l’historique. À défaut, date de début d’instruction du dossier. Format JJ/MM/AAAA.',
        'Date', lambda s: date_affichee(date_instruction(s, dernier=True)),
    ),
    'date.instruction_apres_complements': AgidaProperty(
        'Date du dernier passage en instruction après une demande de compléments',
        'Dernier passage ou repassage en instruction postérieur à la dernière demande de compléments enregistrée. Vide si aucun passage ne suit cette demande. Format JJ/MM/AAAA.',
        'Date', lambda s: date_affichee(date_instruction(s, dernier=True, apres_complements=True)),
    ),
    'date.reception_dossier': AgidaProperty(
        'Date de réception du dossier',
        'Date de dépôt enregistrée sur le dossier dans AGIDA, au format JJ/MM/AAAA.',
        'Date', lambda s: date_affichee(s.dossier.date_depot),
    ),
    'date.derniere_demande_complements': AgidaProperty(
        'Date de la dernière demande de compléments',
        'Date de la dernière action Demande de compléments dans l’historique. Vide si aucune demande n’est enregistrée. Format JJ/MM/AAAA.',
        'Date', lambda s: date_affichee(derniere_demande_complements(s)),
    ),
    'dossier.numero': AgidaProperty(
        'Numéro du dossier',
        'Numéro du dossier concerné.',
        'Dossier', dossier_numero,
    ),
    'dossier.nom': AgidaProperty(
        'Nom du dossier',
        'Nom du dossier enregistré dans AGIDA.',
        'Dossier', dossier_nom,
    ),
    'document.numero': AgidaProperty(
        'Numéro du document (réservation système)',
        'Numéro attribué ou récupéré pour le document dans la page de génération ; il n’est pas attribué à l’ouverture du formulaire.',
        'Document', lambda source: getattr(source.dossier, '_generation_number', None),
    ),
    'dossier.demande_complements': AgidaProperty(
        'Demande de compléments (Oui/Non)',
        'Oui si au moins une action « Demande de compléments » est enregistrée dans l’historique du dossier, sinon Non. Prend en compte toutes les demandes, même anciennes ou déjà traitées. À utiliser avec le type Oui / Non.',
        'Dossier', dossier_demande_complements,
    ),
    'beneficiaire.prenom_nom': AgidaProperty(
        'Prénom NOM du bénéficiaire',
        'Prénom suivi du NOM en majuscules, séparés par un espace. Si un seul est renseigné, il est utilisé seul. Si les deux sont absents, la valeur reste vide.',
        'Pétitionnaire', beneficiaire_prenom_nom,
    ),
    'beneficiaire.raison_sociale': AgidaProperty(
        'Raison sociale du bénéficiaire',
        'Raison sociale enregistrée pour le bénéficiaire ; si elle est vide, utilise son organisation. Si les deux sont absentes, la valeur reste vide. Aucun raccourci d’affichage n’est utilisé.',
        'Pétitionnaire', beneficiaire_raison_sociale,
    ),
    'demandeur_intermediaire.prenom_nom': AgidaProperty(
        'Prénom NOM du demandeur intermédiaire',
        'Prénom suivi du NOM en majuscules du demandeur intermédiaire. Vide si aucun n’est renseigné ; plusieurs contacts distincts sont signalés comme ambigus.',
        'Pétitionnaire', intermediaire_prenom_nom,
    ),
    'demandeur_intermediaire.raison_sociale': AgidaProperty(
        'Raison sociale du demandeur intermédiaire',
        'Raison sociale du demandeur intermédiaire ; si vide, utilise son organisation. Vide si les deux sont absentes. Aucun raccourci d’affichage n’est utilisé.',
        'Pétitionnaire', intermediaire_raison_sociale,
    ),
}

AVAILABLE_PROPERTIES = {code: info.resolve for code, info in AGIDA_PROPERTIES.items()}
PROPERTY_LABELS = {code: info.label for code, info in AGIDA_PROPERTIES.items()}
PROPERTY_DESCRIPTIONS = {code: info.description for code, info in AGIDA_PROPERTIES.items()}
PROPERTY_CATEGORIES = {code: info.category for code, info in AGIDA_PROPERTIES.items()}


def grouped_property_choices():
    return [(category, [(code, info.label) for code, info in AGIDA_PROPERTIES.items() if info.category == category])
            for category in dict.fromkeys(PROPERTY_CATEGORIES.values())]


def formulaire_type_error(champ_type, value_type):
    """Vérifier le type déclaré du champ, sans dépendre d'un dossier particulier."""
    import unicodedata
    kind = ''.join(c for c in unicodedata.normalize('NFKD', champ_type or '')
                   if not unicodedata.combining(c)).casefold()
    kind = ''.join(c for c in kind if c.isalnum()).removesuffix('champ')
    allowed = {
        'DATE': {'date'},
        'INTEGER': {'integernumber', 'integer', 'entier', 'number', 'nombre'},
        'DECIMAL': {'decimalnumber', 'decimal', 'integernumber', 'integer', 'entier', 'number', 'nombre'},
        'BOOLEAN': {'checkbox', 'yesno', 'boolean', 'booleen', 'ouiNon'.casefold()},
    }
    if value_type in allowed and kind not in allowed[value_type]:
        return (f'Le champ de formulaire de type « {champ_type} » est incompatible avec le type '
                f'« {value_type} ». Choisissez « Texte » pour conserver la réponse telle quelle, '
                'ou sélectionnez un champ compatible.')
    return ''


def source_errors(balise):
    if balise.code == 'document.numero' and (balise.type != Balise.Type.TEXT or balise.mode != Balise.Mode.CONNUE
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
        return [error for item in mappings if item.id_champ.id_champ_type_id
                if (error := formulaire_type_error(item.id_champ.id_champ_type.type, balise.type))]
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
