from autorisations.models.models_documents import Document, DossierDocument
from ..functions import update_fields
import logging

logger = logging.getLogger("ORM_DJANGO")

def sync_dossier_document(dossier_document, id_dossier):
    """
    Synchronise le document résumé d'un dossier (PDF).
    {
        "numero": str,
        "id_format": int,
        "id_nature": int,
        "url_ds": str,
        "emplacement": str,
        "description": str,
        "titre": str
    }
    """
    if not dossier_document:
        logger.warning(f"[WARNING] Le résumé PDF du Dossier {id_dossier} est non renseigné")
        return

    doc_obj, created = Document.objects.get_or_create(
        id_nature_id=dossier_document["id_nature"],
        numero=dossier_document["numero"],
        defaults={
            "id_format_id": dossier_document["id_format"],
            "url_ds": dossier_document["url_ds"],
            "description": dossier_document["description"],
            "titre": dossier_document["titre"],
            "emplacement": dossier_document["emplacement"],
        }
    )

    if created:
        logger.info(f"[CREATE] Document résumé PDF pour Dossier {id_dossier} créé.")
    else:
        updated_fields = update_fields(doc_obj, {
            "id_format_id": dossier_document["id_format"],
            "url_ds": dossier_document["url_ds"],
            "description": dossier_document["description"],
            "titre": dossier_document["titre"],
            "emplacement": dossier_document["emplacement"],
        })
        if updated_fields:
            doc_obj.save()
            logger.info(f"[SAVE] Document résumé PDF mis à jour (Dossier {id_dossier}). Champs modifiés : {', '.join(updated_fields)}.")

    link_obj, created = DossierDocument.objects.get_or_create(
        id_dossier_id=id_dossier,
        id_document_id=doc_obj.id
    )

    if created:
        logger.info(f"[CREATE] Lien DossierDocument créé pour Dossier {id_dossier} et Document {doc_obj.id}.")
