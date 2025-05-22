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

    # A reprendre plus proprement ici. Il faudra aussi regarder les champs (pour les forms concernés) afin de voir si le dossier inclut une autre demande que celle par défaut. 
    liste_demandes = []

    id_type_demande_par_defaut = type_demande_from_nom_demarche(demarche_title, doss['champs'])

    id_priorite = calcul_priorite_instruction(demarche_id, doss)

    if id_type_demande_par_defaut == 999:
        # Ajout des objets Demande(s) pour la démarche PDV son et/ou survol drone

        for c in doss['champs'] :
            if c['label'] == 'Votre demande concerne' :
                if c['stringValue']=='Une prise de vue ou de son sans drone':

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type='Prise de vue et de son').values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    })

                if c['stringValue']=='Une prise de vue ou de son avec drone':

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type='Prise de vue et de son').values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    })

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type='Survol drone').values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    })
                    
                if c['stringValue']=='Un survol en drone sans prise de vue':

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type='Survol drone').values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    })

    else:
        
        liste_demandes.append({
            "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
            "id_priorite": id_priorite,
            "id_demande_type": id_type_demande_par_defaut,
            "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
            "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
        })

    return liste_demandes