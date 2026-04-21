from datetime import datetime
import logging
import os
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.db import transaction
import smbclient
from autorisations.models.models_instruction import AvisManifSportive, Dossier, DossierManifSportive, DossierManifestationLiaison, EtapeDossier, EtatDossier, DossierAction, Action
from autorisations.models.models_utilisateurs import ContactExterne, DossierEnvoiActe, DossierIntermediaireSignature, DossierPublicationRAA, DossierRelecteurQualite, DossierSignataire, EmailOutbox, GroupeinstructeurInstructeur, Instructeur, DossierInstructeur, DossierValideur, TypeContactExterne
from DS.call_DS import accepter_dossier_ds, get_msg_DS, passer_en_instruction_ds,classer_sans_suite_ds, refuser_dossier_ds, repasser_en_instruction_ds
from autorisations import settings
from autorisations.models.models_avis import Avis, DossierAvis
from autorisations.utils.nas_fonctions import _normalize_unc_path, copier_dossier_smb, creer_dossier_sur_nas, ecrire_file_sur_nas, supprimer_dossier_smb_recursif
from declaration_manifestations.get_methods import ajouter_pj_avis, get_access_token, rendre_avis
from instruction.utils.dm import reception_charger_contexte_avis_dm, reception_copier_sous_dossier_dm, reception_deplacer_documents_dossier_dm, reception_lire_donnees_formulaire_avis_dm, reception_mettre_a_jour_emplacement_dossier_dm, reception_preparer_emplacements_dossier_dm, reception_rendre_avis_et_mettre_a_jour_dm, reception_supprimer_ancien_dossier_dm_si_necessaire, reception_traiter_fichier_avis_dm, reception_verifier_acces_et_fichiers_avis_dm, user_est_autorise_a_agir_reception_manif_sportive
from instruction.utils.document_utils import normaliser_emplacement
from instruction.utils.dossier_utils import get_dossier_or_redirect, redirect_error, safe_enregistrer_action, safe_update_etape, safe_update_etat, set_dossier_role
from instruction.utils.files_utils import generate_unique_filename, sanitiser_nom_fichier, valider_fichiers_dm
from instruction.utils.utilisateurs_utils import get_instructeur_or_redirect
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from instruction.services.messagerie_service import envoyer_message_ds, prepare_temp_file, enregistrer_message_bdd
from django.views.decorators.http import require_POST
from django.utils import timezone
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DocumentStatut, DossierDocument, DossierManifSportiveDocument
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from pathlib import Path
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from synchronisation.utils.fichiers import get_nom_disponible



logger = logging.getLogger('ORM_DJANGO')
loggerDS = logging.getLogger("API_DS")


@require_POST
@login_required
def passer_en_pre_instruction(request):

    # --- Récupération dossier ---
    dossier_id_ds = request.POST.get("dossierId")
    dossier, err = get_dossier_or_redirect(request, etape="PASSAGE PRE-INSTRUCTION", id_ds=dossier_id_ds)
    if err:
        return err

    
    # --- Vérification Instructeur ---
    instructeur_connecte, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Passage en pré-instruction")
    if err:
        return err


    # IDs des instructeurs affectés à ce dossier
    instructeurs_dossier_ids_qs = DossierInstructeur.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True)

    if not instructeurs_dossier_ids_qs.exists():
        request.session["preinstruction_message"] = "Vous devez assigner un instructeur au dossier pour pouvoir le passer en pré-instruction."
        return redirect(reverse("preinstruction_dossier", kwargs={"numero": dossier.numero}))

    instructeurs_dossier_ids = set(instructeurs_dossier_ids_qs)

    # --- Vérification du groupe instructeur ---
    groupe = dossier.id_groupeinstructeur
    if not groupe:
        request.session["preinstruction_message"] = "Aucun groupe instructeur n’est défini pour ce dossier. Contactez le support."
        return redirect(reverse("preinstruction_dossier", kwargs={"numero": dossier.numero}))

    instructeurs_groupe_ids = set(
        GroupeinstructeurInstructeur.objects.filter(id_groupeinstructeur=groupe)
        .values_list("id_instructeur", flat=True)
    )

    # --- Vérification instructeur du groupe en cours associé au dossier ---
    intersection = instructeurs_dossier_ids & instructeurs_groupe_ids
    if not intersection:
        request.session["preinstruction_message"] = ("Le dossier n’est associé à aucun instructeur appartenant au groupe instructeur.")
        return redirect(reverse("preinstruction_dossier", kwargs={"numero": dossier.numero}))
    

    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "En pré-instruction", request, break_si_erreur=True)
    if err:
        return err
    

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur_connecte, action="Passage en pré-instruction", request=request)


    request.session.pop("preinstruction_message", None)
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@require_POST
@login_required
def demander_des_complements(request):

    numero = request.POST.get("numero_dossier")
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, etape="DEMANDE DE COMPLÉMENTS", numero=numero)
    if err:
        return err


    # --- Vérification Instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Demande de compléments")
    if err:
        return err


    # --- Vérification données obligatoires ---
    if not body:
        logger.error(f"[DOSSIER {numero}] Demande de compléments par {request.user} : body manquant ")
        return redirect_error(request, f"Vous devez préciser votre demande de compléments. Contactez le support.")
    
    if not dossier.id_ds :
        logger.error(f"[DOSSIER {numero}] Demande de compléments par {request.user} : Le dossier n'a pas de id_ds. (id_ds = {dossier.id_ds})")
        return redirect_error(request, f"L'ID du dossier Démarche Numérique est introuvable. Contactez le support.")
    

    tmp_file_path = None
    try:
        if fichier:
            tmp_file_path = prepare_temp_file(fichier)
            result = envoyer_message_ds(dossier.id_ds, instructeur, body, fichier, fichier.content_type, tmp_file_path, numero, correction=True)
        else:
            result = envoyer_message_ds(dossier.id_ds, instructeur, body, num_dossier=numero, correction=True)

        # --- Vérification réponse DS ---
        if not result or "data" not in result or "dossierEnvoyerMessage" not in result["data"] :
            logger.error(f"[DOSSIER {numero}] Demande de compléments par {request.user} : Echec demande complément sur DS — Réponse API : {result}")
            return redirect_error(request, f"Échec de la demande de compléments sur Démarche Numérique. Contactez le support.")
        

        if result.get("data"):
            id_ds_msg = result["data"]["dossierEnvoyerMessage"]["message"]["id"]
            try:
                url_ds = get_msg_DS(int(numero), id_ds_msg) if fichier else None
            except Exception as e:
                logger.warning(f"[DOSSIER {numero}] Demande de compléments par {request.user} : Impossible de récupérer l’URL DS du message {id_ds_msg} (on continue quand même) : {e}")


             # --- Enregistrement du message en BDD ---
            try:
                enregistrer_message_bdd(dossier, request.user.email, body, fichier, id_ds=id_ds_msg, url_ds=url_ds)
            except Exception as e:
                logger.error(f"[DOSSIER {numero}] Demande de compléments par {request.user} : Erreur lors de l’enregistrement du message en base : {e}")
                return redirect_error(request, f"Erreur lors de l’enregistrement du message en base. Contactez le support.")

            
            # --- Mise à jour Étape ---
            safe_update_etape(dossier, "En attente de compléments", request, break_si_erreur=False) # On continue si Erreur

            # --- Mise à jour État ---
            safe_update_etat(dossier, "en_construction", request, break_si_erreur=False) # On continue si Erreur
           
            # --- Enregistrer Action ---
            safe_enregistrer_action(dossier, instructeur, action="Demande de compléments", request=request)

    finally:
        # --- Nettoyage fichier temporaire ---
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

    return redirect(reverse('instruction_dossier_messagerie', args=[dossier.numero]))



@require_POST
@login_required
def dossier_non_soumis_a_autorisation(request):
    """
    Classe un Dossier comme 'Non soumis à autorisation'
    """

    dossier_id_ds = request.POST.get("dossierId")
    motivation = request.POST.get("motivation", "").strip()


    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, etape="NON SOUMIS À AUTO", id_ds=dossier_id_ds)
    if err:
        return err
    

    # --- Motivation requise ---
    if not motivation and dossier.present_sur_ds :
        logger.warning(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} : Justification manquante.")
        return redirect_error(request, f"Une justification est requise pour classer le dossier comme 'Non soumis à autorisation'.")
    

    # --- Vérification Instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Classer comme 'Non soumis à autorisation'")
    if err:
        return err



    # ==========================================
    # --- Actions côté Démarche Numérique ---
    # ==========================================
    if dossier.present_sur_ds :

        # --- PASSAGE EN INSTRUCTION SUR DS ---
        # Si Etat Dossier en construction + Etape Dossier en pré-instruction ou à affecter
        if dossier.id_etat_dossier.nom == "en_construction" and dossier.id_etape_dossier.etape in ["En pré-instruction", "À affecter"]:
            result = passer_en_instruction_ds(dossier.id_ds, instructeur)
            if not result.get("success"):
                logger.error(f"[DOSSIER {dossier.numero}] Erreur lors du passage en instruction DS par {request.user} : {result.get('message')}")
                return redirect_error(request, f"Erreur lors du passage en instruction sur Démarche Numérique. Contactez le support.")


        # --- CLASSEMENT SANS SUITE SUR DS ---
        result = classer_sans_suite_ds(dossier.id_ds, instructeur, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Échec du classement sans suite DS par {request.user} : {result.get('message')}")
            return redirect_error(request, f"Erreur lors du classement sans suite sur Démarche Numérique. Contactez le support.")


    # ========================
    # --- Actions côté BDD ---
    # ========================

    # --- Mise à jour Étape ---
    safe_update_etape(dossier, "Non soumis à autorisation", request, break_si_erreur=False) # On continue si Erreur
    
    # --- Mise à jour État ---
    if dossier.present_sur_ds :
        safe_update_etat(dossier, "sans_suite", request, break_si_erreur=False) # On continue si Erreur

    # Maj Date Fin Instruction
    try:
        dossier.date_fin_instruction = timezone.now()
        dossier.save()
    except Exception as e:
        logger.warning(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} - Erreur MAJ date_fin_instruction à {timezone.now()} : {e}")
        # on continue

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, action="Classé sans suite", request=request)



    # ==============================================
    # --- DOSSIER DECLARATION MANIFESTATIONS LIÉ ---
    # ==============================================
    try :

        if dossier.id_demarche.type.lower() == 'manifestations sportives':
            # Vérification si liaison existante
            liaison_dossDN = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()

            if liaison_dossDN :
                dossier_dm_id = liaison_dossDN.id_dossier_manif.id

                # Récupération du dossier DM
                dossier_dm = DossierManifSportive.objects.filter(id=dossier_dm_id).first()
                if not dossier_dm:
                    logger.error(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} - "
                                f"Dossier Déclaration Manifestations (id={dossier_dm_id}) introuvable en base.")
                    return redirect_error(request, "Le dossier a bien été classé comme non soumis introuvable sur Démarche Numérique, "
                                "mais un problème est survenu lors du classement sur Déclaration Manifestations. Contactez le support.")
                
                num_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations

                # Récupération de l'avis associé
                avis_dm = AvisManifSportive.objects.filter(id_dossier_manif_sportive=dossier_dm).first()
                if not avis_dm:
                    logger.error(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} - "
                                f"Aucun Avis DM associé au Dossier DM {num_dossier_dm}.")

                    return redirect_error(request, "Le dossier a bien été classé comme non soumis sur Démarche Numérique, "
                                f"mais l'avis n'a pas pu être rendu sur Déclaration Manifestations pour le dossier n° {num_dossier_dm} (aucun avis associé en base). Contactez le support.")
        
                avis_id = avis_dm.id_avis_manif_sportive


                if avis_dm.date_reponse :
                    # ------------------
                    # AVIS DM DEJA RENDU
                    # ------------------
                    logger.warning(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} - "
                                   f"Avis (avis_id={avis_id}) déjà soumis sur DM.")
                    
                    messages.info(request, f"Aucun changement sur Déclaration Manifestations, un avis '{avis_dm.reponse_avis}' a déjà été rendu.")
                    
                    if not dossier_dm.archive :
                        dossier_dm.archive = True
                        dossier_dm.save(update_fields=["archive"])
                
                else :
                    # -------------------------------------
                    # CLASSER LE DOSSIER COMME NON CONCERNÉ
                    # -------------------------------------
                    # Récupération du token API
                    token = get_access_token()
                    
                    if not motivation :
                        motivation = ""

                    # 0-None, 1-favorable, 2-défavorable, 3-non concerné  (lève exception si erreur)
                    response_avis = rendre_avis(token, avis_id, 3, motivation)
                    logger.info(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} - "
                                f"Avis 'non concerné' soumis avec succès sur DM (avis_id={avis_id}). Réponse API : {response_avis}")

                    # ------------------
                    # MAJ Avis DM en BDD
                    # ------------------
                    avis_dm.date_reponse = timezone.now()
                    avis_dm.reponse_avis = "non concerné"
                    avis_dm.prescriptions = motivation
                    avis_dm.save(update_fields=["date_reponse", "prescriptions", "reponse_avis"])
                    logger.info(f"Avis DM {avis_id} mis à jour en base.")

                    # ---------------------
                    # MAJ Dossier DM en BDD
                    # ---------------------
                    etape_cible = EtapeDossier.objects.get(etape="Non soumis à autorisation")
                    dossier_dm.archive = True
                    dossier_dm.id_etape = etape_cible
                    dossier_dm.save(update_fields=["archive", "id_etape"])
                    logger.info(f"Dossier DM {num_dossier_dm} mis à jour en base (etape : {etape_cible.etape}, archive : True)")


    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} - "
                                f"Erreur lors de la soumission de l'avis en 'non concerné' sur Déclaration Manifestations : {e}")
        
        return redirect_error(request, "Le dossier a bien été classé comme non soumis sur Démarche Numérique, mais une erreur est survenue lors de la "
                                "soumission de l'avis sur Déclaration Manifestations. Contactez le support.")
        

    return redirect(reverse('instruction_dossier', kwargs={'num_dossier': dossier.numero}))



"""
@require_POST
@login_required
def refuse_le_dossier(request):

    dossier_id_ds = request.POST.get("dossierId")
    motivation = request.POST.get("motivation", "").strip()

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, etape="REFUS DOSSIER", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Vérification Instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Refuser le dossier")
    if err:
        return err
    
    
    # --- Vérification justification ---
    # if not motivation and dossier.present_sur_ds:
    #     logger.warning(f"[DOSSIER {dossier.numero}] User {request.user} a tenté de refuser le dossier sans justification.")
    #     return redirect_error(request, f"Une justification est requise pour refuser le dossier.")
    

    # ==========================================
    # --- Actions côté Démarche Numérique ---
    # ==========================================
    if dossier.present_sur_ds :

        # Si l'étape est 'En pré-instruction' et l'état 'en_construction' --> passer l'état à en_instruction
        if dossier.id_etat_dossier.nom == 'en_construction' and dossier.id_etape_dossier.etape == 'En pré-instruction' :

            # Passage en instruction sur DS
            result = passer_en_instruction_ds(dossier.id_ds, instructeur)
            if not result.get("success"):
                logger.error(f"[DOSSIER {dossier.numero}] Erreur lors du passage en instruction DS par {request.user} : {result.get('message')}")
                return redirect_error(request, f"Erreur lors du passage en instruction sur Démarche Numérique. Contactez le support.")

        # Refus du dossier sur DS
        result = refuser_dossier_ds(dossier.id_ds, instructeur, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Échec du refus DS : {result.get('message')}")
            return redirect_error(request, f"Erreur lors du refus sur Démarche Numérique. Contactez le support.")


    # ========================
    # --- Actions côté BDD ---
    # ========================

    # --- Mise à jour Étape ---
    safe_update_etape(dossier, "Refusé", request, break_si_erreur=False) # On continue si Erreur

    # --- Mise à jour État ---
    if dossier.present_sur_ds :
        safe_update_etat(dossier, "refuse", request, break_si_erreur=False) # On continue si Erreur

    # Maj Date Fin Instruction
    try:
        dossier.date_fin_instruction = timezone.now()
        dossier.save()
    except Exception as e:
        logger.warning(f"[DOSSIER {dossier.numero}] Refus par {request.user} - Erreur MAJ date_fin_instruction à {timezone.now()} : {e}")
        # on continue

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, action="Classé comme refusé", request=request)
    

    return redirect(reverse('instruction_dossier', kwargs={'num_dossier': dossier.numero}))

"""



@require_POST
@login_required
def passer_en_instruction(request):

    dossier_id_ds = request.POST.get("dossierId")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "PASSAGE EN INSTRUCTION", id_ds=dossier_id_ds)
    if err: 
        return err

    # --- Vérification instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Passage en instruction")
    if err: 
        return err

    # etat_actuel_dossier = get_object_or_404(EtatDossier, id=dossier.id_etat_dossier_id)
    

    # Passage en instruction sur DS
    if dossier.present_sur_ds and dossier.id_etat_dossier.nom.lower() != "en_instruction" :
        result = passer_en_instruction_ds(dossier.id_ds, instructeur)

        if not result.get("success"):
                logger.error(f"[DOSSIER {dossier.numero}] Erreur lors du passage en instruction DS par {request.user} : {result.get('message')}")
                return redirect_error(request, f"Erreur lors du passage en instruction sur Démarche Numérique. Contactez le support.")
        

    # --- Mise à jour Étape ---
    safe_update_etape(dossier, "En instruction", request, break_si_erreur=False) # On continue si Erreur

    # --- Mise à jour État ---
    safe_update_etat(dossier, "en_instruction", request, break_si_erreur=False) # On continue si Erreur

    
    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, action="Passage en instruction", request=request)


    # Maj Date Fin Instruction
    try:
        dossier.date_debut_instruction = timezone.now()
        dossier.save()
    except Exception as e:
        logger.warning(f"[DOSSIER {dossier.numero}] Passage en Instruction par {request.user} Erreur MAJ date_debut_instruction à {timezone.now()} : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def faire_valider_une_demande_d_avis(request):

    dossier_id_ds = request.POST.get("dossierId")
    nature = request.POST.get("nature_document")
    validant = request.POST.get("choix-validant") #Objet Instructeur
    # fichier = request.FILES.get("piece_jointe")
    nom_fichier = (request.POST.get("piece_jointe_work") or "").strip()
    nom_fichier_rapport_ca = (request.POST.get("piece_jointe_rapport_ca_work") or "").strip()
    ids_selectionnes = request.POST.getlist("avis_selectionnes")
    
    # ========================
    # ---   VERIFICATION   ---
    # ========================
    if not dossier_id_ds :
        return redirect_error(request, "❌ L'id du dossier est manquant. Contactez le support.")
    
    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "VALIDATION AVANT DEMANDE AVIS", id_ds=dossier_id_ds)
    if err: 
        return err
    
    if not nature :
        return redirect_error(request, "❌ La nature du projet d'acte est manquante. Contactez le support.")

    else :
        # --- Récupération nature ---
        nature_obj = DocumentNature.objects.filter(nature=nature).first()
        if not nature_obj:
            logger.error(f"[DOSSIER {dossier.numero}] User {request.user} : Aucune nature Document trouvée pour '{nature}'")
            return redirect_error(request, f"❌ Le nature de document '{nature}' n'a pas été trouvée en base. Contactez le support.")
    
    if not nom_fichier :
        return redirect_error(request, "❌ Le projet d'acte n'a pas été sélectionné.")

    # Rapport CA obligatoire pour une Délibération CA
    if nature == "Déliberation CA" and not nom_fichier_rapport_ca:
        return redirect_error(request, "❌ Le projet de rapport du CA n'a pas été sélectionné.")
    
    else :

        # --- Extension ---
        extension = Path(nom_fichier).suffix.lower()
        if extension not in {".doc", ".docx", ".odt"} :
            return redirect_error(request, f"❌ Le fichier joint doit etre .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}.")
        
        # --- Récupération format ---
        format_obj = DocumentFormat.objects.filter(format=extension.lstrip('.')).first()
        if not format_obj:
            logger.error(f"[DOSSIER {dossier.numero}] User {request.user} : Aucun format Document trouvé pour '{extension}'")
            return redirect_error(request, f"❌ Le format de document '{extension}' n'a pas été trouvé en base. Contactez le support.")
        
        

        # --- Récupération statut ---
        statut_obj = DocumentStatut.objects.filter(statut="À valider").first()
        if not statut_obj:
            logger.error(f"[DOSSIER {dossier.numero}] User {request.user} : Statut 'À valider' introuvable dans DocumentStatut")
            return redirect_error(request, "❌ Le statut 'À valider' n'a pas été trouvé en base. Contactez le support.")

    if not validant :
        return redirect_error(request, "❌ Envoi pour validation avant demande d'avis : Aucun validant sélectionné.")

    else :
        # --- Récupération validant ---
        validant_obj = Instructeur.objects.filter(id=validant).first()
        if not validant_obj:
            logger.error(f"[DOSSIER {dossier.numero}] User {request.user} : Aucun validant trouvé avec l'id : {validant}")
            return redirect_error(request, "❌ Le validant n'a pas été trouvé en base. Contactez le support.")
    
    if not ids_selectionnes :
        return redirect_error(request, "❌ Aucun avis sélectionné. Contactez le support.")
    

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Envoi pour validation avant demande d'avis")
    if err: 
        return err
    

    avis_selectionnes = Avis.objects.filter(id__in=ids_selectionnes)
    if not avis_selectionnes:
        logger.error(f"[DOSSIER {dossier.numero}] Faire valider une demande d'avis (User {request.user}) - Aucun avis trouvé avec les id : {ids_selectionnes}")
        return redirect_error(request, f"❌ Aucun avis trouvé avec les id : {ids_selectionnes}. Contactez le support.")
       

    # Vérification que le file sélectionné est bien dans le sous dossier Work
    dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")
    full_path = os.path.join(os.environ.get("NAS_ROOT"), dossier_path)
    creer_dossier_sur_nas(full_path)
    filepath = os.path.join(full_path, nom_fichier)

    if not smbclient.path.exists(filepath):
        return redirect_error(request, f"❌ Le projet d’acte doit être placé dans le sous-dossier 'Work' du dossier concerné.")
    

    # ========================
    # --- Mise à jour Avis ---
    # ========================
    for avis in avis_selectionnes:
        avis.statut = "À valider"
        avis.save()


    # =======================
    # --- Ajout validant ---
    # =======================
    try:
        # Suppression des valideurs du dossier (si existants)
        deleted_count, _ = DossierValideur.objects.filter(id_dossier=dossier).delete()
        if deleted_count > 0:
            logger.info(f"[DOSSIER {dossier.numero}] {deleted_count} validant(s) existant(s) supprimé(s) du dossier.")
        
        DossierValideur.objects.get_or_create(id_dossier=dossier, id_instructeur=validant_obj)
        logger.info(f"[DOSSIER {dossier.numero}] Validant·e {validant_obj} ajouté·e.")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'affectation du validant·e {validant} : {e}")


    # ==============================
    # --- Create Document en BDD ---
    # ==============================
    try:
        
        # Enregistrer en BDD
        doc, created = Document.objects.get_or_create(
                            emplacement=dossier_path, titre=nom_fichier,
                            defaults={
                                "id_format": format_obj,
                                "id_nature": nature_obj,
                                "id_statut": statut_obj,
                                "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                            })
        if created:
            DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
            logger.info(f"[DOSSIER {dossier.numero}] Document {nature_obj.nature} {nom_fichier} créé en base par {request.user}.")
        else:
            doc.id_statut = statut_obj
            doc.id_nature = nature_obj
            doc.id_format = format_obj
            doc.description = f"{nature_obj.nature} du dossier {dossier.numero}"
            doc.numero = None
            doc.save()
            logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_obj.nature} {nom_fichier} déjà existant en base – aucune création")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors du changement d'étape 'Faire valider une demande d'avis' par {request.user} - Erreur lors de la création ou de la MAJ du Document {nom_fichier} en base : {e}")
    

    ########################
    # Projet rapport CA
    ########################
    if nature == "Déliberation CA":

        extension_rapport = Path(nom_fichier_rapport_ca).suffix.lower()
        if extension_rapport not in {".doc", ".docx", ".odt"}:
            return redirect_error(request, f"❌ Le projet de rapport du CA doit être .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension_rapport}.")

        filepath_rapport = os.path.join(full_path, nom_fichier_rapport_ca)
        if not smbclient.path.exists(filepath_rapport):
            return redirect_error(request, "❌ Le projet de rapport du CA doit être placé dans le sous-dossier 'Work' du dossier concerné.")

        try:
            nature_rapport_obj = DocumentNature.objects.filter(nature="Projet Rapport CA").first()
            if not nature_rapport_obj:
                return redirect_error(request,"❌ Nature 'Projet Rapport CA' introuvable en base. Contactez le support.")

            format_rapport_obj = DocumentFormat.objects.filter(format=extension_rapport.lstrip('.')).first()
            if not format_rapport_obj:
                return redirect_error(request, f"❌ Le format '{extension_rapport}' n'a pas été trouvé en base. Contactez le support.")

            doc_rapport, created = Document.objects.get_or_create(
                emplacement=dossier_path,
                titre=nom_fichier_rapport_ca,
                defaults={
                    "id_format": format_rapport_obj,
                    "id_nature": nature_rapport_obj,
                    "id_statut": statut_obj,
                    "description": f"{nature_rapport_obj.nature} du dossier {dossier.numero}",
                }
            )

            if created:
                DossierDocument.objects.create(id_dossier=dossier, id_document=doc_rapport)
                logger.info(
                    f"[DOSSIER {dossier.numero}] Document {nature_rapport_obj.nature} {nom_fichier_rapport_ca} créé en base par {request.user}."
                )
                
            else:
                doc_rapport.id_statut = statut_obj
                doc_rapport.id_nature = nature_rapport_obj
                doc_rapport.id_format = format_rapport_obj
                doc_rapport.description = f"{nature_rapport_obj.nature} du dossier {dossier.numero}"
                doc_rapport.numero = None
                doc_rapport.save()
                logger.warning(
                    f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_rapport_obj.nature} {nom_fichier_rapport_ca} déjà existant en base – aucune création"
                )

        except Exception as e:
            logger.error(
                f"[DOSSIER {dossier.numero}] Erreur lors du changement d'étape 'Faire valider une demande d'avis' par {request.user} - "
                f"Erreur lors de la création ou de la MAJ du Document {nom_fichier_rapport_ca} en base : {e}"
            )


    # Changer Etape
    err = safe_update_etape(dossier, "À valider avant demande d'avis", request, break_si_erreur=True)
    if err: 
        return err

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, action="Envoyé pour validation", request=request)
    
    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def faire_valider_le_projet_d_acte(request):

    dossier_id_ds = request.POST.get("dossierId")
    nature = request.POST.get("nature_document")
    validant = request.POST.get("choix-validant") #Objet Instructeur
    # fichier = request.FILES.get("piece_jointe")
    # fichier_rapport_CA = request.FILES.get("piece_jointe_rapport_ca")
    nom_fichier_rapport_ca = (request.POST.get("piece_jointe_rapport_ca_work") or "").strip()
    nom_fichier = (request.POST.get("piece_jointe_work") or "").strip()


    # =========================
    # ---   VERIFICATIONS   ---
    # =========================

    if not dossier_id_ds :
        return redirect_error(request, "❌ L'id du dossier est manquant. Contactez le support.")
    
    if not nature :
        return redirect_error(request, "❌ La nature du projet d'acte est manquante. Contactez le support.")
    
    # Récup nature
    nature_obj = DocumentNature.objects.filter(nature=nature).first()
    if not nature_obj:
        logger.error(f"[FAIRE VALIDER PROJET] Nature '{nature}' introuvable en base (user={request.user})")
        return redirect_error(request, f"❌ La nature '{nature}' n'existe pas en base. Contactez le support.")

    if not nom_fichier:
        return redirect_error(request, "❌ Le projet d'acte n'a pas été sélectionné.")
    
    extension = Path(nom_fichier).suffix.lower()
    if extension not in {".doc", ".docx", ".odt"}:
        return redirect_error(request, f"❌ Le projet d'acte doit être .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "VALIDATION PROJET ACTE", id_ds=dossier_id_ds)
    if err: return err

    format_obj = DocumentFormat.objects.filter(format=extension.lstrip('.')).first()
    if not format_obj:
        logger.error(f"[VALIDER PROJET ACTE] Format '{extension}' introuvable")
        return redirect_error(request, f"❌ Format '{extension}' introuvable en base. Contactez le support.")

    statut_obj = DocumentStatut.objects.filter(statut="À valider").first()
    if not statut_obj:
        logger.error(f"[DOSSIER {dossier.numero}] User {request.user} : Statut 'À valider' introuvable dans DocumentStatut")
        return redirect_error(request, "❌ Le statut 'À valider' n'existe pas en base. Contactez le support.")

    # Validant
    if not validant:
        return redirect_error(request, "❌ Aucun validant sélectionné.")

    validant_obj = Instructeur.objects.filter(id=validant).first()
    if not validant_obj:
        logger.error(f"[VALIDER PROJET ACTE] User {request.user} : Aucun validant trouvé avec l'id : {validant}")
        return redirect_error(request, "❌ Le validant choisi n'existe pas.")

    
    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Validation projet d'acte")
    if err: return err


    # Vérification que le file sélectionné est bien dans le sous dossier Work
    dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")
    full_path = os.path.join(os.environ.get("NAS_ROOT"), dossier_path)
    creer_dossier_sur_nas(full_path)

    # filepath = os.path.join(full_path, fichier.name)
    # if not smbclient.path.exists(filepath):
    #     return redirect_error(request, "❌ Le projet d’acte doit être dans le sous-dossier 'Work' du dossier concerné.")

    filepath = os.path.join(full_path, nom_fichier)
    if not smbclient.path.exists(filepath):
        return redirect_error(request, "❌ Le projet d’acte doit être dans le sous-dossier 'Work' du dossier concerné.")


    ############################## 
    # Sauvegarde du Projet d'acte
    ##############################
    try:

        # Enregistrer en BDD
        doc, created = Document.objects.get_or_create(
                        emplacement=dossier_path, titre=nom_fichier, id_format=format_obj,
                        defaults={
                            "id_format": format_obj,
                            "id_nature": nature_obj,
                            "id_statut": statut_obj,
                            "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                        }
                    )

        if created:
            DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
            logger.info(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {nom_fichier} créé dans le dossier Work")
            
        else:
            doc.id_statut = statut_obj
            doc.id_nature = nature_obj
            # Force un nouveau numéro
            doc.numero = None
            doc.save()
            logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_obj.nature} {nom_fichier} déjà existant en base – aucune création")
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] {nature_obj.nature} : Erreur lors du changement d'étape 'Faire valider le projet d'acte' par {request.user} - Erreur lors de la création du Document {nom_fichier} en base : {e}")



    ########################
    # Projet rapport CA
    ########################

    if nature == "Déliberation CA":
        if not nom_fichier_rapport_ca:
            return redirect_error(request, "❌ Le projet de rapport du CA n'a pas été sélectionné.")

        extension_rapport = Path(nom_fichier_rapport_ca).suffix.lower()
        if extension_rapport not in {".doc", ".docx", ".odt"}:
            return redirect_error(request, f"❌ Le projet de rapport du CA doit être .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension_rapport}")

        filepath_rapport = os.path.join(full_path, nom_fichier_rapport_ca)
        if not smbclient.path.exists(filepath_rapport):
            return redirect_error(request, "❌ Le projet de rapport du CA doit être placé dans le sous-dossier 'Work' du dossier concerné.")

        try:
            nature_rapport_obj = DocumentNature.objects.filter(nature="Projet Rapport CA").first()
            if not nature_rapport_obj:
                return redirect_error(request, "❌ Nature 'Projet Rapport CA' introuvable en base. Contactez le support.")

            format_rapport_obj = DocumentFormat.objects.filter(format=extension_rapport.lstrip('.')).first()
            if not format_rapport_obj:
                return redirect_error(request, f"❌ Format '{extension_rapport}' non trouvé en base. Contactez le support.")

            doc, created = Document.objects.get_or_create(
                emplacement=dossier_path,
                titre=nom_fichier_rapport_ca,
                defaults={
                    "id_format": format_rapport_obj,
                    "id_nature": nature_rapport_obj,
                    "id_statut": statut_obj,
                    "description": f"{nature_rapport_obj.nature} du dossier {dossier.numero}",
                }
            )

            if created:
                DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
                logger.info(f"[DOSSIER {dossier.numero}] {nature_rapport_obj.nature} {nom_fichier_rapport_ca} créé dans le dossier Work")
            else:
                doc.id_statut = statut_obj
                doc.id_nature = nature_rapport_obj
                doc.id_format = format_rapport_obj
                doc.description = f"{nature_rapport_obj.nature} du dossier {dossier.numero}"
                doc.numero = None
                doc.save()
                logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_rapport_obj.nature} {nom_fichier_rapport_ca} déjà existant en base – aucune création")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Projet Rapport CA : erreur lors de la création du document {nom_fichier_rapport_ca} en base : {e}")

    # =======================
    # --- Ajout validant ---
    # =======================
    try:
        # Suppression des valideurs du dossier (si existants)
        deleted_count, _ = DossierValideur.objects.filter(id_dossier=dossier).delete()
        if deleted_count > 0:
            logger.info(f"[DOSSIER {dossier.numero}] {deleted_count} validant(s) existant(s) supprimé(s) du dossier.")

        valideur, created = DossierValideur.objects.get_or_create(id_dossier=dossier,id_instructeur=validant_obj)
        logger.info(f"[DOSSIER {dossier.numero}] Validant·e {validant_obj} affecté·e au dossier.")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'affectation du validant·e {validant} : {e}")


    # Changer Etape
    err = safe_update_etape(dossier, "À valider avant signature", request, break_si_erreur=True)
    if err: 
        return err

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, action="Envoyé pour validation", request=request)

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def avis_envoye(request):

    dossier_id_ds = request.POST.get("dossierId")

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[DOSSIER {dossier.numero}] Échec de l'envoi de l'avis par {request.user} : ID du dossier DS manquant dans le formulaire.")
        return redirect_error(request, f"❌ Envoi de l'avis impossible : ID du dossier DS manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "AVIS ENVOYÉ", id_ds=dossier_id_ds)
    if err: 
        return err
    
     # --- Vérification Instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Envoyer avis")
    if err: 
        return err


    # Check qu'il ne reste pas d'avis non envoyés
    avis_a_envoyer = Avis.objects.filter(
        id__in=DossierAvis.objects.filter(
            id_dossier=dossier,
            id_avis__statut="À envoyer"
        ).values_list("id_avis", flat=True)
    ).count()

    if avis_a_envoyer > 0 :
        return redirect_error(request, "❌ Il reste un ou plusieurs avis à envoyer.")


    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "En attente réponse d'avis", request, break_si_erreur=True)
    if err:
        return err
    
    
    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, "Avis demandé", request)

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def valider_le_modele_de_demande_d_avis_et_le_projet_d_acte(request):
    
    dossier_id_ds = request.POST.get("dossierId")

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[VALIDER AVANT DEMANDE AVIS] Échec de la validation du modèle de demande d'avis et du projet d'acte par {request.user} : ID du dossier DS manquant dans le formulaire.")
        return redirect_error(request, f"❌ ID du dossier DS manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "VALIDER AVANT DEMANDE AVIS", id_ds=dossier_id_ds)
    if err: 
        return err
    
    # --- Vérification Instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Validé avant demande d'avis")
    if err: 
        return err


    # --- MAJ des Documents (valider --> Validé) ---
    statut_a_valider = DocumentStatut.objects.filter(statut="À valider").first()
    statut_valide_avant_demande_avis = DocumentStatut.objects.filter(statut="Validé avant demande d'avis").first()

    if not statut_a_valider :
        logger.error(f"[DOSSIER {dossier.numero}] Échec de la validation du modèle de demande d'avis et du projet d'acte par {request.user} : DocumentStatut 'À valider' introuvable en base.")
        return redirect_error(request, "❌ Statut 'À valider' introuvable en base. Contactez le support.")
    
    if not statut_valide_avant_demande_avis:
        logger.error(f"[DOSSIER {dossier.numero}] Échec de la validation du modèle de demande d'avis et du projet d'acte par {request.user} : DocumentStatut 'Validé avant demande d'avis' introuvable en base.")
        return redirect_error(request, "❌ Statut 'Validé avant demande d'avis' introuvable en base. Contactez le support.")

    docs_a_valider = DossierDocument.objects.filter(id_dossier=dossier, id_document__id_statut=statut_a_valider)

    for doc in docs_a_valider :
        try:
            d = doc.id_document
            d.id_statut = statut_valide_avant_demande_avis
            d.save()
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Échec de la validation du modèle de demande d'avis et du projet d'acte par {request.user} : Erreur MAJ du statut du Document {d.id} : {e}")


    # --- MAJ des Avis (A valider --> A envoyer) ---
    avis_a_valider = Avis.objects.filter(
        id__in=DossierAvis.objects.filter(
            id_dossier=dossier,
            id_avis__statut="À valider"
        ).values_list("id_avis", flat=True)
    )

    for avis in avis_a_valider:
        try :
            avis.statut = "À envoyer"
            avis.save()
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Échec de la validation du modèle de demande d'avis et du projet d'acte par {request.user} : Erreur MAJ du statut de l'Avis {avis.id} : {e}")


    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "Avis à envoyer", request, break_si_erreur=True)
    if err:
        return err
    
    # --- Enregistrer Action ---
    nom_prenom = instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom
    safe_enregistrer_action(dossier, instructeur, "Validé avant demande d'avis", request, description=nom_prenom)

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def repasser_en_instruction(request):

    dossier_id_ds = request.POST.get("dossierId")

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[REPASSAGE EN INSTRUCTION] User={request.user} : ID du dossier DS manquant")
        return redirect_error(request, "❌ Impossible de repasser en instruction : ID Démarche Numérique du dossier manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "REPASSAGE EN INSTRUCTION", id_ds=dossier_id_ds)
    if err: 
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Repassage en instruction")
    if err:
        return err


    # --- Récupération état actuel ---
    etat_actuel_dossier = dossier.id_etat_dossier.nom.lower() if dossier.id_etat_dossier else ""


    # --- Repassage en instruction sur DS
    if dossier.present_sur_ds :

        # Uniquement si l'état n'est pas déjà 'en_instruction'
        if etat_actuel_dossier != "en_instruction":
            result = repasser_en_instruction_ds(dossier.id_ds, instructeur)

            if not result.get("success"):
                if result.get('message') == "Le dossier est déjà en instruction" :
                    logger.warning(f"[DOSSIER {dossier.numero}] Le dossier n'est pas repassé en instruction sur DS car il est déjà en instruction : {result.get('message')}")
                    return redirect_error(request, "❌ Le dossier n'est pas repassé en instruction sur Démarche Numérique car il est déjà en instruction. Contactez le support.")

                elif result.get('message') == "Le dossier est déjà en construction" :
                    logger.warning(f"[DOSSIER {dossier.numero}] Le dossier n'est pas repassé en instruction sur DS car il est déjà en construction : {result.get('message')}")
                    return redirect_error(request, "❌ Le dossier n'est pas repassé en instruction sur Démarche Numérique car il est déjà en construction. Contactez le support.")
 
                else:
                    logger.error(f"[DOSSIER {dossier.numero}] Échec du repassage en instruction du dossier par {request.user} : {result.get('message')}")
                    return redirect_error(request, "❌ Le dossier n'est pas repassé en instruction sur Démarche Numérique. Contactez le support.")


    # --- Mise à jour Étape ---
    safe_update_etape(dossier, "En instruction", request, break_si_erreur=False) # On continue si Erreur

    # --- Mise à jour État ---
    safe_update_etat(dossier, "en_instruction", request, break_si_erreur=False) # On continue si Erreur

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, "Repassage en instruction", request)


    # =============================================
    # ===   Réinitialisation Statuts et Rôles   ===
    # =============================================

    # Nettoyage rôles
    DossierSignataire.objects.filter(id_dossier=dossier).delete()
    DossierRelecteurQualite.objects.filter(id_dossier=dossier).delete()
    DossierValideur.objects.filter(id_dossier=dossier).delete()


    # Documents 
    statuts_cibles = {"à envoyer", "à signer", "à relire", "à valider"}
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

    for lien in documents_du_dossier:
        doc = lien.id_document
        statut_actuel = doc.id_statut.statut.lower() if doc.id_statut else ""

        if statut_actuel in statuts_cibles:
            doc.id_statut = None
            doc.save()
            logger.info(f"[DOSSIER {dossier.numero}] Repassage en Instruction par {request.user} : Statut du document '{doc.titre}' ({doc.id_nature.nature}) remis à NULL.")

    # Avis
    avis_a_reset = Avis.objects.filter(id_dossier=dossier, statut="À valider")

    for avis in avis_a_reset:
        avis.statut = "Brouillon"
        try:
            avis.save()
            logger.info(f"[DOSSIER {dossier.numero}] Repassage en Instruction par {request.user} : Avis {avis.id} remis en statut 'Brouillon'")
        except ValidationError as e:
            logger.error(f"[DOSSIER {dossier.numero}] Repassage en Instruction par {request.user} : Impossible de remettre l'avis {avis.id} en 'Brouillon' : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))




@require_POST
@login_required
def acte_inchange_envoyer_pour_relecture_qualite(request):

    dossier_id_ds = request.POST.get("dossierId")

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[ENVOI POUR RELECTURE QUALITÉ] User={request.user} : ID du dossier DS manquant dans le formulaire.")
        return redirect_error(request, "❌ Échec de l'envoi pour relecture : ID Démarche Numérique du dossier manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "ENVOI POUR RELECTURE QUALITÉ", id_ds=dossier_id_ds)
    if err: 
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Envoyer pour relecture qualité")
    if err:
        return err


   # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "En relecture qualité", request, break_si_erreur=True)
    if err:
        return err

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, "Envoyé pour relecture qualité", request)

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def valider_et_envoyer_pour_relecture_qualite(request):
    
    dossier_id_ds = request.POST.get("dossierId")
    relecteur = request.POST.get("choix-relecteur") #Objet Instructeur

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[VALIDATION AVANT RELECTURE QUALITÉ] User={request.user} : ID du dossier DS manquant dans le formulaire.")
        return redirect_error(request, "❌ Échec de l'envoi pour relecture : ID Démarche Numérique du dossier manquant. Contactez le support.")

    # --- Vérification choix relecteur ---
    if not relecteur:
        return redirect_error(request, "❌ Vous devez choisir un relecteur qualité.")


    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "RELECTURE QUALITÉ", id_ds=dossier_id_ds)
    if err: 
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Valider avant relecture qualité")
    if err:
        return err


    # --- Récupération relecteur ---
    relecteur_obj = Instructeur.objects.filter(id=relecteur).first()
    if not relecteur_obj:
        logger.error(f"[DOSSIER {dossier.numero}] Validation avant relecture qualité ({request.user}) : Relecteur introuvable (id={relecteur})")
        return redirect_error(request, "❌ Le relecteur sélectionné n’a pas été trouvé en base. Contactez le support.")

    # --- Récupération statut 'À relire' ---
    statut_relire = DocumentStatut.objects.filter(statut__iexact="à relire").first()
    if not statut_relire:
        logger.error(f"[DOSSIER {dossier.numero}] Validation avant relecture qualité ({request.user}) : Statut 'À relire' introuvable en base.")
        return redirect_error(request, "❌ Statut 'À relire' introuvable en base. Contactez le support.")


    # ==============================
    # Ajout du relecteur au dossier
    # ==============================
    try:
        DossierRelecteurQualite.objects.get_or_create(id_dossier=dossier, id_instructeur=relecteur_obj)
        logger.info(f"[DOSSIER {dossier.numero}] Relecteur.rice {relecteur_obj} affecté·e au dossier.")
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Validation avant relecture qualité ({request.user}) : Erreur lors de l'affectation du relecteur.rice {relecteur} : {e}")


    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "En relecture qualité", request, break_si_erreur=True)
    if err: 
        return err

    # --- Enregistrer Action ---
    nom_prenom = instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom
    safe_enregistrer_action(dossier, instructeur, "Validé avant signature", request, description=nom_prenom)


    # =============================================
    #  Mise à jour documents À valider --> À relire
    # =============================================
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

    for lien in documents_du_dossier:
        doc = lien.id_document
        statut = doc.id_statut.statut.lower() if doc.id_statut else ""

        if statut in {"à valider", "validé avant demande d'avis"}:
            doc.id_statut = statut_relire
            try:
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → À relire.")

            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Validation avant relecture qualité ({request.user}) - Erreur MAJ statut document {doc.id} : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def envoyer_les_modifications_de_l_acte_pour_validation(request):
    
    dossier_id_ds = request.POST.get("dossierId")

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[ENVOI POUR VALIDATION] User={request.user} : ID du dossier DS manquant dans le formulaire.")
        return redirect_error(request, "❌ Échec de l'envoi pour validation : ID Démarche Numérique du dossier manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "ENVOI POUR VALIDATION", id_ds=dossier_id_ds)
    if err: 
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Envoyer pour validation")
    if err:
        return err


    # --- Récupération statuts ---
    statut_a_valider = DocumentStatut.objects.filter(statut__iexact="À valider").first()
    statut_valide_avant_demande_avis = DocumentStatut.objects.filter(statut__iexact="Validé avant demande d'avis").first()

    # MAJ statut Documents
    docs_valide_avant_demande_avis = DossierDocument.objects.filter(id_dossier=dossier, id_document__id_statut=statut_valide_avant_demande_avis)

    for doc in docs_valide_avant_demande_avis :
        try:
            d = doc.id_document
            d.id_statut = statut_a_valider
            d.save()
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Envoi pour validation ({request.user}) : Erreur MAJ statut Document {doc.id} : {e}")


    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "À valider avant signature", request, break_si_erreur=True)
    if err:
        return err

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, "Envoyé pour validation", request)

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def pret_a_la_signature(request):

    dossier_id_ds = request.POST.get("dossierId")
    intermediaire_CA_id = request.POST.get("intermediaireCA") # ID instructeur
    intermediaire_dir_id = request.POST.get("intermediaire_dir") # ID instructeur
    
    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[PRÊT À LA SIGNATURE] User={request.user} : ID DS manquant dans le formulaire.")
        return redirect_error(request, "❌ Échec : ID Démarche Numérique du dossier manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "PRÊT À LA SIGNATURE", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Récupération instructeur connecté ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Prêt à la signature")
    if err:
        return err
    
    # --- Récupération statut 'À signer' ---
    statut_a_signer = DocumentStatut.objects.filter(statut__iexact="à signer").first()
    if not statut_a_signer:
        logger.error(f"[DOSSIER {dossier.numero}] Échec du changement d'étape à 'En attente de signature' par {request.user} : Statut 'À signer' introuvable en base.")
        return redirect_error(request, "❌ Statut 'À signer' introuvable en base. Contactez le support.")


    # ================================
    #   INTERMÉDIAIRE SIGNATURE
    # ================================
    # Supprime les anciens intermédiaires associés au dossier
    DossierIntermediaireSignature.objects.filter(id_dossier=dossier).delete()

    # Intermédiaire CA
    if intermediaire_CA_id:
        intermediaire_CA = Instructeur.objects.filter(id=intermediaire_CA_id).first()

        if intermediaire_CA:  
            try:
                DossierIntermediaireSignature.objects.create(id_dossier=dossier, id_instructeur=intermediaire_CA)
                logger.info(f"[DOSSIER {dossier.numero}] Intermédiaire CA ajouté : {intermediaire_CA}")
            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Échec du changement d'étape à 'En attente de signature' par {request.user} : Erreur ajout intermédiaire CA : {e}")


    # Intermédiaire Directeur
    if intermediaire_dir_id:
        intermediaire_dir = Instructeur.objects.filter(id=intermediaire_dir_id).first()

        if intermediaire_dir:
            try:
                DossierIntermediaireSignature.objects.create(id_dossier=dossier, id_instructeur=intermediaire_dir)
                logger.info(f"[DOSSIER {dossier.numero}] Intermédiaire Directeur ajouté : {intermediaire_dir}")
            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Échec du changement d'étape à 'En attente de signature' par {request.user} : Erreur ajout intermédiaire Directeur : {e}")

    
    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "En attente de signature", request, break_si_erreur=True)
    if err:
        return err

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, "Prêt à la signature", request)


    # --- Mise à jour Doc "À relire" --> "À signer"
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")
    for lien in documents_du_dossier:
        doc = lien.id_document
        statut = doc.id_statut.statut.lower() if doc.id_statut else ""

        if statut == "à relire":
            try:
                doc.id_statut = statut_a_signer
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → À signer.")

            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Changement d'étape à 'En attente de signature' par {request.user} : Erreur MAJ statut document {doc.id} : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))




# Methode raccourci pour SPPN
@require_POST
@login_required
def acte_pret_a_la_signature(request):

    dossier_id_ds = request.POST.get("dossierId")
    intermediaire_CA_id = request.POST.get("intermediaireCA") # ID instructeur
    intermediaire_dir_id = request.POST.get("intermediaire_dir") # ID instructeur

    nature = request.POST.get("nature_document")
    # fichier = request.FILES.get("piece_jointe")
    nom_fichier = (request.POST.get("piece_jointe_work") or "").strip()
    # fichier_rapport_CA = request.FILES.get("piece_jointe_rapport_ca")
    nom_fichier_rapport_ca = (request.POST.get("piece_jointe_rapport_ca_work") or "").strip()

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[PRÊT À LA SIGNATURE] User={request.user} : ID DS manquant dans le formulaire.")
        return redirect_error(request, "❌ Échec : ID Démarche Numérique du dossier manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "PRÊT À LA SIGNATURE", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Récupération instructeur connecté ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Prêt à la signature")
    if err:
        return err
    
    # --- Récupération statut 'À signer' ---
    statut_a_signer = DocumentStatut.objects.filter(statut__iexact="à signer").first()
    if not statut_a_signer:
        logger.error(f"[DOSSIER {dossier.numero}] Échec du changement d'étape à 'En attente de signature' par {request.user} : Statut 'À signer' introuvable en base.")
        return redirect_error(request, "❌ Statut 'À signer' introuvable en base. Contactez le support.")

    if not nature :
        return redirect_error(request, "❌ La nature du projet d'acte est manquante. Contactez le support.")
    
    # Récup nature
    nature_obj = DocumentNature.objects.filter(nature=nature).first()
    if not nature_obj:
        logger.error(f"[DOSSIER {dossier.numero}] Échec du changement d'étape à 'En attente de signature' par {request.user} : Nature '{nature}' introuvable en base (user={request.user})")
        return redirect_error(request, f"❌ La nature '{nature}' n'existe pas en base. Contactez le support.")

    if not nom_fichier:
        return redirect_error(request, "❌ Le projet d'acte n'a pas été sélectionné.")

    # Fichier 
    # if not fichier:
    #     return redirect_error(request, "❌ Le projet d'acte n'a pas été joint.")

    # Vérification que l'extension du file est .doc, .docx, .pdf, .odt
    extension = Path(nom_fichier).suffix.lower()
    if extension not in {".doc", ".docx", ".odt"} :
        return redirect_error(request, f"❌ Le projet d'acte joint doit etre .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
    
    # Rapport CA
    if nature == "Déliberation CA" and not nom_fichier_rapport_ca:
        return redirect_error(request, "❌ Le projet de rapport du CA n'a pas été sélectionné.")

    if nature == "Déliberation CA" and nom_fichier and nom_fichier_rapport_ca and nom_fichier == nom_fichier_rapport_ca:
        logger.warning(f"[DOSSIER {dossier.numero}] Prêt à la signature refusé par {request.user} : "
            f"le projet de délibération et le projet de Rapport CA sont identiques ({nom_fichier})."
        )
        return redirect_error(request, "❌ Le projet de délibération et le projet de Rapport CA doivent être deux documents différents.")



    format_obj = DocumentFormat.objects.filter(format=extension.lstrip('.')).first()
    if not format_obj:
        logger.error(f"[VALIDER PROJET ACTE] Format '{extension}' introuvable")
        return redirect_error(request, f"❌ Format '{extension}' introuvable en base. Contactez le support.")


    # Vérification que le file sélectionné est bien dans le sous dossier Work
    dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")
    full_path = os.path.join(os.environ.get("NAS_ROOT"), dossier_path)
    creer_dossier_sur_nas(full_path)

    filepath = os.path.join(full_path, nom_fichier)
    if not smbclient.path.exists(filepath):
        return redirect_error(request, "❌ Le projet d’acte doit être dans le sous-dossier 'Work' du dossier concerné.")
    


    ############################## 
    # Sauvegarde du Projet d'acte
    ##############################
    try:
        # Écriture du fichier sur le NAS ?
        # if not ecrire_file_sur_nas(fichier, filepath): 
        #     raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {filepath}")
        
        # Enregistrer en BDD
        doc, created = Document.objects.get_or_create(
                        emplacement=dossier_path, titre=nom_fichier, id_format=format_obj,
                        defaults={
                            "id_format": format_obj,
                            "id_nature": nature_obj,
                            "id_statut": statut_a_signer,
                            "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                        }
                    )

        if created:
            DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
            logger.info(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {nom_fichier} créé dans le dossier Work")
            
        else:
            doc.id_statut = statut_a_signer
            doc.id_nature = nature_obj
            doc.id_format = format_obj
            doc.description = f"{nature_obj.nature} du dossier {dossier.numero}"
            doc.save()
            logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_obj.nature} {nom_fichier} déjà existant en base – aucune création")
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] {nature_obj.nature} : Erreur lors du changement d'étape 'En attente de signature' par {request.user} - Erreur lors de la création du Document {nom_fichier} en base : {e}")



    ########################
    # Projet rapport CA
    ########################

    if nature == "Déliberation CA" :

        extension_rapport = Path(nom_fichier_rapport_ca).suffix.lower()
        if extension_rapport not in {".doc", ".docx", ".odt"} :
            return redirect_error(request, f"❌ Le projet de rapport du CA joint doit etre .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension_rapport}")
        
        filepath_rapport = os.path.join(full_path, nom_fichier_rapport_ca)
        # Vérification que le projet Rapport CA est bien dans le sous dossier Work
        if not smbclient.path.exists(filepath_rapport):
            return redirect_error(request, "❌ Le projet de rapport du CA doit être placé dans le sous-dossier 'Work' du dossier concerné.")

        try:
            # Écriture du fichier sur le NAS
            # if not ecrire_file_sur_nas(fichier, filepath_rapport): 
            #     raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {filepath_rapport}")

            nature_rapport_obj  = DocumentNature.objects.filter(nature="Projet Rapport CA").first()
            if not nature_rapport_obj :
                return redirect_error(request, "❌ Nature 'Projet Rapport CA' introuvable en base. Contactez le support.")

            format_rapport_obj  = DocumentFormat.objects.filter(format=extension_rapport.lstrip('.')).first()
            if not format_rapport_obj :
                return redirect_error(request, f"❌ Format '{extension_rapport}' non trouvé en base. Contactez le support.")


            # Enregistrer en BDD
            doc, created = Document.objects.get_or_create(
                                emplacement=dossier_path, titre=nom_fichier_rapport_ca,
                                defaults={
                                    "id_format": format_rapport_obj ,
                                    "id_nature": nature_rapport_obj ,
                                    "id_statut": statut_a_signer,  # Récupéré précédemment
                                    "description": f"{nature_rapport_obj .nature} du dossier {dossier.numero}",
                                }
                            )
            if created:
                
                DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
                logger.info(f"[DOSSIER {dossier.numero}] {nature_rapport_obj .nature} {nom_fichier_rapport_ca} créé dans le dossier Work")
            else:
                
                doc.id_statut = statut_a_signer
                doc.id_nature = nature_rapport_obj 
                doc.id_format = format_rapport_obj 
                doc.description = f"{nature_rapport_obj .nature} du dossier {dossier.numero}"
                doc.numero = None
                doc.save()
                logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_rapport_obj .nature} {nom_fichier_rapport_ca} déjà existant en base – aucune création")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] {nature_rapport_obj .nature} : Erreur lors du changement d'étape 'En attente de signature' par {request.user} - Erreur lors de la création du Document {nom_fichier_rapport_ca} en base : {e}")



    # ================================
    #   INTERMÉDIAIRE SIGNATURE
    # ================================
    # Supprime les anciens intermédiaires associés au dossier
    DossierIntermediaireSignature.objects.filter(id_dossier=dossier).delete()

    # Intermédiaire CA
    if intermediaire_CA_id:
        intermediaire_CA = Instructeur.objects.filter(id=intermediaire_CA_id).first()

        if intermediaire_CA:  
            try:
                DossierIntermediaireSignature.objects.create(id_dossier=dossier, id_instructeur=intermediaire_CA)
                logger.info(f"[DOSSIER {dossier.numero}] Intermédiaire CA ajouté : {intermediaire_CA}")
            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Échec du changement d'étape à 'En attente de signature' par {request.user} : Erreur ajout intermédiaire CA : {e}")


    # Intermédiaire Directeur
    if intermediaire_dir_id:
        intermediaire_dir = Instructeur.objects.filter(id=intermediaire_dir_id).first()

        if intermediaire_dir:
            try:
                DossierIntermediaireSignature.objects.create(id_dossier=dossier, id_instructeur=intermediaire_dir)
                logger.info(f"[DOSSIER {dossier.numero}] Intermédiaire Directeur ajouté : {intermediaire_dir}")
            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Échec du changement d'étape à 'En attente de signature' par {request.user} : Erreur ajout intermédiaire Directeur : {e}")

    
    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "En attente de signature", request, break_si_erreur=True)
    if err:
        return err

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, "Prêt à la signature", request)


    # --- Mise à jour Doc "À relire" --> "À signer"
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")
    for lien in documents_du_dossier:
        doc = lien.id_document
        statut = doc.id_statut.statut.lower() if doc.id_statut else ""

        if statut == "à relire":
            try:
                doc.id_statut = statut_a_signer
                doc.id_nature = nature_obj
                doc.id_format = format_obj
                doc.description = f"{nature_obj.nature} du dossier {dossier.numero}"
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → À signer.")

            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Changement d'étape à 'En attente de signature' par {request.user} : Erreur MAJ statut document {doc.id} : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))






@require_POST
@login_required
def acte_pret_a_etre_envoye(request):

    dossier_id_ds = request.POST.get("dossierId")
    fichier = request.FILES.get("piece_jointe")
    fichier_rapportCA = request.FILES.get("pj_rapport_CA")
    signataire_id = request.POST.get("choix-signataire") # id Instructeur
    envoyeur_id = request.POST.get("choix-envoi-acte-peti") # id Instructeur
    nature_document = request.POST.get("nature_document")
    id_doc_a_signer = request.POST.get("id_doc_a_signer")
    id_projet_rapport_ca = request.POST.get("id_projet_rapport_ca")

    # =========================
    #     VÉRIFICATIONS
    # =========================

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[ACTE PRÊT À ENVOI] User={request.user} : ID DS manquant.")
        return redirect_error(request, "❌ ID Démarche Numérique manquant. Contactez le support.")

     # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "ACTE PRÊT À ENVOI", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Récupération instructeur connecté ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Acte prêt à être envoyé")
    if err:
        return err
    
    # --- Vérification Statut ---
    statut_a_envoyer = DocumentStatut.objects.filter(statut__iexact = "à envoyer").first()
    if not statut_a_envoyer:
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Statut 'À envoyer' introuvable en base.")
        return redirect_error(request, "❌ Statut 'À envoyer' introuvable en base. Contactez le support.")
    
    # --- Vérification Nature Acte ---
    doc_nature = DocumentNature.objects.filter(nature__iexact = nature_document).first()
    if not doc_nature:
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Nature {nature_document} introuvable en base.")
        return redirect_error(request, f"❌ Nature '{nature_document}' introuvable en base. Contactez le support.")
    
    # --- Vérification Rapport CA ---
    if fichier_rapportCA :
        doc_nature_rapportCA = DocumentNature.objects.filter(nature__iexact = "Rapport CA").first()
        if not doc_nature_rapportCA:
            logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Nature {doc_nature_rapportCA} introuvable en base.")
            return redirect_error(request, f"❌ Nature 'Rapport CA' introuvable en base. Contactez le support.")

        extension_RapCA = Path(fichier_rapportCA.name).suffix.lower()
        if extension_RapCA != ".pdf" :
            return redirect_error(request, f"❌ Le rapport du CA doit etre au format PDF --> Type de fichier non autorisé : {extension_RapCA}")

        if not id_projet_rapport_ca :
            logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Le projet de Rapport CA n'est pas reconnu.")
            return redirect_error(request, f"❌ Le projet de Rapport CA n'est pas reconnu. Contactez le support.")
        else :
            projet_rapportCA = Document.objects.filter(id=id_projet_rapport_ca).first()
            if not projet_rapportCA :
                logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' : Projet de Rapport CA id={str(id_projet_rapport_ca)} introuvable.")
                return redirect_error(request,f"❌ Le projet de Rapport CA (id = {str(id_projet_rapport_ca)}) est introuvable en base. Contactez le support.")

    
    # --- Vérification Format PDF ---
    format_pdf = DocumentFormat.objects.filter(format__iexact = "pdf").first()
    if not format_pdf:
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Format PDF introuvable en base.")
        return redirect_error(request, "❌ Format PDF introuvable en base. Contactez le support.")

    # --- Vérification Signataire ---
    signataire = get_object_or_404(Instructeur, id=signataire_id)
    if not signataire:
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Instructeur (ID {signataire_id}) introuvable en base.")
        return redirect_error(request, f"❌ Instructeur (ID {signataire_id}) introuvable en base. Contactez le support.")
    
    # --- Vérification Envoyeur ---
    envoyeur = get_object_or_404(Instructeur, id=envoyeur_id)
    if not envoyeur:
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Instructeur (ID {envoyeur_id}) introuvable en base.")
        return redirect_error(request, f"❌ Instructeur (ID {envoyeur_id}) introuvable en base. Contactez le support.")
    
    # Vérification Acte au format PDF
    if not fichier:
        return redirect_error(request, "❌ Aucun fichier Acte fourni.")
    
    extension = Path(fichier.name).suffix.lower()
    if extension != ".pdf" :
        return redirect_error(request, f"❌ L'acte signé doit etre au format PDF --> Type de fichier non autorisé : {extension}")
    
    # Vérification sur le projet d'acte existant
    if id_doc_a_signer :
        projet_acte = Document.objects.filter(id=id_doc_a_signer).first()
        if not projet_acte:
            logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' : Projet d'acte id={str(id_doc_a_signer)} introuvable.")
            return redirect_error(request,f"❌ Le projet d'acte (id = {str(id_doc_a_signer)}) est introuvable en base. Contactez le support.")
        if not projet_acte.numero :
            logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Le projet d'acte n'a pas de numéro.")
            return redirect_error(request, f"❌ Le projet d'acte n'a pas eu de numéro attribué. Contactez le support.")
    else :
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Le projet d'acte n'est pas reconnu.")
        return redirect_error(request, f"❌ Le projet d'acte n'est pas reconnu. Contactez le support.")


    # Vérification dossier Actes
    dossier_path = os.path.join(dossier.emplacement, "Actes/").replace("\\", "/")
    full_path = os.path.join(os.environ.get("NAS_ROOT"), dossier_path)
    creer_dossier_sur_nas(full_path)


    # =================================
    #   Écriture Acte signé dans /Actes
    # =================================

    """
    Ici on est dans acte_pret_a_etre_envoye : manifestement c'est là que les actes signés (pdf) et rapport CA (pdf) sont écrit dans /Actes
    Regarder ce qui se passe dans : envoyer_l_acte, envoyer_l_acte_de_refus --> J'ai l'impression qu'on Copie des trucs dans /Actes aussi ???
    
    """

    # === 1. On génère le nom (ex : DIR-I-2026-031_05-03-26) ===
    if nature_document == "Déliberation CA" :
        prefixe = "DELIB-CA"
    elif nature_document == "Arrêté directeur" :
        prefixe = "DIR-I"
    elif nature_document == "Avis conforme" :
        prefixe = "AVIS-CONFORME"
    elif nature_document == "Avis simple" :
        prefixe = "AVIS-SIMPLE"
    else : 
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Nature {nature_document} n'est pas parmis : Déliberation CA, Arrêté directeur, Avis conforme, Avis simple.")
        return redirect_error(request, f"❌ Nature de document '{nature_document}' non reconnue. Contactez le support.")
    
    date_du_jour = datetime.today().strftime("%d-%m")
    nom_acte_genere = f"{prefixe}-{projet_acte.numero}_{date_du_jour}"


    # === 2. On s'assure qu'on a un nom unique ===
    titre_final_acte_signe, abs_file_path_acte_signe = generate_unique_filename(
        dir_abs_path = full_path, 
        dir_rel_path = dossier_path, 
        base_filename = f"{nom_acte_genere}.pdf"
    )

    abs_file_path_acte_signe = _normalize_unc_path(abs_file_path_acte_signe)
    

    # === 3. On écrit dans le dossier /Actes ===
    if not ecrire_file_sur_nas(fichier, abs_file_path_acte_signe): 
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Échec de l’écriture du fichier {nom_acte_genere}.pdf sur {abs_file_path_acte_signe}.")
        return redirect_error(request, f"❌ Échec de l’écriture du fichier {nom_acte_genere}.pdf sur {abs_file_path_acte_signe}. Contactez le support.")

    
    logger.info(f"[DOSSIER {dossier.numero}] Transmission de l'acte signé par {request.user} : {nature_document} ({nom_acte_genere}.pdf) écrit dans le dossier Actes.")
    
    # filepath = os.path.join(full_path, fichier.name)
    # err = save_if_not_exists(request, dossier, fichier, filepath, fail_if_exists=True)
    # if err:
    #     return err


    # ====================================
    #   Écriture Rapport CA PDF (optionnel)
    # ====================================
    filepath_rapportCA = None

    if fichier_rapportCA :

        # === 1. On génère le nom (ex : RapportCA_05-03-26) ===
        nom_rapportCA_genere = f"RapportCA_{date_du_jour}"

        
        # === 2. On s'assure qu'on a un nom unique ===
        titre_final_rapportCA, abs_file_path_rapportCA = generate_unique_filename(
            dir_abs_path = full_path, 
            dir_rel_path = dossier_path, 
            base_filename = f"{nom_rapportCA_genere}.pdf"
        )

        abs_file_path_rapportCA = _normalize_unc_path(abs_file_path_rapportCA)


        # === 3. On écrit dans le dossier /Actes ===
        if not ecrire_file_sur_nas(fichier_rapportCA, abs_file_path_rapportCA): 
            raise (f"Échec de l’écriture du fichier {nom_rapportCA_genere}.pdf sur {abs_file_path_rapportCA}")
        
        logger.info(f"[DOSSIER {dossier.numero}] Transmission de l'acte signé par {request.user} : Rapport CA ({nom_rapportCA_genere}.pdf) écrit dans le dossier Actes.")

        # filepath_rapportCA = os.path.join(full_path, fichier_rapportCA.name)
        
        # err = save_if_not_exists(request, dossier, fichier_rapportCA, filepath_rapportCA, fail_if_exists=True)
        # if err:
        #     return err



    # -----------------------------------
    # Remise à zéro des statuts documents 
    # -----------------------------------
    statuts_cibles = {"à envoyer", "à signer", "à relire", "à valider"}
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

    for lien in documents_du_dossier:
        doc = lien.id_document
        statut_actuel = doc.id_statut.statut.lower() if doc.id_statut else ""

        if statut_actuel in statuts_cibles:
            try :
                doc.id_statut = None
                doc.save()
                # logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé : statut du document '{doc.titre}' remis à NULL.")
            
            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Changement d'étape à 'Acte à envoyer' par {request.user} : Erreur MAJ statut document {doc.id} : {e}")


    # ----------------------------------
    # Création du doc (Acte) "À envoyer" 
    # ----------------------------------

    """
    On met à jour le doc projet_acte (projet acte word devient acte signé pdf : statut, format, numero, path, description) plutot que de faire un get_or_create
    --> titre_final_acte_signe à la place du fichier.name 
    """

    try:
        projet_acte.id_statut = statut_a_envoyer
        projet_acte.id_format = format_pdf
        projet_acte.titre = f"{titre_final_acte_signe}.pdf"
        projet_acte.emplacement = dossier_path
        projet_acte.description = f"{nature_document} pour le dossier {dossier.numero}"
        projet_acte.save()

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Échec MAJ {nature_document} (id={projet_acte.id}) en BDD : {e}")
        return redirect_error(request,f"❌ {nature_document} copié dans le Dossier '/Actes' mais échec de sa mise à jour en base. Contactez le support.")
                

    # doc, created = Document.objects.get_or_create(
    #                         emplacement=dossier_path, titre=fichier.name,
    #                         defaults={
    #                             "id_format": format_pdf,
    #                             "id_nature": doc_nature,
    #                             "id_statut": statut_a_envoyer,
    #                             "description": f"{doc_nature.nature} du dossier {dossier.numero}",
    #                         }
    #                     )
    
    # if created:
    #     DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
    #     logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé : {fichier.name} ({doc_nature.nature} 'À envoyer') créé et lié au dossier")
    # else:
    #     try :
    #         doc.id_statut = statut_a_envoyer
    #         doc.save()
    #         logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé : {fichier.name} ({doc_nature.nature}, {doc.id_statut.statut}) déjà existant – statut changé à 'À envoyer'")
    #     except Exception as e:
    #         logger.error(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé ({request.user}) : Erreur lors de la MAJ au statut 'à envoyer' du document {doc.id} : {e}")


    # ---------------------------------
    # Création Document Rapport CA
    # ---------------------------------
    if fichier_rapportCA :

        """ 
        On met à jour le doc projet_rapportCA (Projet Rapport CA word devient Rapport CA (Word ou pdf ici ?) : statut, format, path, description) plutot que de faire un get_or_create
        --> nom unique à la place du fichier_rapportCA.name  (TO DO)   
        """

        try:
            projet_rapportCA.id_statut = statut_a_envoyer
            projet_rapportCA.id_format = format_pdf
            projet_rapportCA.id_nature = doc_nature_rapportCA
            projet_rapportCA.titre = f"{titre_final_rapportCA}.pdf"
            projet_rapportCA.emplacement = dossier_path
            projet_rapportCA.description = f"{doc_nature_rapportCA} du dossier {dossier.numero}"
            projet_rapportCA.save()

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Échec MAJ Projet Rapport CA (id={projet_rapportCA.id}) en BDD : {e}")
            return redirect_error(request,f"❌ {doc_nature_rapportCA} copié dans le Dossier '/Actes' mais échec de sa mise à jour en base. Contactez le support.")

        # doc_ca, created = Document.objects.get_or_create(
        #                         emplacement=dossier_path, titre=fichier_rapportCA.name,
        #                         defaults={
        #                             "id_format": format_pdf,
        #                             "id_nature": doc_nature_rapportCA,
        #                             "description": f"{doc_nature_rapportCA.nature} du dossier {dossier.numero}",
        #                         }
        #                     )
        
        # if created:
        #     DossierDocument.objects.create(id_dossier=dossier, id_document=doc_ca)
        #     logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé - Transmission du Rapport CA : {fichier.name} (Document {doc_ca.numero}) créé et lié au dossier")
        # else:
        #     try :
        #         doc_ca.id_statut = statut_a_envoyer
        #         doc_ca.save()
        #         logger.warning(f"[DOSSIER {dossier.numero}] Transmission du Rapport CA par {request.user} : {fichier.name} (Document {doc_ca.numero}, Statut {doc_ca.id_statut.statut}) déjà existant – statut changé à 'À envoyer'")

        #     except Exception as e:
        #         logger.error(f"[DOSSIER {dossier.numero}] Passage Étape 'Acte prêt à être envoyé' par {request.user} - Transmission du Rapport CA : Erreur lors de la MAJ au statut 'à envoyer' du document {doc_ca.id} existant : {e}")




    # Ajout du signataire au dossier
    err = set_dossier_role(DossierSignataire, dossier, signataire, "Signataire", request)
    if err:
        return err
    

    # Ajout de l'envoyeur d'acte au dossier
    err = set_dossier_role(DossierEnvoiActe, dossier, envoyeur, "Envoyeur d'acte", request)
    if err:
        return err
    

    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "Acte à envoyer", request, break_si_erreur=True)
    if err:
        return err


    # --- Enregistrer Action ---
    signataire_nom_prenom = f"{signataire.id_agent_autorisations.nom} {signataire.id_agent_autorisations.prenom}"
    safe_enregistrer_action(dossier, instructeur, "Acte signé", request, description=signataire_nom_prenom)

    return redirect(request.META.get("HTTP_REFERER", "/"))

 

@require_POST
@login_required
def classer_le_dossier_comme_accepte(request):
    
    dossier_id_ds = request.POST.get("dossierId")

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[ACCEPTATION DOSSIER] User={request.user} : ID DS manquant.")
        return redirect_error(request, "❌ Impossible de classer le dossier comme accepté : ID DS manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "ACCEPTATION DOSSIER", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Classer comme accepté")
    if err:
        return err


    # --- Mise à jour document publié au RAA ---
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

    for lien in documents_du_dossier:
        doc = lien.id_document
        try:
            if doc.id_statut and doc.id_statut.statut.lower() == "envoyé" and not doc.publie_au_raa:
                doc.publie_au_raa = True
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Document {doc.titre} publié au RAA par {request.user}.")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la MAJ publié_au_raa ({request.user}) pour le Document {doc.id} : {e}")
            return redirect_error(request, f"❌ Erreur lorsqu'on tente d'indiquer la bonne publication au RAA du document {doc.titre}. Contactez le support.")


    # --- Mise à jour Date Fin Instruction ---
    try:
        dossier.date_fin_instruction = timezone.now()
        dossier.save()
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur MAJ date_fin_instruction par {request.user} (date = {timezone.now()}) : {e}")
        messages.error(request, "❌ Erreur lors de la mise à jour de la date de fin d’instruction. Contactez le support.")
        # on continue


    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "Accepté", request, break_si_erreur=True)
    if err:
        return err

    #Dossier Action
    safe_enregistrer_action(dossier, instructeur, "Classé comme accepté", request)

    return redirect(request.META.get("HTTP_REFERER", "/"))




@require_POST
@login_required
def classer_le_dossier_comme_refuse(request):
    
    dossier_id_ds = request.POST.get("dossierId")

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[REFUS DOSSIER] User={request.user} : ID DS manquant.")
        return redirect_error(request, "❌ Impossible de classer le dossier comme refusé : ID DS manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "REFUS DOSSIER", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Classer comme refusé")
    if err:
        return err


    # --- Mise à jour document publié au RAA ---
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

    for lien in documents_du_dossier:
        doc = lien.id_document
        try:
            if doc.id_statut and doc.id_statut.statut.lower() == "envoyé" and not doc.publie_au_raa:
                doc.publie_au_raa = True
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Document {doc.titre} publié au RAA par {request.user}.")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la MAJ publié_au_raa ({request.user}) pour le Document {doc.id} : {e}")
            return redirect_error(request, f"❌ Erreur lorsqu'on tente d'indiquer la bonne publication au RAA du document {doc.titre}. Contactez le support.")


    # --- Mise à jour Date Fin Instruction ---
    try:
        dossier.date_fin_instruction = timezone.now()
        dossier.save()
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur MAJ date_fin_instruction par {request.user} (date = {timezone.now()}) : {e}")
        messages.error(request, "❌ Erreur lors de la mise à jour de la date de fin d’instruction. Contactez le support.")
        # on continue


    # --- Mise à jour Étape ---
    err = safe_update_etape(dossier, "Refusé", request, break_si_erreur=True)
    if err:
        return err

    # Dossier Action
    safe_enregistrer_action(dossier, instructeur, "Classé comme refusé", request)

    return redirect(request.META.get("HTTP_REFERER", "/"))






####################################################
###             ACTE D'ACCEPTATION               ###
####################################################
@login_required
@require_POST
def envoyer_l_acte(request):

    dossier_id_ds = request.POST.get("dossierId")
    dossier_numero = request.POST.get("dossier_numero")
    motivation = request.POST.get("motivation", "Votre demande a été acceptée.")
    document_id = request.POST.get("document_id_existant")  #ID du Doc à envoyer
    rapportCA_id = request.POST.get("rapportCA_id")
    nature_document = request.POST.get("nature_document")
    publieur_raa_id = request.POST.get("choix-publieur-raa") # id Instructeur

    root_folder = os.path.join(os.environ.get("NAS_ROOT"))

    # ============================
    #        VÉRIFICATIONS
    # ============================

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[ENVOYER ACTE] User={request.user} : ID DS manquant.")
        return redirect_error(request, "❌ Impossible d'envoyer l'acte : ID DS manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "ENVOYER ACTE", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Envoyer l'acte")
    if err:
        return err

    # --- Nature de l'acte ---
    if not nature_document:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Nature du document {document_id} (Statut : À envoyer) manquante dans le formulaire.")
        return redirect_error(request,"❌ La nature (Arrêté, Délibération...) de l’acte à envoyer est manquante. Contactez le support.")

    nature_obj = DocumentNature.objects.filter(nature__iexact=nature_document.strip()).first()
    if not nature_obj:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Document id={document_id} : Nature {nature_document} introuvable.")
        return redirect_error(request,f"❌ La nature de document '{nature_document}' est introuvable en base. Contactez le support.")
    
    # --- Publieur RAA ---
    if nature_obj.nature != "Déliberation CA" :
        if not publieur_raa_id :
            return redirect_error(request,"❌ Vous devez choisir la personne chargée de publier l’acte au RAA.")
        
        publieur_raa = Instructeur.objects.filter(id=publieur_raa_id).first()
        if not publieur_raa:
            logger.error(f"[DOSSIER {dossier_numero}] Échec envoi acte ({request.user}) : Publieur RAA introuvable (id={publieur_raa_id}).")
            return redirect_error(request, f"❌ Publieur.se RAA introuvable en base. Contactez le support.")

    # --- Document à envoyer ---
    if not document_id:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : ID du document signé (Statut : À envoyer) manquant dans le formulaire.")
        return redirect_error(request,"❌ L'acte signé à envoyer est introuvable depuis l'application (ID du document NULL). Contactez le support.")

    document = Document.objects.filter(id=document_id).select_related("id_format").first()
    if not document:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Document id={document_id} (Statut : À envoyer) introuvable.")
        return redirect_error(request,"❌ Le document signé à envoyer est introuvable en base. Contactez le support.")
    
    # --- Format de l'acte ---
    if not document.id_format or not document.id_format.format:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Format du Document id={document.id} (Statut : À envoyer) introuvable.")
        return redirect_error(request,"❌ Le format du document signé est introuvable en base. Contactez le support.")

    # --- Statut "Envoyé"
    statut_envoye = DocumentStatut.objects.filter(statut__iexact="envoyé").first()
    if not statut_envoye:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Statut 'Envoyé' introuvable.")
        return redirect_error(request, "❌ Statut 'Envoyé' introuvable en base. Contactez le support.")
        

    # ===================================================
    #            LECTURE DE L'ACTE SIGNÉ
    # ===================================================
    try:
        # Construire l’emplacement de stockage
        dossier_path = dossier.emplacement
        emplacement_relatif_dossier_acte = os.path.join(dossier_path, 'Actes/')
        emplacement_absolu_dossier_acte = os.path.join(os.environ.get("NAS_ROOT"), emplacement_relatif_dossier_acte)

        emplacement_doc = os.path.join(emplacement_relatif_dossier_acte, f"{document.titre}")
        full_path_doc = os.path.join(os.environ.get("NAS_ROOT"), emplacement_doc)


        # Définir le Content Type à partir du Format du Doc
        format_str = document.id_format.format.lower()
        if format_str == 'pdf':
            content_type = 'application/pdf'
        elif format_str in ['jpg', 'jpeg']:
            content_type = 'image/jpeg'
        elif format_str == 'png':
            content_type = 'image/png'
        else:
            content_type = 'application/octet-stream'

        try:
            with smbclient.open_file(full_path_doc, mode="rb") as f:
                fichier = SimpleUploadedFile(name=document.titre, content=f.read(), content_type=content_type)

        except Exception as e:
            logger.error(f"[DOSSIER {dossier_numero}] Échec envoi acte ({request.user}) : Impossible de lire le fichier {full_path_doc} : {e}")
            return redirect_error(request,"❌ Impossible de lire le fichier de l’acte sur le serveur. Contactez le support.")
        

        # --- Vérification Format de l'acte ---
        nom, extension = os.path.splitext(fichier.name)
        ext = extension.lstrip('.').lower()
        format_obj = DocumentFormat.objects.filter(format__iexact=ext).first()
        if not format_obj:
            logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Document id={document_id} : Format {ext} introuvable.")
            return redirect_error(request,f"❌ Le format de document '{ext}' est introuvable en base. Contactez le support.")
    

        # ============================================
        #      ACCEPTATION DU DOSSIER SUR DS
        # ============================================
        if dossier.present_sur_ds :
            result = accepter_dossier_ds(dossier_id_ds, instructeur, motivation, fichier)
        
            if result["success"]:
                loggerDS.info(f"[DOSSIER {dossier_numero}] accepté avec succès par {instructeur}")

            else:
                logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l'acceptation du dossier sur DS par {instructeur} : {result['message']}")
                return redirect_error(request, f"Erreur lors de l'acceptation du dossier sur Démarche Numérique. Contactez le support.")



        try :
            with transaction.atomic():
                # -------------------------------------------------------
                # Ajout de la personne chargée de publier l'acte au RAA
                # ------------------------------------------------------
                if nature_obj.nature != "Déliberation CA" :
                    err = set_dossier_role(DossierPublicationRAA, dossier, publieur_raa, "Publieur RAA", request)
                    if err:
                        return err
                

                # ============================================
                #     MISE À JOUR ÉTAPE / ÉTAT / ACTION
                # ============================================
                # --- Mise à jour Étape ---
                if nature_obj.nature == "Déliberation CA" :
                    # On classe le dossier comme accepté
                    err = safe_update_etape(dossier, "Accepté", request, break_si_erreur=True)
                    if err:
                        return err
                    
                else :
                    safe_update_etape(dossier, "À publier au RAA", request, break_si_erreur=False) # On continue si Erreur

                # --- Mise à jour État ---
                safe_update_etat(dossier, "accepte", request, break_si_erreur=False) # On continue si Erreur

                # --- Enregistrer Action ---
                safe_enregistrer_action(dossier, instructeur, "Acte envoyé", request)
                if nature_obj.nature == "Déliberation CA" :
                    safe_enregistrer_action(dossier, instructeur, "Classé comme accepté", request)

                

                # ==============================================
                #     Mise à jour Doc "À envoyer" --> "Envoyé"
                # ==============================================
                documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")
                for lien in documents_du_dossier:
                    doc = lien.id_document
                    statut = doc.id_statut.statut.lower() if doc.id_statut else ""

                    if statut == "à envoyer":
                        try:
                            doc.id_statut = statut_envoye
                            doc.save()
                            logger.info(f"[DOSSIER {dossier.numero}] Statut de {doc.id_nature.nature} '{doc.titre}' mis à jour → Envoyé.")
                        except Exception as e:
                            logger.error(f"[DOSSIER {dossier.numero}] Envoi acte ({request.user}) : Erreur MAJ statut (À Envoyer → Envoyé) du document {doc.id} : {e}")
                    
                    # On considère que la délibération du CA a été publiée au RAA
                    if doc.id_nature.nature == "Déliberation CA" :
                        doc.publie_au_raa = True
                        doc.save()

        except Exception as e:
            logger.error(f"[DOSSIER {dossier_numero}] Envoi acte d'acceptation ({request.user}) - Document id={document_id} : Acte bien envoyé sur Démarche Numérique mais erreur lors de la mise à jour de la base locale : {e}")
            return redirect_error(request, "Acte bien envoyé sur Démarche Numérique mais erreur lors de la mise à jour de la base locale. Contactez le support.")



        
        





        # ==============================================
        #     Envoyer une copie de l'acte par Mail
        # ==============================================
        partager_par_mail = request.POST.get("partager_par_mail")  # "oui" ou "non"
        emails = request.POST.getlist("emails_copie[]")

        emails_nouveaux = request.POST.getlist("email_contact[]")
        emails_selectionnes_lower = { (e or "").strip().lower() for e in emails }
        noms = request.POST.getlist("nom_contact[]")
        prenoms = request.POST.getlist("prenom_contact[]")
        types = request.POST.getlist("type_contact[]")
        raisons = request.POST.getlist("raison_sociale[]")
        motivation_copie_mail = request.POST.get("motivation_copie_mail")

        if partager_par_mail == "oui" :

            # =======================================
            # 1) AJOUT DES NOUVEAUX CONTACTS EXTERNES
            # =======================================
            for i, email in enumerate(emails_nouveaux):
                email_clean = (email or "").strip()
                if not email_clean:
                    continue

                try:
                    validate_email(email_clean)
                except ValidationError:
                    logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Email invalide ignoré: {email}")
                    continue

                # chip supprimée => on ignore (pas de création, pas d'envoi)
                if email_clean.lower() not in emails_selectionnes_lower:
                    continue

                nom = (noms[i] if i < len(noms) else "").strip()
                prenom = (prenoms[i] if i < len(prenoms) else "").strip()
                raison = (raisons[i] if i < len(raisons) else "").strip()
                type_id = types[i] if i < len(types) else None

                type_obj = None
                if type_id:
                    type_obj = TypeContactExterne.objects.filter(id=type_id).first()
                if not type_obj:
                    type_obj, _ = TypeContactExterne.objects.get_or_create(type="Autre")

                contact, created = ContactExterne.objects.get_or_create(
                    email=email_clean,
                    id_type= type_obj,
                    defaults={
                        "nom": nom,
                        "prenom": prenom,
                        "raison_sociale": raison
                    }
                )
                if created:
                    logger.info(f"[DOSSIER {dossier_numero}] Envoi de l'acte par mail : Nouveau ContactExterne créé via formulaire : {contact}")

                # Ajouter ce mail aux destinataires
                # emails.append(email)


            # ================================
            # 2) NORMALISATION + DEDOUBLONNAGE
            # ================================
            emails_norm = []
            seen = set()

            for e in emails:
                e_norm = (e or "").strip()
                if not e_norm:
                    continue

                e_key = e_norm.lower()
                if e_key in seen:
                    continue

                try:
                    validate_email(e_norm)
                except ValidationError:
                    logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Email invalide ignoré: {e_norm}")
                    continue

                seen.add(e_key)
                emails_norm.append(e_norm)

            if not emails_norm:
                logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Aucun email valide sélectionné pour l’envoi de l'acte en copie. Liste des emails transmis : {emails}")
            
            else:
                # =========================
                # 3) ENVOI DE L'EMAIL
                # =========================
                sujet = f"{nature_document} – Dossier {dossier.numero}"
                context = {"body": motivation_copie_mail}
                template_name = "mail_en_copie"
                emails_txt = ", ".join(emails_norm)

                try :
                    dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

                except Exception as e:
                    logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Échec de l'envoi de l'acte en copie par mail - Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
                    return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

                # return None si Erreur 
                outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Envoi de l'acte", document=document)
                
                if outbox :
                    ok, err = envoi_mail(outbox.id)

                else :
                    logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Erreur lors de la création de l'EmailOutbox, Les users qui n'ont pas été notifiés par mail : {emails_txt}")
                    return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

                if ok:
                    logger.info(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Envoi en copie de l'acte par Mail ({outbox.id}) envoyée à {', '.join(outbox.to)} ")
                else:
                    logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Échec envoi en copie de l'acte par Mail ({outbox.id}) à {', '.join(outbox.to)} : {err}")
                    return redirect_error(request, f"L'envoi en copie de l'acte par Mail à {', '.join(outbox.to)} a échoué. Contactez le support.")
        


        """
        ###############################################
        ###############################################
        A TESTER
        ###############################################
        ###############################################
        """
        # =================================================================
        # --- RENDRE AVIS + DÉPOSER ACTE SUR DECLARATION MANIFESTATIONS ---
        # =================================================================
        try :

            if dossier.id_demarche.type.lower() == 'manifestations sportives':
                # Vérification si liaison existante
                liaison_dossDN = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()

                if liaison_dossDN :
                    dossier_dm_id = liaison_dossDN.id_dossier_manif.id

                    # Récupération du dossier DM
                    dossier_dm = DossierManifSportive.objects.filter(id=dossier_dm_id).first()
                    if not dossier_dm:
                        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte d'acceptation ({request.user}) : "
                                    f"Dossier Déclaration Manifestations (id={dossier_dm_id}) introuvable en base.")
                        return redirect_error(request, "Le dossier a bien été accepté sur Démarche Numérique, "
                                    "mais un problème est survenu lors du dépôt de l'avis favorable sur Déclaration Manifestations. Contactez le support.")
                    
                    num_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations

                    # Récupération de l'avis associé
                    avis_dm = AvisManifSportive.objects.filter(id_dossier_manif_sportive=dossier_dm).first()
                    if not avis_dm:
                        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte d'acceptation ({request.user}) : "
                                    f"Aucun Avis DM associé au Dossier DM {num_dossier_dm}.")

                        return redirect_error(request, "Le dossier a bien été accepté sur Démarche Numérique, "
                                    f"mais l'avis n'a pas pu être rendu sur Déclaration Manifestations pour le dossier n° {num_dossier_dm} (aucun avis associé en base). Contactez le support.")
            
                    avis_id = avis_dm.id_avis_manif_sportive

                    if avis_dm.date_reponse :
                        # ------------------
                        # AVIS DM DEJA RENDU
                        # ------------------
                        logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte d'acceptation ({request.user}) : "
                                    f"Avis (avis_id={avis_id}) déjà soumis sur DM.")
                        
                        messages.info(request, f"Aucun changement sur Déclaration Manifestations, un avis '{avis_dm.reponse_avis}' a déjà été rendu.")
                        
                        if not dossier_dm.archive :
                            dossier_dm.archive = True
                            dossier_dm.save(update_fields=["archive"])
                    
                    else :
                        # -------------------------------------
                        # RENDRE UN AVIS FAVORABLE SUR DM
                        # -------------------------------------
                        # Récupération du token API
                        token = get_access_token()
                        
                        if not motivation :
                            motivation = ""

                        # 0-None, 1-favorable, 2-défavorable, 3-non concerné  (lève exception si erreur)
                        response_avis = rendre_avis(token, avis_id, 1, motivation)
                        logger.info(f"[DOSSIER {dossier_numero}] Envoi acte d'acceptation ({request.user}) : "
                                    f"Avis 'favorable' soumis avec succès sur DM (avis_id={avis_id}). Réponse API : {response_avis}")

                        # ------------------
                        # MAJ Avis DM en BDD
                        # ------------------
                        avis_dm.date_reponse = timezone.now()
                        avis_dm.reponse_avis = "favorable"
                        avis_dm.prescriptions = motivation
                        avis_dm.save(update_fields=["date_reponse", "prescriptions", "reponse_avis"])
                        logger.info(f"Avis DM {avis_id} mis à jour en base.")

                        # ---------------------
                        # MAJ Dossier DM en BDD
                        # ---------------------
                        etape_cible = EtapeDossier.objects.get(etape="Accepté")
                        dossier_dm.archive = True
                        dossier_dm.id_etape = etape_cible
                        dossier_dm.save(update_fields=["archive", "id_etape"])
                        logger.info(f"Dossier DM {num_dossier_dm} mis à jour en base (etape : {etape_cible.etape}, archive : True)")


                    #######################################################
                    ###        DÉPOSER ACTE SUR DM ET SUR LE NAS        ###
                    #######################################################
                    erreur = reception_traiter_fichier_avis_dm(request, fichier=fichier, token=token, avis_id=avis_id, dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=dossier_dm.emplacement, sous_dossier_cible="Annexes/Declaration Manifestations/", nature_document="Arrêté directeur", description_document="Acte envoyé sur Déclaration Manifestations.", message_erreur_metier="L'acte' a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
                    if erreur:
                        return erreur


        except Exception as e:
            logger.error(f"[DOSSIER {dossier_numero}] Envoi acte d'acceptation ({request.user}) : "
                         f"Erreur lors de la soumission de l'avis 'favorable' sur Déclaration Manifestations : {e}")
            
            return redirect_error(request, "Le dossier a bien été accepté sur Démarche Numérique, "
                                    f"mais l'avis n'a pas pu être rendu sur Déclaration Manifestations. Contactez le support.")
            





    except Exception as e:
        logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier par {instructeur.email}: {str(e)}")
        return redirect_error(request, f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier sur DS par {instructeur.email}: {str(e)}")

    return redirect(request.META.get("HTTP_REFERER", "/"))





###############################################
###             ACTE DE REFUS               ###
###############################################
@login_required
@require_POST
def envoyer_l_acte_de_refus(request):

    dossier_id_ds = request.POST.get("dossierId")
    dossier_numero = request.POST.get("dossier_numero")
    motivation = request.POST.get("motivation", "Votre demande a été refusée.")
    document_id = request.POST.get("document_id_existant")  #ID du Doc à envoyer
    rapportCA_id = request.POST.get("rapportCA_id")
    nature_document = request.POST.get("nature_document")
    publieur_raa_id = request.POST.get("choix-publieur-raa") # id Instructeur

    root_folder = os.path.join(os.environ.get("NAS_ROOT"))

    # ============================
    #        VÉRIFICATIONS
    # ============================

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[ENVOYER ACTE] User={request.user} : ID DS manquant.")
        return redirect_error(request, "❌ Impossible d'envoyer l'acte : ID DS manquant. Contactez le support.")

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "ENVOYER ACTE", id_ds=dossier_id_ds)
    if err:
        return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Envoyer l'acte")
    if err:
        return err

    # --- Nature de l'acte ---
    if not nature_document:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Nature du document {document_id} (Statut : À envoyer) manquante dans le formulaire.")
        return redirect_error(request,"❌ La nature (Arrêté, Délibération...) de l’acte à envoyer est manquante. Contactez le support.")

    nature_obj = DocumentNature.objects.filter(nature__iexact=nature_document.strip()).first()
    if not nature_obj:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Document id={document_id} : Nature {nature_document} introuvable.")
        return redirect_error(request,f"❌ La nature de document '{nature_document}' est introuvable en base. Contactez le support.")
    
    # --- Publieur RAA ---
    if nature_obj.nature != "Déliberation CA" :
        if not publieur_raa_id :
            return redirect_error(request,"❌ Vous devez choisir la personne chargée de publier l’acte au RAA.")
        
        publieur_raa = Instructeur.objects.filter(id=publieur_raa_id).first()
        if not publieur_raa:
            logger.error(f"[DOSSIER {dossier_numero}] Échec envoi acte ({request.user}) : Publieur RAA introuvable (id={publieur_raa_id}).")
            return redirect_error(request, f"❌ Publieur.se RAA introuvable en base. Contactez le support.")

    # --- Document à envoyer ---
    if not document_id:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : ID du document signé (Statut : À envoyer) manquant dans le formulaire.")
        return redirect_error(request,"❌ L'acte signé à envoyer est introuvable depuis l'application (ID du document NULL). Contactez le support.")

    document = Document.objects.filter(id=document_id).select_related("id_format").first()
    if not document:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Document id={document_id} (Statut : À envoyer) introuvable.")
        return redirect_error(request,"❌ Le document signé à envoyer est introuvable en base. Contactez le support.")
    
    # --- Format de l'acte ---
    if not document.id_format or not document.id_format.format:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Format du Document id={document.id} (Statut : À envoyer) introuvable.")
        return redirect_error(request,"❌ Le format du document signé est introuvable en base. Contactez le support.")

    # --- Statut "Envoyé"
    statut_envoye = DocumentStatut.objects.filter(statut__iexact="envoyé").first()
    if not statut_envoye:
        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) : Statut 'Envoyé' introuvable.")
        return redirect_error(request, "❌ Statut 'Envoyé' introuvable en base. Contactez le support.")
        

    try:
        # Construire l’emplacement de stockage
        dossier_path = dossier.emplacement
        emplacement_relatif_dossier_acte = os.path.join(dossier_path, 'Actes/')
        emplacement_absolu_dossier_acte = os.path.join(os.environ.get("NAS_ROOT"), emplacement_relatif_dossier_acte)

        emplacement_doc = os.path.join(emplacement_relatif_dossier_acte, f"{document.titre}")
        full_path_doc = os.path.join(os.environ.get("NAS_ROOT"), emplacement_doc)


        # Définir le Content Type à partir du Format du Doc
        format_str = document.id_format.format.lower()
        if format_str in ['jpg', 'jpeg']:
            content_type = 'image/jpeg'
        elif format_str == 'png':
            content_type = 'image/png'
        elif format_str == 'pdf':
            content_type = 'application/pdf'
        else:
            content_type = 'application/octet-stream'

        try:
            with smbclient.open_file(full_path_doc, mode="rb") as f:
                fichier = SimpleUploadedFile(name=document.titre, content=f.read(), content_type=content_type)


        except Exception as e:
            logger.error(f"[DOSSIER {dossier_numero}] Échec envoi acte ({request.user}) : Impossible de lire le fichier {full_path_doc} : {e}")
            return redirect_error(request,"❌ Impossible de lire le fichier de l’acte sur le serveur. Contactez le support.")
        

        # --- Vérification Format de l'acte ---
        nom, extension = os.path.splitext(fichier.name)
        ext = extension.lstrip('.').lower()
        format_obj = DocumentFormat.objects.filter(format__iexact=ext).first()
        if not format_obj:
            logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Document id={document_id} : Format {ext} introuvable.")
            return redirect_error(request,f"❌ Le format de document '{ext}' est introuvable en base. Contactez le support.")
    
        

        # ============================================
        #      REFUS DU DOSSIER SUR DS
        # ============================================
        if dossier.present_sur_ds :

            result = refuser_dossier_ds(dossier_id_ds, instructeur, motivation, fichier)
        
            if not result["success"]:
                logger.error(f"[DOSSIER {dossier_numero}] Erreur lors du refus du dossier sur DS par {instructeur} : {result['message']}")
                return redirect_error(request, f"Erreur lors du refus du dossier sur Démarche Numérique. Contactez le support.")


        try :
            with transaction.atomic():

                # -------------------------------------------------------
                # Ajout de la personne chargée de publier l'acte au RAA
                # ------------------------------------------------------
                if nature_obj.nature != "Déliberation CA" :
                    err = set_dossier_role(DossierPublicationRAA, dossier, publieur_raa, "Publieur RAA", request)
                    if err:
                        return err
                

                # ============================================
                #     MISE À JOUR ÉTAPE / ÉTAT / ACTION
                # ============================================

                # --- Mise à jour Étape ---
                if nature_obj.nature == "Déliberation CA" :
                    # On classe le dossier comme refusé
                    err = safe_update_etape(dossier, "Refusé", request, break_si_erreur=True)
                    if err:
                        return err
                    
                else :
                    safe_update_etape(dossier, "À publier au RAA", request, break_si_erreur=False) # On continue si Erreur

                # --- Mise à jour État ---
                safe_update_etat(dossier, "refuse", request, break_si_erreur=False) # On continue si Erreur

                # --- Enregistrer Action ---
                safe_enregistrer_action(dossier, instructeur, "Acte envoyé", request)
                if nature_obj.nature == "Déliberation CA" :
                    safe_enregistrer_action(dossier, instructeur, "Classé comme refusé", request)



                # ==============================================
                #     Mise à jour Doc "À envoyer" --> "Envoyé"
                # ==============================================
                documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")
                for lien in documents_du_dossier:
                    doc = lien.id_document
                    statut = doc.id_statut.statut.lower() if doc.id_statut else ""

                    if statut == "à envoyer":
                        try:
                            doc.id_statut = statut_envoye
                            doc.save()
                            logger.info(f"[DOSSIER {dossier.numero}] Statut de {doc.id_nature.nature} '{doc.titre}' mis à jour → Envoyé.")
                        except Exception as e:
                            logger.error(f"[DOSSIER {dossier.numero}] Envoi acte ({request.user}) : Erreur MAJ statut (À Envoyer → Envoyé) du document {doc.id} : {e}")
                    
                    # On considère que la délibération du CA a été publiée au RAA
                    if doc.id_nature.nature == "Déliberation CA" :
                        doc.publie_au_raa = True
                        doc.save()
        except Exception as e:
            logger.error(f"[DOSSIER {dossier_numero}] Envoi acte de refus ({request.user}) - Document id={document_id} : Acte bien envoyé sur Démarche Numérique mais erreur lors de la mise à jour de la base locale : {e}")
            return redirect_error(request, "Acte de refus bien envoyé sur Démarche Numérique mais erreur lors de la mise à jour de la base locale. Contactez le support.")


            




        # ==============================================
        #     Envoyer une copie de l'acte par Mail
        # ==============================================
        partager_par_mail = request.POST.get("partager_par_mail")  # "oui" ou "non"
        emails = request.POST.getlist("emails_copie[]")

        emails_nouveaux = request.POST.getlist("email_contact[]")
        emails_selectionnes_lower = { (e or "").strip().lower() for e in emails }
        noms = request.POST.getlist("nom_contact[]")
        prenoms = request.POST.getlist("prenom_contact[]")
        types = request.POST.getlist("type_contact[]")
        raisons = request.POST.getlist("raison_sociale[]")
        motivation_copie_mail = request.POST.get("motivation_copie_mail")

        if partager_par_mail == "oui" :

            # =======================================
            # 1) AJOUT DES NOUVEAUX CONTACTS EXTERNES
            # =======================================
            for i, email in enumerate(emails_nouveaux):
                email_clean = (email or "").strip()
                if not email_clean:
                    continue

                try:
                    validate_email(email_clean)
                except ValidationError:
                    logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Email invalide ignoré: {email}")
                    continue

                # chip supprimée => on ignore (pas de création, pas d'envoi)
                if email_clean.lower() not in emails_selectionnes_lower:
                    continue

                nom = (noms[i] if i < len(noms) else "").strip()
                prenom = (prenoms[i] if i < len(prenoms) else "").strip()
                raison = (raisons[i] if i < len(raisons) else "").strip()
                type_id = types[i] if i < len(types) else None

                type_obj = None
                if type_id:
                    type_obj = TypeContactExterne.objects.filter(id=type_id).first()
                if not type_obj:
                    type_obj, _ = TypeContactExterne.objects.get_or_create(type="Autre")

                contact, created = ContactExterne.objects.get_or_create(
                    email=email_clean,
                    id_type= type_obj,
                    defaults={
                        "nom": nom,
                        "prenom": prenom,
                        "raison_sociale": raison
                    }
                )
                if created:
                    logger.info(f"[DOSSIER {dossier_numero}] Envoi de l'acte par mail : Nouveau ContactExterne créé via formulaire : {contact}")

                # Ajouter ce mail aux destinataires
                # emails.append(email)


            # ================================
            # 2) NORMALISATION + DEDOUBLONNAGE
            # ================================
            emails_norm = []
            seen = set()

            for e in emails:
                e_norm = (e or "").strip()
                if not e_norm:
                    continue

                e_key = e_norm.lower()
                if e_key in seen:
                    continue

                try:
                    validate_email(e_norm)
                except ValidationError:
                    logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Email invalide ignoré: {e_norm}")
                    continue

                seen.add(e_key)
                emails_norm.append(e_norm)

            if not emails_norm:
                logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Aucun email valide sélectionné pour l’envoi de l'acte en copie. Liste des emails transmis : {emails}")
            
            else:
                # =========================
                # 3) ENVOI DE L'EMAIL
                # =========================
                sujet = f"{nature_document} – Dossier {dossier.numero}"
                context = {"body": motivation_copie_mail}
                template_name = "mail_en_copie"
                emails_txt = ", ".join(emails_norm)

                try :
                    dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

                except Exception as e:
                    logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Échec de l'envoi de l'acte en copie par mail - Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
                    return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

                # return None si Erreur 
                outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Envoi de l'acte", document=document)
                
                if outbox :
                    ok, err = envoi_mail(outbox.id)

                else :
                    logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Erreur lors de la création de l'EmailOutbox, Les users qui n'ont pas été notifiés par mail : {emails_txt}")
                    return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

                if ok:
                    logger.info(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Envoi en copie de l'acte par Mail ({outbox.id}) envoyée à {', '.join(outbox.to)} ")
                else:
                    logger.error(f"[DOSSIER {dossier_numero}] Envoi acte ({request.user}) - Échec envoi en copie de l'acte par Mail ({outbox.id}) à {', '.join(outbox.to)} : {err}")
                    return redirect_error(request, f"L'envoi en copie de l'acte par Mail à {', '.join(outbox.to)} a échoué. Contactez le support.")
        



        

        """
        ###############################################
        ###############################################
        A TESTER
        ###############################################
        ###############################################
        """
        # =================================================================
        # --- RENDRE AVIS + DÉPOSER ACTE SUR DECLARATION MANIFESTATIONS ---
        # =================================================================
        try :

            if dossier.id_demarche.type.lower() == 'manifestations sportives':
                # Vérification si liaison existante
                liaison_dossDN = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()

                if liaison_dossDN :
                    dossier_dm_id = liaison_dossDN.id_dossier_manif.id

                    # Récupération du dossier DM
                    dossier_dm = DossierManifSportive.objects.filter(id=dossier_dm_id).first()
                    if not dossier_dm:
                        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte de refus ({request.user}) : "
                                    f"Dossier Déclaration Manifestations (id={dossier_dm_id}) introuvable en base.")
                        return redirect_error(request, "Le dossier a bien été refusé sur Démarche Numérique, "
                                    "mais un problème est survenu lors du dépôt de l'avis défavorable sur Déclaration Manifestations. Contactez le support.")
                    
                    num_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations

                    # Récupération de l'avis associé
                    avis_dm = AvisManifSportive.objects.filter(id_dossier_manif_sportive=dossier_dm).first()
                    if not avis_dm:
                        logger.error(f"[DOSSIER {dossier_numero}] Envoi acte de refus ({request.user}) : "
                                    f"Aucun Avis DM associé au Dossier DM {num_dossier_dm}.")

                        return redirect_error(request, "Le dossier a bien été refusé sur Démarche Numérique, "
                                    f"mais l'avis n'a pas pu être rendu sur Déclaration Manifestations pour le dossier n° {num_dossier_dm} (aucun avis associé en base). Contactez le support.")
            
                    avis_id = avis_dm.id_avis_manif_sportive

                    if avis_dm.date_reponse :
                        # ------------------
                        # AVIS DM DEJA RENDU
                        # ------------------
                        logger.warning(f"[DOSSIER {dossier_numero}] Envoi acte de refus ({request.user}) : "
                                    f"Avis (avis_id={avis_id}) déjà soumis sur DM.")
                        
                        messages.info(request, f"Aucun changement sur Déclaration Manifestations, un avis '{avis_dm.reponse_avis}' a déjà été rendu.")
                        
                        if not dossier_dm.archive :
                            dossier_dm.archive = True
                            dossier_dm.save(update_fields=["archive"])
                    
                    else :
                        # -------------------------------------
                        # RENDRE UN AVIS DÉFAVORABLE SUR DM
                        # -------------------------------------
                        # Récupération du token API
                        token = get_access_token()
                        
                        if not motivation :
                            motivation = ""

                        # 0-None, 1-favorable, 2-défavorable, 3-non concerné  (lève exception si erreur)
                        response_avis = rendre_avis(token, avis_id, 2, motivation)
                        logger.info(f"[DOSSIER {dossier_numero}] Envoi acte de refus ({request.user}) : "
                                    f"Avis 'défavorable' soumis avec succès sur DM (avis_id={avis_id}). Réponse API : {response_avis}")

                        # ------------------
                        # MAJ Avis DM en BDD
                        # ------------------
                        avis_dm.date_reponse = timezone.now()
                        avis_dm.reponse_avis = "défavorable"
                        avis_dm.prescriptions = motivation
                        avis_dm.save(update_fields=["date_reponse", "prescriptions", "reponse_avis"])
                        logger.info(f"Avis DM {avis_id} mis à jour en base.")

                        # ---------------------
                        # MAJ Dossier DM en BDD
                        # ---------------------
                        etape_cible = EtapeDossier.objects.get(etape="Refusé")
                        dossier_dm.archive = True
                        dossier_dm.id_etape = etape_cible
                        dossier_dm.save(update_fields=["archive", "id_etape"])
                        logger.info(f"Dossier DM {num_dossier_dm} mis à jour en base (etape : {etape_cible.etape}, archive : True)")


                        #######################################################
                        ###        DÉPOSER ACTE SUR DM ET SUR LE NAS        ###
                        #######################################################
                        erreur = reception_traiter_fichier_avis_dm(request, fichier=fichier, token=token, avis_id=avis_id, dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=dossier_dm.emplacement, sous_dossier_cible="Annexes/Declaration Manifestations/", nature_document="Arrêté directeur", description_document="Acte envoyé sur Déclaration Manifestations.", message_erreur_metier="L'acte' a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
                        if erreur:
                            return erreur
                


        except Exception as e:
            logger.error(f"[DOSSIER {dossier_numero}] Envoi acte de refus ({request.user}) : "
                         f"Erreur lors de la soumission de l'avis 'défavorable' sur Déclaration Manifestations : {e}")
            
            return redirect_error(request, "Le dossier a bien été refusé sur Démarche Numérique, "
                                    f"mais l'avis n'a pas pu être rendu sur Déclaration Manifestations. Contactez le support.")




    except Exception as e:
        logger.error(f"[DOSSIER {dossier_numero}] Erreur lors du refus du dossier par {instructeur.email}: {str(e)}")
        return redirect_error(request, f"[DOSSIER {dossier_numero}] Erreur lors du refus du dossier sur DS par {instructeur.email}: {str(e)}")

    return redirect(request.META.get("HTTP_REFERER", "/"))

