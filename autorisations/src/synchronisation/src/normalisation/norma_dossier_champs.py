from datetime import datetime
import logging
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature
from autorisations.models.models_instruction import Champ, ChampType
from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz
from synchronisation.src.utils.fichiers import fetch_geojson
from synchronisation.src.utils.conversion import extraire_nom_et_extension

logger = logging.getLogger('ORM_DJANGO')
def dossiers_champs_normalize(doss, emplacement_dossier):
    liste_dossiers_champs = []

    for ch in doss["champs"]:

        liste_documents = []
        # id_champ_type = Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id_champ_type", flat=True).first()
        # type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()
        # id_document = None
     
        # if type_du_champ == "piece_justificative":
        if ch["__typename"] == "PieceJustificativeChamp" :
            for f in ch["files"]:
                nom_fichier, extension_fichier = extraire_nom_et_extension(f["filename"])

                liste_documents.append({
                    "id_format": get_first_id(DocumentFormat, format=extension_fichier),
                    "id_nature": get_first_id(DocumentNature, nature="Pièce jointe demandeur"),
                    "url_ds": f["url"],
                    "emplacement": f"{emplacement_dossier}/Annexes/",
                    "description": ch["label"],
                    "titre": f"{nom_fichier}.{extension_fichier}",
                })

                # id_document = get_first_id(Document, format=extension_fichier, titre=nom_fichier, url_ds=f["url"])

                # id_champ=get_first_id(Champ, id_ds=ch["id"], nom=ch["label"])
                # if not id_champ:
                #     titre_demarche_sans_apostrophe = titre_demarche.replace("'", " ").replace("’", " ")
                #     logger.error(f"[ERROR] Le champ {ch["label"]} (démarche = {titre_demarche_sans_apostrophe}) n'a pas été trouvé sur Postgres.")
                # else :
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
            geometrie_du_champ = fetch_geojson(doss["geojson"]["url"]) if ch["__typename"] == "CarteChamp" else None

            # id_champ=get_first_id(Champ, id_ds=ch["id"], nom=ch["label"])
                
            # if not id_champ:
            #     logger.error(f"[ERROR] Le champ {ch["label"]} (id D-S = {ch["id"]}) n'a pas été trouvé sur Postgres.")
            # else :
                
            dico_champ = {
                # "id_champ": id_champ,
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
