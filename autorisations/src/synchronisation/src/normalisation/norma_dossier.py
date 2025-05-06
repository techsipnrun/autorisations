from datetime import datetime
from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz
from synchronisation.src.utils.conversion import formater_nom_personne_morale
from synchronisation.src.utils.instruction import calcul_date_limite_instruction
from synchronisation.src.utils.fichiers import fetch_geojson


from autorisations.models.models_instruction import EtatDossier, Groupeinstructeur, DossierType


def dossier_normalize(id_demarche, doss, emplacement_dossier):
    """
    Normalise les données d'un dossier en provenance de Démarches Simplifiées.
    :param id_demarche: ID interne de la démarche (FK)
    :param doss: Données brutes d'un dossier
    :return: Dictionnaire normalisé pour l'objet Dossier
    """

    geojson = fetch_geojson(doss["geojson"]["url"]) if doss["geojson"] else None

    date_depot = parse_datetime_with_tz(doss["dateDepot"])


    if doss['demandeur']['__typename'] == 'PersonneMorale' :
        nom_personne_morale = formater_nom_personne_morale(doss['demandeur'])


    return {
        "id_ds": doss["id"],
        "id_etat_dossier": get_first_id(EtatDossier, nom=doss["state"]),
        "id_demarche": id_demarche,
        "numero": doss["number"],
        "id_groupeinstructeur": get_first_id(Groupeinstructeur, nom=doss["groupeInstructeur"]["label"]),
        "date_depot": date_depot,
        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
        "id_dossier_type": get_first_id(DossierType, type="nouveau"), # nouveau par défaut mais chopper info dans les champs
        # "id_dossier_parent": "",  # À compléter si les dossiers parents sont gérés
        "note": "",
        "nom_dossier": f"{doss['number']}_{doss['demandeur']['nom']}_{doss['demandeur']['prenom']}_{date_depot.strftime("%d-%m")}" if doss['demandeur']['__typename'] == 'PersonnePhysique'  #Personne Physique
                                                                                                    else f"{doss['number']}_{nom_personne_morale}_{date_depot.strftime("%d-%m")}", # Personne Morale
        # "emplacement":f"/{doss["number"]}_{doss['demandeur']['nom']}_{doss['demandeur']['prenom']}", # Arborescence à compléter
        "emplacement": emplacement_dossier,
        "date_limite_traitement": calcul_date_limite_instruction(doss["dateDepot"], id_demarche),
        # "date_limite_traitement": datetime(2050, 1, 1),
        "geometrie": geojson,
    }
