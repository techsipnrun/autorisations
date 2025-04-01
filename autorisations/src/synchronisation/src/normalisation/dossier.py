from datetime import datetime
from synchronisation.src.functions import fetch_geojson, get_first_id
from autorisations.models.models_instruction import EtatDossier, Groupeinstructeur, DossierType


def dossier_normalize(id_demarche, doss):
    """
    Normalise les données d'un dossier en provenance de Démarches Simplifiées.
    :param id_demarche: ID interne de la démarche (FK)
    :param doss: Données brutes d'un dossier
    :return: Dictionnaire normalisé pour l'objet Dossier
    """

    geojson = fetch_geojson(doss["geojson"]["url"]) if doss["geojson"] else None

    return {
        "id_ds": doss["id"],
        "id_etat_dossier": get_first_id(EtatDossier, nom=doss["state"]),
        "id_demarche": id_demarche,
        "numero": doss["number"],
        "id_groupeinstructeur": get_first_id(Groupeinstructeur, nom=doss["groupeInstructeur"]["label"]),
        "date_depot": datetime.fromisoformat(doss["dateDepot"]),
        "date_fin_instruction": doss["dateTraitement"],
        "id_dossier_type": get_first_id(DossierType, type="nouveau"),
        "id_ds_dossier_parent": "",  # À compléter si les dossiers parents sont gérés
        "note": "",
        "nom_dossier": f"{doss['number']}_{doss['demandeur']['nom']}_{doss['demandeur']['prenom']}",
        "emplacement": "/emplacement/a_definir/",
        "date_limite_traitement": datetime(2050, 1, 1),
        "geometrie": geojson,
    }
