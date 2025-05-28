from autorisations.models.models_instruction import Dossier, DossierChamp, Champ, ChampType
from autorisations.models.models_documents import Document
from ..utils.model_helpers import get_first_id, update_fields
from ..utils.fichiers import write_geojson, write_pj
import logging

logger = logging.getLogger("ORM_DJANGO")

# def sync_dossier_champs(dossier_champs, id_dossier):
#     """
#     Synchronise les DossierChamps
    
#     {
#         "documents": [{"numero", "id_format", "id_nature", "url_ds", "emplacement", "description", "titre"}, ...],
#         "champ": {"nom_champ", "id_ds", "valeur", "date_saisie", "geometrie", "id_document"=None}
#     }
#     """

#     for ch in dossier_champs:
#         dossier_champ = ch["champ"]
#         documents = ch.get("documents", [])

#         id_champ=get_first_id(Champ, id_ds=dossier_champ["id_ds"], nom=dossier_champ["nom_champ"])

#         id_champ_type = Champ.objects.filter(id=id_champ).values_list("id_champ_type_id", flat=True).first()
#         type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()

#         if documents:
#             for doc in documents:
#                 document_obj, doc_created = Document.objects.get_or_create(
#                     emplacement=doc["emplacement"], titre=doc["titre"], id_nature_id=doc["id_nature"],
#                     defaults={
#                         "id_format_id": doc["id_format"],
#                         "url_ds": doc["url_ds"], 
#                         "description": doc["description"],
#                     }
#                 )

#                 #Document créé
#                 if doc_created:
#                     logger.info(f"[CREATE] Document ({type_du_champ}) pour Champ {id_champ} du Dossier {id_dossier} créé.")
#                     write_pj(doc["emplacement"], doc["titre"], doc["url_ds"])

#                 #Document déjà existant
#                 else :
              
#                     updated_fields = update_fields(document_obj, {
#                         "url_ds": doc["url_ds"], 
#                         "description": doc["description"],
#                     }, date_fields=["date_saisie"])

#                     if updated_fields:
#                         document_obj.save()
#                         logger.info(f"[SAVE] Document mis à jour (doc: {document_obj.id}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")

#                 champ_obj, created = DossierChamp.objects.get_or_create(
#                     id_dossier_id=id_dossier,
#                     id_champ_id=id_champ,
#                     defaults={
#                         "valeur": dossier_champ["valeur"],
#                         "date_saisie": dossier_champ["date_saisie"],
#                         "geometrie": dossier_champ.get("geometrie"),
#                         "id_document_id": document_obj.id,
#                     }
#                 )

#                 if created:
#                     logger.info(f"[CREATE] DossierChamp (champ: {id_champ}, dossier: {id_dossier}) créé.")


#                 else:
#                     updated_fields = update_fields(champ_obj, {
#                         "valeur": dossier_champ["valeur"],
#                         "date_saisie": dossier_champ["date_saisie"],
#                         "geometrie": dossier_champ.get("geometrie"),
#                     }, date_fields=["date_saisie"])

#                     if updated_fields:
#                         champ_obj.save()

#                         logger.info(f"[SAVE] DossierChamp mis à jour (champ: {id_champ}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")
#         else:
#             champ_obj, created = DossierChamp.objects.get_or_create(
#                 id_dossier_id=id_dossier,
#                 id_champ_id=id_champ,
#                 defaults={
#                     "valeur": dossier_champ["valeur"],
#                     "date_saisie": dossier_champ["date_saisie"],
#                     "geometrie": dossier_champ.get("geometrie"),
#                 }
#             )

#             if created:
#                 logger.info(f"[CREATE] DossierChamp (champ: {id_champ}, dossier: {id_dossier}) créé.")


#             else:
#                 updated_fields = update_fields(champ_obj, {
#                     "valeur": dossier_champ["valeur"],
#                     "date_saisie": dossier_champ["date_saisie"],
#                     "geometrie": dossier_champ.get("geometrie"),
#                 }, date_fields=["date_saisie"])

#                 if updated_fields:
#                     champ_obj.save()


#                     logger.info(f"[SAVE] DossierChamp mis à jour (champ: {id_champ}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")



def sync_dossier_champs(dossier_champs, id_dossier):
    """
    Synchronise les DossierChamps avec ou sans pièce jointe.
    """

    for ch in dossier_champs:
        dossier_champ = ch["champ"]
        documents = ch.get("documents", [])

        id_champ = get_first_id(Champ, id_ds=dossier_champ["id_ds"], nom=dossier_champ["nom_champ"])
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
                else:
                    updated_fields = update_fields(document_obj, {
                        "url_ds": doc["url_ds"],
                        "description": doc["description"],
                    })
                    if updated_fields:
                        document_obj.save()
                        logger.info(f"[SAVE] Document mis à jour (doc: {document_obj.id}, dossier: {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")

                # 🔄 Réutiliser un champ sans document si possible
                champ_obj = DossierChamp.objects.filter(
                    id_dossier_id=id_dossier,
                    id_champ_id=id_champ,
                    id_document__isnull=True
                ).order_by("id").first()

                if champ_obj:
                    updated_fields = update_fields(champ_obj, {
                        "valeur": dossier_champ["valeur"],
                        "date_saisie": dossier_champ["date_saisie"],
                        "geometrie": dossier_champ.get("geometrie"),
                        "id_document_id": document_obj.id,
                    }, date_fields=["date_saisie"])
                    if updated_fields:
                        champ_obj.save()
                        logger.info(f"[SAVE] DossierChamp (champ: {id_champ}, dossier: {id_dossier}) mis à jour avec PJ. Champs modifiés : {', '.join(updated_fields)}.")
                else:
                    champ_obj = DossierChamp.objects.create(
                        id_dossier_id=id_dossier,
                        id_champ_id=id_champ,
                        id_document_id=document_obj.id,
                        valeur=dossier_champ["valeur"],
                        date_saisie=dossier_champ["date_saisie"],
                        geometrie=dossier_champ.get("geometrie"),
                    )
                    logger.info(f"[CREATE] Nouveau DossierChamp (champ: {id_champ}, dossier: {id_dossier}) avec PJ.")
        else:
            # Pour les champs sans document
            champ_obj, created = DossierChamp.objects.get_or_create(
                id_dossier_id=id_dossier,
                id_champ_id=id_champ,
                id_document_id=None,
                defaults={
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                }
            )

            if created:
                logger.info(f"[CREATE] DossierChamp (champ: {id_champ}, dossier: {id_dossier}) sans PJ créé.")
            else:
                updated_fields = update_fields(champ_obj, {
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                }, date_fields=["date_saisie"])
                if updated_fields:
                    champ_obj.save()
                    logger.info(f"[SAVE] DossierChamp (champ: {id_champ}, dossier: {id_dossier}) sans PJ mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
