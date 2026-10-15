"""Auteur et droits des annexes Notes, à partir des métadonnées existantes."""
import re

from django.contrib.auth import get_user_model
from django.db.models.functions import Lower

from autorisations.models.models_utilisateurs import Instructeur


def auteur_annexe(document, dossier):
    correspondance = re.fullmatch(
        rf"Annexe ajouté(?:e)? par l'instructeur (.+) sur le dossier {re.escape(str(dossier.numero))}",
        document.description or "",
    )
    return correspondance.group(1) if correspondance else None


def peut_supprimer_annexe(document, dossier, user):
    # Comparaison exacte : « louis » ne doit pas correspondre à « louis.calu ».
    return bool(user.is_authenticated and auteur_annexe(document, dossier) == user.get_username())


def preparer_annexes_notes(annexes, dossier, user):
    annexes = list(annexes)
    auteurs = {auteur_annexe(document, dossier) for document in annexes} - {None}
    comptes = {
        compte.get_username(): compte
        for compte in get_user_model().objects.filter(username__in=auteurs)
    } if auteurs else {}
    emails = {
        (comptes[auteur].email if auteur in comptes else auteur).strip().casefold()
        for auteur in auteurs
    }
    # Une seule lecture des agents pour toutes les annexes du dossier.
    instructeurs = {
        instructeur.email.strip().casefold(): instructeur
        for instructeur in Instructeur.objects.annotate(email_normalise=Lower("email"))
        .filter(email_normalise__in=emails).select_related("id_agent_autorisations")
    } if emails else {}
    for document in annexes:
        auteur = auteur_annexe(document, dossier)
        compte = comptes.get(auteur)
        email = ((compte.email if compte else auteur) or "").strip().casefold()
        instructeur = instructeurs.get(email)
        agent = instructeur.id_agent_autorisations if instructeur else None
        nom_agent = " ".join(part.strip() for part in (agent.prenom, agent.nom) if part and part.strip()) if agent else ""
        document.depose_par = nom_agent or (compte.get_full_name().strip() if compte else "") or auteur
        document.peut_supprimer = peut_supprimer_annexe(document, dossier, user)
    return annexes
