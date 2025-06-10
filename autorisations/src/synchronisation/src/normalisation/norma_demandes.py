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


    # Ajout des objets Demande(s) pour la démarche PDV son et/ou survol drone
    if id_type_demande_par_defaut == 999:
        
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


    # Travaux hors urbanisme
    if demarche_id == 2 :
 
        for c in doss['champs'] :
            # Préciser les modalités d’accès au chantier des engins, du matériel, des matériaux et du personnel
            if c['id'] == 'Q2hhbXAtNTE0OTc2Nw==' : 
                if 'Hélicoptère' in c['stringValue']:

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type="Survol hélicoptère").values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    }) 
            
            # Un survol de drone est-il prévu dans le cadre des travaux ?
            if c['id'] == 'Q2hhbXAtNTE0OTUxNQ==' :
                if c['stringValue']=='true':

                    liste_demandes.append({
                    "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                    "id_priorite": id_priorite,
                    "id_demande_type": DemandeType.objects.filter(type="Survol drone").values_list("id", flat=True).first(),
                    "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                    "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                }) 
            
            # Une prise de vue ou de son en cœur de Parc est-elle prévue dans le cadre des travaux ?
            if c['id'] == 'Q2hhbXAtNTE0OTY5Nw==' :
                if c['stringValue']=='true':

                    liste_demandes.append({
                    "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                    "id_priorite": id_priorite,
                    "id_demande_type": DemandeType.objects.filter(type="Prise de vue et de son").values_list("id", flat=True).first(),
                    "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                    "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                })
                

    # Mission scientifique en cœur du Parc
    '''
    La mission est réalisée dans le cadre de travaux, ou prévoit l'utilisation d'un drone ou d'un hélicoptère, ou prévoit la réalisation d'une prise de vue OUI/NON
        - La mission prévoit l’utilisation d’un drone
        - Un survol motorisé (en hélicoptères, ULM, petits avions, etc.) en cœur de Parc national est-il prévu dans le cadre de la mission scientifique
        - La mission prévoit la réalisation de prises de vue ou de son
        - La mission implique la réalisation de travaux
    '''
    if demarche_id == 5 :

        for c in doss['champs'] :
            # La mission prévoit l’utilisation d’un drone
            if c['id'] == 'Q2hhbXAtNTIwNjU3OQ==' : 
                if c['stringValue']=='true':

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type="Survol drone").values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    }) 

            # Un survol motorisé (en hélicoptères, ULM, petits avions, etc.) en cœur de Parc national est-il prévu dans le cadre de la mission scientifique
            if c['id'] == 'Q2hhbXAtNTIwNjU4MA==' : 
                if c['stringValue']=='true':

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type="Survol hélicoptère").values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    })

            # La mission prévoit la réalisation de prises de vue ou de son
            if c['id'] == 'Q2hhbXAtNTIwNjU4MQ==' : 
                if c['stringValue']=='true':

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type="Prise de vue et de son").values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    })

            # La mission implique la réalisation de travaux
            if c['id'] == 'Q2hhbXAtNTIwNjYzMg==' : 
                if c['stringValue']=='true':

                    liste_demandes.append({
                        "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                        "id_priorite": id_priorite,
                        "id_demande_type": DemandeType.objects.filter(type="Travaux").values_list("id", flat=True).first(),
                        "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                        "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                    })



    # Manifestations publiques
    '''
    Un survol de drone en cœur de Parc est-il prévu dans le cadre de la manifestation ?
    Un survol motorisé (en hélicoptères, ULM, petits avions, etc.) en cœur de Parc est-il prévu dans le cadre de la manifestation ?
    Une prise de vue ou de son en cœur de Parc est-elle prévue dans le cadre de la manifestation ?
    '''
    if demarche_id == 11 :
        for c in doss['champs'] :
            # Un survol de drone en cœur de Parc est-il prévu dans le cadre de la manifestation ?
            if c['id'] == 'Q2hhbXAtNTIxMDY2MA==' :
                    if c['stringValue']=='true':

                        liste_demandes.append({
                            "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                            "id_priorite": id_priorite,
                            "id_demande_type": DemandeType.objects.filter(type="Survol drone").values_list("id", flat=True).first(),
                            "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                            "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                        })

            # Un survol motorisé (en hélicoptères, ULM, petits avions, etc.) en cœur de Parc est-il prévu dans le cadre de la manifestation ?
            if c['id'] == 'Q2hhbXAtNTIxMDY2MQ==' :
                    if c['stringValue']=='true':

                        liste_demandes.append({
                            "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                            "id_priorite": id_priorite,
                            "id_demande_type": DemandeType.objects.filter(type="Survol hélicoptère").values_list("id", flat=True).first(),
                            "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                            "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                        })

            # Une prise de vue ou de son en cœur de Parc est-elle prévue dans le cadre de la manifestation ?
            if c['id'] == 'Q2hhbXAtNTIxMDY2Mg==' :
                    if c['stringValue']=='true':

                        liste_demandes.append({
                            "id_etat_demande": get_first_id(EtatDemande, nom=doss["state"]),
                            "id_priorite": id_priorite,
                            "id_demande_type": DemandeType.objects.filter(type="Prise de vue et de son").values_list("id", flat=True).first(),
                            "date_depot": parse_datetime_with_tz(doss["dateDepot"]),
                            "date_fin_instruction": parse_datetime_with_tz(doss["dateTraitement"]),
                        })



    return liste_demandes