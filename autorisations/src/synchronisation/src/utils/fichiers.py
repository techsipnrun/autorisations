import json
import logging
import os
from typing import Optional

import requests

from synchronisation.src.utils.conversion import formater_nom_personne_morale, parse_datetime_with_tz


loggerORM = logging.getLogger("ORM_DJANGO")
loggerFile = logging.getLogger("APP")
loggerDS = logging.getLogger("API_DS")

# Vérification de la présence de ROOT_FOLDER
if not os.environ.get("ROOT_FOLDER"):
    raise RuntimeError("La variable d'environnement ROOT_FOLDER est requise.")


def ensure_dossier_root(emplacement: str) -> Optional[str]:
    """
    Crée le dossier racine basé sur la variable d’environnement ROOT_FOLDER et retourne son chemin complet.

    Args:
        emplacement (str): Chemin relatif à la racine ROOT_FOLDER.

    Returns:
        Optional[str]: Chemin absolu du dossier créé ou existant, ou None si ROOT_FOLDER est manquant.
    """
    racine = os.environ.get("ROOT_FOLDER")

    if not racine:
        loggerFile.error("[ROOT] Variable ROOT_FOLDER manquante.")
        return None
    
    chemin = os.path.join(racine, emplacement)
    os.makedirs(chemin, exist_ok=True)
    return chemin



def write_resume_pdf(emplacement, name, url_du_pdf):
    """
    Télécharge un PDF depuis une URL et l’enregistre localement dans le dossier spécifié.

    Args:
        emplacement (str): Chemin relatif à ROOT_FOLDER.
        name (str): Nom du fichier PDF (avec extension).
        url_du_pdf (str): URL publique du fichier PDF à télécharger.

    Returns:
        Optional[str]: Chemin absolu du fichier créé, ou None en cas d’échec.
    """
    chemin_fichier = ensure_dossier_root(emplacement)
    chemin_complet = os.path.join(chemin_fichier, name)

    try:

        response = requests.get(url_du_pdf, timeout=15)
        response.raise_for_status()

        with open(chemin_complet, "wb") as f:
            f.write(response.content)

        # loggerFile.info(f"RÉSUMÉ PDF téléchargé et écrit : {name}")

    except requests.exceptions.RequestException as e:
        loggerFile.error(f"[ERREUR] Impossible de télécharger le RÉSUMÉ PDF : {e}")
    except Exception as e:
        loggerFile.error(f"[ERREUR] Impossible d’écrire le RÉSUMÉ PDF {chemin_complet} : {e}")

    return chemin_complet



def write_geojson(emplacement, nom_geojson, contenu_geojson):
    """
    Écrit un fichier GeoJSON (.geojson) dans un dossier spécifique. Le fichier est écrasé s’il existe.

    Args:
        emplacement (str): Chemin relatif à ROOT_FOLDER.
        nom_geojson (str): Nom du fichier GeoJSON.
        contenu_geojson (dict): Données au format dict ou JSON serialisable.

    Returns:
        Optional[str]: Chemin absolu du fichier écrit, ou None en cas d’échec.
    """
    chemin_fichier = ensure_dossier_root(emplacement)
    chemin_complet = os.path.join(chemin_fichier, nom_geojson)

    try:
        with open(chemin_complet, "w", encoding="utf-8") as f:
            json.dump(contenu_geojson, f, ensure_ascii=False, indent=2)
            
        loggerFile.info(f"[GEOJSON] Fichier écrit : {nom_geojson}")
    except Exception as e:
        loggerFile.error(f"[ERREUR] Impossible d’écrire le fichier GeoJSON {chemin_complet} : {e}")

    return chemin_fichier



def write_pj(emplacement, name, url_pj):
    """
    Télécharge une pièce jointe depuis une URL et l’enregistre dans le dossier demandé.

    Args:
        emplacement (str): Chemin relatif à ROOT_FOLDER (ex: "Activites/2025/123456_NOM/Annexes/").
        name (str): Nom du fichier avec extension (ex: "photo.jpg").
        url_pj (str): URL publique de la pièce jointe à télécharger.

    Returns:
        Optional[str]: Chemin absolu du fichier enregistré, ou None si le fichier existe déjà ou en cas d’erreur.
    """
    chemin_dossier = ensure_dossier_root(emplacement)

    safe_name = os.path.basename(name)
    chemin_fichier = os.path.join(chemin_dossier, safe_name)

    try:
        if os.path.exists(chemin_fichier):
            loggerFile.error(f"[FICHIER EXISTANT] La pièce jointe {chemin_fichier} existe déjà. Aucun téléchargement effectué.")
            return

        response = requests.get(url_pj, timeout=15)
        response.raise_for_status()

        with open(chemin_fichier, "wb") as f:
            f.write(response.content)

        loggerFile.info(f"[PJ] Pièce jointe téléchargée et écrite : {chemin_fichier}")
    except requests.exceptions.RequestException as e:
        loggerFile.error(f"[HTTP ERROR] Impossible de télécharger la pièce jointe ({name}) : {e}")
    except Exception as e:
        loggerFile.error(f"[FILE ERROR] Impossible d’écrire la pièce jointe {chemin_fichier} : {e}")
    
    return chemin_fichier




def create_emplacement(emplacement_dossier):
    """
    Crée un dossier principal et les sous-dossiers standards s’il n’existe pas déjà.

    Args:
        emplacement_dossier (str): Chemin relatif à ROOT_FOLDER (ex: "Travaux/2025/123456_DUPONT_Jean").

    Returns:
        bool: True si les dossiers ont été créés ou existent déjà, False en cas d’erreur.
    """
    chemin_complet = ensure_dossier_root(emplacement_dossier)

    try:
        if not os.path.exists(chemin_complet):
            os.makedirs(chemin_complet)
            loggerFile.info(f"[INFO] Dossier principal créé : {chemin_complet}")
        else:
            loggerFile.info(f"[INFO] Dossier déjà existant : {chemin_complet}")

        # Sous-dossiers standards
        sous_dossiers = ["Annexes", "Actes", "Avis", "Carto", "Work"]
        for nom in sous_dossiers:
            chemin_sous_dossier = os.path.join(chemin_complet, nom)

            if not os.path.exists(chemin_sous_dossier):
                os.makedirs(chemin_sous_dossier)
                loggerFile.info(f"    → Création : {chemin_sous_dossier}")
            else:
                loggerFile.info(f"    → Déjà présent : {chemin_sous_dossier}")
        return True
    
    except Exception as e:
        loggerFile.error(f"Impossible de créer les sous-dossiers pour {emplacement_dossier} : {e}")
        return False


def fetch_geojson(url: str) -> Optional[dict]:
    """
    Récupère un fichier GeoJSON à partir d'une URL.

    Args:
        url (str): URL du fichier GeoJSON.

    Returns:
        dict | None: Données GeoJSON si succès, sinon None.
    """
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        loggerDS.error(f"[GEOJSON] Timeout lors de la requête vers {url}")
    except requests.exceptions.HTTPError as e:
        loggerDS.error(f"[GEOJSON] Erreur HTTP {response.status_code} : {e}")
    except requests.exceptions.RequestException as e:
        loggerDS.error(f"[GEOJSON] Erreur réseau lors de la récupération de {url} : {e}")
    except ValueError as e:
        loggerDS.error(f"[GEOJSON] Réponse invalide pour {url} : {e}")
    except Exception as e:
        loggerDS.exception(f"[GEOJSON] Erreur inattendue : {e}")
    return None


import json

def geoareas_to_geojson_text(geoareas):
    """
    Convertit une liste de géométries (geoAreas) en texte GeoJSON exploitable.
    
    :param geoareas: Liste de dictionnaires contenant des objets {"geometry": {...}}
    :return: Chaîne GeoJSON (format texte JSON)
    """
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": item["geometry"],
                "properties": {}
            }
            for item in geoareas if "geometry" in item
        ]
    }
    return geojson



def construire_emplacement_dossier(doss: dict, contact_beneficiaire: dict, titre_demarche: str) -> str:
    """
    Construit dynamiquement un chemin d’emplacement pour stocker un dossier.

    Args:
        doss (dict): Dictionnaire représentant le dossier DS (inclut 'number', 'dateDepot', 'demandeur').
        contact_beneficiaire (dict): Dictionnaire contenant les infos du bénéficiaire (nom, prénom).
        titre_demarche (str): Titre de la démarche (sert à classer dans le bon dossier).

    Returns:
        str: Chemin relatif type "Travaux/2025/Soumis_urbanisme/123456_DUPONT_Jean_22-03"
    """
    titre = (titre_demarche or "").lower()

    # 1. Type autorisation
    if "travaux" in titre:
        type_autorisation = "Travaux"
    elif "mission scientifique" in titre:
        type_autorisation = "Missions_scientifiques"
    elif "activités commerciales" in titre:
        type_autorisation = "Activites_commerciales"
    elif "activités agricoles" in titre:
        type_autorisation = "Activites_agricoles"
    elif "prise de vue" in titre or "drone" in titre:
        type_autorisation = "PDV_et_son"
    elif "hélicoptère" in titre:
        type_autorisation = "Survol_hélicoptere"
    elif "arêtes" in titre:
        type_autorisation = "Aretes"
    elif "manifestations publiques" in titre:
        type_autorisation = "Manifestations_publiques"
    elif "planification et d'urbanisme" in titre:
        type_autorisation = "Documents_planification_urbanisme"
    else:
        type_autorisation = "Autre"

    # 2. Type démarche (si applicable)
    type_demarche = ""
    if type_autorisation == "Travaux":
        if "soumis à autorisation d'urbanisme" in titre:
            type_demarche = "Soumis_urbanisme"
        elif "non soumis" in titre:
            type_demarche = "Non_soumis_urbanisme"
        elif "aire d’adhésion" in titre or "aire d'adhésion" in titre:
            type_demarche = "Aire_adhesion"
    elif type_autorisation == "Missions_scientifiques":
        if "cœur du parc" in titre or "coeur du parc" in titre:
            type_demarche = "Coeur_de_parc"
        elif "espace protégé" in titre:
            type_demarche = "Espace_protege"

    # 3. Année
    try:
        date_depot = parse_datetime_with_tz(doss.get("dateDepot"))
        annee = str(date_depot.year)
    except Exception:
        date_depot = None
        annee = "0000"

    # 4. Nom du dossier
    if not doss["number"] :
        loggerDS.error(f"Erreur lors de la construction de l'emplacement du Dossier {doss["id"]} : le number n'a pas été récupéré sur DS")
    else:
        numero = str(doss.get("number", "000000"))


    demandeur_type = doss.get("demandeur", {}).get("__typename")

    if demandeur_type == "PersonnePhysique":
        nom = contact_beneficiaire.get("nom", "Inconnu").replace(" ", "_").upper()
        prenom = contact_beneficiaire.get("prenom", "Inconnu").replace(" ", "_").capitalize()
        date_suffix = date_depot.strftime("%d-%m") if date_depot else "XX-XX"
        dossier_part = f"{numero}_{nom}_{prenom}_{date_suffix}"

    elif demandeur_type == "PersonneMorale":
        nom_morale = formater_nom_personne_morale(doss.get("demandeur", {}))
        date_suffix = date_depot.strftime("%d-%m") if date_depot else "XX-XX"
        dossier_part = f"{numero}_{nom_morale}_{date_suffix}"

    else:
        dossier_part = f"{numero}_Inconnu"

    # 5. Assemblage
    path_parts = [type_autorisation, annee]
    if type_demarche:
        path_parts.append(type_demarche)
    path_parts.append(dossier_part)

    return "/".join(path_parts)
