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
    dossiers_instructeurs = dossier_instructeur_normalize(d)
    dossiers_interlocuteurs = dossier_interlocuteur_normalize(d)

    liste_documents = []
    dossiers_champs = dossiers_champs_normalize(d, liste_documents) # + Documents des champs "pièces justificatives"
    
    # Contact Externe :
        # Beneficiare, DemandeurIntermédiaire --> Besoin de recup des champs du formulaire 
        # Expert --> get or create au moment de la création de demande d'avis

    contacts_externes = contact_externe_normalize(d) # To do : demandeur intermédiaire + bénéficiaire
    dossiers_beneficiaires = dossier_beneficiaire_normalize(d)
    dossiers_documents = dossier_document_normalize(d, liste_documents)

    liste_messages_documents = []
    messages = message_normalize(d, liste_messages_documents, liste_documents) # + Document + Message_document

    demandes = demande_normalize(d)

    """On laisse de côté en attendant la finalisation des forms sur DS"""
    # demandes_champs = demande_champ_normalize(d)
    # documents = document_normalize(d)


    """On gère les avis en interne!!"""
    # avis = avis_normalize(d)
    # demandes_avis = demande_avis_normalize(d)
    # experts = expert_normalize(d)
    # avis_documents = avis_document_normalize(d)  # + Documents

    
    # Retourner toutes les données normalisées dans un dictionnaire structuré
    return {
        "demarche": demarche,
        "champs": champs,
        "dossiers": dossiers,
        "dossiers_instructeurs": dossiers_instructeurs,
        "dossiers_interlocuteurs": dossiers_interlocuteurs,
        "dossiers_champs": dossiers_champs,
        "contact_externe": contacts_externes,
        "dossier_beneficiaire": dossiers_beneficiaires,
        "dossier_documents": dossiers_documents,
        "messages": messages,
        "demandes": demandes,
        "documents" : liste_documents,
        "messages_documents" : liste_messages_documents,
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
        id_demarche = Demarche.objects.filter(id_ds=d["id"], numero=d["number"]).values_list("id", flat=True).first()

        geojson = fetch_geojson(doss["geojson"]["url"]) if doss["geojson"] else None
        liste_doss.append({
                "id_ds": doss["id"],
                "id_etat_dossier": EtatDossier.objects.filter(nom=doss["state"]).values_list("id", flat=True).first(),
                "id_demarche": id_demarche,
                "numero": doss["number"],
                "id_groupeinstructeur": "GET_OR_CREATE",
                "date_depot": datetime.fromisoformat(doss["dateDepot"]),
                "date_fin_instruction": doss["dateTraitement"],
                "id_dossier_type": DossierType.objects.filter(type="nouveau").values_list("id", flat=True).first(),  # Nouveau par défaut
                "id_ds_dossier_parent": "",  # Laisser vide pour commencer
                "note": "",
                "nom_dossier": f"projet_{doss['demandeur']['nom']}_{doss['demandeur']['prenom']}_{datetime.fromisoformat(doss['dateDepot']).year}",  # En attendant la norme de nommage
                "emplacement": "/emplacement/a_definir/",  # Arborescence à définir
                "date_limite_traitement": datetime(2050, 1, 1),  # En attendant les calculs par rapport à la date de début d'instruction
                "geometrie": geojson,
        })

    return liste_doss


def dossier_instructeur_normalize(d):
    liste_doss_instru = []

    for doss in d["dossiers"]["nodes"] :
        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()

        if doss.get("instructeurs"):
            for instru in doss["instructeurs"] :
                liste_doss_instru.append({
                    "id_dossier": id_dossier,
                    # "id_instructeur":Instructeur.objects.filter(email=instru["email"]).values_list("id", flat=True).first(), #filtre que sur l'email pour le moment
                    "id_instructeur": "GET_OR_CREATE",
                })
    return liste_doss_instru

def dossier_interlocuteur_normalize(d):
    liste_doss_interlo = []

    for doss in d["dossiers"]["nodes"] :
        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()

        liste_doss_interlo.append({
            "id_interlocuteur_ds": doss["usager"]["id"],
            # "id_demandeur_intermediaire": (
            #     None if (doss.get("prenomMandataire") is not None and doss.get("nomMandataire") is not None)
            #     else ContactExterne.objects.filter(email=doss["usager"]["email"]).values_list("id", flat=True).first()
            # ),
            "id_demandeur_intermediaire":"GET_OR_CREATE",
            "id_dossier": "GET",
        })
    return liste_doss_interlo


def dossiers_champs_normalize(d, liste_documents):
    liste_dossiers_champs = []
    for doss in d["dossiers"]["nodes"] :
        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()

        for ch in doss["champs"] :

                id_champ_type = Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id_champ_type", flat=True).first()
                type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()
                id_document = None
                if (type_du_champ == "piece_justificative") :

                    nom_fichier, extension_fichier = extraire_nom_et_extension(ch["files"]["filename"])

                    id_document = Document.objects.filter(format=extension_fichier, titre=nom_fichier, url_ds=ch["files"]["url"]).values_list("id", flat=True).first()

                    liste_documents.append({
                        # "numero":"",   concerne plutot les arretés, demande d'avis etc..
                        # "id_format": DocumentFormat.objects.filter(format=extension_fichier).values_list("id", flat=True).first(),
                        "id_format": "GET_OR_CREATE",
                        "id_nature": DocumentNature.objects.filter(nature="Pièce jointe demandeur").values_list("id", flat=True).first(),
                        "url_ds": ch["files"]["url"],
                        "emplacement":"/emplacement/a_definir/",
                        "description":ch["label"],
                        "titre": nom_fichier,
                    })

                geometrie_du_champ = fetch_geojson(doss["geojson"]["url"]) if ch["__typename"] == "CarteChamp" else None
                liste_dossiers_champs.append({
                    "id_dossier": "GET",
                    # "id_champ": Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id", flat=True).first(),
                    "id_champ": "GET_OR_CREATE",
                    "valeur": ch["stringValue"],
                    "date_saisie": datetime.fromisoformat(ch["updatedAt"]),
                    "geometrie": geometrie_du_champ,
                    "id_document": id_document,
                })


    return liste_dossiers_champs


def contact_externe_normalize(d):
    """ 
        Beneficiare, DemandeurIntermédiaire --> Besoin de recup des champs du formulaire 
        Expert --> get or create au moment de la création de demande d'avis
    """
    liste_contacts_ext = []

    for doss in d["dossiers"]["nodes"] :
        liste_contacts_ext.append({
            "email": "",
            "id_type": "",
            "nom": "",
            "prenom": "",
        }

        )

    return liste_contacts_ext


def dossier_beneficiaire_normalize(d):
    liste_doss_benef = []

    for doss in d["dossiers"]["nodes"] :
        liste_doss_benef.append({
            "id_dossier_interlocuteur": "GET",
            "id_beneficiaire": "GET",
        })

    return liste_doss_benef


def dossier_document_normalize(d, liste_documents):
    liste_doss_docu = []

    for doss in d["dossiers"]["nodes"] :

        nom_fichier, extension_fichier = extraire_nom_et_extension(doss["pdf"]["filename"])

        liste_documents.append({
            "numero": doss["number"],
            "id_format": DocumentFormat.objects.filter(format=extension_fichier).values_list("id", flat=True).first(),
            "id_nature": DocumentNature.objects.filter(nature="Résumé dossier").values_list("id", flat=True).first(),
            "url_ds": doss["pdf"]["url"],
            "emplacement":"/emplacement/a_definir/",
            "description": f"Résumé du dossier {doss["number"]}",
            "titre": nom_fichier,
        })


        liste_doss_docu.append({
            "id_dossier": "GET",
            "id_document": "GET",
        })

    return liste_doss_docu

def message_normalize(d, liste_msg_doc, liste_doc):
    liste_messages = []

    for doss in d["dossiers"]["nodes"] :
        for m in doss["messages"] :

            contient_pj = True if m["attachments"] else False
            liste_messages.append({
                            "id_ds": m["id"],
                            "body": m["body"],
                            "date_envoi": m["createdAt"],
                            "piece_jointe": contient_pj,
                            "email_emetteur": m["email"],
                            "id_dossier": "GET",
                            # "lu": False,  #Faux par défaut
                        })
            
            if m["attachments"]:
                for file in m["attachments"]:

                    liste_doc.append({
                        # "numero": "",  pas concerné ici
                        "id_format": "GET or CREATE",
                        "id_nature": "PJ demandeur ou instructeur",
                        "url_ds": file["url"],
                        "emplacement":"/emplacement/a_definir/",  #TO DO
                        "description": f"Pièce jointe dans la messagerie du dossier {doss["number"]}",
                        "titre": file["filename"],
                    })

                    liste_msg_doc.append({
                        "id_message": "GET",
                        "id_document": "GET",
                    })

    return liste_messages


def demande_normalize(d):
    liste_dem = []
    type_demande_par_defaut = type_demande_from_nom_demarche(d)
    for doss in d["dossiers"]["nodes"] :

        if type_demande_par_defaut == 999 : # on est sur la demarche PDV son et survol drone
            print("demande pdv son ou survol drone")
            # if demande survol --> create demande survol
            # if demande PDV son --> create demande PDV son

        else:

            liste_dem.append({
                        "id_etat_demande": EtatDemande.objects.filter(nom=doss["state"]).values_list("id", flat=True).first(), # par défaut meme etat que le dossier
                        "id_priorite": "", # TO DO
                        "id_dossier": "GET",
                        "id_demande_type": type_demande_par_defaut, #TO DO
                        "date_depot": "", # TO DO champ["updatedAt"]
                        "date_fin_instruction": doss["dateTraitement"],  # par défaut meme date de fin que le dossier
                        # "soumis_controle": "", #false par défaut
                    })


        # if tel champ est "oui" alors je créé un objet demande (exemple: votre demande de travaux inclut-elle un survol de drone?)
        """liste_dem.append({
            "id_etat_demande": EtatDemande.objects.filter(nom=doss["state"]).values_list("id", flat=True).first(), # par défaut meme etat que le dossier
            "id_priorite": "", # TO DO
            "id_dossier": "GET",
            "id_demande_type": "dépend du champ", #TO DO
            "date_depot": "", # TO DO champ["updatedAt"]
            "date_fin_instruction": doss["dateTraitement"],  # par défaut meme date de fin que le dossier
            # "soumis_controle": "", #false par défaut
        })"""

    return liste_dem

# def avis_normalize(d):
#     liste_avis = []

#     for doss in d["dossiers"]["nodes"] :
#          for a in doss["avis"]:
            
#             liste_avis.append({
#                 "id_ds": a["id"],
#                 "id_avis_nature": "", # à renseigner au moment de la création de l'avis
#                 "id_dossier": "GET",
#                 "id_avis_thematique": "", # à renseigner au moment de la création de l'avis
#                 "id_expert": "GET",
#                 "id_expert_ds": a["expert"]["id"],
#                 "id_instructeur": "GET",
#                 "note": "Avis ",
#                 # "favorable": "", # à renseigner en clic bouton dans l'appli
#                 "date_limite": datetime(2050, 1, 1),  # En attendant les calculs par rapport à la date de la demande
#                 # "date_presentation": "", # à renseigner dans l'appli le cas échéant
#                 "date_demande_avis": "",
#                 "date_reponse_avis": "",
#                 "mode_contact": "",
#             })


#     return liste_avis

# def demande_avis_normalize(d):
#     return None

# def expert_normalize(d):
#     return None

# def avis_document_normalize(d):
#     return None



if __name__ == "__main__":
    
    init_setup()

    from autorisations.models.models_instruction import EtatDemarche, Demarche, ChampType, DossierType, EtatDossier, Dossier, Champ, Demande, EtatDemande
    from autorisations.models.models_utilisateurs import Groupeinstructeur, ContactExterne, Instructeur, DossierBeneficiaire
    from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, Message, MessageDocument
    from DS.call_DS_test import get_number_demarche_Postgres, recup_data_DS
    from synchronisation.src.functions import fetch_geojson, extraire_nom_et_extension, type_demande_from_nom_demarche
    numeros_demarche = get_number_demarche_Postgres()


    # for num in numeros_demarche :
    #     datas_DS = recup_data_DS(num)

    # Test pour une démarche
    # datas_DS = recup_data_DS(numeros_demarche[0])
    datas_DS = recup_data_DS(114543)

    normalize_process(datas_DS["demarche"])



















# def dossier_normalize(d):

#     liste_doss = []
    
#     for doss in d["dossiers"]["nodes"] :
#         dico_all_info_dossier = {}
#         id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()
#         id_demarche = Demarche.objects.filter(id_ds=d["id"], numero=d["number"]).values_list("id", flat=True).first()

        #Dossier_Champ
            #Document
        #Contact_externe
        #Dossier_Beneficiare
        #DossierDocument (pdf..)
        #Message
        #Message_Document
        

        # dico_all_info_dossier["dossier"] = {
        #         "id_ds": doss["id"],
        #         "id_etat_dossier": EtatDossier.objects.filter(nom=doss["state"]).values_list("id", flat=True).first(),
        #         "id_demarche": id_demarche,
        #         "numero": doss["number"],
        #         # "id_groupeinstructeur": "",  # Laisser vide pour commencer
        #         "date_depot": datetime.fromisoformat(doss["dateDepot"]),
        #         "date_fin_instruction": doss["dateTraitement"],
        #         "id_dossier_type": DossierType.objects.filter(type="nouveau").values_list("id", flat=True).first(),  # Nouveau par défaut
        #         # "id_ds_dossier_parent": "TO DO",  # Laisser vide pour commencer
        #         # "note": "TO DO",
        #         "nom_dossier": f"projet_{doss['demandeur']['nom']}_{doss['demandeur']['prenom']}_{datetime.fromisoformat(doss['dateDepot']).year}",  # En attendant la norme de nommage
        #         "emplacement": "/emplacement/a_definir/",  # Arborescence à définir
        #         "date_limite_traitement": datetime(2050, 1, 1),  # En attendant les calculs par rapport à la date de début d'instruction
        # }

        # dico_all_info_dossier["dossier_instructeur"] = []
        # if doss.get("instructeurs"):
        #     for instru in doss["instructeurs"] :
        #         dico_all_info_dossier["dossier_instructeur"].append({
        #             "id_dossier": Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first(),
        #             "id_instructeur":Instructeur.objects.filter(email=instru["email"]).values_list("id", flat=True).first(), #filtre que sur l'email pour le moment
        #         })


        # dico_all_info_dossier["dossier_interlocuteur"] = {
        #     "id_interlocuteur_ds": doss["usager"]["id"],
        #     "id_demandeur_intermediaire": (
        #         None if (doss.get("prenomMandataire") is not None and doss.get("nomMandataire") is not None)
        #         else ContactExterne.objects.filter(email=doss["usager"]["email"]).values_list("id", flat=True).first()
        #     ),  
        #     "id_dossier": id_dossier,
        # }

    #     dico_all_info_dossier["dossier_champ"] = []
    #     dico_all_info_dossier["document"] = []

    #     for ch in doss["champs"] :

    #         # TROUVER UN MOYEN DE CREER LE DOCUMENT ET LE CHAMP piece_justificative

    #         id_champ_type = Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id_champ_type", flat=True).first()
    #         type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()
    #         if (type_du_champ == "piece_justificative") :

    #             dico_all_info_dossier["document"].append({
    #                 # "numero":"",   concerne plutot les arretés, demande d'avis etc..
    #                 "id_format": DocumentFormat.objects.filter(format="pdf").values_list("id", flat=True).first(),  #pdf par défaut pour lemoment
    #                 "id_nature": DocumentNature.objects.filter(nature="Pièce jointe demandeur").values_list("id", flat=True).first(),
    #                 "url_ds": ch["files"]["url"],
    #                 "emplacement":"/emplacement/a_definir/",
    #                 "description":ch["label"],
    #             })

    #         geometrie_du_champ = fetch_geojson(doss["geojson"]["url"]) if ch["__typename"] == "CarteChamp" else None
    #         dico_all_info_dossier["dossier_champ"].append({
    #             "id_dossier": id_dossier,
    #             "id_champ": Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id", flat=True).first(),
    #             "valeur": ch["stringValue"],
    #             "date_saisie": datetime.fromisoformat(ch["updatedAt"]),
    #             "geometrie": geometrie_du_champ,
    #             # "id_document": "",  faire crea document avant
    #         })



    #     liste_doss.append({ })
    # return liste_doss


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