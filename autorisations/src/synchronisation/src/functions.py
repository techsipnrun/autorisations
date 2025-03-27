"""
    Fonctions python réutilisables
"""


from datetime import date, datetime
import os
import requests
import json

from autorisations.models.models_instruction import DemandeType


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


def save_to_json(data_dict, folder="outputs"):
    os.makedirs(folder, exist_ok=True)  # Crée le dossier s'il n'existe pas

    for key, value in data_dict.items():
        with open(os.path.join(folder, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=4, default=convert_datetime)
        print(f" Données enregistrées dans : {key}.json")
