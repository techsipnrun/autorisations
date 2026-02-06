from datetime import datetime
import logging
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature
from autorisations.models.models_instruction import Champ, ChampType, Demarche
from autorisations.models.models_utilisateurs import TypeContactExterne
from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz
from synchronisation.src.utils.fichiers import fetch_geojson, geoareas_to_geojson_text
from synchronisation.src.utils.conversion import extraire_nom_et_extension

logger = logging.getLogger('ORM_DJANGO')
def dossiers_champs_normalize(doss, emplacement_dossier, contacts):


    liste_dossiers_champs = []

    PERSONNE_MORALE_AVEC_DEMANDEUR_INTER = False

    # contacts_externes = {
    #     'beneficiaire': {},
    #     'demandeur_intermediaire': {},
    #     'demandeur_pers_morale': {}
    # }

    for ch in doss["champs"]:

        liste_documents = []

        if ch["__typename"] == "PieceJustificativeChamp" :
            for f in ch["files"]:
                
                nom_fichier, extension_fichier = extraire_nom_et_extension(f["filename"])               
                id_format = get_first_id(DocumentFormat, format=extension_fichier)
                if not id_format:
                    logger.error(f"Format de document inconnu : {extension_fichier} pour le dossier {doss['number']}")
                    continue

                liste_documents.append({
                    "id_format": id_format,
                    "id_nature": get_first_id(DocumentNature, nature="Pièce jointe demandeur"),
                    "url_ds": f["url"],
                    "emplacement": f"{emplacement_dossier}Annexes/",
                    "description": ch["label"],
                    "titre": f"{nom_fichier}.{extension_fichier}",
                })

                dico_champ = {
                    "nom_champ": ch["label"],
                    "id_ds": ch["id"],
                    # "id_champ": id_champ,
                    "valeur": ch["stringValue"],
                    "date_saisie": parse_datetime_with_tz(ch["updatedAt"]),
                    "geometrie": None,
                    "id_document": None,
                }

                liste_dossiers_champs.append({
                    "documents": liste_documents,
                    "champ": dico_champ
                })
        elif ch["__typename"] == "RepetitionChamp" :

            dico_repet_champ = {}
            for row in ch["rows"]:
                # row["id"] = id de l'instance 1
                dico_repet_champ[row["id"]] = []
                for c in row["champs"] :
                    if not (c["__typename"] == "TextChamp" and c["stringValue"] == ""):
                        dico_repet_champ[row["id"]].append({
                            "id_ds": c["id"],
                            "nom": c["label"],
                            "valeur": c["stringValue"],
                        })

            dico_champ = {
                    "nom_champ": ch["label"],
                    "id_ds": ch["id"],
                    "valeur": dico_repet_champ,
                    "date_saisie": parse_datetime_with_tz(ch["updatedAt"]),
                    "geometrie": geometrie_du_champ,
                    "id_document": None,
                }
            
            liste_dossiers_champs.append({
                "champ": dico_champ
            })
            
        else:
            # geometrie_du_champ1 = fetch_geojson(doss["geojson"]["url"]) if ch["__typename"] == "CarteChamp" else None
            geometrie_du_champ = geoareas_to_geojson_text(ch["geoAreas"]) if ch["__typename"] == "CarteChamp" else None
            
            # Si le module carto n'a pas été rempli --> on met l'attribut 'geometrie_a_saisir' à True
            if ch["label"] == 'Choix de la méthode pour localiser le projet': 
                if 'Remplir le module de cartographie' not in ch["stringValue"] :
                    # Sont concernées : Missions scientifiques 5, Hélico  7, PDV son drone 8, Manifs publiques 11
                    
                    dico_champ = {
                        "geometrie_a_saisir": True,
                        "nom_champ": ch["label"],
                        "id_ds": ch["id"],
                        "valeur": ch["stringValue"],
                        "date_saisie": parse_datetime_with_tz(ch["updatedAt"]),
                        "geometrie": geometrie_du_champ,
                        "id_document": None,
                    }
                else :
                    dico_champ = {
                        "geometrie_a_saisir": False,
                        "nom_champ": ch["label"],
                        "id_ds": ch["id"],
                        "valeur": ch["stringValue"],
                        "date_saisie": parse_datetime_with_tz(ch["updatedAt"]),
                        "geometrie": geometrie_du_champ,
                        "id_document": None,
                    }

            else :    
                dico_champ = {
                    "nom_champ": ch["label"],
                    "id_ds": ch["id"],
                    "valeur": ch["stringValue"],
                    "date_saisie": parse_datetime_with_tz(ch["updatedAt"]),
                    "geometrie": geometrie_du_champ,
                    "id_document": None,
                }


                ############################################################################
                ###    COMPLEMENT D'INFO SUR LE BENEFICIAIRE / DEMANDEUR INTERMEDIAIRE   ###
                ############################################################################

                # -------------------------------
                # Remplisseur = Personne physique
                # -------------------------------
                if contacts.get('beneficiaire') :
                    
                    # if not contacts['demandeur_intermediaire'] :
                    #Beneficiaire
                    if ch['label'] == "Email du bénéficiaire" and ch["stringValue"] != None and not contacts["beneficiaire"].get("email"):
                        contacts["beneficiaire"]["email"] = ch["stringValue"]
                    if ch['label'] == "Adresse du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["adresse"] = ch["stringValue"]
                    if ch['label'] == "Numéro de téléphone du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["telephone"] = ch["stringValue"]
                    if ch['label'] == "Nom de l'organisation" and ch["stringValue"] != None:   # Nom de l'organisation (du bénéficiaire ?)
                        contacts["beneficiaire"]["organisation"] = ch["stringValue"]
                    if ch['label'] == "Numéro de SIRET" and ch["stringValue"] != None:  # Numéro de SIRET (du bénéficiaire ?)
                        contacts["beneficiaire"]["siret"] = ch["stringValue"]

                    # ----------------------------------------------------------------------------------
                    # Remplisseur = Personne physique qui s'est déclaré comme un demandeur intermédiaire
                    # ----------------------------------------------------------------------------------
                    # Si la personne ne s'est pas déclaré comme intermédiaire à l'entrée du form : on ne créé pas le contact externe Demandeur Intermédiaire
                    if contacts.get('demandeur_intermediaire') :
                        if ch['label'] == "Numéro de téléphone du demandeur intermédiaire" and ch["stringValue"] != None:
                            contacts["demandeur_intermediaire"]["telephone"] = ch["stringValue"]
                        if ch['label'] == "Nom de l'organisation du demandeur intermédiaire" and ch["stringValue"] != None:
                            contacts["demandeur_intermediaire"]["organisation"] = ch["stringValue"]
                            contacts["demandeur_intermediaire"]["raison_sociale"] = ch["stringValue"]
                        if ch['label'] == "Adresse du demandeur intermédiaire" and ch["stringValue"] != None:
                            contacts["demandeur_intermediaire"]["adresse"] = ch["stringValue"]


                # -----------------------------
                # Remplisseur = Personne morale
                # -----------------------------
                elif contacts.get('demandeur_pers_morale') :
                    if ch['label'] == "Votre administration agit en tant qu’intermédiaire pour un autre pétitionnaire" :
                        if ch["stringValue"] == "true" :
                            PERSONNE_MORALE_AVEC_DEMANDEUR_INTER = True
                   
                    # Complément d'information du remplisseur dans le form
                    if ch['label'] == "Votre nom" and ch["stringValue"] != None :
                        contacts['demandeur_pers_morale']["nom"] = ch["stringValue"]
                    if ch['label'] == "Votre prénom" and ch["stringValue"] != None :
                        contacts['demandeur_pers_morale']["prenom"] = ch["stringValue"]
                    if ch['label'] == "Votre numéro de téléphone " and ch["stringValue"] != None :
                        contacts['demandeur_pers_morale']["telephone"] = ch["stringValue"]
                
                    # Le remplisseur du form (Personne Morale) fait l'intermédiaire, le beneficiaire est déclaré dans le form
                    if ch['label'] == "Nom du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["nom"] = ch["stringValue"]
                    if ch['label'] == "Prénom du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["prenom"] = ch["stringValue"]
                    if ch['label'] == "Email du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["email"] = ch["stringValue"]
                        contacts['beneficiaire']['id_type'] = get_first_id(TypeContactExterne, type="Demandeur intermédiaire")
                    if ch['label'] == "Adresse du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["adresse"] = ch["stringValue"]
                    if ch['label'] == "Numéro de téléphone du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["telephone"] = ch["stringValue"]
                    if ch['label'] == "Nom de l'organisation du bénéficiaire" and ch["stringValue"] != None:
                        contacts["beneficiaire"]["organisation"] = ch["stringValue"]
                        contacts["beneficiaire"]["raison_sociale"] = ch["stringValue"]
                    if ch['label'] == "Numéro de SIRET" and ch["stringValue"] != None:  # Numéro de SIRET (du bénéficiaire ?)
                        contacts["beneficiaire"]["siret"] = ch["stringValue"]
                    

            if PERSONNE_MORALE_AVEC_DEMANDEUR_INTER :
                remplisseur_type = 'demandeur_intermediaire'
                type_contact = get_first_id(TypeContactExterne, type="Demandeur intermédiaire")
            else :
                remplisseur_type = 'beneficiaire'
                type_contact = get_first_id(TypeContactExterne, type="Bénéficiaire")

            # On transfère contacts['demandeur_pers_morale'] --> contacts['demandeur_intermediaire']
            if contacts.get('demandeur_pers_morale') :
                source = contacts.get("demandeur_pers_morale", {})

                if source.get("raison_sociale"):
                    contacts[remplisseur_type]["raison_sociale"] = source["raison_sociale"]
                if source.get("organisation"):
                    contacts[remplisseur_type]["organisation"] = source["organisation"]
                if source.get("email"):
                    contacts[remplisseur_type]["email"] = source["email"]
                contacts[remplisseur_type]["id_type"] = type_contact
                if source.get("siret"):
                    contacts[remplisseur_type]["siret"] = source["siret"]
                if source.get("adresse"):
                    contacts[remplisseur_type]["adresse"] = source["adresse"]
                if source.get("nom"):
                    contacts[remplisseur_type]["nom"] = source["nom"]
                if source.get("prenom"):
                    contacts[remplisseur_type]["prenom"] = source["prenom"]
                if source.get("telephone"):
                    contacts[remplisseur_type]["telephone"] = source["telephone"]

            liste_dossiers_champs.append({
                "champ": dico_champ
            })
        


    return liste_dossiers_champs, contacts
