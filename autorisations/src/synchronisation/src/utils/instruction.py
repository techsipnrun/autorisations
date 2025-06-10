
from datetime import timedelta
import logging
from autorisations.models.models_instruction import DemandeType, Demarche, Priorite
from django.utils.timezone import now, is_naive, get_current_timezone, make_aware
from synchronisation.src.utils.conversion import parse_datetime_with_tz


loggerApp = logging.getLogger("APP")
loggerORM = logging.getLogger("ORM_DJANGO")


def calcul_priorite_instruction(id_demarche, doss):
    """
    Calcule la priorité d’instruction d’un dossier.

    Si le dossier est déjà traité (accepte/refuse/sans_suite) → priorité "traite".
    Sinon, compare la date limite à la date actuelle pour déterminer un niveau
    (urgent, normal, faible) en fonction du ratio de temps restant.

    Args:
        id_demarche (int): ID de la démarche liée au dossier.
        doss (dict): Données du dossier, incluant "dateDepot" et "state".

    Returns:
        Optional[int]: ID de la priorité, ou None en cas d’erreur.
    """
    if doss["state"] == "accepte" or doss["state"] == "refuse" or doss["state"] == "sans_suite" :
        return Priorite.objects.filter(niveau="traite").values_list("id", flat=True).first()
    
    else :
        date_depot_dossier = doss["dateDepot"]

        if id_demarche != 3 :  
            delais_jours_instruction = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()

        else :  # pour les travaux soumis à urbanisme le temps d'instruction max n'est pas le meme (selon  Permis Construire ou Déclaration Préalable)
            # si DP : 45 jours
            # sinon 120 jours (valeur de la colonne delais_jours_instruction)
            delais_jours_instruction = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()
    
        if not date_depot_dossier :
            loggerORM.error(f"[DOSSIER {doss['number']}] Erreur lors du calcul de Priorité d'instruction du dossier : la date de dépot du dossier est null")
            return None

        if delais_jours_instruction is None :
            loggerORM.error(f"[DOSSIER {doss['number']}] Erreur lors du calcul de Priorité d'instruction du dossier : la colonne delais_jours_instruction de la Démarche " +
                   f"{Demarche.objects.filter(id=id_demarche).values_list("type", flat=True).first()} est null")
            return None

        # Conversion de la date ISO 8601 en datetime Python
        try:
            date_depot = parse_datetime_with_tz(date_depot_dossier)
        except ValueError:
            return None  # ou logguer une erreur

        date_limite = date_depot + timedelta(days=delais_jours_instruction)
        today = now()

        if is_naive(today):
            today = make_aware(today, get_current_timezone())


        # Calcul du ratio restant
        jours_restants = (date_limite - today).total_seconds() / (3600 * 24)
        ratio_restant = jours_restants / delais_jours_instruction

        if ratio_restant < 0.3:
            niveau = "urgent"
        elif ratio_restant < 0.8:
            niveau = "normal"
        else:
            niveau = "faible"

        return Priorite.objects.filter(niveau=niveau).values_list("id", flat=True).first()
    


def calcul_date_limite_instruction(date_depot_iso: str, id_demarche: int):
    """
    Calcule la date limite théorique d’instruction en fonction de la date de dépôt
    et du délai prévu par la démarche.

    Args:
        date_depot_iso (str): Date ISO de dépôt.
        id_demarche (int): Identifiant de la démarche.

    Returns:
        Optional[datetime]: Date limite calculée ou None en cas d’erreur.
    """
    if not date_depot_iso:
        return None
    try:
        date_depot = parse_datetime_with_tz(date_depot_iso)
        delais = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()

        if delais is not None:
            return date_depot + timedelta(days=delais)
        
    except Exception as e:
        loggerApp.error(f"Erreur lors du calcul de la date_limite_instruction: {e}")
    return None



def calcul_priorite_instruction(id_demarche, doss):
    """
    Calcule la priorité d’instruction d’un dossier.

    Si le dossier est déjà traité (accepte/refuse/sans_suite) → priorité "traite".
    Sinon, compare la date limite à la date actuelle pour déterminer un niveau
    (urgent, normal, faible) en fonction du ratio de temps restant.

    Args:
        id_demarche (int): ID de la démarche liée au dossier.
        doss (dict): Données du dossier, incluant "dateDepot" et "state".

    Returns:
        Optional[int]: ID de la priorité, ou None en cas d’erreur.
    """

    # Cas 1 : Dossier déjà terminé
    if doss["state"] in ["accepte", "refuse", "sans_suite"]:
        return Priorite.objects.filter(niveau="traite").values_list("id", flat=True).first()

    # Cas 2 : Dossier en cours → on récupère la date de dépôt et le délai autorisé
    date_depot_dossier = doss["dateDepot"]
    delais_jours = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()

    if not date_depot_dossier:
        loggerORM.warning(f"[PRIORITE] Dossier sans date de dépôt (ID démarche : {id_demarche})")
        return None

    if delais_jours is None:
        description = Demarche.objects.filter(id=id_demarche).values_list("description", flat=True).first()
        loggerORM.warning(f"[PRIORITE] Délai d'instruction manquant pour la démarche : {description}")
        return None

    try:
        date_depot = parse_datetime_with_tz(date_depot_dossier)
    except ValueError:
        loggerApp.warning(f"[PRIORITE] Erreur de parsing date : {date_depot_dossier}")
        return None

    date_limite = date_depot + timedelta(days=delais_jours)
    today = now()

    if is_naive(today):
        today = make_aware(today, get_current_timezone())

    jours_restants = (date_limite - today).total_seconds() / (3600 * 24)
    ratio = jours_restants / delais_jours

    if ratio < 0.3:
        niveau = "urgent"
    elif ratio < 0.8:
        niveau = "normal"
    else:
        niveau = "faible"

    return Priorite.objects.filter(niveau=niveau).values_list("id", flat=True).first()



def calcul_date_limite_instruction(date_depot_iso: str, id_demarche: int):
    """
    Calcule la date limite théorique d’instruction en fonction de la date de dépôt
    et du délai prévu par la démarche.

    Args:
        date_depot_iso (str): Date ISO de dépôt.
        id_demarche (int): Identifiant de la démarche.

    Returns:
        Optional[datetime]: Date limite calculée ou None en cas d’erreur.
    """
    if not date_depot_iso:
        return None
    try:
        date_depot = parse_datetime_with_tz(date_depot_iso)
        delais = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()
        if delais is not None:
            return date_depot + timedelta(days=delais)
    except Exception as e:
        loggerApp.warning(f"[DELAIS] Erreur dans le calcul de la date limite : {e}")
    return None



def type_demande_from_nom_demarche(nom_demarche: str, champs: list):
    """
    Déduit le type de demande (DemandeType) à partir du nom d’une démarche.

    Args:
        nom_demarche (str): Nom complet de la démarche.
        champs (list(dict)) : Liste des champs du dossier  [{label: '', stringValue:''}, ...]

    Returns:
        Optional[int]: ID du DemandeType, ou 999 pour cas particulier, ou None si non reconnu.
    """
    correspondances = {
        "Activités commerciales": "Activités commerciales",
        "Travaux": "Travaux",
        "Mission scientifique": "Missions scientifiques",
        "hélicoptère": "Survol hélicoptère",
        "arêtes": "Arêtes",
        "Activités agricoles": "Activités agricoles",
        "Documents de planification et d'urbanisme": "Documents de planification et d'urbanisme",
        "Manifestations publiques": "Manifestations publiques"
    }

    for mot_clef, type_ in correspondances.items():
        if mot_clef in nom_demarche:
            return DemandeType.objects.filter(type=type_).values_list("id", flat=True).first()

    if "Prise de vue et de son" in nom_demarche:
        return 999

    loggerApp.error(f"[TYPE DEMANDE] Nom non reconnu : {nom_demarche}")
    return None
