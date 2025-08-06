import requests
import time
from dotenv import load_dotenv
import os
import logging

loggerDM = logging.getLogger("API_DM")


# ==== Chargement des variables d'environnement ====
load_dotenv()
USERNAME = os.getenv("DM_USERNAME")
PASSWORD = os.getenv("DM_PASSWORD")
CLIENT_ID = os.getenv("DM_CLIENT_ID")
CLIENT_SECRET = os.getenv("DM_CLIENT_SECRET")
API_URL = os.getenv("DM_API_URL")


# ==== URLS ====
TOKEN_URL = f"{API_URL}o/token/"
AVIS_LIST_URL = f"{API_URL}api/Avis/"
AVIS_DETAIL_URL = f"{API_URL}" + "api/Avis/{}"
DOSSIER_DETAIL_URL = f"{API_URL}" + "api/Dossier/{}"
GEOJSON_URL = f"{API_URL}" + "api/Dossier/{}/carto_GeoJson/"
GPX_URL = f"{API_URL}" + "api/Dossier/{}/carto_GPX"


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
        loggerDM.error(f"[{response.status_code}] Erreur lors de la récupération du token : {response.text}")
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


