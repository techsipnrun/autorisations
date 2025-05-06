"""
    Fonctions python réutilisables
"""


from datetime import date, datetime, timedelta
import logging
import os
from dotenv import load_dotenv
import requests
import json
from django.utils.timezone import now, is_naive, get_current_timezone, make_aware
from autorisations.models.models_instruction import DemandeType, Priorite, Demarche
from django.db import models
from dateutil.parser import parse
from pytz import timezone

from autorisations.settings import BASE_DIR

# Chemin du fichier .env en fonction de l'environnement
# ENVIRONMENT = os.getenv("DJANGO_ENV", "dev")  # dev par défaut, DJANGO_ENV=prod python manage.py runserver pour lancer en prod
# dotenv_path = BASE_DIR / f".env.{ENVIRONMENT}"
# load_dotenv(dotenv_path)

logger = logging.getLogger("ORM_DJANGO")

def fetch_geojson(url):
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("Erreur : délai d'attente dépassé (timeout).")
    except requests.exceptions.HTTPError as e:
        print(f"Erreur HTTP : {e}")
    except Exception as e:
        print(f"Erreur générale : {e}")
    return None
    

def extraire_nom_et_extension(filename):
    nom, extension = os.path.splitext(filename)
    nom = nom.replace('.', '_')
    extension = extension.lstrip('.')  # Enlever le point
    return nom, extension


def type_demande_from_nom_demarche(nom_demarche):

    if "Activités commerciales" in nom_demarche :
        return DemandeType.objects.filter(type="Activités commerciales").values_list("id", flat=True).first()
        # return 7
    elif "Travaux" in nom_demarche:
        return DemandeType.objects.filter(type="Travaux").values_list("id", flat=True).first()
        # return 4
    elif "Mission scientifique" in nom_demarche :
        return DemandeType.objects.filter(type="Missions scientifiques").values_list("id", flat=True).first()
        # return 5
    elif "Survol motorisé" in nom_demarche :
        return DemandeType.objects.filter(type="Survol hélicoptère").values_list("id", flat=True).first()
        # return 9
    elif "arêtes" in nom_demarche :
        return DemandeType.objects.filter(type="Arêtes").values_list("id", flat=True).first()
        # return 3
    elif "Activités agricoles" in nom_demarche :
        return DemandeType.objects.filter(type="Activités agricoles").values_list("id", flat=True).first()
        # return 6
    elif "Prise de vue et de son" in nom_demarche :
        return 999  # Cas particulier à traiter à part (drone OU pdv)
    else:
        # print(nom_demarche)
        return None
    

def convert_datetime(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()  # Format ISO 8601 lisible : '2025-03-27'
    raise TypeError(f"Type {type(obj)} non sérialisable en JSON")


def save_to_json(data_dict, folder="synchronisation/src/outputs"):
    os.makedirs(folder, exist_ok=True)  # Crée le dossier s'il n'existe pas

    for key, value in data_dict.items():
        with open(os.path.join(folder, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=4, default=convert_datetime)
        print(f" Données enregistrées dans : {key}.json")


def calcul_priorite_instruction(id_demarche, doss):
    # Plusieurs cas :
        #Dossier deja traité --> id_prio 4
        #Dossier en cours --> on regarde datedepot et le colonne demarche.delais_jours_instruction

    if doss["state"] == "accepte" or doss["state"] == "refuse" or doss["state"] == "sans_suite" :
        return Priorite.objects.filter(niveau="traite").values_list("id", flat=True).first()
    
    else :
        date_depot_dossier = doss["dateDepot"]

        if id_demarche != 3 :  
            delais_jours_instruction = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()

        else :  # pour les travaux soumis à urbanisme le temps d'instruction max n'est pas le meme (selon  Permis Construire ou Déclaration Préalable)
            # si DP : 45 jours
            # sinon 120 jours (valeur de la colonne delais_jours_instruction)
            delais_jours_instruction = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()
    
        if not date_depot_dossier :
            print("Erreur lors du calcul de Priorité d'instruction du dossier : la date de dépot du dossier est null")
            return None

        if delais_jours_instruction is None :
            print("Erreur lors du calcul de Priorité d'instruction du dossier : la colonne delais_jours_instruction de la " +
                   f"{Demarche.objects.filter(id=id_demarche).values_list("description", flat=True).first()} est null")
            return None

        # Conversion de la date ISO 8601 en datetime Python
        try:
            date_depot = parse_datetime_with_tz(date_depot_dossier)
        except ValueError:
            return None  # ou logguer une erreur

        date_limite = date_depot + timedelta(days=delais_jours_instruction)
        today = now()

        if is_naive(today):
            today = make_aware(today, get_current_timezone())


        # Calcul du ratio restant
        jours_restants = (date_limite - today).total_seconds() / (3600 * 24)
        ratio_restant = jours_restants / delais_jours_instruction

        if ratio_restant < 0.3:
            niveau = "urgent"
        elif ratio_restant < 0.8:
            niveau = "normal"
        else:
            niveau = "faible"

        return Priorite.objects.filter(niveau=niveau).values_list("id", flat=True).first()
    

def update_fields(obj, data: dict, date_fields: list = []):
    updated = []
    for field, new_val in data.items():
        old_val = getattr(obj, field)
        if field in date_fields:
            old_val = parse_datetime_with_tz(old_val)
            new_val = parse_datetime_with_tz(new_val)

        if old_val != new_val:
            setattr(obj, field, new_val)
            updated.append(field)
    return updated


def foreign_keys_add_suffixe_id(model_class, data):
    corrected = {}
    for field, value in data.items():
        if hasattr(model_class, field):
            model_field = getattr(model_class, field)
            if hasattr(model_field, 'field') and isinstance(model_field.field, models.ForeignKey):
                corrected[f"{field}_id"] = value
            else:
                corrected[field] = value
        else:
            corrected[field] = value
    return corrected


def clean_date(val):
    if isinstance(val, datetime):
        return val.date()
    elif isinstance(val, str):
        return parse(val).date()
    return val  # si c’est déjà une date, on ne fait rien


def parse_datetime_with_tz(dt_input):
    """
    Convertit une chaîne ISO 8601 ou un datetime (naïf ou aware)
    en datetime avec le fuseau horaire Indian/Reunion.
    """
    if not dt_input:
        return None

    # 1. Parse string si besoin
    if isinstance(dt_input, str):
        dt = parse(dt_input)
    elif isinstance(dt_input, datetime):
        dt = dt_input
    else:
        raise TypeError(f"Entrée non supportée : {dt_input} ({type(dt_input)})")

    # 2. Si naïf, on suppose qu’il est en Europe/Paris
    paris_tz = timezone("Europe/Paris")
    if is_naive(dt):
        dt = paris_tz.localize(dt)

    # 3. Conversion explicite vers Indian/Reunion
    reunion_tz = timezone("Indian/Reunion")
    dt = dt.astimezone(reunion_tz)

    return dt


def get_first_id(model, **filters):
    """
    Renvoie le premier ID d’un objet correspondant aux filtres donnés.
    :param model: Le modèle Django à interroger
    :param filters: Les champs de filtrage (ex: nom="Jean", type="pdf")
    :return: L'ID (int) ou None
    """
    return model.objects.filter(**filters).values_list("id", flat=True).first()


def clean_email(value):
    return value.strip().lower() if value else None

def clean_name(value):
    return value.strip().lower().capitalize() if value else ""

def clean_surname(value):
    return value.strip().upper() if value else ""


def calcul_date_limite_instruction(date_depot_iso: str, id_demarche: int):
    from autorisations.models.models_instruction import Demarche
    from datetime import datetime, timedelta

    if not date_depot_iso:
        return None
    try:
        date_depot = parse_datetime_with_tz(date_depot_iso)
        delais = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()
        if delais is not None:
            return date_depot + timedelta(days=delais)
    except Exception as e:
        print(f"[ERREUR] calcul_date_limite_instruction: {e}")
    return None




def construire_emplacement_dossier(doss, contact_beneficiaire, titre_demarche):
    # 1. Type autorisation
    titre = titre_demarche.lower()
    if "travaux" in titre:
        type_autorisation = "Travaux"
    elif "mission scientifique" in titre:
        type_autorisation = "Missions_scientifiques"
    elif "activités commerciales" in titre:
        type_autorisation = "Activites_commerciales"
    elif "activité agricole" in titre:
        type_autorisation = "Activite_agricoles"
    elif "prise de vue" in titre or "drone" in titre:
        type_autorisation = "PDV_et_son"
    elif "survol hélicoptère" in titre:
        type_autorisation = "Survol"
    elif "courses d’arêtes" in titre:
        type_autorisation = "Aretes"
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
        date_depot = parse_datetime_with_tz(doss["dateDepot"])
        annee = str(date_depot.year)
    except:
        annee = "0000"

    # 4. Dossier = numero_nom_prenom pour PersonnPhysique et numero_nom pour PersonneMorale
    numero = str(doss["number"])
    if doss['demandeur']['__typename'] == 'PersonnePhysique' :
        nom = contact_beneficiaire.get("nom", "Inconnu").replace(" ", "_").upper()
        prenom = contact_beneficiaire.get("prenom", "Inconnu").replace(" ", "_").lower().capitalize()
        dossier_part = f"{numero}_{nom}_{prenom}_{date_depot.strftime("%d-%m")}"

    if doss['demandeur']['__typename'] == 'PersonneMorale' :
        dossier_part = f"{numero}_{formater_nom_personne_morale(doss["demandeur"])}_{date_depot.strftime("%d-%m")}"

    path_parts = [type_autorisation, annee]
    if type_demarche:
        path_parts.append(type_demarche)
    path_parts.append(dossier_part)

    return "/".join(path_parts)


def create_emplacement(emplacement_dossier):
    """
    Crée l'emplacement physique du dossier sur le disque selon le path fourni,
    en y ajoutant les sous-dossiers standards.

    :param emplacement_dossier: chaîne de type "Travaux/2025/Soumis_urbanisme/123456_DUPONT_Jean"
    """

    racine = os.environ.get('ROOT_FOLDER')
    # ROOT_FOLDER = 'J:\0_Fonctionnement_general\08_AUTORISATIONS\080_Projet_Application\Bancarisation\'

    if not racine:
        print("[ERREUR] Variable d’environnement ROOT_FOLDER non définie.")
        return

    chemin_complet = os.path.join(racine, emplacement_dossier)

    try:
        if not os.path.exists(chemin_complet):
            os.makedirs(chemin_complet)
            print(f"[INFO] Dossier principal créé : {chemin_complet}")
        else:
            print(f"[INFO] Dossier déjà existant : {chemin_complet}")

        # Sous-dossiers standards
        sous_dossiers = ["Annexes", "Actes", "Avis", "Carto", "Work"]
        for nom in sous_dossiers:
            chemin_sous_dossier = os.path.join(chemin_complet, nom)
            if not os.path.exists(chemin_sous_dossier):
                os.makedirs(chemin_sous_dossier)
                print(f"    → Création : {chemin_sous_dossier}")
            else:
                print(f"    → Déjà présent : {chemin_sous_dossier}")

    except Exception as e:
        print(f"[ERREUR] Impossible de créer les dossiers pour {emplacement_dossier} : {e}")


def write_resume_pdf(emplacement, name, url_du_pdf):
    """
    Télécharge un PDF depuis une URL et l’écrit dans le dossier spécifié.

    :param emplacement: Chemin relatif à ROOT_FOLDER
    :param name: Nom du fichier sans extension
    :param url_du_pdf: URL publique du fichier à télécharger
    """
    racine = os.environ.get("ROOT_FOLDER")
    if not racine:
        logger.error(f"[ERREUR] ROOT_FOLDER non défini dans les variables d’environnement (création du résumé {{name}}.pdf)")
        return

    chemin_dossier = os.path.join(racine, emplacement)
    chemin_fichier = os.path.join(chemin_dossier, f"{name}.pdf")

    try:
        os.makedirs(chemin_dossier, exist_ok=True)

        response = requests.get(url_du_pdf, timeout=15)
        response.raise_for_status()

        with open(chemin_fichier, "wb") as f:
            f.write(response.content)

        logger.info(f"[FILE] PDF téléchargé et écrit : {chemin_fichier}")

    except requests.exceptions.RequestException as e:
        logger.error(f"[HTTP ERROR] Impossible de télécharger le PDF : {e}")
    except Exception as e:
        logger.error(f"[FILE ERROR] Impossible d’écrire le fichier {chemin_fichier} : {e}")



def write_geojson(emplacement, nom_geojson, contenu_geojson):
    """
    Écrit un fichier .geojson dans le dossier spécifié.
    Écrase le fichier s'il existe déjà.

    :param emplacement: Chemin relatif à ROOT_FOLDER
    :param nom_geojson: Nom du fichier (sans extension)
    :param contenu_geojson: Dictionnaire ou JSON serialisable (géométrie)
    """
    racine = os.environ.get("ROOT_FOLDER")
    if not racine:
        logger.error(f"[ERREUR] ROOT_FOLDER non défini dans les variables d’environnement (écriture du geojson : {nom_geojson}).")
        return

    chemin_dossier = os.path.join(racine, emplacement)
    chemin_fichier = os.path.join(chemin_dossier, f"{nom_geojson}")

    try:
        os.makedirs(chemin_dossier, exist_ok=True)
        with open(chemin_fichier, "w", encoding="utf-8") as f:
            json.dump(contenu_geojson, f, ensure_ascii=False, indent=2)
            
        logger.info(f"[GEOJSON] Fichier écrit : {chemin_fichier}")
    except Exception as e:
        logger.error(f"[ERREUR] Impossible d’écrire le fichier GeoJSON {chemin_fichier} : {e}")

def write_pj(emplacement, name, url_pj):
    """
    Télécharge une pièce jointe depuis une URL et l’écrit dans le dossier spécifié.

    :param emplacement: chemin relatif à ROOT_FOLDER (ex: Activites/2025/123456_DUPONT/Annexes/)
    :param name: nom du fichier avec extension 
    :param url_pj: URL de téléchargement de la pièce jointe
    """
    racine = os.environ.get("ROOT_FOLDER")
    if not racine:
        logger.error("[ERREUR] ROOT_FOLDER non défini dans les variables d’environnement (écriture de PJ)")
        return

    chemin_dossier = os.path.join(racine, emplacement)
    chemin_fichier = os.path.join(chemin_dossier, name)

    try:
        os.makedirs(chemin_dossier, exist_ok=True)
        
        
        if os.path.exists(chemin_fichier):
            logger.error(f"[FICHIER EXISTANT] La pièce jointe {chemin_fichier} existe déjà. Aucun téléchargement effectué.")
            return

        response = requests.get(url_pj, timeout=15)
        response.raise_for_status()

        with open(chemin_fichier, "wb") as f:
            f.write(response.content)

        logger.info(f"[PJ] Pièce jointe téléchargée et écrite : {chemin_fichier}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[HTTP ERROR] Impossible de télécharger la pièce jointe ({name}) : {e}")
    except Exception as e:
        logger.error(f"[FILE ERROR] Impossible d’écrire la pièce jointe {chemin_fichier} : {e}")


def formater_nom_personne_morale(data):
    """
    Extrait et formate le nom d'une Personne Morale (entreprise ou association) en minuscules avec des underscores.

    :param data: Dictionnaire contenant les champs 'entreprise' ou 'association'
    :return: Chaîne formatée (str)
    """

    if data.get("entreprise") :
        raison = data.get("entreprise", {}).get("raisonSociale")
        nom_entreprise = data.get("entreprise", {}).get("nom")

    if data.get("association") :
        titre = data.get("association", {}).get("titre")

    nom = raison or nom_entreprise or titre or ""
    return nom.strip().lower().replace(" ", "_")