import logging
import smbclient
import os
from smbprotocol import exceptions as smb_exceptions
from django.core.files.uploadedfile import UploadedFile
import platform
import subprocess
import re
import ntpath

from instruction.utils.document_utils import normaliser_emplacement


loggerApp = logging.getLogger("APP")



def _normalize_unc_path(p: str) -> str:
    if not p:
        return p

    # 1) Unifier les séparateurs
    p = p.strip().replace("/", "\\")

    # 2) Forcer EXACTEMENT deux backslashes au début (UNC),
    #    même si on en reçoit 1, 3, 4...
    p = re.sub(r"^\\+", r"\\\\", p)

    # 3) Réduire les backslashes multiples ailleurs à un seul,
    #    en conservant le préfixe UNC "\\"
    p = "\\\\" + re.sub(r"\\{2,}", r"\\", p[2:])

    return p


# Configuration
GROUPE_NAS = "autorisations"
GROUPE_NAS_LINUX = r"PNRUN\autorisations"
GROUPE_NAS_SMB = "PNRUN\\autorisations"
NAS_ROOT = os.getenv('NAS_ROOT').rstrip("\\/")
NAS_UNC_PREFIX = _normalize_unc_path(f"{NAS_ROOT}")
NAS_MOUNT_POINT = "/mnt/nas_autorisations"  # point de montage sur Linux


def ecrire_file_sur_nas(source, chemin_destination):
    """
    Écrit un fichier sur le NAS via SMB (écrase si un fichier du meme nom existe deja)
    Peut écrire depuis :
        - un fichier Django UploadedFile (ex: request.FILES['fichier'])
        - un chemin local (str) pointant vers un fichier existant

    Nécessite que smbclient.ClientConfig() ait été exécuté au démarrage (voir apps.py).

    :param source: objet UploadedFile OU chemin complet local (str)
    :param chemin_destination: chemin complet SMB distant (ex: //x-wing/autodev_data\Annexes\doc.pdf)
    :return: True si succès, False sinon
    """

    try:
        # --- Création du dossier distant si nécessaire ---
        dossier_parent = ntpath.dirname(chemin_destination)
        # loggerApp.warning(f"chemin_destination : {chemin_destination}")
        # loggerApp.warning(f"dossier_parent: {dossier_parent}")
        if not smbclient.path.exists(dossier_parent):
            smbclient.makedirs(dossier_parent)
            loggerApp.info(f"[NAS] Dossier créé sur le NAS : {normaliser_emplacement(dossier_parent)}")

        # --- Écriture selon le type de source ---
        if isinstance(source, UploadedFile):
            # Cas 1 : Fichier uploadé via Django
            with smbclient.open_file(chemin_destination, mode="wb") as dst:
                for chunk in source.chunks():
                    dst.write(chunk)
            loggerApp.info(f"[NAS] ✅ Fichier {source.name} écrit sur {chemin_destination}")
            src_label = source.name

        elif isinstance(source, str):
            # Cas 2 : Chemin local
            src_label = os.path.basename(source)

            if not smbclient.path.exists(source):
                loggerApp.error(f"[NAS] ❌ Le fichier local n'existe pas : {source}")
                return False
            
            with smbclient.open_file(source, "rb") as src, smbclient.open_file(chemin_destination, "wb") as dst:
                for chunk in iter(lambda: src.read(4096), b""):
                    dst.write(chunk)

            loggerApp.info(f"[NAS] Fichier {src_label} écrit sur {chemin_destination}")

        elif isinstance(source, bytes):
            src_label = chemin_destination.split("/")[-1]

            with smbclient.open_file(chemin_destination, mode="wb") as dst:
                dst.write(source)

            loggerApp.info(f"[NAS] Fichier {src_label} écrit sur {chemin_destination}")


        else:
            loggerApp.error(f"[NAS] ⚠️ Type de source non supporté : {type(source)}. La fonction 'ecrire_file_sur_nas' n'accepte que des UploadedFile ou des String (= path complet du fichier)")
            loggerApp.error(
                f"[NAS] ⚠️ Type de source non supporté : {type(source)}. "
                "La fonction 'ecrire_file_sur_nas' n'accepte que UploadedFile, str (= path complet du fichier) ou bytes."
            )
            
            return False

        return True

    # --- Gestion des erreurs spécifiques ---
    except smb_exceptions.LogonFailure as e:
        loggerApp.error(f"[NAS] ❌ Échec d’authentification SMB (admin_auto) lors de l'écriture du fichier {str(source)} : {e}")
    except smb_exceptions.SMBOSError as e:
        if "being used by another process" in str(e) :
            loggerApp.warning(f"[NAS] ⚠️ Erreur SMB lors de l'écriture du fichier {str(source)} : Le fichier était ouvert et donc bloqué par un utilisateur.")
        else :
            loggerApp.error(f"[NAS] ⚠️ Erreur SMB lors de l'écriture du fichier {str(source)} : {e}")
    except PermissionError as e:
        loggerApp.error(f"[NAS] ⛔ Permission refusée sur {chemin_destination} : {e}")
    except FileNotFoundError as e:
        loggerApp.error(f"[NAS] ❌ Fichier source {str(source)} introuvable : {e}")
    except Exception as e:
        loggerApp.exception(f"[NAS] ⚠️ Erreur inattendue lors de l’écriture du fichier {str(source)} : {e}")

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
            loggerApp.info(f"[NAS] Dossier créé sur le NAS : {normaliser_emplacement(chemin_dossier)}")
        return True
    except Exception as e:
        loggerApp.exception(f"[NAS] ⚠️ Erreur lors de la création du dossier NAS : {e}")
        return False



def supprimer_file_sur_nas(chemin_fichier):
    r"""
    Supprime un fichier sur le NAS via SMB.
    Nécessite que smbclient.ClientConfig() ait été exécuté au démarrage (voir apps.py).

    :param chemin_fichier: chemin complet SMB distant (ex: \\x-wing\autodev_data\Annexes\doc.pdf)
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




def _unc_to_mount_path(unc_path: str) -> str:
    # \\x-wing\autodev_data\foo\bar -> /mnt/nas_autorisations/foo/bar
    p = _normalize_unc_path(unc_path)
    if not p.startswith(NAS_UNC_PREFIX):
        raise ValueError(f"UNC inattendu: {unc_path}")
    suffix = p[len(NAS_UNC_PREFIX):].lstrip("\\/")
    return os.path.join(NAS_MOUNT_POINT, suffix.replace("\\", "/"))


def _unc_to_smb_share_and_relpath(unc_path: str) -> tuple[str, str]:
    # \\x-wing\autodev_data\foo\bar -> ("//x-wing/autodev_data", "foo/bar")
    p = _normalize_unc_path(unc_path)
    parts = p.lstrip("\\").split("\\")
    server, share = parts[0], parts[1]
    rel = "/".join(parts[2:])
    return f"//{server}/{share}", rel


def _apply_ntfs_modify_for_group(unc_path: str, group_domain: str) -> bool:
    smb_user = os.getenv("SMB_ACL_USER")
    smb_pass = os.getenv("SMB_ACL_PASS")
    smb_domain = os.getenv("SMB_ACL_DOMAIN", "PNRUN")

    if not smb_user or not smb_pass:
        loggerApp.error("[ACL][Linux][SMB] ❌ SMB_ACL_USER/SMB_ACL_PASS manquants.")
        return False

    smb_share, relpath = _unc_to_smb_share_and_relpath(unc_path)

    # Auth Samba : DOMAIN\user%password
    auth = f"{smb_domain}\\{smb_user}%{smb_pass}"

    ace = f"ACL:{group_domain}:ALLOWED/3/CHANGE"

    cmd = [
        "smbcacls",
        smb_share,
        relpath,
        "-U", auth,
        "--add", ace,
    ]


    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    if result.returncode != 0:
        loggerApp.error(
            f"[ACL][Linux][SMB] ❌ smbcacls KO sur {smb_share}/{relpath}. "
            f"stdout={result.stdout.strip()} stderr={result.stderr.strip()}"
        )
        return False

    loggerApp.info(f"[ACL][Linux][SMB] ✅ Modify accordé à {group_domain} sur {smb_share}/{relpath}")
    return True



def donner_droits_ecriture_groupe(dossier_work: str) -> bool:
    """
    Donne les droits de modification au groupe AD sur le dossier Work.

    - Windows : icacls
    - Linux   : crée le dossier via /mnt (CIFS) puis applique ACL NTFS via smbcacls
    """
    system = platform.system()

    try:
        # normalisation antislashs
        dossier_work_unc = _normalize_unc_path(dossier_work)


        if system == "Windows": 
            # Ici on attend un UNC utilisable par icacls
            if not creer_dossier_sur_nas(dossier_work_unc):
                loggerApp.error(f"[ACL][Windows] ❌ Le dossier {dossier_work_unc} n'existe pas.")
                return False

            cmd = [
                "icacls",
                dossier_work_unc,
                "/grant",
                f"{GROUPE_NAS_LINUX}:(OI)(CI)M"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

            if result.returncode != 0:
                loggerApp.error(
                    f"[ACL][Windows] ❌ Droits 'Modify' non accordés à '{GROUPE_NAS_LINUX}' sur {dossier_work_unc}. "
                    f"Erreur icacls : {result.stderr or result.stdout}"
                )
                return False

            return True

        elif system == "Linux":
            # 0) On attend un UNC pour pouvoir calculer le chemin monté + appliquer smbcacls
            # if not dossier_work_unc.startswith(NAS_UNC_PREFIX):
            if not (dossier_work_unc == NAS_UNC_PREFIX or dossier_work_unc.startswith(NAS_UNC_PREFIX + "\\")):
                loggerApp.error(f"[ACL][Linux] ❌ UNC attendu (prefix {NAS_UNC_PREFIX}) : {dossier_work_unc}")
                return False

            # 1) Sécurité : le NAS doit être monté, sinon on risquerait de créer localement
            if not os.path.ismount(NAS_MOUNT_POINT):
                loggerApp.error(f"[ACL][Linux] ❌ NAS non monté sur {NAS_MOUNT_POINT}")
                return False

            # 2) Créer le dossier via le montage
            dossier_work_mount = _unc_to_mount_path(dossier_work_unc)
            os.makedirs(dossier_work_mount, exist_ok=True)
            loggerApp.info(f"[ACL][Linux] 📁 Dossier créé via mount : {dossier_work_mount}")

            # 3) Appliquer ACL NTFS (Modify) via SMB sur le UNC (pas setfacl)
            ok = _apply_ntfs_modify_for_group(dossier_work_unc, GROUPE_NAS_SMB)
            return ok

        else:
            loggerApp.error(f"[ACL] ⚠️ Système non supporté : {system}")
            return False

    except FileNotFoundError as e:
        loggerApp.error(f"[ACL] ❌ Outil manquant : {e}")
    except Exception as e:
        loggerApp.exception(f"[ACL] ⚠️ Erreur inattendue lors de l’attribution des droits : {e}")

    return False




def copier_dossier_smb(src, dst, logger):
    """
    Copie récursivement un dossier sur un partage SMB.

    Args:
        src (str): chemin source
        dst (str): chemin destination
    """

    # Si le dossier source n'existe pas → rien à faire
    if not smbclient.path.exists(src):
        logger.warning(f"[COPY FILE] Dossier source introuvable : {src}")
        return

    # Créer le dossier destination si besoin
    if not smbclient.path.exists(dst):
        smbclient.makedirs(dst)

    for item in smbclient.listdir(src):
        src_path = os.path.join(src, item)
        dst_path = os.path.join(dst, item)

        if smbclient.path.isdir(src_path):
            # récursif
            copier_dossier_smb(src_path, dst_path, logger)

        else:
            # copie fichier
            with smbclient.open_file(src_path, mode="rb") as fsrc:
                with smbclient.open_file(dst_path, mode="wb") as fdst:
                    fdst.write(fsrc.read())

            logger.info(f"[COPY FILE] {_normalize_unc_path(src_path)} -> {_normalize_unc_path(dst_path)}")



def supprimer_dossier_smb_recursif(path, logger=None):
    """
    Supprime récursivement un dossier SMB et tout son contenu.
    """
    if not smbclient.path.exists(path):
        if logger:
            logger.warning(f"[DELETE DOSSIER] Dossier introuvable : {path}")
        return

    for item in smbclient.listdir(path):
        item_path = os.path.join(path, item)

        if smbclient.path.isdir(item_path):
            supprimer_dossier_smb_recursif(item_path, logger=logger)
        else:
            smbclient.remove(item_path)
            if logger:
                logger.info(f"[DELETE DOSSIER] Dossier non vide, Fichier supprimé : {item_path}")

    smbclient.rmdir(path)
