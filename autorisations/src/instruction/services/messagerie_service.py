# messagerie_service.py

import logging
import tempfile
import os
import hashlib
import base64

from django.core.files.uploadedfile import SimpleUploadedFile
from DS.graphql_client import GraphQLClient
from DS.call_DS import envoyer_message_avec_pj as ds_envoyer_message_avec_pj
from BDD.pg_functions import create_message_bdd

logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  

def prepare_temp_file(fichier):
    # fichier.seek(0)
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(fichier.name)[1]) as tmp_file:
        tmp_file.write(fichier.read())
        tmp_file_path = tmp_file.name
    return tmp_file_path

def envoyer_message_ds(dossier_id_ds, instructeur_id_ds, body, fichier=None, content_type=None, chemin_fichier=None, num_dossier=None):

    client = GraphQLClient()

    if fichier and chemin_fichier:
        loggerDS.info(f"Tentative envoi message AVEC pièce jointe pour dossier {num_dossier}")
        print(f"params : ")
        print(f"dossier_id_ds = {dossier_id_ds}, instructeur_id = {instructeur_id_ds}, chemin_fichier_original = {chemin_fichier}, content_type = {content_type}")
        return ds_envoyer_message_avec_pj(
            dossier_id=dossier_id_ds,
            instructeur_id=instructeur_id_ds,
            chemin_fichier_original=chemin_fichier,
            content_type=content_type
        )
    else:
        loggerDS.info(f"Tentative envoi message SANS pièce jointe pour dossier {num_dossier}")
        variables = {
            "input": {
                "dossierId": dossier_id_ds,
                "instructeurId": instructeur_id_ds,
                "body": body
            }
        }
        return client.execute_query("DS/mutations/send_message.graphql", variables)

def enregistrer_message_bdd(dossier, user_email, body, fichier=None, id_ds=None):
    from django.utils import timezone
    if fichier:
        fichier_bdd = SimpleUploadedFile(
            name=fichier.name,
            content=fichier.read(),
            content_type=fichier.content_type
        )
        create_message_bdd(
            body=body,
            email_emetteur=user_email,
            dossier_obj=dossier,
            date_envoi=timezone.now(),
            document_file=fichier_bdd,
            document_title=fichier.name,
            document_format_str=fichier.name.split('.')[-1].lower(),
            id_ds=id_ds
        )
    else:
        create_message_bdd(
            body=body,
            email_emetteur=user_email,
            dossier_obj=dossier,
            date_envoi=timezone.now(),
            id_ds=id_ds
        )
