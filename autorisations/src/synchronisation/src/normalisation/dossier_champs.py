from datetime import datetime
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature
from autorisations.models.models_instruction import Champ, ChampType
from synchronisation.src.functions import fetch_geojson, get_first_id, extraire_nom_et_extension


def dossiers_champs_normalize(doss, id_dossier):
    liste_dossiers_champs = []

    for ch in doss["champs"]:

        liste_documents = []
        id_champ_type = Champ.objects.filter(id_ds=ch["id"], nom=ch["label"]).values_list("id_champ_type", flat=True).first()
        type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()
        id_document = None

        if type_du_champ == "piece_justificative":
            for f in ch["files"]:
                nom_fichier, extension_fichier = extraire_nom_et_extension(f["filename"])

                liste_documents.append({
                    "id_format": get_first_id(DocumentFormat, format=extension_fichier),
                    "id_nature": get_first_id(DocumentNature, nature="Pièce jointe demandeur"),
                    "url_ds": f["url"],
                    "emplacement": "/emplacement/a_definir/",
                    "description": ch["label"],
                    "titre": nom_fichier,
                })

                id_document = get_first_id(Document, format=extension_fichier, titre=nom_fichier, url_ds=f["url"])

                dico_champ = {
                    "id_dossier": id_dossier,
                    "id_champ": get_first_id(Champ, id_ds=ch["id"], nom=ch["label"]),
                    "valeur": ch["stringValue"],
                    "date_saisie": datetime.fromisoformat(ch["updatedAt"]),
                    "geometrie": None,
                    "id_document": id_document,
                }

                liste_dossiers_champs.append({
                    "documents": liste_documents,
                    "champ": dico_champ
                })

        else:
            geometrie_du_champ = fetch_geojson(doss["geojson"]["url"]) if ch["__typename"] == "CarteChamp" else None

            dico_champ = {
                "id_dossier": id_dossier,
                "id_champ": get_first_id(Champ, id_ds=ch["id"], nom=ch["label"]),
                "valeur": ch["stringValue"],
                "date_saisie": datetime.fromisoformat(ch["updatedAt"]),
                "geometrie": geometrie_du_champ,
                "id_document": None,
            }

            liste_dossiers_champs.append({
                "champ": dico_champ
            })

    return liste_dossiers_champs
