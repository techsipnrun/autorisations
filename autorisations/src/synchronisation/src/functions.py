"""
    Fonctions python réutilisables
"""


from datetime import date, datetime, timedelta
import os
import requests
import json
from django.utils.timezone import now, is_naive, get_current_timezone, make_aware
from autorisations.models.models_instruction import DemandeType, Priorite, Demarche
from django.db import models
from dateutil.parser import parse



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

    if nom_demarche == "Demande d'autorisation : Activités commerciales en cœur du Parc national de la Réunion":
        return DemandeType.objects.filter(type="Activités commerciales").values_list("id", flat=True).first()
        # return 7
    elif nom_demarche == "Demande d'autorisation : Travaux en cœur du Parc national de la Réunion, non soumis à autorisation d'urbanisme":
        return DemandeType.objects.filter(type="Travaux").values_list("id", flat=True).first()
        # return 4
    elif nom_demarche == "Demande d'autorisation : Travaux en cœur du Parc national de la Réunion et soumis à autorisation d'urbanisme":
        return DemandeType.objects.filter(type="Travaux").values_list("id", flat=True).first()
        # return 4
    elif nom_demarche == "Demande d'autorisation : Travaux en aire d’adhésion":
        return DemandeType.objects.filter(type="Travaux").values_list("id", flat=True).first()
        # return 4
    elif nom_demarche == "Demande d'autorisation : Mission scientifique en cœur du Parc national de la Réunion":
        return DemandeType.objects.filter(type="Missions scientifiques").values_list("id", flat=True).first()
        # return 5
    elif nom_demarche == "Demande d'autorisation : Mission scientifique en espace protégé":
        return DemandeType.objects.filter(type="Missions scientifiques").values_list("id", flat=True).first()
        # return 5
    elif nom_demarche == "Demande d'autorisation : Survol hélicoptère en cœur du Parc national de la Réunion":
        return DemandeType.objects.filter(type="Survol hélicoptère").values_list("id", flat=True).first()
        # return 9
    elif nom_demarche == "Demande d'autorisation : Courses d’arêtes en cœur du Parc national de la Réunion":
        return DemandeType.objects.filter(type="Arêtes").values_list("id", flat=True).first()
        # return 3
    elif nom_demarche == "Demande d'autorisation : Activités agricoles en cœur du Parc national de la Réunion":
        return DemandeType.objects.filter(type="Activités agricoles").values_list("id", flat=True).first()
        # return 6
    elif nom_demarche == "Demande d'autorisation : Prise de vue et de son et/ou survol de drone en cœur du Parc national de la Réunion":
        return 999  # Cas particulier à traiter à part
    else:
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
            date_depot = datetime.fromisoformat(date_depot_dossier)
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
            niveau = "haute"
        elif ratio_restant < 0.8:
            niveau = "moyenne"
        else:
            niveau = "faible"

        return Priorite.objects.filter(niveau=niveau).values_list("id", flat=True).first()
    

def update_fields(obj, data: dict, date_fields: list = []):
    updated = []
    for field, new_val in data.items():
        old_val = getattr(obj, field)
        if field in date_fields:
            old_val = clean_date(old_val)
            new_val = clean_date(new_val)

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
        date_depot = datetime.fromisoformat(date_depot_iso)
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
        date_depot = datetime.fromisoformat(doss["dateDepot"])
        annee = str(date_depot.year)
    except:
        annee = "0000"

    # 4. Dossier = numero_nom_prenom
    numero = str(doss["number"])
    nom = contact_beneficiaire.get("nom", "Inconnu").replace(" ", "_").upper()
    prenom = contact_beneficiaire.get("prenom", "Inconnu").replace(" ", "_").lower().capitalize()
    dossier_part = f"{numero}_{nom}_{prenom}"

    path_parts = [type_autorisation, annee]
    if type_demarche:
        path_parts.append(type_demarche)
    path_parts.append(dossier_part)

    return "/".join(path_parts)

