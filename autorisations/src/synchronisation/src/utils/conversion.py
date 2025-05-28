from datetime import datetime
import logging
import os
from django.utils.timezone import now, is_naive, get_current_timezone, make_aware
from pytz import timezone
from dateutil.parser import parse
from typing import Dict

loggerApp = logging.getLogger("APP")

def parse_datetime_with_tz(dt_input):
    """
    Convertit une date/heure en datetime aware avec le fuseau horaire Indian/Reunion.

    Si l'entrée est une chaîne (str), elle est parsée avec dateutil.
    Si elle est naïve (sans timezone), on suppose qu'elle est en Europe/Paris.
    Le résultat est ensuite converti vers Indian/Reunion.

    Args:
        dt_input (Union[str, datetime]): Date ou chaîne ISO à convertir.

    Returns:
        Optional[datetime]: Datetime avec timezone Indian/Reunion, ou None si input invalide.

    Raises:
        TypeError: Si l'entrée n’est ni une chaîne ni un objet datetime.
    """
    if not dt_input:
        return None

    # 1. Parse string si besoin
    if isinstance(dt_input, str):
        dt = parse(dt_input)
    elif isinstance(dt_input, datetime):
        dt = dt_input
    else:
        raise TypeError(f"Entrée non supportée : {dt_input} ({type(dt_input)})")

    # 2. Si naïf, on suppose qu’il est en Europe/Paris
    paris_tz = timezone("Europe/Paris")
    if is_naive(dt):
        dt = paris_tz.localize(dt)

    # 3. Conversion explicite vers Indian/Reunion
    reunion_tz = timezone("Indian/Reunion")
    dt = dt.astimezone(reunion_tz)

    return dt


def clean_date(val):
    """
    Nettoie et convertit une valeur vers un objet `date`.

    Args:
        val (Union[str, datetime, date]): Une date ou une chaîne parsable.

    Returns:
        date: Date extraite ou convertie.
    """

    if isinstance(val, datetime):
        return val.date()
    elif isinstance(val, str):
        try:
            return parse(val).date()
        except Exception as e:
            loggerApp.error(f"Impossible de parser la date '{val}' : {e}")
            return None
    return val  # si c’est déjà une date, on ne fait rien



def clean_name(value):
    """
    Nettoie un prénom ou nom : supprime les espaces, met en minuscule
    puis capitalise la première lettre.

    Args:
        value (str): Chaîne à nettoyer.

    Returns:
        str: Chaîne nettoyée et capitalisée (ex: "Jean").
    """
    return value.strip().lower().capitalize() if value else ""



def clean_surname(value):
    """
    Nettoie un nom de famille : supprime les espaces, convertit en majuscules.

    Args:
        value (str): Chaîne à nettoyer.

    Returns:
        str: Chaîne en majuscules (ex: "DUPONT").
    """
    return value.strip().upper() if value else ""


def clean_email(value):
    """
    Nettoie un champ d'adresse email : suppression des espaces et mise en minuscules.

    Args:
        value (str): Adresse email en entrée.

    Returns:
        Optional[str]: Email nettoyé ou None si l’entrée est vide ou invalide.
    """
    return value.strip().lower() if value else None


def extraire_nom_et_extension(filename):
    """
    Sépare un nom de fichier en deux parties : nom (sans extension) et extension (sans le point).
    Remplace les points dans le nom par des underscores.

    Args:
        filename (str): Nom de fichier (ex: "rapport.final.pdf").

    Returns:
        tuple[str, str]: Tuple (nom_sans_extension, extension) (ex: ("rapport_final", "pdf")).
    """
    nom, extension = os.path.splitext(filename)
    nom = nom.replace('.', '_').replace(' ', '_')
    extension = extension.lstrip('.')  # Enlever le point
    return nom, extension



def formater_nom_personne_morale(data: Dict) -> str:
    """
    Extrait et formate le nom d'une personne morale (entreprise ou association) 
    en minuscules et avec des underscores à la place des espaces.

    Args:
        data (dict): Dictionnaire contenant les champs 'entreprise' ou 'association'.
                     Exemples : 
                     {
                         "entreprise": {"raisonSociale": "SARL TOTO"},
                         "association": {"titre": "Les amis du parc"}
                     }

    Returns:
        str: Nom formaté (ex: "sarl_toto", "les_amis_du_parc"), ou chaîne vide si aucun nom trouvé.
    """
    raison = data.get("entreprise", {}).get("raisonSociale", "")
    if data["entreprise"] :
        nom_entreprise = data.get("entreprise", {}).get("nom", "")
    if data["association"] :
        titre = data.get("association", {}).get("titre", "")

    nom = raison or nom_entreprise or titre
    return nom.strip().lower().replace(" ", "_")
