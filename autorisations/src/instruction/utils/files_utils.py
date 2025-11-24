import json
import logging
import os
import smbclient
from django.shortcuts import redirect
from django.contrib import messages

from autorisations import settings
from autorisations.models.models_documents import Document, DossierDocument
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


def generate_unique_filename(dir_abs_path: str, dir_rel_path: str, base_filename: str):
    """
    Génère un nom de fichier unique en vérifiant :
      - la présence physique dans dir_abs_path
      - la présence en BDD via model (Document par défaut)

    Renvoie : (titre_final, nom_complet)
        titre_final : nom sans extension (ex: "rapport_2")
        abs_file_path : Chemin absolu de "rapport_2.pdf"

    dir_abs_path : chemin absolu du dossier contenant le file (ex: /mnt/nas/D123/Actes/)
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




def save_and_update_document(request, dossier, fichier, document, format_obj, nature_obj, statut_obj, abs_file_path, rel_dir_path):
    """
    Écrit physiquement un document (écrasement si deja présent) et met à jour l’objet Document associé.
    Renvoie : None ou redirect_error(...)
    """

    num = dossier.numero

    # 1) Supprimer l'ancien doc si doublon
    doc_existant = Document.objects.filter(emplacement=rel_dir_path, titre=document.titre).first()

    if doc_existant and doc_existant.id != document.id:
        try:
            DossierDocument.objects.filter(id_document=doc_existant.id).delete()
            doc_existant.delete()
            logger.warning(f"[DOSSIER {num}] Ancien DossierDocument (id document={doc_existant.id}) supprimé par {request.user}.")
        except Exception as e:
            logger.error(f"[DOSSIER {num}] Erreur lors de la suppression de l'ancien DossierDocument (id document={doc_existant.id}) : {e}")
            return redirect_error(request, "❌ Erreur lors de la suppression de l'ancien acte du même nom. Contactez le support.")

    # 2) Log écrasement éventuel
    if smbclient.path.exists(abs_file_path):
        logger.warning(f"[DOSSIER {num}] Écrasement de l'acte existant (avec le même nom) par {request.user} : {abs_file_path}")

    # 3) Écriture physique
    if not ecrire_file_sur_nas(fichier, abs_file_path):
        logger.error(f"[DOSSIER {num}] Échec de l’écriture du fichier {fichier.name} sur {abs_file_path}")
        return redirect_error(request, f"❌ Échec de l’écriture du fichier {fichier.name} dans {abs_file_path}. Contactez le support.")

    logger.info(f"[DOSSIER {num}] Fichier '{document.titre}' écrit dans {abs_file_path}")

    # 4) Mise à jour du Document en BDD
    try:
        document.id_format = format_obj
        document.id_nature = nature_obj
        document.id_statut = statut_obj
        document.emplacement = rel_dir_path
        document.description = f"{nature_obj.nature} pour le dossier {dossier.numero}"
        document.save()

    except Exception as e:
        logger.error(f"[DOSSIER {num}] Erreur MAJ Document {document.id} : {e}")
        return redirect_error(request, "❌ Erreur lors de la mise à jour du Document {document.titre} en base. Contactez le support.")

    return None


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
