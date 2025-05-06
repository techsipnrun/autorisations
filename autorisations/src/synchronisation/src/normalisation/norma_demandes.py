from datetime import datetime
from autorisations.models.models_instruction import EtatDemande, DemandeType
from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz
from synchronisation.src.utils.instruction import calcul_priorite_instruction, type_demande_from_nom_demarche

def demande_normalize(demarche_id, demarche_title, doss):
    """
    Normalise les données de demande à partir d'un dossier et d'une démarche.
    
    :param demarche_id: ID de la démarche (int)
    :param demarche_title: Titre de la démarche (str)
    :param doss: Dictionnaire contenant les données du dossier (dict)
    :return: Liste de demandes normalisées (list)
    """
    liste_demandes = []

    id_type_demande_par_defaut = type_demande_from_nom_demarche(demarche_title)
    # print(id_type_demande_par_defaut)

    if id_type_demande_par_defaut == 999:
        print("Demande PDV SON ou Survol drone : Script de normalisation à faire pour l'objet demande")
        # TODO: implémenter la logique pour PDV SON et Survol Drone
        # Exemple :
        # if demande survol --> liste_dem.append(demande survol)
        # if demande PDV son --> liste_dem.append(demande PDV son)
    else:
        id_priorite = calcul_priorite_instruction(demarche_id, doss)
        # print(f"id priorité : {id_priorite}")
        liste_demandes.append({
            "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
            "id_priorite": id_priorite,
            "id_demande_type": id_type_demande_par_defaut,
            "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
            "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
        })

    return liste_demandes