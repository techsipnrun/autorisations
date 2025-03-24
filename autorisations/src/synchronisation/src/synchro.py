from datetime import datetime
import os
import sys
import django





def init_setup():
    '''
    Init Setup Django pour run le file dans le terminal
    '''

    CURRENT_DIR = os.path.dirname(__file__)
    SRC_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))  # src/
    
    sys.path.append(SRC_DIR)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "autorisations.settings")

    django.setup()




def normalize_process(d):
    """
    Normalise toutes les entités nécessaires à partir des données récupérées pour une démarche donnée.
    :param dem: Données brutes d'une démarche récupérée via GraphQL
    :return: Dictionnaires normalisés pour tous les objets associés à la démarche
    """


    ''' gérer en interne'''
    # groupeInstructeur = groupeinstructeur_normalize(d["groupeInstructeurs"])
    # groupeInstructeur_demarche = groupeinstructeur_demarche_normalize(d)
    #GroupeInstructeur_Instructeur
    #Instructeur


    # Normalisation des différentes entités
    demarche = demarche_normalize(d)
    champs = champ_normalize(d)
    dossiers = dossier_normalize(d)
        #Dossier_Instructeur
        #Dossier_Champ
            #Document
        #Contact_externe
        #Dossier_Interlocuteur
        #Dossier_Beneficiare
        #DossierDocument (pdf..)
        #Message
        #Message_Document
    
    #demandes = demande_normalize(d)
        #Demande_Champ
            #Document

    
    # Retourner toutes les données normalisées dans un dictionnaire structuré
    return {
        "demarche": demarche,
        "champs": champs,
        "dossiers": dossiers,
    }


def demarche_normalize(d):

    dico_demarche = {
        "id_ds": d["id"],
        "numero": d["number"],
        "titre": d["title"],
        # "etat": EtatDemarche.objects.get(nom=d["state"]),
        "id_etat" : EtatDemarche.objects.filter(nom=d["state"]).values_list("id", flat=True).first(),
        "date_creation": datetime.fromisoformat(d["dateCreation"]),
        "date_derniere_modif": datetime.fromisoformat(d["dateDerniereModification"]),
        "description": d["description"],
    }
    return dico_demarche


def champ_normalize(d):
    liste_ch = []
    for ch in d["champDescriptors"] :
        liste_ch.append({
                            "id_ds": ch["id"],
                            "nom": ch["label"],
                            "id_champ_type": ChampType.objects.filter(type=ch["type"]).values_list("id", flat=True).first(),
                            "description": ch["description"],
                            "id_demarche": Demarche.objects.filter(id_ds=d["id"], numero=d["number"]).values_list("id", flat=True).first(),
                            "requis":ch["required"],
                        })
    
    return liste_ch



def dossier_normalize(d):

    liste_doss = []
    for doss in d["dossiers"]["nodes"] :

        liste_doss.append({
                            "id_ds": doss["id"],
                            "id_etat_dossier": "TO DO",
                            "id_demarche": "TO DO",
                            "numero": doss["number"],
                            "id_groupeinstructeur": "TO DO",
                            "date_depot": datetime.fromisoformat(doss["dateDepot"]),
                            "date_fin_instruction": "TO DO",
                            "id_dossier_type": "TO DO",
                            "id_ds_dossier_parent": "TO DO",
                            "note": "TO DO",
                            "nom_dossier": "TO DO",
                            "emplacement": "TO DO",
                            "date_limite_traitement": "TO DO",
                        })
    return liste_doss




# def groupeinstructeur_normalize(gi):
#     liste_gi = []
#     for g in gi:
#         liste_gi.append({"nom": g["label"]})

#     return liste_gi


# def groupeinstructeur_demarche_normalize(d):
#     liste_gi_d = []

#     for gi in d["groupeInstructeurs"] :
#         dico_groupeinstructeur_demarche = {
#             "id_demarche": Demarche.objects.filter(id_ds=d["id"], numero=d["number"]).values_list("id", flat=True).first(),
#             "id_groupeinstructeur": Groupeinstructeur.objects.filter(nom=gi["label"]).values_list("id", flat=True).first(),
#             "id_groupeinstructeur_ds": gi["id"],
#         }

#         liste_gi_d.append(dico_groupeinstructeur_demarche)

#     return liste_gi_d



if __name__ == "__main__":
    
    init_setup()

    from autorisations.models.models_instruction import EtatDemarche, Demarche, ChampType
    from autorisations.models.models_utilisateurs import Groupeinstructeur
    from DS.call_DS_test import get_number_demarche_Postgres, recup_data_DS

    numeros_demarche = get_number_demarche_Postgres()

    # for num in numeros_demarche :
    #     datas_DS = recup_data_DS(num)

    # Test pour une démarche
    datas_DS = recup_data_DS(numeros_demarche[0])

    normalize_process(datas_DS["demarche"])

