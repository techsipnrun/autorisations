"""Lecture des sources de date d'activité depuis les vues d'instruction."""

from datetime import datetime

from synchronisation.utils.date_activite import parser_date_activite


def extraire_date_debut_activite_dm(sources, dossier_dm):
    """Retourne la première date DM exploitable selon l'ordre configuré.

    Les sources sont des ``DemarcheDateActiviteChamp`` déjà ordonnées. Les
    sources DN sont volontairement ignorées : un dossier DM orphelin ne les
    possède pas.
    """
    for source in sources:
        if source.source != "dm" or not source.champ_dm:
            continue

        valeur = getattr(dossier_dm, source.champ_dm, None)
        if valeur is None or (isinstance(valeur, str) and not valeur.strip()):
            continue
        if isinstance(valeur, datetime):
            return valeur

        try:
            return parser_date_activite(str(valeur).strip())
        except (TypeError, ValueError, OverflowError):
            continue

    return None
