from datetime import datetime
import logging
from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz
from synchronisation.src.utils.conversion import formater_nom_personne_morale
from synchronisation.src.utils.instruction import calcul_date_limite_instruction
from synchronisation.src.utils.fichiers import fetch_geojson


from autorisations.models.models_instruction import EtapeDossier, EtatDossier, Groupeinstructeur, DossierType


def dossier_normalize(id_demarche, doss, emplacement_dossier):
    """
    Normalise les données d'un dossier en provenance de Démarches Simplifiées.
    :param id_demarche: ID interne de la démarche (FK)
    :param doss: Données brutes d'un dossier
    :return: Dictionnaire normalisé pour l'objet Dossier
    """
    loggerSynchro = logging.getLogger("SYNCHRONISATION")
    
    geojson = fetch_geojson(doss["geojson"]["url"]) if doss["geojson"] else None

    date_depot = parse_datetime_with_tz(doss["dateDepot"])

    # Personne Morale
    if doss['demandeur']['__typename'] == 'PersonneMorale' :
        nom_personne_morale = formater_nom_personne_morale(doss['demandeur'], doss)
        nom_dossier = f"{doss['number']}_{nom_personne_morale}_{date_depot.strftime('%d-%m')}"

    #Personne Physique
    elif doss['demandeur']['__typename'] == 'PersonnePhysique' :  
        nom_dossier = f"{doss['number']}_{doss['demandeur']['nom'].upper()}_{doss['demandeur']['prenom']}_{date_depot.strftime('%d-%m')}"   

    else : 
        loggerSynchro.error(f" Erreur lors de la normalisation du Dossier {doss['number']} : Le demandeur n'est ni une personne physique ni une personne morale")

    # Log synchro
    loggerSynchro.info(f"Dossier {nom_dossier}")



    return {
        "id_ds": doss["id"],
        "id_etat_dossier": get_first_id(EtatDossier, nom=doss["state"]),
        "id_demarche": id_demarche,
        "numero": doss["number"],
        "id_groupeinstructeur": get_first_id(Groupeinstructeur, nom=doss["groupeInstructeur"]["label"]),
        "date_depot": date_depot,
        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),

        # "id_dossier_type": get_first_id(DossierType, type="nouveau"), # nouveau par défaut mais chopper info dans les champs
        # "id_dossier_parent": "",  # À compléter si les dossiers parents sont gérés
        
        "note": "",
        "nom_dossier": nom_dossier,
        "emplacement": emplacement_dossier,
        "date_limite_traitement": calcul_date_limite_instruction(doss["dateDepot"], id_demarche),  #On est sur que le délais d'instruction est lancé dès la reception du doss ?
        "geometrie": geojson,
        "present_sur_ds": True,
    }

    #Check champ formulaire : dossierGroupe pour identifier les dossier liés (peut etre plus cohérent de lemettre dans le syncho file)
