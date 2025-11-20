import logging

from django.shortcuts import redirect
from autorisations.models.models_instruction import Dossier
from django.contrib import messages

from autorisations.models.models_utilisateurs import Instructeur

logger = logging.getLogger("ORM_DJANGO")



def get_instructeur_or_redirect(request, numero_dossier, action):
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {numero_dossier}] Tentative d'action ({action}) du User {request.user} sans profil Instructeur.")
        messages.error(request, "Vous devez disposer d’un profil Instructeur. Contactez le support.")
        return None, redirect(request.META.get("HTTP_REFERER", "/"))
    return instructeur, None

