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
    dossiers = dossiers_normalize_process(d)

    

    """On laisse de côté en attendant la finalisation des forms sur DS"""
    # demandes_champs = demande_champ_normalize(d)
        # documents = document_normalize(d)


    
    # Retourner toutes les données normalisées dans un dictionnaire structuré
    return {
        "demarche": demarche,
        "groupeinstructeurs_demarches": groupeinstructeurs_demarches, #id_groupeinstructeur
        "champs": champs,
        "dossiers": dossiers, #id_groupeinstructeur, id_ds_dossier_parent, emplacement
    }


def demarche_normalize(d):

    dico_demarche = {
        "id_ds": d["id"],
        "numero": d["number"],
        "titre": d["title"],
        "id_etat" : EtatDemarche.objects.filter(nom=d["state"]).values_list("id", flat=True).first(),
        "date_creation": datetime.fromisoformat(d["dateCreation"]),
        "date_derniere_modif": datetime.fromisoformat(d["dateDerniereModification"]),
        # "description": d["description"], #Pas besoin de la description
    }
    return dico_demarche


def groupeinstructeur_demarche_normalize(d):

    liste_gi = []   
    for gi in d["groupeInstructeurs"]:
        if gi["label"]!= 'Groupe inactif' :

            id_gi = Groupeinstructeur.objects.filter(nom=gi["label"]).values_list("id", flat=True).first()
            if not id_gi :
                logger.error(f"[ERROR] L'ID du groupe instructeur {gi['label']} n'a pas été trouvé sur Postgres.")
            else :
                liste_gi.append({
                    "id_demarche":Demarche.objects.filter(id_ds=d["id"], numero=d["number"]).values_list("id", flat=True).first(),
                    "id_groupeinstructeur":Groupeinstructeur.objects.filter(nom=gi["label"]).values_list("id", flat=True).first(), 
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



def dossiers_normalize_process(d):

    id_demarche = Demarche.objects.filter(id_ds=d["id"], numero=d["number"]).values_list("id", flat=True).first()

    dossiers = []
    for doss in d["dossiers"]["nodes"] :

        id_dossier = Dossier.objects.filter(id_ds=doss["id"], numero=doss["number"]).values_list("id", flat=True).first()

        dico_dossier = {
            'dossier': dossier_normalize(id_demarche, doss),
            'contacts_externes': contact_externe_normalize(doss),
            'dossier_interlocuteur': dossier_interlocuteur_normalize(doss, id_dossier),
            'dossier_beneficiaire': dossier_beneficiaire_normalize(doss),
            # Pour le moment on renseigne tous les champs dans dossier_champs (plus tard on fera une distinction avec demande_champs)
            'dossier_champs': dossiers_champs_normalize(doss, id_dossier),
            'dossier_document': dossier_document_normalize(doss, id_dossier),
            'messages': message_normalize(doss, id_dossier),
            'demandes': demande_normalize(d["id"], d["title"], doss, id_dossier)
        }

        dossiers.append(dico_dossier)
        
    return dossiers


def dossier_normalize(id_demarche, doss):

    geojson = fetch_geojson(doss["geojson"]["url"]) if doss["geojson"] else None

    return({
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



def contact_externe_normalize(doss):
    """ 
        Beneficiare, DemandeurIntermédiaire --> Besoin de recup des champs du formulaire 
        Expert --> get or create au moment de la création de demande d'avis
    """
    contacts_externes = {'beneficiaire': {}, 'demandeur_intermediaire': {}}

    # Demandeur intermédiaire (le cas échéant)
    if (doss.get("prenomMandataire") is not None and doss.get("nomMandataire") is not None):

        contacts_externes['demandeur_intermediaire'] = {
            "email": doss['usager']['email'],
            "id_type": TypeContactExterne.objects.filter(type="demandeur_intermediaire").values_list("id", flat=True).first(),
            "nom": doss['nomMandataire'],
            "prenom": doss['prenomMandataire'],
        }

        # Bénéficiaire sachant qu'il y a un demandeur intermédiaire
        email_beneficaire = None
        if doss['demandeur']['__typename'] == "PersonnePhysique" :
            email_beneficaire = doss['demandeur']['email'] if doss['demandeur']['email'] else None

        contacts_externes['beneficiaire'] = {
            "email": email_beneficaire,
            "id_type": TypeContactExterne.objects.filter(type="beneficiaire").values_list("id", flat=True).first(),
            "nom": doss['demandeur']['nom'],
            "prenom": doss['demandeur']['prenom'],
        }


    # Bénéficiaire sans demandeur intermédiaire
    else :
        email_beneficaire = doss['usager']['email'],

        contacts_externes['beneficiaire'] = {
            "email": email_beneficaire,
            "id_type": TypeContactExterne.objects.filter(type="beneficiaire").values_list("id", flat=True).first(),
            "nom": doss['demandeur']['nom'],
            "prenom": doss['demandeur']['prenom'],
        }

    return contacts_externes




def dossier_interlocuteur_normalize(doss, id_dossier):

    if (doss.get("prenomMandataire") is None and doss.get("nomMandataire") is None):
        id_demandeur_intermediaire = None

    else:
        type_demandeur_intermediaire = TypeContactExterne.objects.filter(type="demandeur_intermediaire").values_list("id", flat=True).first()
        id_demandeur_intermediaire = ContactExterne.objects.filter(email=doss["usager"]["email"], id_type=type_demandeur_intermediaire).values_list("id", flat=True).first()

    return  {
                "id_interlocuteur_ds": doss["usager"]["id"],
                "id_demandeur_intermediaire": id_demandeur_intermediaire,
                "id_dossier": id_dossier,
            }



def dossiers_champs_normalize(doss, id_dossier):
    liste_dossiers_champs = []
    
    for ch in doss["champs"] :
            
        liste_documents = [] # pour les champs de type pièces justificatives

        id_champ_type = Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id_champ_type", flat=True).first()
        type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()
        id_document = None

        # Champ Pièces Justificatives
        if (type_du_champ == "piece_justificative") :
            for f in ch["files"] :

                nom_fichier, extension_fichier = extraire_nom_et_extension(f["filename"])

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

                dico_champ = {
                    "id_dossier": id_dossier,
                    "id_champ": Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id", flat=True).first(),
                    "valeur": ch["stringValue"],
                    "date_saisie": datetime.fromisoformat(ch["updatedAt"]),
                    "geometrie": None,
                    "id_document": id_document,
                }

                liste_dossiers_champs.append({
                    'documents': liste_documents,
                    'champ': dico_champ
                })

        # Champ (Hors Pièces Justificatives)
            """VERIFIER que les autres champs n'ont pas de pieces jointes (ex: CarteChamp)"""
        else :
            geometrie_du_champ = fetch_geojson(doss["geojson"]["url"]) if ch["__typename"] == "CarteChamp" else None

            dico_champ = {
                "id_dossier": id_dossier,
                "id_champ": Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id", flat=True).first(),
                "valeur": ch["stringValue"],
                "date_saisie": datetime.fromisoformat(ch["updatedAt"]),
                "geometrie": geometrie_du_champ,
                "id_document": None,
            }

            liste_dossiers_champs.append({
                    'champ': dico_champ
                })


    return liste_dossiers_champs



def dossier_beneficiaire_normalize(doss):
 
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


    return  {
                "id_dossier_interlocuteur": DossierInterlocuteur.objects.filter(id_interlocuteur_ds=doss["usager"]["id"]).values_list("id", flat=True).first(),
                "id_beneficiaire": id_beneficiaire,
            }



def dossier_document_normalize(doss, id_dossier):
   
    nom_fichier, extension_fichier = extraire_nom_et_extension(doss["pdf"]["filename"])

    dico_pdf = {
        "numero": doss["number"],
        "id_format": DocumentFormat.objects.filter(format=extension_fichier).values_list("id", flat=True).first(),
        "id_nature": DocumentNature.objects.filter(nature="Résumé dossier").values_list("id", flat=True).first(),
        "url_ds": doss["pdf"]["url"],
        "emplacement":"/emplacement/a_definir/",
        "description": f"Résumé du dossier {doss["number"]}",
        "titre": nom_fichier,
    }

    id_pdf_format = DocumentFormat.objects.filter(format="pdf").values_list("id", flat=True).first(),
    id_nature_resume_dossier = DocumentNature.objects.filter(nature="Résumé dossier").values_list("id", flat=True).first(),
    dossier_document = {
        "id_dossier": id_dossier,
        "id_document": Document.objects.filter(id_format=id_pdf_format, id_nature=id_nature_resume_dossier, numero=doss["number"]).values_list("id", flat=True).first(),
    }

    return {
        'resume_pdf': dico_pdf,
        'dossier_document': dossier_document,
    }



def message_normalize(doss, id_dossier):
    
    liste_messages = []

    for m in doss["messages"] :

        contient_pj = True if m["attachments"] else False

        dico_message = {
            "id_ds": m["id"],
            "body": m["body"],
            "date_envoi": m["createdAt"],
            "piece_jointe": contient_pj,
            "email_emetteur": m["email"],
            "id_dossier": id_dossier,
            # "lu": False,  #Faux par défaut
        }

        liste_files_message = []
        liste_msg_doc = []

        if contient_pj and not m.get("email", "").endswith("@reunion-parcnational.fr"):
        # if contient_pj :
            for file in m["attachments"]:

                nom_fichier, extension_fichier = extraire_nom_et_extension(file["filename"])
                id_format_doc = DocumentFormat.objects.filter(format=extension_fichier).values_list("id", flat=True).first()
                id_nature_doc = DocumentNature.objects.filter(nature="Pièce jointe demandeur").values_list("id", flat=True).first()
                liste_files_message.append({
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
                    # A terme filtrer sur l'emplacement du fichier
                    "id_document": Document.objects.filter(id_format=id_format_doc, id_nature=id_nature_doc, url_ds=file["url"]).values_list("id", flat=True).first(),
                })

        liste_messages.append({
            'message': dico_message,
            'documents': liste_files_message,
            'message_documents': liste_msg_doc
        })

    return liste_messages


def demande_normalize(demarche_id_ds, demarche_title, doss, id_dossier):
    
    liste_demandes = []

    type_demande_par_defaut = type_demande_from_nom_demarche(demarche_title)

    if type_demande_par_defaut == 999 : # on est sur la demarche PDV son et survol drone
        print("Demande PDV SON ou Survol drone : Script de normalisation à faire pour l'objet demande")
        # if demande survol --> liste_dem.append(demande survol)
        # if demande PDV son --> liste_dem.append(demande PDV son)

    else:
        id_priorite = calcul_priorite_instruction(demarche_id_ds, doss) # À condition que la colonne delais_jours_instruction soit remplie pour la démarche
        liste_demandes.append({
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

    return liste_demandes




if __name__ == "__main__":
    
    init_setup()

    from autorisations.models.models_instruction import EtatDemarche, Demarche, ChampType, DossierType, EtatDossier, Dossier, Champ, Demande, EtatDemande, DemandeType
    from autorisations.models.models_utilisateurs import Groupeinstructeur, ContactExterne, Instructeur, DossierBeneficiaire, TypeContactExterne, DossierInterlocuteur
    from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, Message, MessageDocument
    from DS.call_DS_test import get_number_demarche_Postgres, recup_data_DS
    from synchronisation.src.functions import fetch_geojson, extraire_nom_et_extension, type_demande_from_nom_demarche, save_to_json, calcul_priorite_instruction
    from synchronisation.src.synchro import *
    # numeros_demarche = get_number_demarche_Postgres()


    # for num in numeros_demarche :
    #     datas_DS = recup_data_DS(num)

    # Test pour une démarche
    # datas_DS = recup_data_DS(numeros_demarche[0])
    datas_DS = recup_data_DS(114297)

    resultats = normalize_process(datas_DS["demarche"])
    save_to_json(resultats)
    synchro_process(resultats)
