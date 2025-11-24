import logging
import smbclient
import os
from smbprotocol import exceptions as smb_exceptions
from django.core.files.uploadedfile import UploadedFile
import platform
import subprocess


loggerApp = logging.getLogger("APP")

# Configuration
GROUPE_NAS = "autorisations"
GROUPE_NAS_LINUX = "PNRUN\\autorisations"
NAS_UNC_PREFIX = r"\\orangers\autodev_data"
NAS_MOUNT_POINT = "/mnt/nas_autorisations"  # point de montage sur Linux


def _is_unc(path: str) -> bool:
    """Retourne True si le chemin est de type UNC."""
    return path.startswith("\\\\") or path.startswith("smb://")


def _to_local_if_needed(path: str) -> str:
    """Convertit un chemin UNC en chemin local monté, sinon le renvoie inchangé."""
    if _is_unc(path):
        return path.replace(NAS_UNC_PREFIX, NAS_MOUNT_POINT).replace("\\", "/")
    return path


def ecrire_file_sur_nas(source, chemin_destination):
    """
    Écrit un fichier sur le NAS via SMB.
    Peut écrire depuis :
        - un fichier Django UploadedFile (ex: request.FILES['fichier'])
        - un chemin local (str) pointant vers un fichier existant

    Nécessite que smbclient.ClientConfig() ait été exécuté au démarrage (voir apps.py).

    :param source: objet UploadedFile OU chemin complet local (str)
    :param chemin_destination: chemin complet SMB distant (ex: //orangers/autodev_data\Annexes\doc.pdf)
    :return: True si succès, False sinon
    """

    try:
        # --- Création du dossier distant si nécessaire ---
        dossier_parent = os.path.dirname(chemin_destination)
        if not smbclient.path.exists(dossier_parent):
            smbclient.makedirs(dossier_parent)
            loggerApp.info(f"[NAS] 📁 Dossier créé sur le NAS : {dossier_parent}")

        # --- Écriture selon le type de source ---
        if isinstance(source, UploadedFile):
            # ✅ Cas 1 : Fichier uploadé via Django
            with smbclient.open_file(chemin_destination, mode="wb") as dst:
                for chunk in source.chunks():
                    dst.write(chunk)
            loggerApp.info(f"[NAS] ✅ Fichier {source.name} écrit sur {chemin_destination}")

        elif isinstance(source, str):
            # ✅ Cas 2 : Chemin local
            if not smbclient.path.exists(source):
                loggerApp.error(f"[NAS] ❌ Le fichier local n'existe pas : {source}")
                return False

            with open(source, "rb") as src, smbclient.open_file(chemin_destination, mode="wb") as dst:
                for chunk in iter(lambda: src.read(4096), b""):
                    dst.write(chunk)
            loggerApp.info(f"[NAS] ✅ Fichier {source.name} écrit sur {chemin_destination}")

        else:
            loggerApp.error(f"[NAS] ⚠️ Type de source non supporté : {type(source)}. La fonction 'ecrire_file_sur_nas' n'accepte que des UploadedFile ou des String (= path complet du fichier)")
            return False

        return True

    # --- Gestion des erreurs spécifiques ---
    except smb_exceptions.LogonFailure as e:
        loggerApp.error(f"[NAS] ❌ Échec d’authentification SMB (admin_auto) lors de l'écriture du fichier {source.name} : {e}")
    except smb_exceptions.SMBOSError as e:
        loggerApp.error(f"[NAS] ⚠️ Erreur SMB lors de l'écriture du fichier {source.name} : {e}")
    except PermissionError as e:
        loggerApp.error(f"[NAS] ⛔ Permission refusée sur {chemin_destination} : {e}")
    except FileNotFoundError as e:
        loggerApp.error(f"[NAS] ❌ Fichier source {source.name} introuvable : {e}")
    except Exception as e:
        loggerApp.exception(f"[NAS] ⚠️ Erreur inattendue lors de l’écriture du fichier {source.name} : {e}")

    return False


def creer_dossier_sur_nas(chemin_dossier):
    """
    Crée un dossier (et ses parents) sur le NAS si nécessaire.
    :param chemin_dossier: chemin complet SMB distant
    :return: True si le dossier existe ou a été créé, False sinon
    """
    try:
        if not smbclient.path.exists(chemin_dossier):
            smbclient.makedirs(chemin_dossier)
            loggerApp.info(f"[NAS] 📁 Dossier créé sur le NAS : {chemin_dossier}")
        return True
    except Exception as e:
        loggerApp.exception(f"[NAS] ⚠️ Erreur lors de la création du dossier NAS : {e}")
        return False



def supprimer_file_sur_nas(chemin_fichier):
    r"""
    Supprime un fichier sur le NAS via SMB.
    Nécessite que smbclient.ClientConfig() ait été exécuté au démarrage (voir apps.py).

    :param chemin_fichier: chemin complet SMB distant (ex: \\orangers\autodev_data\Annexes\doc.pdf)
    :return: True si succès, False sinon
    """

    try:
        # Vérifie si le fichier existe sur le NAS
        if not smbclient.path.exists(chemin_fichier):
            loggerApp.warning(f"[NAS] ⚠️ Fichier introuvable sur le NAS : {chemin_fichier}")
            return False

        # Suppression du fichier distant
        smbclient.remove(chemin_fichier)
        loggerApp.info(f"[NAS] 🗑️ Fichier supprimé du NAS : {chemin_fichier}")
        return True

    except smb_exceptions.LogonFailure as e:
        loggerApp.error(f"[NAS] ❌ Échec d’authentification SMB (admin_auto) lors de la suppression du {chemin_fichier} : {e}")
    except smb_exceptions.SMBOSError as e:
        loggerApp.error(f"[NAS] ⚠️ Erreur SMB lors de la suppression du {chemin_fichier} : {e}")
    except PermissionError as e:
        loggerApp.error(f"[NAS] ⛔ Permission refusée pour supprimer {chemin_fichier} : {e}")
    except FileNotFoundError as e:
        loggerApp.error(f"[NAS] ❌ Fichier non trouvé pour suppression du fichier {chemin_fichier} : {e}")
    except Exception as e:
        loggerApp.exception(f"[NAS] ⚠️ Erreur inattendue lors de la suppression du fichier {chemin_fichier} : {e}")

    return False




def donner_droits_ecriture_groupe(dossier_work: str) -> bool:
    """
    Donne les droits d'écriture (modification) au groupe défini sur un dossier 'Work'.

    - Windows : utilise icacls (droits Modify)
    - Linux   : utilise setfacl (droits rwx)
    Le dossier doit exister et le groupe est constant (défini en haut du fichier).
    """
    system = platform.system()

    try:
        # On dédoublone les antislashs
        dossier_work = dossier_work.replace('\\\\', '\\')

        if system == "Linux":
            # Convertir UNC vers chemin monté localement
            if dossier_work.startswith(NAS_UNC_PREFIX):
                dossier_work = dossier_work.replace(NAS_UNC_PREFIX, NAS_MOUNT_POINT).replace("\\", "/")
                loggerApp.info(f"[ACL][Linux] 🔄 Conversion UNC → local : {dossier_work}")
            elif not dossier_work.startswith("/mnt"):
                loggerApp.warning(f"[ACL][Linux] Chemin non NAS : {dossier_work}")
                return False
            
            # Créer localement si le dossier n'existe pas
            if not os.path.exists(dossier_work):
                os.makedirs(dossier_work, exist_ok=True)
                loggerApp.info(f"[ACL][Linux] 📁 Dossier créé localement : {dossier_work}")

        if system == "Windows" :
            if not creer_dossier_sur_nas(dossier_work):
            # if not creer_dossier_sur_nas("\\\\orangers\\autodev_data\\Travaux/2025/Aire_adhesion/24314203_commune_de_saint_paul_20-05/Work") :
                loggerApp.error(f"[ACL] ❌ Le dossier {dossier_work} n'existe pas.")
                return False
            

        if system == "Windows":

            cmd = [
                "icacls",
                dossier_work,
                "/grant",
                f"{GROUPE_NAS}:(OI)(CI)M"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                loggerApp.error(f"[ACL][Windows] ❌ Erreur icacls : {result.stderr or result.stdout}")
                return False

            loggerApp.info(f"[ACL][Windows] ✅ Droits 'Modify' accordés à '{GROUPE_NAS}' sur {dossier_work}")
            return True

        elif system == "Linux":
            # Linux nécessite que le partage soit monté localement
            if dossier_work.startswith("\\\\"):
                loggerApp.error(f"[ACL][Linux] ⚠️ Chemin UNC non supporté : {dossier_work}")
                return False

            cmds = [
                ["setfacl", "-m", f"g:{GROUPE_NAS_LINUX}:rwx", dossier_work],
                ["setfacl", "-d", "-m", f"g:{GROUPE_NAS_LINUX}:rwx", dossier_work]
            ]

            for cmd in cmds:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    loggerApp.error(f"[ACL][Linux] ❌ Erreur setfacl : {result.stderr or result.stdout}")
                    return False

            loggerApp.info(f"[ACL][Linux] ✅ Droits 'rwx' accordés à '{GROUPE_NAS_LINUX}' sur {dossier_work}")
            return True

        else:
            loggerApp.error(f"[ACL] ⚠️ Système non supporté : {system}")
            return False

    except FileNotFoundError as e:
        loggerApp.error(f"[ACL] ❌ Outil manquant ({'icacls' if system == 'Windows' else 'setfacl'}) : {e}")
    except Exception as e:
        loggerApp.exception(f"[ACL] ⚠️ Erreur inattendue lors de l’attribution des droits : {e}")

    return False
