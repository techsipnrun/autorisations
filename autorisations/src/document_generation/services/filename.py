"""Résolution contrôlée du nom de sortie : aucun fichier écrit, aucun Document créé."""

import re

from django.utils import timezone

from autorisations.models.models_generation import valider_nom_fichier
from .providers import ResolutionSource


def fragment_nom_fichier(value):
    """Retire les espaces et séparateurs incompatibles avec un nom de fichier."""
    return re.sub(r'[\s<>:"/\\|?*\x00-\x1f]+', '-', str(value)).strip(' .-')


def resolve_filename(pattern, dossier, *, today=None, source=None, document_number=None):
    """Résout seulement les variables utilisées, avec une date locale commune."""
    valider_nom_fichier(pattern)
    today = today or timezone.localdate()
    values = {"dossier.numero": str(dossier.numero), "num_doss": str(dossier.numero),
              "date.annee": str(today.year), "date.jour": today.strftime("%d-%m-%y")}
    if '{document.numero}' in pattern:
        if not document_number:
            raise ValueError('Générez ou récupérez le numéro du document pour compléter le nom du fichier.')
        values['document.numero'] = str(document_number)
    if "{beneficiaire.identite}" in pattern:
        contact = (source or ResolutionSource(dossier)).beneficiaire
        if contact is None:
            raise ValueError("Le nom du fichier nécessite un bénéficiaire renseigné.")
        identity = (contact.raison_sociale or '').strip()
        if not identity:
            identity = '-'.join(value for value in ((contact.nom or '').strip().upper(), (contact.prenom or '').strip()) if value)
        identity = fragment_nom_fichier(identity)
        if not identity:
            raise ValueError("La raison sociale ou le nom du bénéficiaire doit être renseigné pour nommer le fichier.")
        values["beneficiaire.identite"] = identity
    filename = re.sub(r"\{([^{}]+)\}", lambda match: fragment_nom_fichier(values[match.group(1)]), pattern)
    filename = fragment_nom_fichier(filename)
    valider_nom_fichier(filename)
    if len(filename) > 200:
        raise ValueError("Le nom du fichier calculé dépasse 200 caractères.")
    return filename
