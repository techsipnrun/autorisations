import json
import logging
import os
import re
from typing import Optional
import unicodedata
import smbclient
from smbprotocol import exceptions as smb_exceptions
from pathlib import Path

import requests
from django.core.files.uploadedfile import SimpleUploadedFile

from autorisations.utils.nas_fonctions import creer_dossier_sur_nas, donner_droits_ecriture_groupe, ecrire_file_sur_nas
from synchronisation.utils.conversion import formater_nom_personne_morale, parse_datetime_with_tz


loggerORM = logging.getLogger("ORM_DJANGO")
loggerApp = logging.getLogger("APP")
loggerDS = logging.getLogger("API_DS")
loggerSynchro = logging.getLogger("SYNCHRONISATION")

# Vérification de la présence de NAS_ROOT
if not os.environ.get("NAS_ROOT"):
    raise RuntimeError("La variable d'environnement NAS_ROOT est requise.")


def ensure_dossier_root(emplacement: str) -> Optional[str]:
    """
    Crée le dossier racine basé sur la variable d’environnement NAS_ROOT et retourne son chemin complet.

    Args:
        emplacement (str): Chemin relatif à la racine NAS_ROOT.

    Returns:
        Optional[str]: Chemin absolu du dossier créé ou existant, ou None si NAS_ROOT est manquant.
    """
    # racine = os.environ.get("NAS_ROOT")
    racine = os.environ.get("NAS_ROOT")

    if not racine:
        loggerApp.error("[ACCÈS NAS] Variable NAS_ROOT manquante.")
        return None
    
    chemin = os.path.join(racine, emplacement)
    creer_dossier_sur_nas(chemin)
    return chemin





def write_resume_pdf(emplacement, name, url_du_pdf):
    """
    Télécharge un PDF depuis une URL et l’enregistre sur le NAS dans le dossier spécifié.

    Args:
        emplacement (str): Chemin relatif à NAS_ROOT (ex: "Dossiers/12345/").
        name (str): Nom du fichier PDF (avec extension).
        url_du_pdf (str): URL publique du fichier PDF à télécharger.

    Returns:
        Optional[str]: Chemin complet sur le NAS du fichier créé, ou None en cas d’échec.
    """

    # Construction du chemin complet SMB
    nas_root = os.getenv("NAS_ROOT")
    if not nas_root:
        loggerApp.error("[NAS] ❌ Variable d'environnement NAS_ROOT non définie.")
        return None
    chemin_fichier = ensure_dossier_root(emplacement)
    chemin_complet = os.path.join(chemin_fichier, name)

    try:
        # --- Téléchargement du PDF ---
        response = requests.get(url_du_pdf, timeout=20)
        response.raise_for_status()

        # Écriture
        fichier_temp = SimpleUploadedFile(name=name, content=response.content, content_type="application/pdf")
        if ecrire_file_sur_nas(fichier_temp, chemin_complet):
            return chemin_complet
        else:
            loggerORM.error(f"[NAS] ❌ Échec lors de l’écriture du PDF '{name}' sur le NAS.")
            return None

    except requests.exceptions.RequestException as e:
        loggerORM.error(f"[HTTP ERROR] Erreur lors du téléchargement du PDF '{name}' depuis {url_du_pdf} : {e}")
    except Exception as e:
        loggerORM.exception(f"[ECRITURE RÉSUMÉ PDF] ⚠️ Erreur inattendue lors du téléchargement ou de l’écriture du PDF '{name}' : {e}")

    return None




def write_geojson(emplacement, nom_geojson, contenu_geojson):
    """
    Écrit un fichier GeoJSON (.geojson) dans un dossier spécifique. Le fichier est écrasé s’il existe.

    Args:
        emplacement (str): Chemin relatif à NAS_ROOT.
        nom_geojson (str): Nom du fichier GeoJSON.
        contenu_geojson (dict): Données au format dict ou JSON serialisable.

    Returns:
        Optional[str]: Chemin absolu du fichier écrit, ou None en cas d’échec.
    """

    

    chemin_fichier = ensure_dossier_root(emplacement)
    chemin_complet = os.path.join(chemin_fichier, nom_geojson)

    try:
        # with open(chemin_complet, "w", encoding="utf-8") as f:
        with smbclient.open_file(chemin_complet, mode="w", encoding="utf-8") as f:
            json.dump(contenu_geojson, f, ensure_ascii=False, indent=2)
            
        loggerApp.info(f"[GEOJSON] Fichier écrit : {chemin_complet}")
    except Exception as e:
        loggerApp.error(f"[GEOJSON] Erreur lors de l'écriture du fichier GeoJSON {chemin_complet} : {e}")

    return chemin_fichier



def write_pj(emplacement, name, url_pj, ecrase = False):
    """
    Télécharge une pièce jointe depuis une URL et l’enregistre dans le dossier demandé.

    Args:
        emplacement (str): Chemin relatif à NAS_ROOT (ex: "Activites/2025/123456_NOM/Annexes/").
        name (str): Nom du fichier avec extension (ex: "photo.jpg").
        url_pj (str): URL publique de la pièce jointe à télécharger.

    Returns:
        Optional[str]: Chemin absolu du fichier enregistré, ou None si le fichier existe déjà ou en cas d’erreur.
    """
    chemin_dossier = ensure_dossier_root(emplacement)

    safe_name = os.path.basename(name)
    chemin_fichier = os.path.join(chemin_dossier, safe_name)

    # chemin_final = get_nom_disponible(chemin_dossier, safe_name)
    # loggerApp.info(f"chemin_fichier : {chemin_fichier}")

    try:
        if smbclient.path.exists(chemin_fichier) and not ecrase:
            # loggerApp.warning(f"safe_name : {safe_name}  --- chemin_fichier : {chemin_fichier}")
            loggerApp.error(f"[FICHIER EXISTANT] La pièce jointe {chemin_fichier} existe déjà. Aucune écriture effectuée.")
            return

        # response = requests.get(url_pj, timeout=60)
        response = requests.get(url_pj, stream=True, timeout=(10, 300))
        response.raise_for_status()

        # Écriture
        fichier_temp = SimpleUploadedFile(name=name, content=response.content)
        if ecrire_file_sur_nas(fichier_temp, chemin_fichier):
            # loggerApp.info(f"[PJ] Pièce jointe téléchargée et écrite : {chemin_fichier}")
            return chemin_fichier
        else:
            loggerORM.error(f"[NAS] ❌ Échec lors de l’écriture de la pièce jointe '{name}' sur le NAS.")
            return None

    except requests.exceptions.RequestException as e:
        loggerORM.error(f"[HTTP ERROR] Erreur lors du téléchargement de la pièce jointe ({name}) : {e}")
    except Exception as e:
        loggerORM.error(f"[ECRITURE PJ] Erreur inattendue lors du téléchargement ou de l’écriture de la pièce jointe {chemin_fichier} : {e}")
    
    return None


import time

def write_pj_volumineuse(emplacement, name, url_pj, ecrase=False):
    """
    Télécharge une pièce jointe depuis une URL distante et l’écrit en streaming sur le NAS.

    Cette fonction :
    - télécharge le fichier en mode streaming (optimisé pour les fichiers volumineux) ;
    - écrit directement sur le NAS via smbclient ;
    - supprime le fichier partiel en cas d’erreur.

    Args:
        emplacement (str): "Activites/2025/123456_NOM/Annexes/"
        name (str): "document.pdf"
        url_pj (str): URL publique ou accessible de la pièce jointe à télécharger.
        ecrase (bool, optional): False (par défaut), True si on veut écraser un potentiel fichier existant sur le NAS.

    Returns:
        str | None:
            - Chemin absolu du fichier écrit sur le NAS en cas de succès.
            - None si :
                * le fichier existe déjà et ecrase=False
                * une erreur survient (réseau, écriture, etc.)

    Notes:
        - Utilise un téléchargement en streaming pour limiter l’usage mémoire.
        - En cas d’échec, un nettoyage automatique du fichier partiel est tenté.

    """
    chemin_dossier = ensure_dossier_root(emplacement)
    safe_name = os.path.basename(name)
    chemin_fichier = os.path.join(chemin_dossier, safe_name)

    try:
        if smbclient.path.exists(chemin_fichier) and not ecrase:
            loggerApp.error(f"[FICHIER EXISTANT] {chemin_fichier} existe déjà.")
            return None

        start_time = time.time()

        with requests.get(url_pj, stream=True, timeout=(10, 400)) as response:
            response.raise_for_status()

            # Taille totale (si connue)
            total_size = response.headers.get("Content-Length")
            total_size = int(total_size) if total_size and total_size.isdigit() else None

            if total_size:
                total_mo = round(total_size / (1024 * 1024), 2)
                if total_mo and total_mo > 20:
                    loggerApp.info(f"[PJ DOWNLOAD] Début téléchargement '{name}' ({total_mo} Mo)")
            else:
                loggerApp.info(f"[PJ DOWNLOAD] Début téléchargement '{name}' (taille inconnue)")

            bytes_written = 0
            last_log_percent = 0

            with smbclient.open_file(chemin_fichier, mode="wb") as dst:
                for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1 Mo
                    if chunk:
                        dst.write(chunk)
                        bytes_written += len(chunk)

                        # --- LOG PROGRESSION POUR LES FICHIERS LOURDS ---
                        if total_mo > 20 and total_size :
                            percent = int((bytes_written / total_size) * 100)

                            # log tous les 20%
                            if percent >= last_log_percent + 20:
                                loggerApp.info(
                                    f"[PJ DOWNLOAD] {name} : {percent}% ({round(bytes_written / (1024*1024), 2)} Mo)"
                                )
                                last_log_percent = percent
                        # else:
                        #     # si taille inconnue → log tous les 5 Mo
                        #     if bytes_written % (5 * 1024 * 1024) < 1024 * 1024:
                        #         loggerApp.info(
                        #             f"[PJ DOWNLOAD] {name} : {round(bytes_written / (1024*1024), 2)} Mo écrits"
                        #         )

        duration = round(time.time() - start_time, 2)
        size_mo = round(bytes_written / (1024 * 1024), 2)

        loggerApp.info(f"[PJ OK] {name} téléchargé ({size_mo} Mo) en {duration}s → {chemin_fichier}")

        return chemin_fichier

    except requests.exceptions.RequestException as e:
        loggerORM.error(f"[HTTP ERROR] {name} : {e}")

    except Exception as e:
        loggerORM.error(f"[ECRITURE PJ] {name} : {e}")

    # nettoyage fichier partiel
    try:
        if smbclient.path.exists(chemin_fichier):
            smbclient.remove(chemin_fichier)
            loggerApp.warning(f"[CLEANUP] Fichier partiel supprimé : {chemin_fichier}")
    except Exception:
        pass

    return None





def get_nom_disponible(dossier_path, nom_fichier):
    nom_base, ext = os.path.splitext(nom_fichier)
    nom_final = nom_base
    i = 2
    racine = os.environ.get("NAS_ROOT")
    chemin_complet = os.path.join(racine, dossier_path, nom_fichier)
    while smbclient.path.exists(chemin_complet):
        nom_final = f"{nom_base}_{i}"
        chemin_complet = os.path.join(racine, dossier_path, nom_final + ext)
        i += 1

    return nom_final + ext



def create_emplacement(emplacement_dossier):
    """
    Crée un dossier principal et les sous-dossiers standards s’il n’existe pas déjà.

    Args:
        emplacement_dossier (str): Chemin relatif à NAS_ROOT (ex: "Travaux/2025/123456_DUPONT_Jean").

    Returns:
        bool: True si les dossiers ont été créés ou existent déjà, False en cas d’erreur.
    """
    chemin_complet = ensure_dossier_root(emplacement_dossier)

    try:

        if not creer_dossier_sur_nas(chemin_complet) :
            loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
            return False


        # Sous-dossiers standards
        sous_dossiers = ["Annexes", "Actes", "Avis", "Carto", "Work"]
        for nom in sous_dossiers:
            chemin_sous_dossier = os.path.join(chemin_complet, nom)

            if not creer_dossier_sur_nas(chemin_sous_dossier) :
                loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
                return False
            
            if nom == 'Work' : 
                # Attribution des droits d'écriture
                donner_droits_ecriture_groupe(chemin_sous_dossier)
                
        return True
    
    except Exception as e:
        loggerApp.error(f"Impossible de créer les sous-dossiers pour {emplacement_dossier} : {e}")
        return False
    


def create_emplacement_manif_sportive(emplacement_dossier):
    """
    Pour un Dossier Déclaration Manifestations n'étant pas lié à un Dossier Démarche Numérique
    Crée un dossier principal et les sous-dossiers standards s’il n’existe pas déjà.

    Args:
        emplacement_dossier (str): Chemin relatif à NAS_ROOT (ex: "Manifestations_sportives/2025/trail_des_geants").

    Returns:
        bool: True si les dossiers ont été créés ou existent déjà, False en cas d’erreur.
    """
    chemin_complet = ensure_dossier_root(emplacement_dossier)

    try:

        if not creer_dossier_sur_nas(chemin_complet) :
            loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
            return False


        # Sous-dossiers standards
        sous_dossiers = ["Annexes", "Carto", "Work"]
        for nom in sous_dossiers:
            chemin_sous_dossier = os.path.join(chemin_complet, nom)

            if not creer_dossier_sur_nas(chemin_sous_dossier) :
                loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
                return False
            
            if nom == 'Work' : 
                # Attribution des droits d'écriture
                donner_droits_ecriture_groupe(chemin_sous_dossier)
             
        return True
    
    except Exception as e:
        loggerApp.error(f"Dossier Déclaration Manifestations n'étant pas lié à un Dossier Démarche Numérique : Impossible de créer les sous-dossiers pour {emplacement_dossier} : {e}")
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
    elif "manifestations sportives" in titre:
        type_autorisation = "Manifestations_sportives"
    elif "planification et d'urbanisme" in titre:
        type_autorisation = "Documents_planification_urbanisme"
    else:
        type_autorisation = "Autre"

    # 2. Type démarche (si applicable)
    type_demarche = ""
    if type_autorisation == "Travaux":
        if "et soumis à autorisation d'urbanisme" in titre:
            type_demarche = "Soumis_urbanisme"
        elif "non soumis à autorisation d'urbanisme" in titre:
            type_demarche = "Non_soumis_urbanisme"
        elif "aire d’adhésion" in titre or "aire d'adhésion" in titre:
            type_demarche = "Aire_adhesion"
    elif type_autorisation == "Missions_scientifiques":
        if "cœur du parc" in titre or "coeur du parc" in titre:
            type_demarche = "Coeur_de_parc"
        elif "espèces protégées" in titre:
            type_demarche = "Especes_protegees"

    # 3. Année
    try:
        date_depot = parse_datetime_with_tz(doss.get("dateDepot"))
        annee = str(date_depot.year)
    except Exception:
        date_depot = None
        annee = "0000"


    # 4. Nom du dossier
    if type_autorisation != "Manifestations_sportives" :

        if not doss["number"] :
            loggerDS.error(f"Erreur lors de la construction de l'emplacement du Dossier {doss['id']} : le number n'a pas été récupéré sur DS")
        else:
            numero = str(doss.get("number", "000000"))

        demandeur_type = doss.get("demandeur", {}).get("__typename")

        if demandeur_type == "PersonnePhysique":
            nom = contact_beneficiaire.get("nom", "Inconnu").replace(" ", "_").upper()
            prenom = contact_beneficiaire.get("prenom", "Inconnu").replace(" ", "_").capitalize()
            date_suffix = date_depot.strftime("%d-%m") if date_depot else "XX-XX"
            dossier_part = f"{numero}_{nom}_{prenom}_{date_suffix}/"

        elif demandeur_type == "PersonneMorale":
            nom_morale = formater_nom_personne_morale(doss.get("demandeur", {}), doss)
            date_suffix = date_depot.strftime("%d-%m") if date_depot else "XX-XX"
            dossier_part = f"{numero}_{nom_morale}_{date_suffix}/"

        else:
            dossier_part = f"{numero}_Inconnu/"

    # Manifestations sportives DN : nom dossier = nom manifestation
    else:
        for ch in doss["champs"]:

            if ch["label"] == "Nom de la manifestation" :
                numero = str(doss.get("number", "000000"))
                nom_manif = nettoyer_nom_fichier(ch["stringValue"])
                dossier_part = f"{numero}_{nom_manif}/"
                break


    # 5. Assemblage
    path_parts = [type_autorisation, annee]
    if type_demarche:
        path_parts.append(type_demarche)
    path_parts.append(dossier_part)

    return "/".join(path_parts)


# def create_emplacement_sport(obj, logger):
#     """
#     Créé l'emplacement d'un dossier Déclaration manifestations sur le NAS
#     """

#     # Manifestations_sportives > 2026 > nom_de_la_manif

#     racine = os.environ.get("NAS_ROOT")
#     chemin_complet = os.path.join(racine, obj.emplacement)

#     if not creer_dossier_sur_nas(chemin_complet) :
#         loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")

#     return chemin_complet


def nettoyer_nom_fichier(nom_dossier):
    # Supprimer les accents
    nom = unicodedata.normalize('NFKD', nom_dossier).encode('ASCII', 'ignore').decode('utf-8')
    
    # Remplacer les espaces et tirets multiples par un underscore
    nom = re.sub(r'[\s\-]+', '_', nom)

    # Supprimer tout caractère non alphanumérique ou underscore
    nom = re.sub(r'[^\w_]', '', nom)

    # Mettre en minuscule
    return nom.lower()



def rendre_titres_uniques(documents):
    """
    Garantit l’unicité des titres de documents en ajoutant un suffixe si nécessaire.

    Principe :
    - Le premier titre rencontré est conservé tel quel.
    - Si un titre est déjà utilisé, on ajoute un suffixe du type : __copie01, __copie02, etc.

    Exemple :
        BILAN.pdf
        BILAN.pdf       → BILAN__copie01.pdf
        BILAN.pdf       → BILAN__copie02.pdf

    Args:
        documents (list[dict]): liste de dictionnaires contenant au minimum la clé "titre"

    Returns:
        list[dict]: la liste modifiée (modification en place des titres)
    """

    # Ensemble des titres déjà attribués pour éviter les doublons
    titres_deja_pris = set()

    # Parcours des documents dans l’ordre
    for doc in documents:

        # Récupération et nettoyage du titre
        titre_original = (doc.get("titre") or "").strip()

        # Si pas de titre → on ignore
        if not titre_original:
            continue

        path = Path(titre_original)
        base = path.stem
        extension = path.suffix

        # Candidat initial = titre d’origine
        candidat = titre_original

        # Compteur pour générer les suffixes __copieXX
        compteur = 1

        # Tant que le titre existe déjà, on génère un nouveau nom
        while candidat in titres_deja_pris:
            candidat = f"{base}__copie{compteur:02d}{extension}"
            compteur += 1

        doc["titre"] = candidat
        titres_deja_pris.add(candidat)

    return documents



def rendre_titre_unique_dans_liste(titre: str, titres_existants: list[str]) -> str:
    """
    Retourne un titre unique en normalisant les suffixes __copieXX.

    Exemple :
        "xx.pdf" -> "xx__copie01.pdf"
        "xx__copie01.pdf" -> "xx__copie02.pdf"

    Args:
        titre (str): titre à vérifier
        titres_existants (list[str]): liste des titres déjà utilisés

    Returns:
        str: titre unique
    """
    titre = (titre or "").strip()
    if not titre:
        return titre

    titres_deja_pris = {t.strip() for t in titres_existants if t and t.strip()}

    path = Path(titre)
    base = path.stem
    extension = path.suffix

    # Regex pour enlever un éventuel suffixe __copieXX
    base_sans_copie = re.sub(r"__copie\d{2}$", "", base)

    # Si le titre original n'existe pas, on le garde
    if titre not in titres_deja_pris:
        return titre

    compteur = 1
    while True:
        candidat = f"{base_sans_copie}__copie{compteur:02d}{extension}"
        if candidat not in titres_deja_pris:
            return candidat
        compteur += 1