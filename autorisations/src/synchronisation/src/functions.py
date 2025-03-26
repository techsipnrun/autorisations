"""
    Fonctions python réutilisables
"""


import os
import requests

def fetch_geojson(url):
    try:
        response = requests.get(url)
        response.raise_for_status()  # Lève une erreur si la réponse n’est pas 200
        return response.json()  # Retourne le contenu GeoJSON parsé
    except Exception as e:
        print(f"Erreur lors du chargement du GeoJSON : {e}")
        return None
    

def extraire_nom_et_extension(filename):
    nom, extension = os.path.splitext(filename)
    nom = nom.replace('.', '_')
    extension = extension.lstrip('.')  # Enlever le point
    return nom, extension

def type_demande_from_nom_demarche(nom_demarche):
    if nom_demarche == "Demande d autorisation : Activités commerciales en cœur du Parc national de la Réunion":
        return 7
    elif nom_demarche == "Demande d autorisation : Travaux en cœur du Parc national de la Réunion, non soumis à autorisation d urbanisme":
        return 4
    elif nom_demarche == "Demande d autorisation : Travaux en cœur du Parc national de la Réunion et soumis à autorisation d urbanisme":
        return 4
    elif nom_demarche == "Demande d autorisation : Travaux en aire d’adhésion":
        return 4
    elif nom_demarche == "Demande d autorisation : Mission scientifique en cœur du Parc national de la Réunion":
        return 5
    elif nom_demarche == "Demande d autorisation : Mission scientifique en espace protégé":
        return 5
    elif nom_demarche == "Demande d autorisation : Survol hélicoptère en cœur du Parc national de la Réunion":
        return 9
    elif nom_demarche == "Demande d autorisation : Courses d’arêtes en cœur du Parc national de la Réunion":
        return 3
    elif nom_demarche == "Demande d autorisation : Activités agricoles en cœur du Parc national de la Réunion":
        return 6
    elif nom_demarche == "Demande d autorisation : Prise de vue et de son et/ou survol de drone en cœur du Parc national de la Réunion":
        return 999  # Cas particulier à traiter à part
    else:
        return None
