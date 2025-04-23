from autorisations.models.models_instruction import Dossier, DossierChamp, Champ, ChampType
from autorisations.models.models_documents import Document
from ..functions import get_first_id, update_fields, write_geojson, write_pj
import logging

logger = logging.getLogger("ORM_DJANGO")

def sync_dossier_champs(dossier_champs, id_dossier):
    """
    Synchronise les DossierChamps
    
    {
        "documents": [{"numero", "id_format", "id_nature", "url_ds", "emplacement", "description", "titre"}, ...],
        "champ": {"nom_champ", "id_ds", "valeur", "date_saisie", "geometrie", "id_document"=None}
    }
    """
     
    for ch in dossier_champs:
        dossier_champ = ch["champ"]
        documents = ch.get("documents", [])

        id_champ=get_first_id(Champ, id_ds=dossier_champ["id_ds"], nom=dossier_champ["nom_champ"])

        id_champ_type = Champ.objects.filter(id=id_champ).values_list("id_champ_type_id", flat=True).first()
        type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()



        if documents:
            for doc in documents:
                document_obj, doc_created = Document.objects.get_or_create(
                    emplacement=doc["emplacement"], titre=doc["titre"], id_nature_id=doc["id_nature"],
                    defaults={
                        "id_format_id": doc["id_format"],
                        "url_ds": doc["url_ds"], 
                        "description": doc["description"],
                    }
                )

                if doc_created:
                    logger.info(f"[CREATE] Document ({type_du_champ}) pour Champ {id_champ} du Dossier {id_dossier} créé.")
                    
                    write_pj(doc["emplacement"], doc["titre"], doc["url_ds"])

                champ_obj, created = DossierChamp.objects.get_or_create(
                    id_dossier_id=id_dossier,
                    id_champ_id=id_champ,
                    id_document_id=document_obj.id,
                    defaults={
                        "valeur": dossier_champ["valeur"],
                        "date_saisie": dossier_champ["date_saisie"],
                        "geometrie": dossier_champ.get("geometrie"),
                    }
                )

                if created:
                    logger.info(f"[CREATE] DossierChamp (champ: {id_champ}, dossier: {id_dossier}) créé.")

                    if dossier_champ.get("geometrie"):
                        call_write_geojson(id_dossier, dossier_champ)

                else:
                    updated_fields = update_fields(champ_obj, {
                        "valeur": dossier_champ["valeur"],
                        "date_saisie": dossier_champ["date_saisie"],
                        "geometrie": dossier_champ.get("geometrie"),
                    }, date_fields=["date_saisie"])

                    if updated_fields:
                        champ_obj.save()

                        if "geometrie" in updated_fields and dossier_champ.get("geometrie"):
                            call_write_geojson(id_dossier, dossier_champ)

                        logger.info(f"[SAVE] DossierChamp mis à jour (champ: {id_champ}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")
        else:
            champ_obj, created = DossierChamp.objects.get_or_create(
                id_dossier_id=id_dossier,
                id_champ_id=id_champ,
                defaults={
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                }
            )

            if created:
                logger.info(f"[CREATE] DossierChamp (champ: {id_champ}, dossier: {id_dossier}) créé.")

                if dossier_champ.get("geometrie"):
                    call_write_geojson(id_dossier, dossier_champ)

            else:
                updated_fields = update_fields(champ_obj, {
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                }, date_fields=["date_saisie"])

                if updated_fields:
                    champ_obj.save()

                    if "geometrie" in updated_fields and dossier_champ.get("geometrie"):
                        call_write_geojson(id_dossier, dossier_champ)

                    logger.info(f"[SAVE] DossierChamp mis à jour (champ: {id_champ}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")



def call_write_geojson(id_dossier, dossier_champ):
    try:
        dossier_obj = Dossier.objects.get(id=id_dossier)
        emplacement_dossier = dossier_obj.emplacement
        num_dossier = dossier_obj.numero
       
        write_geojson(f"{emplacement_dossier}/Carto", f"{num_dossier}.geojson",dossier_champ["geometrie"])

    except Dossier.DoesNotExist:
        logger.error(f"[ERREUR] Aucun dossier trouvé avec l'id {id_dossier} (Tentative de création du fichier {num_dossier}.geojson)")
        return