import logging
import tempfile
import os
from django.http import HttpResponse
from django.utils import timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from DS.graphql_client import GraphQLClient
from DS.call_DS import envoyer_message_avec_pj as ds_envoyer_message_avec_pj
from BDD.pg_functions import create_message_bdd
from autorisations.models.models_utilisateurs import Instructeur


logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  
loggerFiles = logging.getLogger("APP")


def prepare_temp_file(fichier):
    """
    Sauvegarde un fichier Django temporairement sur disque local et retourne le chemin.
    Sert pour un traitement intermédiaire avant écriture sur NAS.
    """
    try:
        ext = os.path.splitext(fichier.name)[1] if fichier.name else ''
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            tmp_file.write(fichier.read())
            return tmp_file.name
    except Exception as e:
        loggerFiles.error(f"[TEMPFILE] Échec de création du fichier temporaire pour '{getattr(fichier, 'name', 'fichier inconnu')}' : {e}")
        return None


def envoyer_message_ds(dossier_id_ds, instructeur, body, fichier=None, content_type=None, chemin_fichier=None, num_dossier=None, correction=False):
    """
    Envoie un message via l’API Démarches Simplifiées, avec ou sans pièce jointe.
    """
    email_instructeur = instructeur.email
    
    client = GraphQLClient()

    if not all([dossier_id_ds, email_instructeur, body]):
        loggerDS.error(
            f"[DOSSIER {num_dossier}] Paramètres manquants pour l'envoi du message : "
            f"dossier_id_ds={dossier_id_ds}, email_instructeur={email_instructeur}, body présent --> {bool(body)}"
        )
        return {"success": False, "message": "Paramètres requis manquants."}

    if fichier and chemin_fichier:
        loggerDS.info(f"[DOSSIER {num_dossier}] Tentative envoi du message avec PJ par {email_instructeur}")

        try:
            if not correction :
                return ds_envoyer_message_avec_pj(
                    dossier_id_ds=dossier_id_ds,
                    instructeur=instructeur,
                    chemin_fichier_original=chemin_fichier,
                    content_type=content_type,
                    body=body,
                )
            
            else:
                return ds_envoyer_message_avec_pj(
                    dossier_id_ds=dossier_id_ds,
                    instructeur=instructeur,
                    chemin_fichier_original=chemin_fichier,
                    content_type=content_type,
                    body=body,
                    correction=True
                )
            
        except Exception as e:
            loggerDS.error (f"[DOSSIER {num_dossier}] Échec envoi message avec PJ sur DS : {e}")
            raise

    else:
        loggerDS.info(f"[DOSSIER {num_dossier}] Tentative d'envoi du message sans PJ par {email_instructeur}")

        if not correction :
            variables = {
                "input": {
                    "dossierId": dossier_id_ds,
                    "instructeurId": os.getenv("ID_DS_BOITE_AUTO"),
                    "body": body
                }
            }
        else:
            variables = {
                "input": {
                    "dossierId": dossier_id_ds,
                    "instructeurId": os.getenv("ID_DS_BOITE_AUTO"),
                    "body": body,
                    "correction": 'incomplete'
                }
            }


        try:
            result = client.execute_query("DS/mutations/send_message.graphql", variables)
            
            if not result["data"] and result["errors"] :
                loggerDS.error(f"[DOSSIER {num_dossier}] Échec envoi message sans PJ sur DS : {result['errors']}")
                return {"success": False, "message": "Échec envoi message sans PJ."}
    
            return result
        
        except Exception as e:
            loggerDS.error (f"[DOSSIER {num_dossier}] Échec envoi message sans PJ sur DS : {e}")
            raise


def enregistrer_message_bdd(dossier, user_email, body, fichier=None, id_ds=None, url_ds = None):
    """
    Enregistre un message en base PostgreSQL (avec pièce jointe éventuelle).
    
    Returns:
        Tuple: (Message, Document or None)
    """

    if fichier:
        fichier.seek(0)
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
            document_description=f"Pièce jointe instructeur dans la messagerie du dossier {dossier.numero}",
            id_ds=id_ds,
            url_ds=url_ds,
        )
    else:
        create_message_bdd(
            body=body,
            email_emetteur=user_email,
            dossier_obj=dossier,
            date_envoi=timezone.now(),
            id_ds=id_ds
        )
