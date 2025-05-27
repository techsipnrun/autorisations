from io import BytesIO
import json
import logging
import sys
import os
import django
import base64
import hashlib
import requests

from autorisations.models.models_instruction import Demarche, Dossier, Message
from DS.graphql_client import GraphQLClient
from autorisations.models.models_utilisateurs import GroupeinstructeurDemarche, Instructeur, Groupeinstructeur



# Spécifie le fichier de logs
loggerDS = logging.getLogger("API_DS")


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

        Returns:
            list: Liste des numéros de démarches
    """

    try:
        # Récupérer toutes les démarches avec leur numéro
        demarches = Demarche.objects.all().values('numero', 'titre')
    except Exception as e:
        loggerDS.error(f"Echec de la récupération des numéros des démarches : {e}")
    
    

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

    Returns:
        dict: Résultat de la requête GraphQL
    '''

    client = GraphQLClient()

    # Query graphQL
    query_file = "DS/queries/get_all.graphql"

    try:
        response = client.execute_query(query_file, {"number": number})
    except Exception as e:
        loggerDS.error(f"Erreur lors de l'exécution de la querie get_all.graphql : {e}")
    
    return response["data"]



def envoyer_message_avec_pj(dossier_id_ds, instructeur_id_ds, chemin_fichier_original, content_type="application/pdf", body=None, correction=False):
    '''
    Envoie un message avec une pièce jointe via l’API Démarches Simplifiées.

    Args:
        dossier_id (str): Identifiant DS du dossier concerné.
        instructeur_id (str): Identifiant DS de l'instructeur émetteur.
        chemin_fichier_original (str): Chemin local vers le fichier à envoyer.
        content_type (str, optional): Type MIME du fichier. Par défaut : "application/pdf".
        body (str, optional): Corps du message. Peut être None.

    Returns:
        dict: Résultat de la mutation GraphQL, avec succès ou message d’erreur.
    
    '''
    client = GraphQLClient()

    num_dossier_pg = Dossier.objects.filter(id_ds=dossier_id_ds).values_list("numero", flat=True).first()
    id_instructeur_pg = Instructeur.objects.filter(id_ds=instructeur_id_ds).values_list("id", flat=True).first()

    loggerDS.info(f"Début d'envoi de pièce jointe pour dossier {num_dossier_pg}, instructeur {instructeur_id_ds}, fichier '{os.path.basename(chemin_fichier_original)}'")

    try:
        # Lire le contenu du fichier
        with open(chemin_fichier_original, "rb") as f:
            file_data = f.read()

        byte_size = len(file_data)
        checksum = base64.b64encode(hashlib.md5(file_data).digest()).decode()

        # Étape 1 : CreateDirectUpload
        create_upload_vars = {
            "input": {
                "filename": os.path.basename(chemin_fichier_original),
                "byteSize": byte_size,
                "checksum": checksum,
                "contentType": content_type,
                "dossierId": dossier_id_ds
            }
        }

        upload_response = client.execute_query("DS/mutations/create_direct_upload.graphql", create_upload_vars)

        if "data" not in upload_response or "createDirectUpload" not in upload_response["data"]:

            loggerDS.error(f"[UPLOAD] Réponse invalide de DS lors du Create Upload (Message avec PJ - Dossier {num_dossier_pg}) : {upload_response}")
            raise Exception("La mutation createDirectUpload a échoué. Clé 'data' manquante.")

        direct_upload = upload_response["data"]["createDirectUpload"]["directUpload"]
        signed_blob_id = direct_upload["signedBlobId"]


        # Étape 2 : Envoi PUT vers l’URL signée avec le même contenu
        upload_url = direct_upload["url"]
        upload_headers = json.loads(direct_upload["headers"])

        response = requests.put(upload_url, headers=upload_headers, data=BytesIO(file_data), stream=True)

        if response.status_code not in [200, 201]:
            loggerDS.error(f"[UPLOAD] Échec de l'upload du fichier (message avec PJ pour le dossier {num_dossier_pg}): {response.status_code} - {response.text}")
            raise Exception(f"Échec de l'upload du fichier (message avec PJ pour le dossier {num_dossier_pg}): {response.status_code} - {response.text}")


        # Étape 3 : Envoyer le message avec l’attachment
        if not correction :
            send_message_vars = {
                "input": {
                    "dossierId": dossier_id_ds,
                    "instructeurId": instructeur_id_ds,
                    "body": body,
                    "attachment": signed_blob_id
                }
            }
        else : 
            send_message_vars = {
                "input": {
                    "dossierId": dossier_id_ds,
                    "instructeurId": instructeur_id_ds,
                    "body": body,
                    "attachment": signed_blob_id,
                    "correction": 'incomplete'
                }
            }



        result = client.execute_query("DS/mutations/send_message.graphql", send_message_vars)

        if result["data"]["dossierEnvoyerMessage"]['errors'] :
            loggerDS.info(f"Erreur : Message avec PJ (Dossier {num_dossier_pg}) pas envoyé : {result["data"]["dossierEnvoyerMessage"]['errors']}")
        else :
            loggerDS.info(f"Message envoyé avec PJ — réponse : {result["data"]["dossierEnvoyerMessage"]["message"]}")
        return result
    

    except Exception as e:
        loggerDS.exception(f"Erreur inattendue pendant l'envoi de pièce jointe pour le Dossier {num_dossier_pg}")
        raise



def suppr_msg_DS(msg):
    """
    Supprime un message via l’API Démarches Simplifiées.

    Args:
        msg (Message): Instance du message à supprimer. Doit contenir `email_emetteur` et `id_ds`.

    Returns:
        dict: Résultat de la mutation GraphQL, avec 'success' (bool) et 'message' (str).
    """

    client = GraphQLClient()

    # Récupérer l'instructeur à partir de l'email de l'émetteur du message
    instructeur = Instructeur.objects.filter(email=msg.email_emetteur).first()
    if not instructeur or not instructeur.id_ds:
        raise Exception(f"Instructeur introuvable pour l'email {msg.email_emetteur}")

    instru_id = instructeur.id_ds  # ID DS de l'instructeur

    delete_message_vars = {
        "input": {
            "instructeurId": instru_id,
            "messageId": msg.id_ds
        }
    }

    # Envoie de la requête GraphQL
    result = client.execute_query("DS/mutations/delete_message.graphql", delete_message_vars)

    # Vérification des erreurs possibles
    if result["data"]["dossierSupprimerMessage"]["errors"]:
        erreurs = "; ".join(err['message'] for err in result['errors'])
        loggerDS.error(f"Erreur suppression du message {msg.id} (Dossier {msg.id_dossier.numero}) sur D-S : {erreurs}")
        raise Exception(f"Erreur suppression message (Dossier {msg.id_dossier.numero}) sur D-S : {erreurs}")
    else:
        loggerDS.info(f"Message {msg.id} supprimé avec succès (Dossier {msg.id_dossier.numero})")
        return {"success": True, "message": f"Message {msg.id} supprimé avec succès (Dossier {msg.id_dossier.numero})"}
    


def get_msg_DS(num_doss, message_id_ds):
    """
    Récupère l'URL de la pièce jointe associée à un message dans un dossier D-S.

    Args:
        num_doss (int): Numéro du dossier.
        msg_id (str): ID D-S du message à retrouver.

    Returns:
        str or None: URL de la pièce jointe si trouvée, sinon None.
    """
      
    client = GraphQLClient()

    var = {
        "number": num_doss
    }

    try:

        result = client.execute_query("DS/queries/get_message.graphql", var)
        

        if result.get("data") :
            if result["data"]["dossier"]["messages"] :

                for m in result["data"]["dossier"]["messages"]:
                    if m["id"] == message_id_ds :

                        if m["attachments"] :
                            return m["attachments"][0]["url"]
                        else:
                            loggerDS.warning(f"Message {message_id_ds} (Dossier {num_doss}) trouvé mais sans pièce jointe.")
                            return None
                        
                loggerDS.warning(f"Aucun message avec l'ID {message_id_ds} trouvé pour le dossier {num_doss}.")
                return None
        else :
            loggerDS.error(f"Erreur : Envoie Message avec PJ --> Echec de récupération de l'url de la PJ (dossier {num_doss}) : {result.get('errors')[0].get('message')} ")
    
    except Exception as e:
        loggerDS.error(f"Erreur lors de la récupération du message {message_id_ds} pour le dossier {num_doss} : {e}")
        return None


def change_groupe_instructeur_ds(dossier_id, groupe_instructeur_id):
    """
    Envoie une mutation GraphQL pour modifier le groupe instructeur associé à un dossier.

    Args:
        dossier_id (str): Identifiant DS du dossier concerné (ex: "RG9zc2llci0yMzY3ODI3NA==").
        groupe_instructeur_id (str): Identifiant DS du groupe instructeur à assigner (ex: "R3JvdXBlSW5zdHJ1Y3RldXItMjg0MjI4").

    Returns:
        dict: Dictionnaire contenant :
            - 'success' (bool) : True si la mutation a réussi, False sinon.
            - 'message' (str)  : Message d'information ou d'erreur.
    """

    # Récupération des IDs sur Postgres
    num_dossier_pg = Dossier.objects.filter(id_ds=dossier_id).values_list("numero", flat=True).first()
    id_groupe_pg = GroupeinstructeurDemarche.objects.filter(id_groupeinstructeur_ds=groupe_instructeur_id).values_list("id_groupeinstructeur_id", flat=True).first()

    nom_groupe = Groupeinstructeur.objects.filter(id=id_groupe_pg).values_list("nom", flat=True).first()
    loggerDS.info(f"Tentative de changement du groupe instructeur pour le dossier {num_dossier_pg} vers {nom_groupe}")

    try:
        client = GraphQLClient()

        query_path = "DS/mutations/change_groupe_instructeur.graphql"
        variables = {
            "input": {
                "dossierId": dossier_id,
                "groupeInstructeurId": groupe_instructeur_id
            }
        }

        result = client.execute_query(query_path, variables)

        if not result:
            loggerDS.error(f"Réponse vide du serveur lors de la mutation change_groupe_instructeur.graphql (Dossier {num_dossier_pg})")
            return {"success": False, "message": "Réponse vide du serveur."}

        if "errors" in result:
            loggerDS.error(f"Erreur lors de la mutation change_groupe_instructeur.graphql (Dossier {num_dossier_pg}) : {result['errors']}")
            return {"success": False, "message": result["errors"]}

        response_data = result.get("data", {}).get("dossierChangerGroupeInstructeur", {})
        if response_data:
            loggerDS.info(f"Groupe instructeur changé avec succès pour le dossier {num_dossier_pg}")
            return {"success": True, "message": response_data.get("message", "OK")}

        loggerDS.warning(f"Mutation change_groupe_instructeur.graphql (Dossier {num_dossier_pg}) réussie mais réponse inattendue.")
        return {"success": False, "message": "Réponse inattendue de la mutation."}

    except Exception as e:
        loggerDS.exception(f"Erreur dans la mutation change_groupe_instructeur.graphql (Dossier {num_dossier_pg}) : {e}")
        return {"success": False, "message": str(e)}



def passer_en_instruction_ds(dossier_id_ds, instructeur_id_ds):
    """
    Passe un dossier en instruction via l’API DS.

    Args:
        dossier_id_ds (str): ID du dossier D-S.
        instructeur_id_ds (str): ID de l’instructeur D-S.

    Returns:
        dict: Résultat de la mutation avec 'success' et 'message'.
    """
    client = GraphQLClient()

    num_dossier_pg = Dossier.objects.filter(id_ds=dossier_id_ds).values_list("numero", flat=True).first()
    email_instructeur = Instructeur.objects.filter(id_ds=instructeur_id_ds).values_list("email", flat=True).first()

    loggerDS.info(f"Tentative de passage en instruction du dossier {num_dossier_pg} par {email_instructeur}")

    try:
        variables = {
            "input": {
                "dossierId": dossier_id_ds,
                "instructeurId": instructeur_id_ds
            }
        }

        result = client.execute_query("DS/mutations/passer_en_instruction.graphql", variables)

        if not result or "data" not in result:
            loggerDS.error(f"[DS] Réponse vide lors du passage en instruction du dossier {num_dossier_pg}")
            return {"success": False, "message": "Réponse vide ou invalide."}

        response_data = result["data"]["dossierPasserEnInstruction"]
        if response_data and not response_data['errors']:
            loggerDS.info(f"[DS] Passage en instruction réussi pour le dossier {num_dossier_pg}")
            return {"success": True, "message": response_data.get("message", "OK")}
        else:
            erreurs = response_data.get("errors", [])
            msg = "; ".join([err["message"] for err in erreurs]) if erreurs else "Erreur inconnue"
            loggerDS.warning(f"[DS] Passage en instruction échoué pour le dossier {num_dossier_pg} : {msg}")
            return {"success": False, "message": msg}

    except Exception as e:
        loggerDS.exception(f"[DS] Exception lors du passage en instruction du dossier {num_dossier_pg}")
        return {"success": False, "message": str(e)}



def classer_sans_suite_ds(dossier_id_ds, instructeur_id_ds, motivation):
    """
    Classe un dossier comme "sans suite" via l'API Démarches Simplifiées.

    Args:
        dossier_id_ds (str): ID du dossier D-S.
        instructeur_id_ds (str): ID de l'instructeur D-S.
        motivation (str): Justification du 'classement sans suite'

    Returns:
        dict: Résultat de la mutation avec 'success' et 'message'.
    """
    client = GraphQLClient()

    num_dossier_pg = Dossier.objects.filter(id_ds=dossier_id_ds).values_list("numero", flat=True).first()
    loggerDS.info(f"Tentative de classement sans suite du dossier {num_dossier_pg} via DS")

    try:
        variables = {
            "input": {
                "dossierId": dossier_id_ds,
                "instructeurId": instructeur_id_ds,
                "motivation": motivation
            }
        }

        result = client.execute_query("DS/mutations/classer_sans_suite.graphql", variables)

        response_data = result.get("data", {}).get("dossierClasserSansSuite", {})

        if not response_data or response_data.get("errors"):
            erreurs = "; ".join([err.get("message", "Erreur inconnue") for err in response_data.get("errors", [])])
            loggerDS.warning(f"[DS] Classement sans suite échoué pour dossier {num_dossier_pg} : {erreurs}")
            return {"success": False, "message": erreurs}

        loggerDS.info(f"[DS] Classement sans suite réussi pour le dossier {num_dossier_pg}")
        return {"success": True, "message": response_data.get("message", "OK")}

    except Exception as e:
        loggerDS.exception(f"[DS] Exception lors du classement sans suite du dossier {num_dossier_pg}")
        return {"success": False, "message": str(e)}




def refuser_dossier_ds(dossier_id_ds, instructeur_id_ds, motivation):
    """
    Refuse un dossier via l'API Démarches Simplifiées.

    Args:
        dossier_id_ds (str): ID du dossier D-S.
        instructeur_id_ds (str): ID de l'instructeur D-S.
        motivation (str): Justification du refus

    Returns:
        dict: Résultat de la mutation avec 'success' et 'message'.
    """
    client = GraphQLClient()

    num_dossier_pg = Dossier.objects.filter(id_ds=dossier_id_ds).values_list("numero", flat=True).first()
    loggerDS.info(f"Tentative de refus du dossier {num_dossier_pg} via DS")

    try:
        variables = {
            "input": {
                "dossierId": dossier_id_ds,
                "instructeurId": instructeur_id_ds,
                "motivation": motivation
            }
        }

        result = client.execute_query("DS/mutations/refuser_dossier.graphql", variables)

        response_data = result.get("data", {}).get("dossierRefuser", {})

        if not response_data or response_data.get("errors"):
            erreurs = "; ".join([err.get("message", "Erreur inconnue") for err in response_data.get("errors", [])])
            loggerDS.warning(f"[DS] Refus échoué pour dossier {num_dossier_pg} : {erreurs}")
            return {"success": False, "message": erreurs}

        loggerDS.info(f"[DS] Refus réussi pour le dossier {num_dossier_pg}")
        return {"success": True, "message": response_data.get("message", "OK")}

    except Exception as e:
        loggerDS.exception(f"[DS] Exception lors du refus du dossier {num_dossier_pg}")
        return {"success": False, "message": str(e)}


def repasser_en_instruction_ds(dossier_id_ds, instructeur_id_ds):
    """
    Rebascule un dossier en instruction via l'API Démarches Simplifiées.

    Args:
        dossier_id_ds (str): ID du dossier D-S.
        instructeur_id_ds (str): ID de l'instructeur D-S.

    Returns:
        dict: Résultat de la mutation avec 'success' et 'message'.
    """
    client = GraphQLClient()

    num_dossier_pg = Dossier.objects.filter(id_ds=dossier_id_ds).values_list("numero", flat=True).first()
    loggerDS.info(f"Tentative de rebasculer en instruction le dossier {num_dossier_pg} via DS")

    try:
        variables = {
            "input": {
                "dossierId": dossier_id_ds,
                "instructeurId": instructeur_id_ds
            }
        }

        result = client.execute_query("DS/mutations/repasser_en_instruction.graphql", variables)

        print(result)
        response_data = result.get("data", {}).get("dossierRepasserEnInstruction", {})

        if not response_data or response_data.get("errors"):
            erreurs = "; ".join([err.get("message", "Erreur inconnue") for err in response_data.get("errors", [])])
            loggerDS.warning(f"[DS] Repassage échoué pour dossier {num_dossier_pg} : {erreurs}")
            return {"success": False, "message": erreurs}

        loggerDS.info(f"[DS] Repassage en instruction réussi pour le dossier {num_dossier_pg}")
        return {"success": True, "message": response_data.get("message", "OK")}

    except Exception as e:
        loggerDS.exception(f"[DS] Exception lors du repassage en instruction du dossier {num_dossier_pg}")
        return {"success": False, "message": str(e)}

