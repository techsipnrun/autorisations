from autorisations.models.models_instruction import DossierChamp, Champ, ChampType
from autorisations.models.models_documents import Document
from functions import update_fields, clean_date
import logging

logger = logging.getLogger("ORM_DJANGO")

def sync_dossier_champs(dossier_champs, id_dossier):
    for ch in dossier_champs:
        dossier_champ = ch["champ"]
        documents = ch.get("documents", [])

        id_champ_type = Champ.objects.filter(id=dossier_champ["id_champ"]).values_list("id_champ_type_id", flat=True).first()
        type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()

        if documents:
            for doc in documents:
                document_obj, doc_created = Document.objects.get_or_create(
                    url_ds=doc["url_ds"], id_nature_id=doc["id_nature"],
                    defaults={
                        "id_format_id": doc["id_format"],
                        "emplacement": doc["emplacement"],
                        "description": doc["description"],
                        "titre": doc["titre"],
                    }
                )

                if doc_created:
                    logger.info(f"[CREATE] Document ({type_du_champ}) pour Champ {dossier_champ['id_champ']} du Dossier {id_dossier} créé.")

                champ_obj, created = DossierChamp.objects.get_or_create(
                    id_dossier_id=id_dossier,
                    id_champ_id=dossier_champ["id_champ"],
                    id_document_id=document_obj.id,
                    defaults={
                        "valeur": dossier_champ["valeur"],
                        "date_saisie": dossier_champ["date_saisie"],
                        "geometrie": dossier_champ.get("geometrie"),
                    }
                )

                if created:
                    logger.info(f"[CREATE] DossierChamp (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}) créé.")
                else:
                    updated_fields = update_fields(champ_obj, {
                        "valeur": dossier_champ["valeur"],
                        "date_saisie": clean_date(dossier_champ["date_saisie"]),
                        "geometrie": dossier_champ.get("geometrie"),
                    }, date_fields=["date_saisie"])

                    if updated_fields:
                        champ_obj.save()
                        logger.info(f"[SAVE] DossierChamp mis à jour (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")
        else:
            champ_obj, created = DossierChamp.objects.get_or_create(
                id_dossier_id=id_dossier,
                id_champ_id=dossier_champ["id_champ"],
                defaults={
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                }
            )

            if created:
                logger.info(f"[CREATE] DossierChamp (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}) créé.")
            else:
                updated_fields = update_fields(champ_obj, {
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": clean_date(dossier_champ["date_saisie"]),
                    "geometrie": dossier_champ.get("geometrie"),
                }, date_fields=["date_saisie"])

                if updated_fields:
                    champ_obj.save()
                    logger.info(f"[SAVE] DossierChamp mis à jour (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")