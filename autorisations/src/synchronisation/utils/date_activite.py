"""Extraction de la date prévisionnelle d'activité depuis les champs DN."""

import logging
import re
import unicodedata
from datetime import datetime

from django.utils import timezone

from synchronisation.utils.conversion import parse_datetime_with_tz


logger = logging.getLogger("SYNCHRONISATION")


MOIS_FRANCAIS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}
DATE_FRANCAISE = re.compile(
    r"^\s*(\d{1,2})\s+([\w\-]+)\s+(\d{4})(?:\s+(?:à\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$",
    re.IGNORECASE,
)


def _sans_accents(texte):
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texte)
        if unicodedata.category(caractere) != "Mn"
    )


def parser_date_activite(valeur):
    """Parse les formats ISO et l'affichage français renvoyé par DN.

    Les valeurs comme ``20 juin 2026 07:00`` ne portent pas de fuseau. Elles
    correspondent à la date et l'heure locales saisies dans le formulaire :
    elles sont donc enregistrées dans le fuseau horaire de l'application
    (Indian/Reunion), pas supposées être en heure de Paris.
    """
    match = DATE_FRANCAISE.match(valeur)
    if match:
        jour, mois, annee, heure, minute, seconde = match.groups()
        mois_numero = MOIS_FRANCAIS.get(_sans_accents(mois).lower())
        if mois_numero is None:
            raise ValueError(f"Mois français inconnu : {mois}")

        date_naive = datetime(
            int(annee),
            mois_numero,
            int(jour),
            int(heure or 0),
            int(minute or 0),
            int(seconde or 0),
        )
        return timezone.make_aware(date_naive, timezone.get_current_timezone())

    return parse_datetime_with_tz(valeur)


def extraire_date_debut_activite(sources, dossier_champs):
    """Renvoie la première date exploitable parmi les champs configurés.

    ``sources`` est ordonné par priorité et contient des couples
    ``(id_ds_du_champ, nom_du_champ)``. Les valeurs proviennent directement
    des données normalisées de Démarche Numérique : aucune requête sur
    ``DossierChamp`` n'est nécessaire.

    Returns:
        tuple[datetime | None, str | None]: la date et le libellé du champ
        retenu. Si tous les champs configurés sont vides ou non interprétables,
        les deux valeurs sont à ``None``.
    """
    valeurs_par_id_ds = {
        str(item["champ"].get("id_ds")): item["champ"].get("valeur")
        for item in dossier_champs
        if item.get("champ", {}).get("id_ds") is not None
    }

    for id_ds, nom_champ in sources:
        valeur = valeurs_par_id_ds.get(str(id_ds))
        if valeur is None or (isinstance(valeur, str) and not valeur.strip()):
            continue

        # Un bloc répétable ou une valeur structurée n'est pas une source de
        # date directement exploitable. La configuration peut alors prévoir un
        # autre champ, de priorité suivante.
        if not isinstance(valeur, str):
            logger.warning(
                "Date d'activité : le champ configuré %r ne contient pas une date texte exploitable.",
                nom_champ,
            )
            continue

        try:
            return parser_date_activite(valeur.strip()), nom_champ
        except (TypeError, ValueError, OverflowError) as exc:
            logger.warning(
                "Date d'activité : valeur %r du champ %r impossible à interpréter : %s",
                valeur,
                nom_champ,
                exc,
            )

    return None, None
