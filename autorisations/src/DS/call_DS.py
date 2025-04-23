from io import BytesIO
import json
import logging
import sys
import os
import django

from autorisations.models.models_instruction import Demarche
from DS.graphql_client import GraphQLClient


# Spécifie le fichier de logs
logger = logging.getLogger("API_DS")


def init_setup():
    '''
    Init Setup Django pour run le file dans le terminal
    '''

    CURRENT_DIR = os.path.dirname(__file__)
    SRC_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))  # src/
    
    sys.path.append(SRC_DIR)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "autorisations.settings")

    django.setup()



def get_number_demarche_Postgres():
    """
        Récupère sur Postgres le numéro 'Démarches-Simplifiées' de nos démarches
    """

    # Récupérer toutes les démarches avec leur numéro
    demarches = Demarche.objects.all().values('numero', 'titre')

    list_number_demarches = []

    # Affichage dans la console
    for d in demarches:
        list_number_demarches.append(d['numero'])

    return list_number_demarches





def recup_data_DS(number):
    '''
    Récupère les informations interessantes pour une démarche via l'API D-S

    Args:
        number : numéro de la démarche
    '''

    client = GraphQLClient()

    # Query graphQL
    query_file = "DS/queries/get_all.graphql"

    # Initialisation dictionnaire
    list_demarches_DS = []

 
    try:
        response = client.execute_query(query_file, {"number": number})
    except Exception as e:
        logger.error(f"Erreur : {e}")
    
    # list_demarches_DS.append(response["data"])
    # return list_demarches_DS

    # Ecriture Json pour check
    # output_file = "DS/response_ds.json"
    # with open(output_file, "w", encoding="utf-8") as f:
    #     json.dump(response["data"], f, ensure_ascii=False, indent=4)
    # print(f"Données enregistrées dans {output_file}")

    return response["data"]


import os
import json
import base64
import hashlib
import requests
import logging

from DS.graphql_client import GraphQLClient

logger = logging.getLogger("API_DS")

def envoyer_message_avec_pj(dossier_id, instructeur_id, chemin_fichier_original, content_type="application/pdf"):

    client = GraphQLClient()

    logger.info(f"[UPLOAD] Début d'envoi de pièce jointe pour dossier {dossier_id}, instructeur {instructeur_id}, fichier '{os.path.basename(chemin_fichier_original)}'")

    try:
        # 📥 Lire le contenu du fichier une seule fois
        with open(chemin_fichier_original, "rb") as f:
            file_data = f.read()

        byte_size = len(file_data)
        # checksum = base64.b64encode(hashlib.sha256(file_data).digest()).decode()
        checksum = base64.b64encode(hashlib.md5(file_data).digest()).decode()



        # MD5 pour vérifier contre l'ETag
        # md5 = hashlib.md5(file_data).hexdigest()
        # logger.info(f"[UPLOAD] MD5 local : {md5}")


        logger.info(f"[UPLOAD] Fichier {chemin_fichier_original} lu : {byte_size} octets, checksum SHA256 calculé")


        print("------ AVANT CREATE UPLOAD -------")
        print(f"byte_size = {byte_size}")
        print(f"checksum = {checksum}")

        # Étape 1 : CreateDirectUpload
        create_upload_vars = {
            "input": {
                "filename": os.path.basename(chemin_fichier_original),
                "byteSize": byte_size,
                "checksum": checksum,
                "contentType": content_type,
                "dossierId": dossier_id
            }
        }

        upload_response = client.execute_query("DS/mutations/create_direct_upload.graphql", create_upload_vars)

        print("------ REPONSE DU CREATE UPLOAD -------")
        print (upload_response)

        if "data" not in upload_response or "createDirectUpload" not in upload_response["data"]:
            logger.error(f"[UPLOAD] Réponse invalide de DS : {upload_response}")
            raise Exception("La mutation createDirectUpload a échoué. Clé 'data' manquante.")

        direct_upload = upload_response["data"]["createDirectUpload"]["directUpload"]
        signed_blob_id = direct_upload["signedBlobId"]

        logger.info("[UPLOAD] Mutation createDirectUpload réussie, blob signé reçu")

        # Étape 2 : Envoi PUT vers l’URL signée avec le même contenu
        upload_url = direct_upload["url"]
        upload_headers = json.loads(direct_upload["headers"])


        print("------ JUSTE AVANT LE PUT -------")
        print(f"headers : {upload_headers}")
        print(f"data : {file_data}")
        print(f"upload_url : {upload_url}")

    


        logger.debug("[UPLOAD] Envoi PUT vers DS")
        response = requests.put(upload_url, headers=upload_headers, data=BytesIO(file_data), stream=True)



        # Après le PUT réussi
        logger.info("[UPLOAD] Téléchargement du fichier uploadé pour recalculer SHA256")

        get_response = requests.get(upload_url)
        uploaded_file_data = get_response.content

        # Recalcule le SHA256 du fichier tel qu’il est chez D-S
        sha256_uploaded = base64.b64encode(hashlib.sha256(uploaded_file_data).digest()).decode()
        logger.info(f"[UPLOAD] SHA256 du fichier uploadé : {sha256_uploaded}")
        logger.info(f"[UPLOAD] SHA256 initial fourni : {checksum}")

        if sha256_uploaded == checksum:
            logger.info("[UPLOAD] Fichier uploadé conforme ✅")
        else:
            logger.error("[UPLOAD] Fichier altéré lors de l'upload ❌")




        if response.status_code not in [200, 201]:
            logger.error(f"[UPLOAD] Échec de l'upload : {response.status_code} - {response.text}")
            raise Exception(f"Échec de l'upload : {response.status_code} - {response.text}")

        logger.info(f"[UPLOAD] PUT réussi (code {response.status_code})")

        # Étape 3 : Envoyer le message avec l’attachment
        send_message_vars = {
            "input": {
                "dossierId": dossier_id,
                "instructeurId": instructeur_id,
                "body": "Message automatique avec PJ depuis Django",
                "attachment": signed_blob_id
            }
        }

        logger.info(f"[UPLOAD] Envoi mutation send_message avec PJ. Input : {send_message_vars}")
        result = client.execute_query("DS/mutations/send_message.graphql", send_message_vars)
        logger.info(f"[UPLOAD] Message envoyé avec PJ — réponse : {result}")

        return result

    except Exception as e:
        logger.exception(f"[UPLOAD] Erreur inattendue pendant l'envoi de pièce jointe pour dossier {dossier_id}")
        raise
