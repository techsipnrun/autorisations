from datetime import datetime
import logging
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature
from autorisations.models.models_instruction import Champ, ChampType
from autorisations.models.models_utilisateurs import TypeContactExterne
from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz
from synchronisation.src.utils.fichiers import fetch_geojson, geoareas_to_geojson_text
from synchronisation.src.utils.conversion import extraire_nom_et_extension

logger = logging.getLogger('ORM_DJANGO')
def dossiers_champs_normalize(doss, emplacement_dossier, contacts):

    # contacts[demandeur_intermediaire] et contacts[beneficiaire]
    # logger.info(contacts['beneficiaire'])
    # logger.info(contacts['demandeur_intermediaire'])

    liste_dossiers_champs = []

    contacts_externes = {
        'beneficiaire': {},
        'demandeur_intermediaire': {}
    }

    for ch in doss["champs"]:

        liste_documents = []

        if ch["__typename"] == "PieceJustificativeChamp" :
            for f in ch["files"]:
                
                nom_fichier, extension_fichier = extraire_nom_et_extension(f["filename"])               
                id_format = get_first_id(DocumentFormat, format=extension_fichier)
                if not id_format:
                    logger.error(f"Format de document inconnu : {extension_fichier} pour le dossier {doss["number"]}")
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
                    "nom_champ": ch["label"],
                    "id_ds": ch["id"],
                    "valeur": ch["stringValue"],
                    "date_saisie": parse_datetime_with_tz(ch["updatedAt"]),
                    "geometrie": geometrie_du_champ,
                    "id_document": None,
                }

                # On ajoute des infos aux contact externes (Bénéficiaire et le cas échéant DemandeurIntermédiaire)
                #Benefiaire
                if ch['label'] == "Email du bénéficiaire" and ch["stringValue"] != None:
                    contacts_externes["beneficiaire"]["email"] = ch["stringValue"]
                if ch['label'] == "Adresse du bénéficiaire" and ch["stringValue"] != None:
                    contacts_externes["beneficiaire"]["adresse"] = ch["stringValue"]
                if ch['label'] == "Numéro de téléphone du bénéficiaire" and ch["stringValue"] != None:
                    contacts_externes["beneficiaire"]["telephone"] = ch["stringValue"]
                if ch['label'] == "Nom de l'organisation" and ch["stringValue"] != None:
                    contacts_externes["beneficiaire"]["organisation"] = ch["stringValue"]
                if ch['label'] == "Numéro de SIRET" and ch["stringValue"] != None:
                    contacts_externes["beneficiaire"]["siret"] = ch["stringValue"]

                #Demandeur Intermédiaire
                if ch['label'] == "Numéro de téléphone du demandeur intermédiaire" and ch["stringValue"] != None:
                    contacts_externes["demandeur_intermediaire"]["telephone"] = ch["stringValue"]
                if ch['label'] == "Nom de l'organisation du demandeur intermédiaire" and ch["stringValue"] != None:
                    contacts_externes["demandeur_intermediaire"]["organisation"] = ch["stringValue"]
                    contacts_externes["demandeur_intermediaire"]["raison_sociale"] = ch["stringValue"]
                if ch['label'] == "Adresse du demandeur intermédiaire" and ch["stringValue"] != None:
                    contacts_externes["demandeur_intermediaire"]["adresse"] = ch["stringValue"]
                if ch['label'] == "Email du demandeur intermédiaire" and ch["stringValue"] != None:
                    contacts_externes["demandeur_intermediaire"]["email"] = ch["stringValue"]
                    contacts_externes['demandeur_intermediaire']['id_type'] = get_first_id(TypeContactExterne, type="demandeur_intermediaire")
                # Attention si jamais le péti ne sélectionne pas 'Demandeur Intermédiaire' dans la page d'ouverture de Démarches Simplifiées, 
                # mais qu'il coche Demandeur Intermédiaire dans le formulaire : On a une contradiction. Ici on fait le choix de le créer malgré tout (mais sans nom ni prénom)
                    
      

            liste_dossiers_champs.append({
                "champ": dico_champ
            })


    # ajout des infos demandeur et benef
    # 'beneficiaire': {'email', 'id_type', 'nom', 'prenom'}
    # 'demandeur_intermediaire': {'email', 'id_type', 'nom'', 'prenom', 'siret', 'raison_sociale', 'organisation', 'adresse'}
    # logger.info(doss['number'])
    # logger.info(contacts_externes)


    return liste_dossiers_champs, contacts_externes
