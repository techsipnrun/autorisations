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
    #GroupeInstructeur_Instructeur
    #Instructeur


    # Normalisation des différentes entités
    demarche = demarche_normalize(d)
    groupeinstructeurs_demarches = groupeinstructeur_demarche_normalize(d)
    champs = champ_normalize(d)


    dossiers = dossier_normalize(d)

    contacts_externes = contact_externe_normalize(d) # To do : demandeur intermédiaire + bénéficiaire
    dossiers_interlocuteurs = dossier_interlocuteur_normalize(d)
    liste_documents = []
    dossiers_champs = dossiers_champs_normalize(d, liste_documents) # + Documents des champs "pièces justificatives"
    dossiers_beneficiaires = dossier_beneficiaire_normalize(d)
    dossiers_documents = dossier_document_normalize(d, liste_documents) # + Résumé dossier pdf
    liste_messages_documents = []
    messages = message_normalize(d, liste_messages_documents, liste_documents) # + Document + Message_document
    demandes = demande_normalize(d)

    """On laisse de côté en attendant la finalisation des forms sur DS"""
    # demandes_champs = demande_champ_normalize(d)
    # documents = document_normalize(d)


    
    # Retourner toutes les données normalisées dans un dictionnaire structuré
    return {
        "demarche": demarche,
        "groupeinstructeurs_demarches": groupeinstructeurs_demarches, #id_groupeinstructeur
        "champs": champs,
        "dossiers": dossiers, #id_groupeinstructeur, id_ds_dossier_parent, emplacement
        "dossiers_interlocuteurs": dossiers_interlocuteurs, #id_demandeur_intermediaire, id_dossier
        "dossiers_champs": dossiers_champs, #id_champ, id_document, id_dossier
        "contact_externe": contacts_externes,
        "dossier_beneficiaire": dossiers_beneficiaires, #id_dossier_interlocuteur, id_beneficiaire
        "dossier_documents": dossiers_documents, #id_document, id_dossier
        "messages": messages, #id_dossier
        "demandes": demandes,  # id_dossier, id_priorite (pour travaux urbanisme : PC/DP)
        "documents" : liste_documents, #emplacement
        "messages_documents" : liste_messages_documents, #id_message, id_document
    }


def demarche_normalize(d):

    dico_demarche = {
        "id_ds": d["id"],
        "numero": d["number"],
        "titre": d["title"],
        "id_etat" : EtatDemarche.objects.filter(nom=d["state"]).values_list("id", flat=True).first(),
        "date_creation": datetime.fromisoformat(d["dateCreation"]),
        "date_derniere_modif": datetime.fromisoformat(d["dateDerniereModification"]),
        "description": d["description"],
    }
    return dico_demarche


def groupeinstructeur_demarche_normalize(d):

    liste_gi = []   
    for gi in d["groupeInstructeurs"]:
        liste_gi.append({
            "id_demarche":d["id"],
            "id_groupeinstructeur":Groupeinstructeur.objects.filter(nom=gi["label"]).values_list("id", flat=True).first(),  # Routage DS pour commencer
            "id_groupeinstructeur_ds":gi["id"],
        })

    return liste_gi


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
    id_demarche = Demarche.objects.filter(id_ds=d["id"], numero=d["number"]).values_list("id", flat=True).first()

    for doss in d["dossiers"]["nodes"] :
        
        geojson = fetch_geojson(doss["geojson"]["url"]) if doss["geojson"] else None
        liste_doss.append({
                "id_ds": doss["id"],
                "id_etat_dossier": EtatDossier.objects.filter(nom=doss["state"]).values_list("id", flat=True).first(),
                "id_demarche": id_demarche,
                "numero": doss["number"],
                "id_groupeinstructeur": Groupeinstructeur.objects.filter(nom=doss["groupeInstructeur"]["label"]).values_list("id", flat=True).first(),  # Routage DS pour commencer
                "date_depot": datetime.fromisoformat(doss["dateDepot"]),
                "date_fin_instruction": doss["dateTraitement"],
                "id_dossier_type": DossierType.objects.filter(type="nouveau").values_list("id", flat=True).first(),  # Nouveau par défaut
                "id_ds_dossier_parent": "",  # Laisser vide pour commencer
                "note": "",
                "nom_dossier": f"{doss["number"]}_{doss['demandeur']['nom']}_{doss['demandeur']['prenom']}",  # En attendant la norme de nommage
                "emplacement": "/emplacement/a_definir/",  # Arborescence à définir
                "date_limite_traitement": datetime(2050, 1, 1),  # En attendant les calculs par rapport à la date de début d'instruction
                "geometrie": geojson,
        })

    return liste_doss



def contact_externe_normalize(d):
    """ 
        Beneficiare, DemandeurIntermédiaire --> Besoin de recup des champs du formulaire 
        Expert --> get or create au moment de la création de demande d'avis
    """
    liste_contacts_ext = []

    for doss in d["dossiers"]["nodes"] :

        # Demandeur intermédiaire (le cas échéant)
        if (doss.get("prenomMandataire") is not None and doss.get("nomMandataire") is not None):

            liste_contacts_ext.append({
                "email": doss['usager']['email'],
                "id_type": TypeContactExterne.objects.filter(type="demandeur_intermediaire").values_list("id", flat=True).first(),
                "nom": doss['nomMandataire'],
                "prenom": doss['prenomMandataire'],
            })

            # Bénéficiaire sachant qu'il y a un demandeur intermédiaire
            email_beneficaire = None
            if doss['demandeur']['__typename'] == "PersonnePhysique" :
                email_beneficaire = doss['demandeur']['email'] if doss['demandeur']['email'] else None
            liste_contacts_ext.append({
                "email": email_beneficaire,
                "id_type": TypeContactExterne.objects.filter(type="beneficiaire").values_list("id", flat=True).first(),
                "nom": doss['demandeur']['nom'],
                "prenom": doss['demandeur']['prenom'],
            })


        # Bénéficiaire sans demandeur intermédiaire
        else :

            email_beneficaire = doss['usager']['email'],
            liste_contacts_ext.append({
                "email": email_beneficaire,
                "id_type": TypeContactExterne.objects.filter(type="beneficiaire").values_list("id", flat=True).first(),
                "nom": doss['demandeur']['nom'],
                "prenom": doss['demandeur']['prenom'],
            })

    return liste_contacts_ext




def dossier_interlocuteur_normalize(d):
    liste_doss_interlo = []

    for doss in d["dossiers"]["nodes"] :
        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()

        liste_doss_interlo.append({
            "id_interlocuteur_ds": doss["usager"]["id"],
            "id_demandeur_intermediaire": (
                None if (doss.get("prenomMandataire") is None and doss.get("nomMandataire") is None)
                else ContactExterne.objects.filter(email=doss["usager"]["email"], id_type=TypeContactExterne.objects.filter(type="demandeur_intermediaire").values_list("id", flat=True).first()).values_list("id", flat=True).first()
            ),
            "id_dossier": id_dossier,
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

                    liste_documents.append({
                        # "numero":"",   concerne plutot les arretés, demande d'avis etc..
                        "id_format": DocumentFormat.objects.filter(format=extension_fichier).values_list("id", flat=True).first(),
                        "id_nature": DocumentNature.objects.filter(nature="Pièce jointe demandeur").values_list("id", flat=True).first(),
                        "url_ds": ch["files"]["url"],
                        "emplacement":"/emplacement/a_definir/",
                        "description":ch["label"],
                        "titre": nom_fichier,
                    })
 
                    id_document = Document.objects.filter(format=extension_fichier, titre=nom_fichier, url_ds=ch["files"]["url"]).values_list("id", flat=True).first() # plus tard filtrer sur l'emplacement du doc

                geometrie_du_champ = fetch_geojson(doss["geojson"]["url"]) if ch["__typename"] == "CarteChamp" else None

                liste_dossiers_champs.append({
                    "id_dossier": id_dossier,
                    "id_champ": Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id", flat=True).first(),
                    "valeur": ch["stringValue"],
                    "date_saisie": datetime.fromisoformat(ch["updatedAt"]),
                    "geometrie": geometrie_du_champ,
                    "id_document": id_document,
                })


    return liste_dossiers_champs





def dossier_beneficiaire_normalize(d):
    liste_doss_benef = []

    for doss in d["dossiers"]["nodes"] :
        id_type_contact_externe = TypeContactExterne.objects.filter(type="beneficiaire").values_list("id", flat=True).first()

        email_beneficaire = None

        if (doss.get("prenomMandataire") is None and doss.get("nomMandataire") is None): # pas de demandeur intermédiaire
            email_beneficaire = doss['demandeur']['email']

        elif doss['demandeur']['__typename'] == "PersonnePhysique" : # demandeur intermédiaire mais le mail du bénéficiare est tout de meme renseigné
            # plus tard : prévoir le cas des personnes morales
            email_beneficaire = doss['demandeur']['email'] if doss['demandeur']['email'] else None

        if email_beneficaire :
            id_beneficiaire = ContactExterne.objects.filter(id_type=id_type_contact_externe, 
                                                            nom=doss['demandeur']['nom'], 
                                                            prenom=doss['demandeur']['prenom'],
                                                            email=email_beneficaire,
                                                            ).values_list("id", flat=True).first(),
        else:
            # problème ici ça garantit pas l'unicité  (idée : choper l'id du beneficaire juste avant (au moment du get or create))
            id_beneficiaire = ContactExterne.objects.filter(id_type=id_type_contact_externe, nom=doss['demandeur']['nom'], prenom=doss['demandeur']['prenom']).values_list("id", flat=True).first(),


        liste_doss_benef.append({
            "id_dossier_interlocuteur": DossierInterlocuteur.objects.filter(id_interlocuteur_ds=doss["usager"]["id"]).values_list("id", flat=True).first(),
            "id_beneficiaire": id_beneficiaire,
        })

    return liste_doss_benef


def dossier_document_normalize(d, liste_documents):
   
    liste_doss_docu = []

    for doss in d["dossiers"]["nodes"] :

        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()
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

        id_pdf_format = DocumentFormat.objects.filter(format="pdf").values_list("id", flat=True).first(),
        id_nature_resume_dossier = DocumentNature.objects.filter(nature="Résumé dossier").values_list("id", flat=True).first(),
        liste_doss_docu.append({
            "id_dossier": id_dossier,
            "id_document": Document.objects.filter(id_format=id_pdf_format, id_nature=id_nature_resume_dossier, numero=doss["number"]).values_list("id", flat=True).first(),
        })

    return liste_doss_docu

def message_normalize(d, liste_msg_doc, liste_doc):
    
    liste_messages = []

    for doss in d["dossiers"]["nodes"] :
        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()
        for m in doss["messages"] :

            contient_pj = True if m["attachments"] else False
            liste_messages.append({
                            "id_ds": m["id"],
                            "body": m["body"],
                            "date_envoi": m["createdAt"],
                            "piece_jointe": contient_pj,
                            "email_emetteur": m["email"],
                            "id_dossier": id_dossier,
                            # "lu": False,  #Faux par défaut
                        })
            
            # if m["attachments"] :
            if m.get("attachments") and not m.get("email", "").endswith("@reunion-parcnational.fr"):
                for file in m["attachments"]:

                    nom_fichier, extension_fichier = extraire_nom_et_extension(file["filename"])
                    id_format_doc = DocumentFormat.objects.filter(format=extension_fichier).values_list("id", flat=True).first()
                    id_nature_doc = DocumentNature.objects.filter(nature="Pièce jointe demandeur").values_list("id", flat=True).first()
                    liste_doc.append({
                        # "numero": "",  pas concerné ici
                        "id_format": id_format_doc,
                        "id_nature": id_nature_doc,
                        "url_ds": file["url"],
                        "emplacement":"/emplacement/a_definir/",  #TO DO
                        "description": f"Pièce jointe dans la messagerie du dossier {doss["number"]}",
                        "titre": nom_fichier,
                    })

                    liste_msg_doc.append({
                        "id_message": Message.objects.filter(id_ds=m["id"],id_dossier=id_dossier).values_list("id", flat=True).first(),
                        #A terme filtrer sur l'emplacement du fichier
                        "id_document": Document.objects.filter(id_format=id_format_doc, id_nature=id_nature_doc, url_ds=file["url"]).values_list("id", flat=True).first(),
                    })

    return liste_messages


def demande_normalize(d):
    
    liste_dem = []
    type_demande_par_defaut = type_demande_from_nom_demarche(d["title"])


    for doss in d["dossiers"]["nodes"] :
        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()

        if type_demande_par_defaut == 999 : # on est sur la demarche PDV son et survol drone
            print("Demande PDV SON ou Survol drone : Script de normalisation à faire pour l'objet demande")
            # if demande survol --> liste_dem.append(demande survol)
            # if demande PDV son --> liste_dem.append(demande PDV son)

        else:
            id_priorite = calcul_priorite_instruction(d["id"], doss) # À condition que la colonne delais_jours_instruction soit remplie pour la démarche
            liste_dem.append({
                        "id_etat_demande": EtatDemande.objects.filter(nom=doss["state"]).values_list("id", flat=True).first(), # par défaut meme etat que le dossier
                        "id_priorite": id_priorite,
                        "id_dossier": id_dossier,
                        "id_demande_type": type_demande_par_defaut, #TO DO
                        "date_depot": doss["dateDepot"], # plus tard champ["updatedAt"]
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




if __name__ == "__main__":
    
    init_setup()

    from autorisations.models.models_instruction import EtatDemarche, Demarche, ChampType, DossierType, EtatDossier, Dossier, Champ, Demande, EtatDemande, DemandeType
    from autorisations.models.models_utilisateurs import Groupeinstructeur, ContactExterne, Instructeur, DossierBeneficiaire, TypeContactExterne, DossierInterlocuteur
    from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, Message, MessageDocument
    from DS.call_DS_test import get_number_demarche_Postgres, recup_data_DS
    from synchronisation.src.functions import fetch_geojson, extraire_nom_et_extension, type_demande_from_nom_demarche, save_to_json, calcul_priorite_instruction
    from autorisations.src.synchronisation.src.synchro import *
    # numeros_demarche = get_number_demarche_Postgres()


    # for num in numeros_demarche :
    #     datas_DS = recup_data_DS(num)

    # Test pour une démarche
    # datas_DS = recup_data_DS(numeros_demarche[0])
    datas_DS = recup_data_DS(114297)

    resultats = normalize_process(datas_DS["demarche"])
    save_to_json(resultats)
    # synchro_process(resultats)
