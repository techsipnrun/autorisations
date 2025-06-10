from datetime import datetime
import logging
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature
from autorisations.models.models_instruction import Champ, ChampType
from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz
from synchronisation.src.utils.fichiers import fetch_geojson, geoareas_to_geojson_text
from synchronisation.src.utils.conversion import extraire_nom_et_extension

logger = logging.getLogger('ORM_DJANGO')
def dossiers_champs_normalize(doss, emplacement_dossier):
    liste_dossiers_champs = []

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
                    "emplacement": f"{emplacement_dossier}/Annexes/",
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

            liste_dossiers_champs.append({
                "champ": dico_champ
            })

    return liste_dossiers_champs
