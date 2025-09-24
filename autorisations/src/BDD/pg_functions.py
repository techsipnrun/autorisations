import logging
import django
import os
from django.db import connection
import requests
from typing import List, Type, Tuple, Optional

from autorisations.models.models_instruction import Demarche
from autorisations.models.models_instruction import Message
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from django.utils import timezone


logger = logging.getLogger('ORM_DJANGO')


def get_number_demarche_Postgres():
    """
    Récupère tous les numéros des démarches enregistrées dans Postgres,
    associées à Démarches-Simplifiées via le champ `numero`.

    Returns:
        list[str]: Liste des numéros de démarches (DS) présents en base,
        ou liste vide en cas d’erreur.
    """
    try:
        # Récupère uniquement les champs nécessaires
        numeros = Demarche.objects.values_list("numero", flat=True)
        return list(numeros)
    except Exception as e:
        import logging
        logging.error(f"[GET] Erreur lors de la récupération des numéros de démarches : {e}")
        return []



def create_message_bdd(
    body, email_emetteur, dossier_obj, 
    date_envoi=None, 
    document_file=None,  # fichier ouvert, ou None
    document_title=None,  # titre affiché (nom d'origine)
    document_format_str=None,  # ex: 'pdf', 'jpg'
    document_nature_str="Pièce jointe message",
    document_description=None,
    id_ds=None,
    url_ds=None
):
    """
    Crée un message (et éventuellement une pièce jointe) dans la base de données.

    Args:
        body (str): Contenu textuel du message.
        email_emetteur (str): Email de l'expéditeur.
        dossier_obj (Dossier): Instance du dossier lié au message.
        date_envoi (datetime, optional): Date d’envoi du message. Utilise l’heure actuelle si None.
        document_file (UploadedFile, optional): Fichier joint (format Django), ou None.
        document_title (str, optional): Nom d’origine de la pièce jointe (ex: "photo.pdf").
        document_format_str (str, optional): Format du document (ex: "pdf", "jpg").
        document_nature_str (str, optional): Nature du document (défaut: "Pièce jointe message").
        document_description (str, optional): Description libre du document.
        id_ds (str, optional): ID du message sur Démarches Simplifiées (DS).
        url_ds (str, optional): URL publique vers la pièce jointe sur DS.

    Returns:
        Tuple[Message, Optional[Document]]: 
            Le message créé et, s’il y en a une, la pièce jointe associée.

    Raises:
        Exception: En cas d’erreur lors de la création du document ou du lien.
    """
    try:

        # 1. Création du message (sans pièce jointe pour l'instant)
        msg = Message.objects.create(
            body=body,
            date_envoi=date_envoi or timezone.now(),
            piece_jointe=bool(document_file),
            email_emetteur=email_emetteur,
            id_dossier=dossier_obj,
            lu=False,
            id_ds=id_ds
        )

        logger.info(f"[DOSSIER {dossier_obj.numero}] Message {id_ds} enregistré en BDD par {email_emetteur}")

        doc = None
        if document_file:

            try:

                # 2. Créer le Document
                # Récupérer ou créer le format et la nature
                doc_format, _ = DocumentFormat.objects.get_or_create(format=document_format_str)
                doc_nature, _ = DocumentNature.objects.get_or_create(nature=document_nature_str)

                # Répertoire cible
                repertoire_annexes = os.path.join(os.environ.get("ROOT_FOLDER"), dossier_obj.emplacement, "Annexes")
                os.makedirs(repertoire_annexes, exist_ok=True)

                # Séparation du nom et extension
                nom_base, ext = os.path.splitext(document_title)
                titre_final = nom_base
                i = 1

                # Boucle jusqu'à trouver un nom de fichier et d'enregistrement non existant
                while True:
                    emplacement = os.path.join(repertoire_annexes, f"{titre_final}{ext}")
                    rel_emplacement = os.path.join(dossier_obj.emplacement, "Annexes/")  # Pour la BDD

                    fichier_existe = os.path.exists(emplacement)
                    enregistrement_existe = Document.objects.filter(emplacement=rel_emplacement, titre=f"{titre_final}{ext}").exists()

                    if not fichier_existe and not enregistrement_existe:
                        break  # nom libre

                    i += 1
                    titre_final = f"{nom_base}_{i}"

                # Écriture du fichier sur disque
                with open(emplacement, 'wb+') as dest:
                    for chunk in document_file.chunks():
                        dest.write(chunk)

                # Création du document en base
                doc = Document.objects.create(
                    id_format=doc_format,
                    id_nature=doc_nature,
                    emplacement=rel_emplacement,
                    titre=f"{titre_final}{ext}",
                    description=document_description or "",
                    url_ds=url_ds,
                )

                logger.info(f"[DOSSIER {dossier_obj.numero}] Document {doc.id} ({document_nature_str}) créé")

                # 3. Créer le lien message-document
                MessageDocument.objects.create(
                    id_message=msg,
                    id_document=doc
                )


            except Exception as e_doc:
                logger.error(f"[DOSSIER {dossier_obj.numero}] Erreur lors de la création de la pièce jointe pour Message {msg.id} : {e_doc}")
                msg.delete()  # rollback du message si le document échoue
                raise Exception(f"Erreur lors de la création du document : {e_doc}")

        return msg, doc
    

    except Exception as e:
        logger.exception(f"[DOSSIER {dossier_obj.numero}] Échec de création du message")
        raise  # pour remonter l'erreur plus haut si besoin


