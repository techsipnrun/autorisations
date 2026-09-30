"""Contrôles de lecture destinés au suivi des dépendances du Back Office."""

from datetime import datetime
import logging
import os

import requests
from django.conf import settings
from django.db import DatabaseError, connections
from django.utils import timezone


logger = logging.getLogger("ORM_DJANGO")


def _verifier_acces_bdd(alias, configure, detail_non_configure, fermer_connexion):
    """Exécute le plus petit contrôle possible sur une connexion Django."""
    hostname = settings.DATABASES.get(alias, {}).get("HOST") or "Non renseigné"
    if not configure:
        return {
            "disponible": False,
            "configure": False,
            "hostname": hostname,
            "detail": detail_non_configure,
        }

    connexion = connections[alias]
    try:
        with connexion.cursor() as curseur:
            curseur.execute("SELECT 1")
            curseur.fetchone()
        return {
            "disponible": True,
            "configure": True,
            "hostname": hostname,
            "detail": None,
        }
    except DatabaseError as exc:
        logger.warning("Vérification de la BDD (%s) en échec : %s", alias, exc)
        return {
            "disponible": False,
            "configure": True,
            "hostname": hostname,
            "detail": "La connexion à la base de données a échoué.",
        }
    finally:
        if fermer_connexion:
            connexion.close()


def verifier_acces_bdd_production():
    """Teste la BDD définie dans .env.prod, strictement en lecture seule."""
    alias = "prod_readonly"
    return _verifier_acces_bdd(
        alias,
        alias in settings.DATABASES,
        "L'accès en lecture seule à la production n'est pas configuré sur cet environnement.",
        fermer_connexion=True,
    )


def verifier_acces_bdd_developpement():
    """Teste la BDD définie dans .env.dev, strictement en lecture seule."""
    return _verifier_acces_bdd(
        "dev_readonly",
        "dev_readonly" in settings.DATABASES,
        "La base de données de développement n'est pas configurée.",
        fermer_connexion=True,
    )


def verifier_disponibilite_swagger(url):
    """Vérifie que l'interface Swagger publiée par cette application répond."""
    try:
        response = requests.get(url, timeout=(3, 8), allow_redirects=True)
        disponible = response.status_code < 500 and response.status_code != 429
        return {
            "disponible": disponible,
            "url": url,
            "status_code": response.status_code,
            "detail": None if disponible else "Swagger a renvoyé une erreur HTTP.",
        }
    except requests.RequestException as exc:
        logger.warning("Vérification de Swagger en échec vers %s : %s", url, exc)
        return {
            "disponible": False,
            "url": url,
            "status_code": None,
            "detail": "Aucune réponse exploitable de Swagger.",
        }


def get_etat_expiration_token_dn():
    """Expose l'échéance renseignée pour le jeton DN, sans jamais afficher le jeton."""
    date_brute = os.getenv("DN_DATE_EXPIRATION_TOKEN")
    if not date_brute:
        return {
            "configure": False,
            "etat": "inconnu",
            "detail": "La date d'expiration du jeton DN n'est pas renseignée.",
        }

    try:
        expiration = datetime.strptime(date_brute, "%Y-%m-%d").date()
    except ValueError:
        return {
            "configure": False,
            "etat": "inconnu",
            "detail": "La date d'expiration du jeton DN est invalide.",
        }

    jours_restants = (expiration - timezone.localdate()).days
    if jours_restants < 0:
        etat = "expire"
    elif jours_restants <= 40:
        etat = "expire_bientot"
    else:
        etat = "valide"

    return {
        "configure": True,
        "etat": etat,
        "expiration": expiration,
        "jours_restants": jours_restants,
        "detail": None,
    }
