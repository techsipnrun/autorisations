import requests
import time
from dotenv import load_dotenv
import os
import logging
import mimetypes
import smbclient

loggerDM = logging.getLogger("API_DM")

# ==== Chargement des variables d'environnement ====
load_dotenv(".env.dev")

USERNAME = os.getenv("DM_USERNAME")
PASSWORD = os.getenv("DM_PASSWORD")
CLIENT_ID = os.getenv("DM_CLIENT_ID")
CLIENT_SECRET = os.getenv("DM_CLIENT_SECRET")
API_URL = os.getenv("DM_API_URL_PREPROD")  # URL de prod car pas d'autres env de dispos pour le moment..


# ==== URLS ====
TOKEN_URL = f"{API_URL}o/token/"
AVIS_LIST_URL = f"{API_URL}api/Avis/"
AVIS_DETAIL_URL = f"{API_URL}" + "api/Avis/{}/"
DOSSIER_DETAIL_URL = f"{API_URL}" + "api/Dossier/{}/"
GEOJSON_URL = f"{API_URL}" + "api/Dossier/{}/carto_GeoJson/"
GPX_URL = f"{API_URL}" + "api/Dossier/{}/carto_GPX/"
PJ_AVIS_URL = f"{API_URL}" + "api/Avis/{}/liste_pj/"  #GET
PJ_DOSSIER_URL = f"{API_URL}" + "api/Dossier/{}/pieceJointe/"  #GET
FILE_URL = f"{API_URL}" + "{}"  #GET
RENDRE_AVIS_URL = f"{API_URL}" + "api/Avis/{}/rendre/"  #POST
AJOUTER_PJ_AVIS_URL = f"{API_URL}" + "api/Avis/{}/ajouter_pj/"  #POST


# Récupération de l'access token
def get_access_token():
    data = {
        "grant_type": "password",
        "username": USERNAME,
        "password": PASSWORD,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(TOKEN_URL, json=data, headers=headers)
    if response.status_code != 200:

        # Extraction d’un message clair
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                err = response.json()
                msg = err.get("error_description") or err.get("error") or err
            except Exception:
                msg = "Réponse JSON invalide"
        else:
            msg = (
                response.text[:200].replace("\n", " ") + "..."
                if response.text else "Aucune réponse renvoyée"
            )

        # loggerDM.error(f"[{response.status_code}] Erreur lors de la récupération du token : {response.text}")
        loggerDM.error(f"[{response.status_code}] Erreur lors de la récupération du token : {msg}")
        response.raise_for_status()
        
    loggerDM.info("")
    loggerDM.info("Token récupéré")
    return response.json()['access_token']


# Récupère tous les avis
def get_all_avis(token):
    headers = {"Authorization": f"Bearer {token}"}
    avis = []
    url = AVIS_LIST_URL

    while url:
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            loggerDM.error(f"[{response.status_code}] GET All Avis : {response.text}")
            response.raise_for_status()

        data = response.json()
        avis.extend(data['results'])
        url = data['next']
    return avis


# Récupère les infos d'un avis
def get_avis_by_id(token, avis_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = AVIS_DETAIL_URL.format(avis_id)
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        loggerDM.error(f"GET Avis {avis_id} : {response.text}")
        response.raise_for_status()

    return response.json()


# Récupère les infos d'un dossier
def get_dossier_by_id(token, manif_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = DOSSIER_DETAIL_URL.format(manif_id)
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        loggerDM.error(f"GET Dossier {manif_id} : {response.text}")
        response.raise_for_status()

    return response.json()


def get_geojson(token, dossier_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = GEOJSON_URL.format(dossier_id)
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        loggerDM.error(f"GET GEOJSON {dossier_id} : {response.text}")
        response.raise_for_status()

    return response.json()


# A VERIF
def _extract_error_message(response):
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            err = response.json()
            if isinstance(err, dict):
                return err.get("detail") or err.get("error_description") or err.get("error") or str(err)
            return str(err)
        except Exception:
            return "Réponse JSON invalide"
    return response.text[:300].replace("\n", " ") if response.text else "Aucune réponse renvoyée"


# A VERIF
def _check_response(response, contexte):
    if response.status_code != 200:
        msg = _extract_error_message(response)
        loggerDM.error(f"[{response.status_code}] {contexte} : {msg}")
        response.raise_for_status()



def get_pj_avis(token, avis_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = PJ_AVIS_URL.format(avis_id)

    response = requests.get(url, headers=headers)
    _check_response(response, f"GET PJ Avis {avis_id}")

    return response.json()



def get_pj_dossier(token, dossier_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = PJ_DOSSIER_URL.format(dossier_id)

    response = requests.get(url, headers=headers)
    _check_response(response, f"GET PJ Dossier {dossier_id}")

    return response.json()



def rendre_avis(token, avis_id, reponse_avis, prescriptions=""):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",}
    url = RENDRE_AVIS_URL.format(avis_id)

    # 0-None, 1-favorable, 2-défavorable, 3-non concerné
    payload = {
        "reponse_avis": reponse_avis,
        "prescriptions": prescriptions
    }

    response = requests.post(url, headers=headers, json=payload)
    _check_response(response, f"POST Rendre Avis {avis_id}")

    if response.content:
        try:
            return response.json()
        except Exception:
            return response.text

    return {"success": True}


def get_file(token, media_path):
    """
    media_path : ex "/media/974/.../fichier.pdf"
    ou URL complète contenant /media/
    """
    headers = {"Authorization": f"Bearer {token}"}

    if media_path.startswith("http"):
        media_path = media_path[media_path.index("/media/"):]

    url = f"{API_URL.rstrip('/')}{media_path}"

    response = requests.get(url, headers=headers, stream=True)
    _check_response(response, f"GET File {media_path}")

    return response.content


def ajouter_pj_avis(token, avis_id, id_document, file_path, demande_de_remonte_en_doc_officiel_b=False):
    """
    Upload d'une pièce jointe à un avis.
    """
    headers = {
        "Authorization": f"Bearer {token}",
    }
    url = AJOUTER_PJ_AVIS_URL.format(avis_id)

    if smbclient.path.exists(file_path):
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        data = {
            "demande_de_remonte_en_doc_officiel_b": str(demande_de_remonte_en_doc_officiel_b).lower(),
            "id": str(id_document),
        }

        with smbclient.open_file(file_path, "rb") as f:
            file = (os.path.basename(file_path), f, mime_type)
            files = {"fichier": file}

            response = requests.post(url, headers=headers, data=data, files=files)

        _check_response(response, f"POST Ajouter PJ Avis {avis_id}")

        if response.content:
            try:
                return response.json()
            except Exception:
                return response.text
    
    else:
        loggerDM(f"AJOUTER PJ AVIS {avis_id} : Échec fichier introuvable : {file_path}")

    return {"success": True}