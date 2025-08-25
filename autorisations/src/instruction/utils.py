from pathlib import Path
from django.utils import timezone
import logging
from autorisations.models.models_instruction import Action, Dossier, DossierAction, EtapeDossier, EtatDossier, Message
import pythoncom
import win32com.client
import os
import subprocess
import tempfile
import shutil

from autorisations.models.models_utilisateurs import DossierInstructeur, DossierRelecteurJuridique, DossierRelecteurQualite, DossierSignataire, DossierValideur


logger = logging.getLogger('ORM_DJANGO')

def format_etat_dossier(etat_technique):
    mapping = {
        "sans_suite": "Sans suite",
        "refuse": "Refusé",
        "en_instruction": "En instruction",
        "en_construction": "En pré-instruction",
        "accepte": "Accepté"
    }
    return mapping.get(etat_technique, etat_technique.replace("_", " ").capitalize())


def changer_etape_si_differente(dossier, nom_etape, user):
    """
    Met à jour l'étape du dossier uniquement si elle est différente de l'étape actuelle.

    Args:
        dossier (Dossier): instance Django du dossier à modifier.
        nom_etape (str): nom exact de l'étape cible (champ `etape` de EtapeDossier).

    Returns:
        bool: True si modification effectuée, False sinon.
    """
    nouvelle_etape = EtapeDossier.objects.filter(etape=nom_etape).first()

    if not nouvelle_etape:
        logger.error(f"[DOSSIER {dossier.numero}] Étape '{nom_etape}' introuvable en base.")
        return False

    if dossier.id_etape_dossier != nouvelle_etape:

        dossier.id_etape_dossier = nouvelle_etape
        # Si on archive le dossier, on met à jour l'attribut 'date_fin_instruction'

        if nouvelle_etape.etape == 'Accepté' or nouvelle_etape.etape == 'Refusé' or nouvelle_etape.etape == 'Non soumis à autorisation' :
            dossier.date_fin_instruction = timezone.now()
            
        dossier.save()

        logger.info(f"[DOSSIER {dossier.numero}] Passe à l'étape --> '{nom_etape}' par {user}")
        return True

    logger.debug(f"[DOSSIER {dossier.numero}] Déjà à l'étape '{nom_etape}' : pas de changement.")
    return False



def changer_etat_si_different(dossier, nom_etat, user):
    """
    Met à jour l'état du dossier uniquement si différent de l'état actuel.

    Args:
        dossier (Dossier): instance Django du dossier à modifier.
        nom_etat (str): nom (insensible à la casse) de l'état cible.
        user (User, optional): utilisateur Django à l'origine du changement.

    Returns:
        bool: True si modification effectuée, False sinon.
    """
    nouvel_etat = EtatDossier.objects.filter(nom__iexact=nom_etat).first()

    if not nouvel_etat:
        logger.error(f"[DOSSIER {dossier.numero}] Échec de changement d'état : '{nom_etat}' introuvable.")
        return False

    if dossier.id_etat_dossier != nouvel_etat:
        dossier.id_etat_dossier = nouvel_etat
        dossier.save()
 
        logger.info(f"[DOSSIER {dossier.numero}] Passage à l'état --> '{nouvel_etat.nom.capitalize()}' par {user}")
        return True

    logger.debug(f"[DOSSIER {dossier.numero}] État inchangé (déjà '{dossier.id_etat_dossier.nom}').")
    return False


def enregistrer_action(dossier, instructeur, nom_action, description=None, date=None):
    action_obj = Action.objects.filter(action=nom_action).first()
    if action_obj and instructeur and not date:
        DossierAction.objects.create(
            id_dossier=dossier,
            id_instructeur=instructeur,
            id_action=action_obj,
            description=description
        )
    elif date :
        DossierAction.objects.create(
            id_dossier=dossier,
            id_instructeur=instructeur,
            id_action=action_obj,
            description=description,
            date=date
        )


# def convertir_docx_en_pdf_win32(path_docx, path_pdf, dossier_numero=None, logger=None):
#     import pythoncom
#     import win32com.client
#     import time

#     try:
#         pythoncom.CoInitialize()

#         if os.path.exists(path_pdf):
#             os.remove(path_pdf)

#         word = win32com.client.Dispatch("Word.Application")
#         word.Visible = False
#         word.DisplayAlerts = 0  # Empêche les popups
#         word.AutomationSecurity = 3  # Désactive macros et alertes

#         doc = word.Documents.Open(
#             path_docx,
#             ConfirmConversions=False,
#             ReadOnly=True,
#             AddToRecentFiles=False,
#             Visible=False,
#             PasswordDocument='',
#         )

#         time.sleep(0.2)  # Pause avant SaveAs

#         doc.SaveAs(path_pdf, FileFormat=17)  # PDF (code 17)
#         doc.Close(False)
#         word.Quit()

#         if logger:
#             logger.info(f"[DOSSIER {dossier_numero}] Conversion réussie DOCX → PDF : {path_pdf}")

#     except Exception as e:
#         if logger:
#             logger.error(f"[DOSSIER {dossier_numero}] Erreur de conversion Word → PDF (win32) : {e}")
#             # logger.error(f"Fichier .docx accessible ? {os.path.exists(path_docx)}")
#             # logger.error(f"Fichier .pdf déjà présent ? {os.path.exists(path_pdf)}")
#         raise

#     finally:
#         pythoncom.CoUninitialize()




def convertir_docx_en_pdf_libreoffice(path_docx, output_dir, dossier_numero=None, logger=None):
    try:
        if not os.path.exists(path_docx):
            raise FileNotFoundError(f"Le fichier source {path_docx} est introuvable.")

        if not os.path.exists(output_dir):
            raise FileNotFoundError(f"Le dossier de sortie {output_dir} est introuvable.")

        # soffice_path = r"C:\Program Files\LibreOffice\program\soffice.exe"
        soffice_path = os.getenv('SOFFICE_PATH')

        if not soffice_path:
            raise EnvironmentError(f"[DOSSIER {dossier_numero}] Conversion PDF : Variable d'environnement 'SOFFICE_PATH' non définie.")

        # logger.info(f"soffice path : {soffice_path}")
        # logger.info(f"output_dir : {output_dir}")
        # logger.info(f"path_docx : {path_docx}")


        with tempfile.TemporaryDirectory() as temp_dir:
            temp_docx = os.path.join(temp_dir, os.path.basename(path_docx))

            shutil.copy(path_docx, temp_docx)

            cmd = [
                soffice_path, "--headless", "--convert-to", "pdf",
                "--outdir", output_dir, path_docx
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            # logger.warning(f"stdout LibreOffice : {result.stdout}")
            # logger.warning(f"stderr LibreOffice : {result.stderr}")


            # Cherche le PDF
            nom_pdf_genere = Path(path_docx).with_suffix(".pdf").name
            pdf_genere_path = os.path.join(output_dir, nom_pdf_genere)

            if not os.path.exists(pdf_genere_path):
                raise FileNotFoundError(f"[DOSSIER {dossier_numero}] PDF attendu introuvable : {pdf_genere_path}")


            if logger:
                logger.info(f"[DOSSIER {dossier_numero}] Conversion LibreOffice -> PDF OK.")

    except Exception as e:
        if logger:
            logger.error(f"[DOSSIER {dossier_numero}] Échec Conversion LibreOffice - PDF ({path_docx}) : {e}")
            # logger.error(f"[DOSSIER {dossier_numero}] Erreur : {e}")
        raise



def dossiers_action_a_faire(dossiers, obj_instructeur):
    """
    Retourne les dossiers où l'utilisateur doit réaliser une action,
    en fonction de son rôle implicite selon l'étape du dossier.
    """
    dossiers_a_traiter_ids = set()

    for dossier in dossiers:
        etape = dossier.id_etape_dossier.etape if dossier.id_etape_dossier else None

        # Vérifications par rôle
        est_instructeur = DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_valideur = DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_relecteur_qualite = DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_relecteur_juridique = DossierRelecteurJuridique.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_signataire = DossierSignataire.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()


        # === Mapping Étape -> Rôle attendu ===
        if est_relecteur_juridique :
            drj = DossierRelecteurJuridique.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).first()
            # Si relecture pas encore faite --> action à faire
            if not drj.relu :
                dossiers_a_traiter_ids.add(dossier.id)

        if etape == "À valider avant signature":
            # Rôle : Valideur
            if est_instructeur:  
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape in ["Non soumis à autorisation", "Refusé", "Accepté"]:

            # Nb messages non lus côté pétitionnaire
            nb_messages_non_lus = Message.objects.filter(
                id_dossier=dossier,
                lu=False
            ).exclude(
                email_emetteur='contact@demarches-simplifiees.fr'
            ).exclude(
                email_emetteur__endswith='reunion-parcnational.fr'
            ).count()

            # Rôle : Instructeur et messages non lus
            if est_instructeur and nb_messages_non_lus > 0:
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape in ["En instruction", "En Pré-instruction", "En attente réponse d'avis", "En attente de compléments"]:
            # Rôle : Instructeur
            if est_instructeur:
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape in ["À affecter", "En relecture qualité", "À publier au RAA", "Acte à envoyer"]:
            # Rôle : Relecteur Qualité
            if est_relecteur_qualite:
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape == "En attente de signature":
            # Rôle : Signataire
            if est_signataire: 
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape == "À valider avant demande d'avis":
            # Rôle : Valideur
            if est_valideur:
                dossiers_a_traiter_ids.add(dossier.id)

    return Dossier.objects.filter(id__in=dossiers_a_traiter_ids)
    # return list(dossiers_a_traiter)
