import json
import logging
import ntpath
import os
import re
import tempfile
import time
import uuid
from http.client import IncompleteRead
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from typing import Optional
import unicodedata
from requests.exceptions import ChunkedEncodingError
import smbclient
from smbprotocol import exceptions as smb_exceptions
from pathlib import Path

import requests
from django.core.files.uploadedfile import SimpleUploadedFile

from autorisations.utils.nas_fonctions import _normalize_unc_path, creer_dossier_sur_nas, donner_droits_ecriture_groupe, ecrire_file_sur_nas
from instruction.utils.document_utils import normaliser_emplacement
from synchronisation.utils.conversion import formater_nom_personne_morale, parse_datetime_with_tz


loggerORM = logging.getLogger("ORM_DJANGO")
loggerApp = logging.getLogger("APP")
loggerDS = logging.getLogger("API_DS")
loggerSynchro = logging.getLogger("SYNCHRONISATION")


# Les traces de réussite détaillées sont réservées aux PJ réellement volumineuses.
SEUIL_LOG_PJ_DETAILLE_OCTETS = 20 * 1024 * 1024

# Vérification de la présence de NAS_ROOT
if not os.environ.get("NAS_ROOT"):
    raise RuntimeError("La variable d'environnement NAS_ROOT est requise.")


def ensure_dossier_root(emplacement: str) -> Optional[str]:
    """
    Crée le dossier racine basé sur la variable d’environnement NAS_ROOT et retourne son chemin complet.

    Args:
        emplacement (str): Chemin relatif à la racine NAS_ROOT.

    Returns:
        Optional[str]: Chemin absolu du dossier créé ou existant, ou None si NAS_ROOT est manquant.
    """
    # racine = os.environ.get("NAS_ROOT")
    racine = os.environ.get("NAS_ROOT")

    if not racine:
        loggerApp.error("[ACCÈS NAS] Variable NAS_ROOT manquante.")
        return None
    
    chemin = os.path.join(racine, emplacement)
    creer_dossier_sur_nas(chemin)
    return chemin





def write_resume_pdf(emplacement, name, url_du_pdf):
    """
    Télécharge un PDF depuis une URL et l’enregistre sur le NAS dans le dossier spécifié.

    Args:
        emplacement (str): Chemin relatif à NAS_ROOT (ex: "Dossiers/12345/").
        name (str): Nom du fichier PDF (avec extension).
        url_du_pdf (str): URL publique du fichier PDF à télécharger.

    Returns:
        Optional[str]: Chemin complet sur le NAS du fichier créé, ou None en cas d’échec.
    """

    # Construction du chemin complet SMB
    nas_root = os.getenv("NAS_ROOT")
    if not nas_root:
        loggerApp.error("[NAS] ❌ Variable d'environnement NAS_ROOT non définie.")
        return None
    chemin_fichier = _normalize_unc_path(ensure_dossier_root(emplacement))
    chemin_complet = _normalize_unc_path(os.path.join(chemin_fichier, name))

    max_retries = 3
    for tentative in range(1, max_retries + 1):
        try:
            # Le timeout de lecture est par bloc reçu : il couvre les PDF DN dont la
            # génération ou l'envoi dépasse ponctuellement les 20 secondes précédentes.
            with requests.get(
                url_du_pdf,
                stream=True,
                timeout=(10, 120),
                headers={"Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                contenu = b"".join(
                    chunk for chunk in response.iter_content(chunk_size=256 * 1024) if chunk
                )

            if not contenu:
                raise _PJTelechargementIncomplet("PDF récapitulatif vide.")

            fichier_temp = SimpleUploadedFile(
                name=name,
                content=contenu,
                content_type="application/pdf",
            )
            if ecrire_file_sur_nas(fichier_temp, chemin_complet):
                return chemin_complet

            loggerORM.error(
                "[RESUME PDF NAS ERROR] %s - écriture sur le NAS impossible.", name,
            )
            return None

        except (
            requests.exceptions.RequestException,
            IncompleteRead,
            Urllib3HTTPError,
            _PJTelechargementIncomplet,
        ) as erreur:
            cause = _cause_transfert_sans_url(erreur)
            if tentative == max_retries:
                loggerORM.error(
                    "[RESUME PDF HTTP ERROR] %s - téléchargement DN impossible après %s tentatives : %s.",
                    name, max_retries, cause,
                )
                return None

            attente = 2 ** tentative
            loggerORM.warning(
                "[RESUME PDF HTTP RETRY] %s - tentative %s/%s échouée (%s), nouvel essai dans %s s.",
                name, tentative, max_retries, cause, attente,
            )
            time.sleep(attente)
        except Exception as erreur:
            loggerORM.error(
                "[RESUME PDF ERROR] %s - erreur inattendue lors du téléchargement ou de l’écriture : %s.",
                name, type(erreur).__name__,
            )
            return None

    return None




def write_geojson(emplacement, nom_geojson, contenu_geojson):
    """
    Écrit un fichier GeoJSON (.geojson) dans un dossier spécifique. Le fichier est écrasé s’il existe.

    Args:
        emplacement (str): Chemin relatif à NAS_ROOT.
        nom_geojson (str): Nom du fichier GeoJSON.
        contenu_geojson (dict): Données au format dict ou JSON serialisable.

    Returns:
        Optional[str]: Chemin absolu du fichier écrit, ou None en cas d’échec.
    """

    
    chemin_rel_pour_log = normaliser_emplacement(os.path.join(emplacement, nom_geojson))
    chemin_fichier = _normalize_unc_path(ensure_dossier_root(emplacement))
    chemin_complet = _normalize_unc_path(os.path.join(chemin_fichier, nom_geojson))

    try:
        # with open(chemin_complet, "w", encoding="utf-8") as f:
        with smbclient.open_file(chemin_complet, mode="w", encoding="utf-8") as f:
            json.dump(contenu_geojson, f, ensure_ascii=False, indent=2)
            
        loggerApp.info(f"[GEOJSON] Fichier écrit : {chemin_rel_pour_log}")
    except Exception as e:
        loggerApp.error(f"[GEOJSON] Erreur lors de l'écriture du fichier GeoJSON {chemin_complet} : {e}")

    return chemin_fichier



def write_pj(emplacement, name, url_pj, ecrase = False):
    """
    Télécharge une pièce jointe depuis une URL et l’enregistre dans le dossier demandé.

    Args:
        emplacement (str): Chemin relatif à NAS_ROOT (ex: "Activites/2025/123456_NOM/Annexes/").
        name (str): Nom du fichier avec extension (ex: "photo.jpg").
        url_pj (str): URL publique de la pièce jointe à télécharger.

    Returns:
        Optional[str]: Chemin absolu du fichier enregistré, ou None si le fichier existe déjà ou en cas d’erreur.
    """
    chemin_dossier = _normalize_unc_path(ensure_dossier_root(emplacement))

    safe_name = os.path.basename(name)
    chemin_fichier = _normalize_unc_path(os.path.join(chemin_dossier, safe_name))

    # chemin_final = get_nom_disponible(chemin_dossier, safe_name)
    # loggerApp.info(f"chemin_fichier : {chemin_fichier}")

    try:
        if smbclient.path.exists(chemin_fichier) and not ecrase:
            # loggerApp.warning(f"safe_name : {safe_name}  --- chemin_fichier : {chemin_fichier}")
            loggerApp.error(f"[FICHIER EXISTANT] La pièce jointe {chemin_fichier} existe déjà. Aucune écriture effectuée.")
            return

        # response = requests.get(url_pj, timeout=60)
        response = requests.get(url_pj, stream=True, timeout=(10, 300))
        response.raise_for_status()

        # Écriture
        fichier_temp = SimpleUploadedFile(name=name, content=response.content)
        if ecrire_file_sur_nas(fichier_temp, chemin_fichier):
            # loggerApp.info(f"[PJ] Pièce jointe téléchargée et écrite : {chemin_fichier}")
            return chemin_fichier
        else:
            loggerORM.error(f"[NAS] ❌ Échec lors de l’écriture de la pièce jointe '{name}' sur le NAS.")
            return None

    except requests.exceptions.RequestException as e:
        loggerORM.error(f"[HTTP ERROR] Erreur lors du téléchargement de la pièce jointe ({name}) : {e}")
    except Exception as e:
        loggerORM.error(f"[ECRITURE PJ] Erreur inattendue lors du téléchargement ou de l’écriture de la pièce jointe {chemin_fichier} : {e}")
    
    return None


class _PJContenuIncoherent(ValueError):
    """Le partiel ne peut pas être complété avec cette réponse HTTP."""


class _PJTelechargementIncomplet(ValueError):
    """La réponse s'est terminée avant la taille annoncée."""


class _PJErreurNAS(ValueError):
    """Écriture ou taille NAS incomplète, décrite sans URL distante."""


def _taille_pj(octets):
    return "taille inconnue" if octets is None else f"{octets / (1024 * 1024):.2f} Mo"


def _logger_info_pj_volumineuse(taille, message, *args):
    """Évite de remplir les logs avec les copies réussies de petites PJ."""
    if taille is not None and taille > SEUIL_LOG_PJ_DETAILLE_OCTETS:
        loggerApp.info(message, *args)


def _cause_transfert_sans_url(erreur):
    # Les messages requests/urllib3 peuvent contenir une URL signée. On décrit
    # les types réels et les codes, sans exposer le texte de ces exceptions.
    causes, a_visiter = [], [erreur]
    while a_visiter and len(causes) < 6:
        cause = a_visiter.pop(0)
        nom = type(cause).__name__
        if nom in causes:
            continue
        causes.append(nom)
        a_visiter.extend(arg for arg in cause.args if isinstance(arg, BaseException))
        if cause.__cause__ is not None:
            a_visiter.append(cause.__cause__)
    response = getattr(erreur, "response", None)
    code = f" - HTTP {response.status_code}" if response is not None else ""
    errno = getattr(erreur, "errno", None)
    if isinstance(errno, int):
        code += f" - errno {errno}"
    return " / ".join(causes) + code


def _telecharger_pj_localement(url_pj, name, temp_path, max_retries):
    taille_attendue = None
    validateur = None
    derniere_cause = ""

    def lire_validateur(response):
        etag = response.headers.get("ETag")
        if etag and not etag.startswith("W/"):
            return ("ETag", etag)
        modification = response.headers.get("Last-Modified")
        return ("Last-Modified", modification) if modification else None

    for tentative in range(1, max_retries + 1):
        offset = os.path.getsize(temp_path)
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
            if validateur:
                headers["If-Range"] = validateur[1]
            _logger_info_pj_volumineuse(
                taille_attendue,
                "[PJ RESUME] %s - reprise à l'octet %s - tentative %s/%s",
                name, offset, tentative, max_retries,
            )
        try:
            with requests.get(url_pj, stream=True, timeout=(10, 400), headers=headers) as response:
                # Une interruption peut survenir après réception du dernier octet.
                if response.status_code == 416:
                    match = re.fullmatch(r"bytes \*/(\d+)", response.headers.get("Content-Range", "").strip())
                    nouveau_validateur = lire_validateur(response)
                    if (match and offset == taille_attendue == int(match[1])
                            and not (validateur and nouveau_validateur and validateur != nouveau_validateur)):
                        _logger_info_pj_volumineuse(
                            offset,
                            "[PJ DOWNLOAD COMPLETE] %s - %s (taille confirmée par HTTP 416)",
                            name, _taille_pj(offset),
                        )
                        return True
                    raise _PJContenuIncoherent("HTTP 416 : le partiel ne correspond pas à la taille distante.")

                response.raise_for_status()
                if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
                    raise _PJContenuIncoherent("Réponse compressée malgré Accept-Encoding: identity.")

                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    if not content_length.strip().isdigit():
                        raise _PJContenuIncoherent("Content-Length invalide.")
                    content_length = int(content_length)

                nouveau_validateur = lire_validateur(response)
                if response.status_code == 206:
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", "").strip(),
                    )
                    if not match:
                        raise _PJContenuIncoherent("Content-Range absent ou invalide pour HTTP 206.")
                    debut, fin, total = map(int, match.groups())
                    if debut != offset or not debut <= fin < total:
                        raise _PJContenuIncoherent("Content-Range incompatible avec le partiel local.")
                    if content_length is not None and content_length != fin - debut + 1:
                        raise _PJContenuIncoherent("Content-Length incompatible avec Content-Range.")
                    if taille_attendue is not None and total != taille_attendue:
                        raise _PJContenuIncoherent("La taille distante a changé pendant le téléchargement.")
                    if validateur and nouveau_validateur and validateur != nouveau_validateur:
                        raise _PJContenuIncoherent("Le contenu distant a changé pendant le téléchargement.")
                    taille_attendue = total
                    fin_reponse = fin + 1
                    mode = "ab"
                    _logger_info_pj_volumineuse(
                        taille_attendue,
                        "[PJ RESUME OK] %s - serveur HTTP accepte Range - HTTP 206",
                        name,
                    )
                elif response.status_code == 200:
                    if offset:
                        loggerApp.warning("[PJ RESUME REFUSED] %s - HTTP 200 : reprise depuis zéro, sans concaténation.", name)
                    # HTTP 200 fournit le fichier entier : abandonner l'ancien partiel.
                    with open(temp_path, "wb"):
                        pass
                    offset = 0
                    taille_attendue = content_length
                    if taille_attendue is None:
                        raise _PJContenuIncoherent("Content-Length absent : impossible de vérifier le fichier complet.")
                    fin_reponse = taille_attendue
                    mode = "wb"
                    validateur = None
                else:
                    raise _PJContenuIncoherent(f"Réponse HTTP {response.status_code} inattendue.")

                validateur = nouveau_validateur or validateur
                _logger_info_pj_volumineuse(
                    taille_attendue,
                    "[PJ DOWNLOAD] %s - %s - taille attendue %s - tentative %s/%s",
                    name, "reprise" if offset else "téléchargement initial",
                    _taille_pj(taille_attendue), tentative, max_retries,
                )
                bytes_written = offset
                prochain_log = offset + max(5 * 1024 * 1024, taille_attendue // 5)
                with open(temp_path, mode) as dst:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        dst.write(chunk)
                        bytes_written += len(chunk)
                        if bytes_written > fin_reponse:
                            raise _PJContenuIncoherent("La réponse dépasse la taille annoncée.")
                        if bytes_written >= prochain_log:
                            _logger_info_pj_volumineuse(
                                taille_attendue,
                                "[PJ DOWNLOAD] %s - %s / %s",
                                name, _taille_pj(bytes_written), _taille_pj(taille_attendue),
                            )
                            prochain_log = bytes_written + max(5 * 1024 * 1024, taille_attendue // 5)

                taille_locale = os.path.getsize(temp_path)
                if taille_locale != taille_attendue or taille_locale != fin_reponse:
                    raise _PJTelechargementIncomplet(
                        f"{taille_locale} octets reçus / {taille_attendue} attendus."
                    )
                _logger_info_pj_volumineuse(
                    taille_locale, "[PJ DOWNLOAD COMPLETE] %s - %s", name, _taille_pj(taille_locale),
                )
                return True

        except _PJContenuIncoherent as erreur:
            derniere_cause = str(erreur)  # Messages internes, jamais d'URL.
            loggerORM.warning("[PJ HTTP INCOHERENT] %s - %s - partiel remis à zéro.", name, derniere_cause)
            with open(temp_path, "wb"):
                pass
            taille_attendue = validateur = None
        except _PJTelechargementIncomplet as erreur:
            derniere_cause = str(erreur)
            loggerORM.warning("[PJ HTTP INTERRUPTED] %s - %s déjà récupérés - %s", name, _taille_pj(os.path.getsize(temp_path)), derniere_cause)
        except (
            requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError,
            requests.exceptions.Timeout, requests.exceptions.RequestException,
            IncompleteRead, Urllib3HTTPError,
        ) as erreur:
            derniere_cause = _cause_transfert_sans_url(erreur)
            loggerORM.warning(
                "[PJ HTTP INTERRUPTED] %s - %s déjà récupérés - tentative %s/%s - %s",
                name, _taille_pj(os.path.getsize(temp_path)), tentative, max_retries, derniere_cause,
            )

        if tentative < max_retries:
            attente = 2 ** tentative
            _logger_info_pj_volumineuse(
                taille_attendue, "[PJ HTTP RETRY] %s - nouvelle tentative dans %s s.", name, attente,
            )
            time.sleep(attente)

    loggerORM.error(
        "[PJ ECHEC DEFINITIF] %s - téléchargement incomplet après %s tentatives - %s / %s récupérés - %s",
        name, max_retries, _taille_pj(os.path.getsize(temp_path)), _taille_pj(taille_attendue), derniere_cause,
    )
    return False


def _copier_pj_complete_sur_nas(temp_path, emplacement, chemin_fichier, name, ecrase, max_retries):
    taille_locale = os.path.getsize(temp_path)
    # Même répertoire que la destination : renommage SMB, sans collision entre workers.
    chemin_partiel = _normalize_unc_path(ntpath.join(
        ntpath.dirname(chemin_fichier), f"{name[:120]}.{uuid.uuid4().hex}.part",
    ))
    for tentative in range(1, max_retries + 1):
        try:
            ensure_dossier_root(emplacement)
            if not ecrase and smbclient.path.exists(chemin_fichier):
                loggerApp.warning("[FICHIER EXISTANT] %s - aucune écriture effectuée.", chemin_fichier)
                return False
            _logger_info_pj_volumineuse(
                taille_locale,
                "[PJ NAS COPY] %s - début copie vers %s - tentative %s/%s",
                name, chemin_partiel, tentative, max_retries,
            )
            with open(temp_path, "rb") as src, smbclient.open_file(chemin_partiel, mode="wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    if dst.write(chunk) != len(chunk):
                        raise _PJErreurNAS("Écriture NAS partielle.")
            taille_nas = smbclient.stat(chemin_partiel).st_size
            if taille_nas != taille_locale:
                raise _PJErreurNAS(f"Taille NAS incorrecte : {taille_nas} / {taille_locale} octets.")
            if ecrase:
                smbclient.replace(chemin_partiel, chemin_fichier)
            else:
                smbclient.rename(chemin_partiel, chemin_fichier)
            _logger_info_pj_volumineuse(
                taille_locale, "[PJ NAS OK] %s copié, vérifié et renommé avec succès.", name,
            )
            return True
        except Exception as erreur:
            loggerORM.warning(
                "[PJ NAS ERROR] %s - tentative %s/%s - %s - téléchargement local conservé.",
                name, tentative, max_retries,
                str(erreur) if isinstance(erreur, _PJErreurNAS) else _cause_transfert_sans_url(erreur),
            )
            try:
                smbclient.remove(chemin_partiel)
            except FileNotFoundError:
                pass
            except Exception as nettoyage:
                loggerORM.warning("[PJ NAS CLEANUP ERROR] %s - %s", name, _cause_transfert_sans_url(nettoyage))
            if tentative < max_retries:
                attente = 2 ** tentative
                _logger_info_pj_volumineuse(
                    taille_locale,
                    "[PJ NAS RETRY] %s - nouvelle copie dans %s s, sans téléchargement HTTP.",
                    name, attente,
                )
                time.sleep(attente)
    loggerORM.error("[PJ ECHEC DEFINITIF] %s - copie NAS impossible après %s tentatives.", name, max_retries)
    return False


def write_pj_volumineuse(emplacement, name, url_pj, ecrase=False):
    """HTTP -> partiel local reprenable -> partiel NAS vérifié -> nom définitif.

    Cinq tentatives HTTP puis cinq tentatives SMB indépendantes. Le partiel local
    est conservé entre les tentatives et supprimé à la fin de cet appel, y compris
    en cas d'abandon. Aucune URL signée n'est écrite dans les logs.
    """
    temp_path = None
    try:
        chemin_dossier = _normalize_unc_path(os.path.join(os.environ["NAS_ROOT"], emplacement))
        safe_name = ntpath.basename(name)
        chemin_fichier = _normalize_unc_path(os.path.join(chemin_dossier, safe_name))
        if not ecrase:
            try:
                if smbclient.path.exists(chemin_fichier):
                    loggerApp.warning("[FICHIER EXISTANT] %s - aucune écriture effectuée.", chemin_fichier)
                    return None
            except Exception as erreur:
                loggerORM.warning("[PJ NAS CHECK] %s - %s - contrôle reporté à la copie.", safe_name, _cause_transfert_sans_url(erreur))
        fd, temp_path = tempfile.mkstemp(prefix="agida-pj-", suffix=".part")
        os.close(fd)
        if not _telecharger_pj_localement(url_pj, safe_name, temp_path, max_retries=5):
            return None
        if _copier_pj_complete_sur_nas(temp_path, emplacement, chemin_fichier, safe_name, ecrase, max_retries=5):
            return chemin_fichier
    except Exception as erreur:
        loggerORM.error("[PJ ECHEC DEFINITIF] %s - préparation/écriture locale impossible - %s", name, _cause_transfert_sans_url(erreur))
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
            except OSError as erreur:
                loggerORM.warning("[PJ LOCAL CLEANUP ERROR] %s - %s", name, _cause_transfert_sans_url(erreur))
    return None

# from requests.exceptions import RequestException, ChunkedEncodingError, ConnectionError

# def write_pj_volumineuse(emplacement, name, url_pj, ecrase=False, max_retries=3):
#     chemin_dossier = ensure_dossier_root(emplacement)
#     safe_name = os.path.basename(name)
#     chemin_fichier = os.path.join(chemin_dossier, safe_name)

#     for tentative in range(1, max_retries + 1):
#         bytes_written = 0
#         total_mo = None

#         try:
#             if smbclient.path.exists(chemin_fichier) and not ecrase:
#                 loggerApp.error(f"[FICHIER EXISTANT] {chemin_fichier} existe déjà.")
#                 return None

#             start_time = time.time()

#             with requests.get(url_pj, stream=True, timeout=(10, 400)) as response:
#                 response.raise_for_status()

#                 total_size = response.headers.get("Content-Length")
#                 total_size = int(total_size) if total_size and total_size.isdigit() else None

#                 if total_size:
#                     total_mo = round(total_size / (1024 * 1024), 2)
#                     loggerApp.info(
#                         f"[PJ DOWNLOAD] Tentative {tentative}/{max_retries} - "
#                         f"Début téléchargement '{name}' ({total_mo} Mo)"
#                     )
#                 else:
#                     loggerApp.info(
#                         f"[PJ DOWNLOAD] Tentative {tentative}/{max_retries} - "
#                         f"Début téléchargement '{name}' (taille inconnue)"
#                     )

#                 last_log_percent = 0

#                 with smbclient.open_file(chemin_fichier, mode="wb") as dst:
#                     for chunk in response.iter_content(chunk_size=1024 * 1024):
#                         if chunk:
#                             dst.write(chunk)
#                             bytes_written += len(chunk)

#                             if total_size and total_mo and total_mo > 20:
#                                 percent = int((bytes_written / total_size) * 100)
#                                 if percent >= last_log_percent + 20:
#                                     loggerApp.info(
#                                         f"[PJ DOWNLOAD] {name} : {percent}% "
#                                         f"({round(bytes_written / (1024 * 1024), 2)} Mo)"
#                                     )
#                                     last_log_percent = percent

#             if total_size and bytes_written != total_size:
#                 raise IOError(
#                     f"Taille téléchargée incomplète : {bytes_written} octets écrits "
#                     f"/ {total_size} attendus"
#                 )

#             duration = round(time.time() - start_time, 2)
#             size_mo = round(bytes_written / (1024 * 1024), 2)

#             loggerApp.info(
#                 f"[PJ OK] {name} téléchargé ({size_mo} Mo) en {duration}s → {chemin_fichier}"
#             )

#             return chemin_fichier

#         except (RequestException, ChunkedEncodingError, ConnectionError, IOError) as e:
#             loggerORM.warning(
#                 f"[PJ RETRY] Tentative {tentative}/{max_retries} échouée pour {name} : {e}"
#             )

#             try:
#                 if smbclient.path.exists(chemin_fichier):
#                     smbclient.remove(chemin_fichier)
#                     loggerApp.warning(f"[CLEANUP] Fichier partiel supprimé : {chemin_fichier}")
#             except Exception as cleanup_error:
#                 loggerORM.warning(f"[CLEANUP ERROR] {name} : {cleanup_error}")

#             if tentative == max_retries:
#                 loggerORM.error(
#                     f"[PJ ECHEC] {name} non téléchargé après {max_retries} tentatives."
#                 )
#                 return None

#             time.sleep(5 * tentative)

#         except Exception as e:
#             loggerORM.exception(f"[ECRITURE PJ] {name} : {e}")

#             try:
#                 if smbclient.path.exists(chemin_fichier):
#                     smbclient.remove(chemin_fichier)
#                     loggerApp.warning(f"[CLEANUP] Fichier partiel supprimé : {chemin_fichier}")
#             except Exception:
#                 pass

#             return None

#     return None




def get_nom_disponible(dossier_path, nom_fichier):
    nom_base, ext = os.path.splitext(nom_fichier)
    nom_final = nom_base
    i = 2
    racine = os.environ.get("NAS_ROOT")
    chemin_complet = os.path.join(racine, dossier_path, nom_fichier)
    while smbclient.path.exists(chemin_complet):
        nom_final = f"{nom_base}_{i}"
        chemin_complet = os.path.join(racine, dossier_path, nom_final + ext)
        i += 1

    return nom_final + ext



def create_emplacement(emplacement_dossier):
    """
    Crée un dossier principal et les sous-dossiers standards s’il n’existe pas déjà.

    Args:
        emplacement_dossier (str): Chemin relatif à NAS_ROOT (ex: "Travaux/2025/123456_DUPONT_Jean").

    Returns:
        bool: True si les dossiers ont été créés ou existent déjà, False en cas d’erreur.
    """
    chemin_complet = _normalize_unc_path(ensure_dossier_root(emplacement_dossier))

    try:

        if not creer_dossier_sur_nas(chemin_complet) :
            loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
            return False


        # Sous-dossiers standards
        sous_dossiers = ["Annexes", "Actes", "Avis", "Carto", "Work"]
        for nom in sous_dossiers:
            chemin_sous_dossier = os.path.join(chemin_complet, nom)

            if not creer_dossier_sur_nas(chemin_sous_dossier) :
                loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
                return False
            
            if nom == 'Work' : 
                # Attribution des droits d'écriture
                donner_droits_ecriture_groupe(chemin_sous_dossier)
                
        return True
    
    except Exception as e:
        loggerApp.error(f"Impossible de créer les sous-dossiers pour {emplacement_dossier} : {e}")
        return False
    


def create_emplacement_manif_sportive(emplacement_dossier):
    """
    Pour un Dossier Déclaration Manifestations n'étant pas lié à un Dossier Démarche Numérique
    Crée un dossier principal et les sous-dossiers standards s’il n’existe pas déjà.

    Args:
        emplacement_dossier (str): Chemin relatif à NAS_ROOT (ex: "Manifestations_sportives/2025/trail_des_geants").

    Returns:
        bool: True si les dossiers ont été créés ou existent déjà, False en cas d’erreur.
    """
    chemin_complet = _normalize_unc_path(ensure_dossier_root(emplacement_dossier))

    try:

        if not creer_dossier_sur_nas(chemin_complet) :
            loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
            return False


        # Sous-dossiers standards
        sous_dossiers = ["Annexes", "Carto", "Work"]
        for nom in sous_dossiers:
            chemin_sous_dossier = os.path.join(chemin_complet, nom)

            if not creer_dossier_sur_nas(chemin_sous_dossier) :
                loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")
                return False
            
            if nom == 'Work' : 
                # Attribution des droits d'écriture
                donner_droits_ecriture_groupe(chemin_sous_dossier)
             
        return True
    
    except Exception as e:
        loggerApp.error(f"Dossier Déclaration Manifestations n'étant pas lié à un Dossier Démarche Numérique : Impossible de créer les sous-dossiers pour {emplacement_dossier} : {e}")
        return False


def fetch_geojson(url: str) -> Optional[dict]:
    """
    Récupère un fichier GeoJSON à partir d'une URL.

    Args:
        url (str): URL du fichier GeoJSON.

    Returns:
        dict | None: Données GeoJSON si succès, sinon None.
    """
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        loggerDS.error(f"[GEOJSON] Timeout lors de la requête vers {url}")
    except requests.exceptions.HTTPError as e:
        loggerDS.error(f"[GEOJSON] Erreur HTTP {response.status_code} : {e}")
    except requests.exceptions.RequestException as e:
        loggerDS.error(f"[GEOJSON] Erreur réseau lors de la récupération de {url} : {e}")
    except ValueError as e:
        loggerDS.error(f"[GEOJSON] Réponse invalide pour {url} : {e}")
    except Exception as e:
        loggerDS.exception(f"[GEOJSON] Erreur inattendue : {e}")
    return None


import json

def geoareas_to_geojson_text(geoareas):
    """
    Convertit une liste de géométries (geoAreas) en texte GeoJSON exploitable.
    
    :param geoareas: Liste de dictionnaires contenant des objets {"geometry": {...}}
    :return: Chaîne GeoJSON (format texte JSON)
    """
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": item["geometry"],
                "properties": {}
            }
            for item in geoareas if "geometry" in item
        ]
    }
    return geojson



def construire_emplacement_dossier(doss: dict, contact_beneficiaire: dict, titre_demarche: str) -> str:
    """
    Construit dynamiquement un chemin d’emplacement pour stocker un dossier.

    Args:
        doss (dict): Dictionnaire représentant le dossier DS (inclut 'number', 'dateDepot', 'demandeur').
        contact_beneficiaire (dict): Dictionnaire contenant les infos du bénéficiaire (nom, prénom).
        titre_demarche (str): Titre de la démarche (sert à classer dans le bon dossier).

    Returns:
        str: Chemin relatif type "Travaux/2025/Soumis_urbanisme/123456_DUPONT_Jean_22-03"
    """
    titre = (titre_demarche or "").lower()

    # 1. Type autorisation
    if "travaux" in titre:
        type_autorisation = "Travaux"
    elif "mission scientifique" in titre:
        type_autorisation = "Missions_scientifiques"
    elif "activités commerciales" in titre:
        type_autorisation = "Activites_commerciales"
    elif "activités agricoles" in titre:
        type_autorisation = "Activites_agricoles"
    elif "prise de vue" in titre or "drone" in titre:
        type_autorisation = "PDV_et_son"
    elif "hélicoptère" in titre:
        type_autorisation = "Survol_hélicoptere"
    elif "arêtes" in titre:
        type_autorisation = "Aretes"
    elif "manifestations publiques" in titre:
        type_autorisation = "Manifestations_publiques"
    elif "manifestations sportives" in titre:
        type_autorisation = "Manifestations_sportives"
    elif "planification et d'urbanisme" in titre:
        type_autorisation = "Documents_planification_urbanisme"
    elif "manœuvres militaires" in titre:
        type_autorisation = "Manoeuvres_militaires"
    else:
        type_autorisation = "Autre"

    # 2. Type démarche (si applicable)
    type_demarche = ""
    if type_autorisation == "Travaux":
        if "et soumis à autorisation d'urbanisme" in titre:
            type_demarche = "Soumis_urbanisme"
        elif "non soumis à autorisation d'urbanisme" in titre:
            type_demarche = "Non_soumis_urbanisme"
        elif "aire d’adhésion" in titre or "aire d'adhésion" in titre:
            type_demarche = "Aire_adhesion"
    elif type_autorisation == "Missions_scientifiques":
        if "cœur du parc" in titre or "coeur du parc" in titre:
            type_demarche = "Coeur_de_parc"
        elif "espèces protégées" in titre:
            type_demarche = "Especes_protegees"

    elif type_autorisation == "Manifestations_sportives" :
        type_demarche = "Demarche Numerique"

    # 3. Année
    try:
        date_depot = parse_datetime_with_tz(doss.get("dateDepot"))
        annee = str(date_depot.year)
    except Exception:
        date_depot = None
        annee = "0000"


    # 4. Nom du dossier
    if type_autorisation != "Manifestations_sportives" :

        if not doss["number"] :
            loggerDS.error(f"Erreur lors de la construction de l'emplacement du Dossier {doss['id']} : le number n'a pas été récupéré sur DS")
        else:
            numero = str(doss.get("number", "000000"))

        demandeur_type = doss.get("demandeur", {}).get("__typename")

        if demandeur_type == "PersonnePhysique":
            nom = contact_beneficiaire.get("nom", "Inconnu").replace(" ", "_").upper()
            prenom = contact_beneficiaire.get("prenom", "Inconnu").replace(" ", "_").capitalize()
            date_suffix = date_depot.strftime("%d-%m") if date_depot else "XX-XX"
            dossier_part = f"{numero}_{nom}_{prenom}_{date_suffix}/"

        elif demandeur_type == "PersonneMorale":
            nom_morale = formater_nom_personne_morale(doss.get("demandeur", {}), doss)
            date_suffix = date_depot.strftime("%d-%m") if date_depot else "XX-XX"
            dossier_part = f"{numero}_{nom_morale}_{date_suffix}/"

        else:
            dossier_part = f"{numero}_Inconnu/"

    # Manifestations sportives DN : nom dossier = nom manifestation
    else:
        for ch in doss["champs"]:

            if ch["label"] == "Nom de la manifestation" :
                numero = str(doss.get("number", "000000"))
                nom_manif = nettoyer_nom_fichier(ch["stringValue"])
                dossier_part = f"{numero}_{nom_manif}/"
                break


    # 5. Assemblage
    path_parts = [type_autorisation, annee]
    if type_demarche:
        path_parts.append(type_demarche)
    path_parts.append(dossier_part)

    return "/".join(path_parts)


# def create_emplacement_sport(obj, logger):
#     """
#     Créé l'emplacement d'un dossier Déclaration manifestations sur le NAS
#     """

#     # Manifestations_sportives > 2026 > nom_de_la_manif

#     racine = os.environ.get("NAS_ROOT")
#     chemin_complet = os.path.join(racine, obj.emplacement)

#     if not creer_dossier_sur_nas(chemin_complet) :
#         loggerORM.error(f"[CREATION FOLDER] Erreur lors de la création des folders sur le NAS : {chemin_complet}")

#     return chemin_complet


def nettoyer_nom_fichier(nom_dossier):
    # Supprimer les accents
    nom = unicodedata.normalize('NFKD', nom_dossier).encode('ASCII', 'ignore').decode('utf-8')
    
    # Remplacer les espaces et tirets multiples par un underscore
    nom = re.sub(r'[\s\-]+', '_', nom)

    # Supprimer tout caractère non alphanumérique ou underscore
    nom = re.sub(r'[^\w_]', '', nom)

    # Mettre en minuscule
    return nom.lower()



def rendre_titres_uniques(documents):
    """
    Garantit l’unicité des titres de documents en ajoutant un suffixe si nécessaire.

    Principe :
    - Le premier titre rencontré est conservé tel quel.
    - Si un titre est déjà utilisé, on ajoute un suffixe du type : __copie01, __copie02, etc.

    Exemple :
        BILAN.pdf
        BILAN.pdf       → BILAN__copie01.pdf
        BILAN.pdf       → BILAN__copie02.pdf

    Args:
        documents (list[dict]): liste de dictionnaires contenant au minimum la clé "titre"

    Returns:
        list[dict]: la liste modifiée (modification en place des titres)
    """

    # Ensemble des titres déjà attribués pour éviter les doublons
    titres_deja_pris = set()

    # Parcours des documents dans l’ordre
    for doc in documents:

        # Récupération et nettoyage du titre
        titre_original = (doc.get("titre") or "").strip()

        # Si pas de titre → on ignore
        if not titre_original:
            continue

        path = Path(titre_original)
        base = path.stem
        extension = path.suffix

        # Candidat initial = titre d’origine
        candidat = titre_original

        # Compteur pour générer les suffixes __copieXX
        compteur = 1

        # Tant que le titre existe déjà, on génère un nouveau nom
        while candidat in titres_deja_pris:
            candidat = f"{base}__copie{compteur:02d}{extension}"
            compteur += 1

        doc["titre"] = candidat
        titres_deja_pris.add(candidat)

    return documents



def rendre_titre_unique_dans_liste(titre: str, titres_existants: list[str]) -> str:
    """
    Retourne un titre unique en normalisant les suffixes __copieXX.

    Exemple :
        "xx.pdf" -> "xx__copie01.pdf"
        "xx__copie01.pdf" -> "xx__copie02.pdf"

    Args:
        titre (str): titre à vérifier
        titres_existants (list[str]): liste des titres déjà utilisés

    Returns:
        str: titre unique
    """
    titre = (titre or "").strip()
    if not titre:
        return titre

    titres_deja_pris = {t.strip() for t in titres_existants if t and t.strip()}

    path = Path(titre)
    base = path.stem
    extension = path.suffix

    # Regex pour enlever un éventuel suffixe __copieXX
    base_sans_copie = re.sub(r"__copie\d{2}$", "", base)

    # Si le titre original n'existe pas, on le garde
    if titre not in titres_deja_pris:
        return titre

    compteur = 1
    while True:
        candidat = f"{base_sans_copie}__copie{compteur:02d}{extension}"
        if candidat not in titres_deja_pris:
            return candidat
        compteur += 1
