from datetime import datetime
from autorisations.models.models_instruction import EtatDemande, DemandeType
from synchronisation.src.functions import get_first_id, calcul_priorite_instruction, type_demande_from_nom_demarche


def demande_normalize(demarche_id, demarche_title, doss, id_dossier):
    """
    Normalise les données de demande à partir d'un dossier et d'une démarche.
    
    :param demarche_id: ID de la démarche (int)
    :param demarche_title: Titre de la démarche (str)
    :param doss: Dictionnaire contenant les données du dossier (dict)
    :param id_dossier: ID du dossier (int)
    :return: Liste de demandes normalisées (list)
    """
    liste_demandes = []

    type_demande_par_defaut = type_demande_from_nom_demarche(demarche_title)

    if type_demande_par_defaut == 999:
        print("Demande PDV SON ou Survol drone : Script de normalisation à faire pour l'objet demande")
        # TODO: implémenter la logique pour PDV SON et Survol Drone
        # Exemple :
        # if demande survol --> liste_dem.append(demande survol)
        # if demande PDV son --> liste_dem.append(demande PDV son)
    else:
        id_priorite = calcul_priorite_instruction(demarche_id, doss)

        liste_demandes.append({
            "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
            "id_priorite": id_priorite,
            "id_dossier": id_dossier,
            "id_demande_type": type_demande_par_defaut,
            "date_depot": doss["dateDepot"],
            "date_fin_instruction": doss["dateTraitement"],
        })

    return liste_demandes