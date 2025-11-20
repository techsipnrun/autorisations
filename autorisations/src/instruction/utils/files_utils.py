import logging
import os
import smbclient
from django.shortcuts import redirect
from django.contrib import messages

from autorisations.utils.nas_fonctions import ecrire_file_sur_nas
from instruction.utils.dossier_utils import redirect_error

logger = logging.getLogger("ORM_DJANGO")



def save_if_not_exists(request, dossier, file_obj, dest_path, fail_if_exists=True):
    """
    Sauvegarde un fichier sur le NAS uniquement s’il n’existe pas déjà.
    Renvoie :
        - None   → OK
        - redirect(...) → en cas d’erreur, géré proprement via redirect_error
    """

    # Le dossier_path est juste utile pour les logs
    dossier_path = os.path.dirname(dest_path).replace("\\", "/")

    # Déjà présent → OK
    if smbclient.path.exists(dest_path) and fail_if_exists :
        logger.info(f"[DOSSIER {dossier.numero}] Pas d'écriture par {request.user} car un fichier du même nom existe déjà : {dossier_path}")
        return redirect_error(request, f"❌ Impossible d'enregistrer le fichier {file_obj.name} : Un fichier du même nom existe déjà à l'emplacement {dossier_path}")

    try:
        if not ecrire_file_sur_nas(file_obj, dest_path):
            raise Exception(f"Échec de l’écriture du fichier {dossier_path} sur le NAS par {request.user}.")

        logger.info(f"[DOSSIER {dossier.numero}] '{file_obj.name}' enregistré dans le Dossier Work par {request.user}.")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'écriture du fichier {dossier_path} sur le NAS par {request.user} : {e}")
        return redirect_error(request, f"❌ Impossible d’enregistrer le fichier {file_obj.name}. Contactez le support.")

    return None
