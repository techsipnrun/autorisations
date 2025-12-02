from datetime import date
import os
from autorisations.models.models_documents import Document, MessageDocument
from autorisations.models.models_instruction import Dossier, Message
from autorisations.models.models_utilisateurs import EmailOutbox
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from ..utils.model_helpers import update_fields
from ..utils.fichiers import write_pj
import logging
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger("SYNCHRONISATION")

def sync_messages(messages, id_dossier):
    """
    Synchronise les Messages, Message_Documents et Documents (pour les PJ)
    
    {
        'message':  {"id_ds", "body", "date_envoi", "piece_jointe", "email_emetteur"},
        'documents': {"id_format", "id_nature", "url_ds", "emplacement", "description", "titre"},
    }
    
    """

    nb_nouv_msg = 0
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
            if message_data["email_emetteur"] == 'contact@demarches-simplifiees.fr' or message_data["email_emetteur"] == 'contact@demarche.numerique.gouv.fr' or 'reunion-parcnational.fr' in message_data["email_emetteur"] :
                lu = True
            else :
                lu = False
                nb_nouv_msg += 1
                   
        else:
            updated_fields = update_fields(msg_obj, {
                "body": message_data["body"],
                "date_envoi": message_data["date_envoi"],
                "piece_jointe": message_data["piece_jointe"],
                #si email_emetteur existe deja et != autorisations@reunion-parcnational.fr  alors on ecrase pas (sinon louis devient auto par ex...)
                # "email_emetteur": message_data["email_emetteur"],  
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


    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    # Notifier les instructeurs
    if nb_nouv_msg > 0 :
        dossier = Dossier.objects.filter(id=id_dossier).first()
        if dossier :
            # si etape dossier != A affecter
                # emails_norm = list(DossierInstructeur.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur__email", flat=True))
            # sinon
                # si mission scientifique
                    # emails_norm = liste des emails de Receptionneurs SPPN
                # sinon
                    # emails_norm = liste des emails de Receptionneurs SAADD


            emails_norm = ["louis.calu@reunion-parcnational.fr"]
            if nb_nouv_msg == 1 :
                sujet = f"Dossier {dossier.numero} - {nb_nouv_msg} nouveau message du pétitionnaire"
            else :
                sujet = f"Dossier {dossier.numero} - {nb_nouv_msg} nouveaux messages du pétitionnaire"

            context = {
                "dossier_numero": dossier.numero,
                "demarche_type": dossier.id_demarche.type,
                "nb_nouv_msg": nb_nouv_msg,
                "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
            }
            template_name = "nouveau_message_petitionnaire"
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

            # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
            existe_deja = EmailOutbox.objects.filter(
                dedupe_key=dedupe,
                date_creation__gte= timezone.now() - timedelta(hours=2)
            ).exists()

            if not existe_deja:
                outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Notification")

                if outbox :
                    ok, err = envoi_mail(outbox.id)
                else :
                    logger.error(f"[DOSSIER {dossier.numero}] Nouveau.x message.s : Erreur lors de la création de l'EmailOutbox, pas de notification pour {', '.join(outbox.to)}")
                    
                if ok:
                    logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Nouveau.x message.s) envoyée à {', '.join(outbox.to)} ")
                else:
                    logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Nouveau.x message.s) à {', '.join(outbox.to)} : {err}")
