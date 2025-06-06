from autorisations.models.models_documents import Document, MessageDocument
from autorisations.models.models_instruction import Message
from ..utils.model_helpers import update_fields
from ..utils.fichiers import write_pj
import logging

logger = logging.getLogger("SYNCHRONISATION")

def sync_messages(messages, id_dossier):
    """
    Synchronise les Messages, Message_Documents et Documents (pour les PJ)
    
    {
        'message':  {"id_ds", "body", "date_envoi", "piece_jointe", "email_emetteur"},
        'documents': {"id_format", "id_nature", "url_ds", "emplacement", "description", "titre"},
    }
    
    """
    for entry in messages:
        message_data = entry.get("message")
        docs = entry.get("documents", [])

        msg_obj, created = Message.objects.get_or_create(
            id_ds=message_data["id_ds"],
            id_dossier_id=id_dossier,
            defaults={
                "body": message_data["body"],
                "date_envoi": message_data["date_envoi"],
                "piece_jointe": message_data["piece_jointe"],
                "email_emetteur": message_data["email_emetteur"],
                "lu": False,
            }
        )

        if created:
            logger.info(f"[CREATE] Message {msg_obj.id_ds} pour Dossier {id_dossier} créé.")
        else:
            updated_fields = update_fields(msg_obj, {
                "body": message_data["body"],
                "date_envoi": message_data["date_envoi"],
                "piece_jointe": message_data["piece_jointe"],
                "email_emetteur": message_data["email_emetteur"],
            }, date_fields=["date_envoi"])

            if updated_fields:
                msg_obj.save()
                logger.info(f"[SAVE] Message {msg_obj.id_ds} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")

        if message_data["piece_jointe"]:
            for doc in docs:
                doc_obj, doc_created = Document.objects.get_or_create(
                    emplacement=doc["emplacement"], id_format_id=doc["id_format"], titre=doc["titre"],
                    defaults={
                        "url_ds": doc["url_ds"],
                        "description": doc["description"],
                        "id_nature_id": doc["id_nature"],
                    }
                )

                if doc_created:
                    logger.info(f"[CREATE] Document joint à Message {msg_obj.id_ds} créé.")

                    write_pj(doc["emplacement"], doc["titre"], doc["url_ds"])

                else:
                    updated_fields = update_fields(doc_obj, {"url_ds": doc["url_ds"], "id_nature_id": doc["id_nature"]})
                    if updated_fields and updated_fields != ['url_ds']: # url_ds est recalculée à chaque fois, on evite de surcharger les logs
                        doc_obj.save()
                        logger.info(f"[SAVE] Document {doc_obj.id} ({doc_obj.id_nature.nature}) mis à jour. Champs modifiés : {', '.join(updated_fields)}.")

                msg_doc_obj, link_created = MessageDocument.objects.get_or_create(
                    id_message_id=msg_obj.id,
                    id_document_id=doc_obj.id
                )

                if link_created:
                    logger.info(f"[CREATE] Lien MessageDocument créé (Message: {msg_obj.id}, Document: {doc_obj.id}).")
