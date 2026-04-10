import json
import logging
import ntpath
import os
import smbclient
from django.shortcuts import redirect
from django.contrib import messages

import re
from django.utils.text import get_valid_filename

from autorisations import settings
from autorisations.models.models_documents import Document, DossierDocument
from autorisations.utils.nas_fonctions import _normalize_unc_path, ecrire_file_sur_nas
from instruction.utils.dossier_utils import redirect_error

logger = logging.getLogger("ORM_DJANGO")



# def save_if_not_exists(request, dossier, file_obj, dest_path, fail_if_exists=True):
#     """
#     Sauvegarde un fichier sur le NAS uniquement s’il n’existe pas déjà.
#     Renvoie :
#         - None   → OK
#         - redirect(...) → en cas d’erreur, géré proprement via redirect_error
#     """

#     # Le dossier_path est juste utile pour les logs
#     dossier_path = ntpath.dirname(dest_path).replace("\\", "/")

#     # Déjà présent → OK
#     if smbclient.path.exists(dest_path) and fail_if_exists :
#         logger.info(f"[DOSSIER {dossier.numero}] Pas d'écriture par {request.user} car un fichier du même nom existe déjà : {_normalize_unc_path(dossier_path)}")
#         return redirect_error(request, f"❌ Impossible d'enregistrer le fichier {file_obj.name} : Un fichier du même nom existe déjà à l'emplacement {_normalize_unc_path(dossier_path)}")

#     try:
#         if not ecrire_file_sur_nas(file_obj, dest_path):
#             raise Exception(f"Échec de l’écriture du fichier {_normalize_unc_path(dossier_path)} sur le NAS par {request.user}.")

#         logger.info(f"[DOSSIER {dossier.numero}] '{file_obj.name}' enregistré dans le Dossier Work par {request.user}.")

#     except Exception as e:
#         logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'écriture du fichier {_normalize_unc_path(dossier_path)} sur le NAS par {request.user} : {e}")
#         return redirect_error(request, f"❌ Impossible d’enregistrer le fichier {file_obj.name}. Contactez le support.")

#     return None


def generate_unique_filename(dir_abs_path: str, dir_rel_path: str, base_filename: str):
    """
    Génère un nom de fichier unique en vérifiant :
      - la présence physique dans dir_abs_path
      - la présence en BDD via model (Document par défaut)

    Renvoie : (titre_final, nom_complet)
        titre_final : nom sans extension (ex: "rapport_2")
        abs_file_path : Chemin absolu de "rapport_2.pdf"

    dir_abs_path : chemin absolu du dossier /Actes
    dir_rel_path : chemin relatif (= emplacement doc BDD) du dossier contenant le file (ex: D123/Actes/)
    base_filename : nom du fichier d'origine (ex: "rapport.pdf")
    """

    try:
        nom_base, ext = os.path.splitext(base_filename)
        titre_final = nom_base
        i = 1

        while True:
            nom_complet = f"{titre_final}{ext}"
            abs_file_path = os.path.join(dir_abs_path, nom_complet)

            fichier_existe = smbclient.path.exists(abs_file_path)

            enregistrement_existe = Document.objects.filter(emplacement=dir_rel_path,titre=nom_complet).exists()

            if not fichier_existe and not enregistrement_existe:
                return titre_final, abs_file_path

            i += 1
            titre_final = f"{nom_base}_{i}"

    except Exception as e:
        raise(f"Erreur lors de la génération d'un nom unique pour le fichier {base_filename} à l'emplacement {dir_abs_path} : {e}")



def load_geojson(rel_path: str):
    """
    Charge un fichier GeoJSON depuis le dossier static.
    Ne lève pas d'exception : log en cas d'erreur et renvoie {}.
    """
    try:
        abs_path = os.path.join(settings.BASE_DIR, rel_path)
        with open(abs_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[GEOJSON] Impossible de charger le fichier {rel_path} : {e}")
        return {}


def valider_fichiers_dm(fichiers, size_max, extensions_ok):
    for fichier in fichiers:
        if fichier.size > size_max:
            raise ValueError(f"Le fichier '{fichier.name}' dépasse la taille maximale autorisée de 5 Mo.")

        _, ext = os.path.splitext(fichier.name)
        ext = ext.lower().lstrip(".")

        if ext not in extensions_ok:
            raise ValueError(f"Le fichier '{fichier.name}' a une extension non autorisée (.{ext}).")
        

def sanitiser_nom_fichier(nom):
    nom = os.path.basename(nom.strip())
    nom = get_valid_filename(nom)
    nom = re.sub(r"[^\w.\- ]", "_", nom)
    return nom