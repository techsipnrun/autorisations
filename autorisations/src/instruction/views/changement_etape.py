from datetime import datetime
import logging
import os
from django.db import IntegrityError
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
import smbclient
from autorisations.models.models_instruction import Dossier, EtapeDossier, EtatDossier, DossierAction, Action
from autorisations.models.models_utilisateurs import ContactExterne, DossierEnvoiActe, DossierIntermediaireSignature, DossierPublicationRAA, DossierRelecteurQualite, DossierSignataire, EmailOutbox, GroupeinstructeurInstructeur, Instructeur, DossierInstructeur, DossierValideur, TypeContactExterne
from DS.call_DS import accepter_dossier_ds, get_msg_DS, passer_en_instruction_ds,classer_sans_suite_ds, refuser_dossier_ds, repasser_en_instruction_ds
from autorisations import settings
from autorisations.models.models_avis import Avis, DossierAvis
from autorisations.utils.nas_fonctions import creer_dossier_sur_nas, ecrire_file_sur_nas
from instruction.utils.dossier_utils import get_dossier_or_redirect, redirect_error, safe_enregistrer_action, safe_update_etape, safe_update_etat, set_dossier_role
from instruction.utils.files_utils import save_if_not_exists
from instruction.utils.utilisateurs_utils import get_instructeur_or_redirect
from notifications.service import compute_dedupe_key, envoi_mail
from instruction.services.messagerie_service import envoyer_message_ds, prepare_temp_file, enregistrer_message_bdd
from instruction.utils_instru import changer_etape_si_differente, changer_etat_si_different, enregistrer_action
from django.views.decorators.http import require_POST
from django.utils import timezone
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DocumentStatut, DossierDocument
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from pathlib import Path
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from psycopg2.errors import UniqueViolation


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
        return redirect_error(request, f"L'ID du dossier Démarches Simplifiées est introuvable. Contactez le support.")
    

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
            return redirect_error(request, f"Échec de la demande de compléments sur Démarches Simplifiées. Contactez le support.")
        

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
    if not motivation:
        logger.warning(f"[DOSSIER {dossier.numero}] Classement comme 'Non soumis à autorisation' par {request.user} : Justification manquante.")
        return redirect_error(request, f"Une justification est requise pour classer le dossier comme 'Non soumis à autorisation'.")
    

    # --- Vérification Instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Classer comme 'Non soumis à autorisation'")
    if err:
        return err



    # ==========================================
    # --- Actions côté Démarches Simplifiées ---
    # ==========================================
    if dossier.present_sur_ds :

        # --- PASSAGE EN INSTRUCTION SUR DS ---
        # Si Etat Dossier en construction + Etape Dossier en pré-instruction ou à affecter
        if dossier.id_etat_dossier.nom == "en_construction" and dossier.id_etape_dossier.etape in ["En pré-instruction", "À affecter"]:
            result = passer_en_instruction_ds(dossier.id_ds, instructeur)
            if not result.get("success"):
                logger.error(f"[DOSSIER {dossier.numero}] Erreur lors du passage en instruction DS par {request.user} : {result.get('message')}")
                return redirect_error(request, f"Erreur lors du passage en instruction sur Démarches Simplifiées. Contactez le support.")


        # --- CLASSEMENT SANS SUITE SUR DS ---
        result = classer_sans_suite_ds(dossier.id_ds, instructeur, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Échec du classement sans suite DS par {request.user} : {result.get('message')}")
            return redirect_error(request, f"Erreur lors du classement sans suite sur Démarches Simplifiées. Contactez le support.")


    # ========================
    # --- Actions côté BDD ---
    # ========================

    # --- Mise à jour Étape ---
    safe_update_etape(dossier, "Non soumis à autorisation", request, break_si_erreur=False) # On continue si Erreur
    
    # --- Mise à jour État ---
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


    return redirect(reverse('instruction_dossier', kwargs={'num_dossier': dossier.numero}))



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
    if not motivation:
        logger.warning(f"[DOSSIER {dossier.numero}] User {request.user} a tenté de refuser le dossier sans justification.")
        return redirect_error(request, f"Une justification est requise pour refuser le dossier.")
    

    # ==========================================
    # --- Actions côté Démarches Simplifiées ---
    # ==========================================
    if dossier.present_sur_ds :

        # Si l'étape est 'En pré-instruction' et l'état 'en_construction' --> passer l'état à en_instruction
        if dossier.id_etat_dossier.nom == 'en_construction' and dossier.id_etape_dossier.etape == 'En pré-instruction' :

            # Passage en instruction sur DS
            result = passer_en_instruction_ds(dossier.id_ds, instructeur)
            if not result.get("success"):
                logger.error(f"[DOSSIER {dossier.numero}] Erreur lors du passage en instruction DS par {request.user} : {result.get('message')}")
                return redirect_error(request, f"Erreur lors du passage en instruction sur Démarches Simplifiées. Contactez le support.")

        # Refus du dossier sur DS
        result = refuser_dossier_ds(dossier.id_ds, instructeur, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Échec du refus DS : {result.get('message')}")
            return redirect_error(request, f"Erreur lors du refus sur Démarches Simplifiées. Contactez le support.")


    # ========================
    # --- Actions côté BDD ---
    # ========================

    # --- Mise à jour Étape ---
    safe_update_etape(dossier, "Refusé", request, break_si_erreur=False) # On continue si Erreur

    # --- Mise à jour État ---
    safe_update_etat(dossier, "refuse", request, break_si_erreur=False) # On continue si Erreur

    # Maj Date Fin Instruction
    try:
        dossier.date_fin_instruction = timezone.now()
        dossier.save()
    except Exception as e:
        logger.warning(f"[DOSSIER {dossier.numero}] Refus par {request.user} - Erreur MAJ date_fin_instruction à {timezone.now()} : {e}")
        # on continue

    # --- Enregistrer Action ---
    safe_enregistrer_action(dossier, instructeur, action="Demande de compléments", request=request)
    

    return redirect(reverse('instruction_dossier', kwargs={'num_dossier': dossier.numero}))




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
                return redirect_error(request, f"Erreur lors du passage en instruction sur Démarches Simplifiées. Contactez le support.")
        

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
    fichier = request.FILES.get("piece_jointe")
    ids_selectionnes = request.POST.getlist("avis_selectionnes")
    
    # ========================
    # ---   VERIFICATION   ---
    # ========================
    if not dossier_id_ds :
        return redirect_error(request, "❌ L'id du dossier est manquant. Contactez le support.")
    
    if not nature :
        return redirect_error(request, "❌ La nature du projet d'acte est manquante. Contactez le support.")

    else :
        # --- Récupération nature ---
        nature_obj = DocumentNature.objects.filter(nature=nature).first()
        if not nature_obj:
            logger.error(f"[DOSSIER {dossier.numero}] User {request.user} : Aucune nature Document trouvée pour '{nature}'")
            return redirect_error(request, "❌ Le nature de document '{{nature}}' n'a pas été trouvée en base. Contactez le support.")
    
    if not fichier :
        return redirect_error(request, "❌ Le projet d'acte n'a pas été joint. Contactez le support.")
    
    else :
        # --- Récupération format ---
        extension = os.path.splitext(fichier.name)[1].lower().lstrip('.')
        format_obj = DocumentFormat.objects.filter(format=extension).first()
        if not format_obj:
            logger.error(f"[DOSSIER {dossier.numero}] User {request.user} : Aucun format Document trouvé pour '{extension}'")
            return redirect_error(request, "❌ Le format de document '{{extension}}' n'a pas été trouvé en base. Contactez le support.")
        
        # --- Extension ---
        extension = Path(fichier.name).suffix.lower()
        if extension not in {".doc", ".docx", ".odt"} :
            return redirect_error(request, f"❌ Le fichier joint doit etre .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}.")

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
    

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "VALIDATION AVANT DEMANDE AVIS", id_ds=dossier_id_ds)
    if err: 
        return err
    

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
    filepath = os.path.join(full_path, fichier.name)

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
                            emplacement=dossier_path, titre=fichier.name,
                            defaults={
                                "id_format": format_obj,
                                "id_nature": nature_obj,
                                "id_statut": statut_obj,
                                "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                            })
        if created:
            DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
            logger.info(f"[DOSSIER {dossier.numero}] Document {nature_obj.nature} {fichier.name} créé en base par {request.user}.")
        else:
            doc.id_statut = statut_obj
            doc.save()
            logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_obj.nature} {fichier.name} déjà existant en base – aucune création")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors du changement d'étape 'Faire valider une demande d'avis' par {request.user} - Erreur lors de la création ou de la MAJ du Document {fichier.name} en base : {e}")
    

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
    fichier = request.FILES.get("piece_jointe")
    fichier_rapport_CA = request.FILES.get("piece_jointe_rapport_ca")

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

    if not fichier:
        return redirect_error(request, "❌ Le projet d'acte n'a pas été joint.")

    # Vérification que l'extension du file est .doc, .docx, .pdf, .odt
    extension = Path(fichier.name).suffix.lower()
    if extension not in {".doc", ".docx", ".odt"} :
        return redirect_error(request, f"❌ Le projet d'acte joint doit etre .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
    

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

    # --- Récupération dossier ---
    dossier, err = get_dossier_or_redirect(request, "VALIDATION PROJET ACTE", id_ds=dossier_id_ds)
    if err: return err

    # --- Récupération instructeur ---
    instructeur, err = get_instructeur_or_redirect(request, numero_dossier=dossier.numero, action="Validation projet d'acte")
    if err: return err


    # Vérification que le file sélectionné est bien dans le sous dossier Work
    dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")
    full_path = os.path.join(os.environ.get("NAS_ROOT"), dossier_path)
    creer_dossier_sur_nas(full_path)

    filepath = os.path.join(full_path, fichier.name)
    if not smbclient.path.exists(filepath):
        return redirect_error(request, "❌ Le projet d’acte doit être dans le sous-dossier 'Work' du dossier concerné.")


    ############################## 
    # Sauvegarde du Projet d'acte
    ##############################
    try:
        # Écriture du fichier sur le NAS
        if not ecrire_file_sur_nas(fichier, filepath): 
            raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {filepath}")
        
        # Enregistrer en BDD
        doc, created = Document.objects.get_or_create(
                        emplacement=dossier_path, titre=fichier.name, id_format=format_obj,
                        defaults={
                            "id_format": format_obj,
                            "id_nature": nature_obj,
                            "id_statut": statut_obj,
                            "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                        }
                    )

        if created:
            DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
            logger.info(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {fichier.name} créé dans le dossier Work")
            
        else:
            doc.id_statut = statut_obj
            doc.id_nature = nature_obj
            doc.save()
            logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_obj.nature} {fichier.name} déjà existant en base – aucune création")
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] {nature_obj.nature} : Erreur lors du changement d'étape 'Faire valider le projet d'acte' par {request.user} - Erreur lors de la création du Document {fichier.name} en base : {e}")



    ########################
    # Projet rapport CA
    ########################

    if fichier_rapport_CA :

        extension_rapport = Path(fichier_rapport_CA.name).suffix.lower()
        if extension_rapport not in {".doc", ".docx", ".odt"} :
            return redirect_error(request, f"❌ Le projet de rapport du CA joint doit etre .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension_rapport}")
        
        filepath_rapport = os.path.join(full_path, fichier_rapport_CA.name)
        # Vérification que le projet Rapport CA est bien dans le sous dossier Work
        if not smbclient.path.exists(filepath_rapport):
            return redirect_error(request, "❌ Le projet de rapport du CA doit être placé dans le sous-dossier 'Work' du dossier concerné.")

        try:
            # Écriture du fichier sur le NAS
            if not ecrire_file_sur_nas(fichier, filepath_rapport): 
                raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {filepath_rapport}")

            nature_obj = DocumentNature.objects.filter(nature="Projet Rapport CA").first()
            if not nature_obj:
                return redirect_error(request, "❌ Nature 'Projet Rapport CA' introuvable en base. Contactez le support.")

            format_obj = DocumentFormat.objects.filter(format=extension_rapport.lstrip('.')).first()
            if not format_obj:
                return redirect_error(request, f"❌ Format '{extension_rapport}' non trouvé en base. Contactez le support.")


            # Enregistrer en BDD
            doc, created = Document.objects.get_or_create(
                                emplacement=dossier_path, titre=fichier_rapport_CA.name,
                                defaults={
                                    "id_format": format_obj,
                                    "id_nature": nature_obj,
                                    "id_statut": statut_obj,  # Récupéré précédemment
                                    "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                                }
                            )
            if created:
                DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
                logger.info(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {fichier_rapport_CA.name} créé dans le dossier Work")
            else:
                doc.id_statut = statut_obj
                doc.save()
                logger.warning(f"[DOSSIER {dossier.numero}] User {request.user}, Document {nature_obj.nature} {fichier.name} déjà existant en base – aucune création")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] {nature_obj.nature} : Erreur lors du changement d'étape 'Faire valider le projet d'acte' par {request.user} - Erreur lors de la création du Document {fichier.name} en base : {e}")


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
        return redirect_error(request, "❌ Impossible de repasser en instruction : ID Démarches Simplifiées du dossier manquant. Contactez le support.")

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
                    return redirect_error(request, "❌ Le dossier n'est pas repassé en instruction sur Démarches Simplifiées car il est déjà en instruction. Contactez le support.")

                elif result.get('message') == "Le dossier est déjà en construction" :
                    logger.warning(f"[DOSSIER {dossier.numero}] Le dossier n'est pas repassé en instruction sur DS car il est déjà en construction : {result.get('message')}")
                    return redirect_error(request, "❌ Le dossier n'est pas repassé en instruction sur Démarches Simplifiées car il est déjà en construction. Contactez le support.")
 
                else:
                    logger.error(f"[DOSSIER {dossier.numero}] Échec du repassage en instruction du dossier par {request.user} : {result.get('message')}")
                    return redirect_error(request, "❌ Le dossier n'est pas repassé en instruction sur Démarches Simplifiées. Contactez le support.")


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
            logger.info(f"[DOSSIER {dossier.numero}] Repassage en Instruction par {request.user} : Statut du document '{doc.titre}' remis à NULL.")

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
        return redirect_error(request, "❌ Échec de l'envoi pour relecture : ID Démarches Simplifiées du dossier manquant. Contactez le support.")

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
        return redirect_error(request, "❌ Échec de l'envoi pour relecture : ID Démarches Simplifiées du dossier manquant. Contactez le support.")

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
        return redirect_error(request, "❌ Échec de l'envoi pour validation : ID Démarches Simplifiées du dossier manquant. Contactez le support.")

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
        return redirect_error(request, "❌ Échec : ID Démarches Simplifiées du dossier manquant. Contactez le support.")

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



@require_POST
@login_required
def acte_pret_a_etre_envoye(request):

    dossier_id_ds = request.POST.get("dossierId")
    fichier = request.FILES.get("piece_jointe")
    fichier_rapportCA = request.FILES.get("pj_rapport_CA")
    signataire_id = request.POST.get("choix-signataire") # id Instructeur
    envoyeur_id = request.POST.get("choix-envoi-acte-peti") # id Instructeur
    nature_document = request.POST.get("nature_document")

    # =====================
    #     VÉRIFICATIONS
    # =====================

    # --- Vérification dossierId ---
    if not dossier_id_ds:
        logger.error(f"[ACTE PRÊT À ENVOI] User={request.user} : ID DS manquant.")
        return redirect_error(request, "❌ ID Démarches Simplifiées manquant. Contactez le support.")

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
    
    # --- Vérification Nature Rapport CA ---
    if fichier_rapportCA :
        doc_nature_rapportCA = DocumentNature.objects.filter(nature__iexact = "Rapport CA").first()
        if not doc_nature_rapportCA:
            logger.error(f"[DOSSIER {dossier.numero}] Echec du changement d'étape à 'Acte à envoyer' ({request.user}) : Nature {doc_nature_rapportCA} introuvable en base.")
            return redirect_error(request, f"❌ Nature 'Rapport CA' introuvable en base. Contactez le support.")
    
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
    
    # Vérification Acte
    if not fichier:
        return redirect_error(request, "❌ Aucun fichier Acte fourni.")
    
    extension = Path(fichier.name).suffix.lower()
    if extension != ".pdf" :
        return redirect_error(request, f"❌ L'acte joint doit etre au format PDF --> Type de fichier non autorisé : {extension}")
    
    # Vérification dossier Work
    dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")
    full_path = os.path.join(os.environ.get("NAS_ROOT"), dossier_path)
    creer_dossier_sur_nas(full_path)


    # =========================
    #   Sauvegarde Acte signé
    # =========================
    filepath = os.path.join(full_path, fichier.name)
    err = save_if_not_exists(request, dossier, fichier, filepath, fail_if_exists=True)
    if err:
        return err


    # ===================================
    #   Sauvegarde Rapport CA (optionnel)
    # ===================================
    filepath_rapportCA = None

    if fichier_rapportCA :
        extensionCA = Path(fichier_rapportCA.name).suffix.lower()
        if extensionCA != ".pdf" :
            return redirect_error(request, f"❌ Le rapport du CA joint doit etre .pdf --> Type de fichier non autorisé : {extensionCA}")
        
        filepath_rapportCA = os.path.join(full_path, fichier_rapportCA.name)
        
        err = save_if_not_exists(request, dossier, fichier_rapportCA, filepath_rapportCA, fail_if_exists=True)
        if err:
            return err


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
                logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé : statut du document '{doc.titre}' remis à NULL.")
            
            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Changement d'étape à 'Acte à envoyer' par {request.user} : Erreur MAJ statut document {doc.id} : {e}")


    # ----------------------------------
    # Création du doc (Acte) "À envoyer" 
    # ----------------------------------
    doc, created = Document.objects.get_or_create(
                            emplacement=dossier_path, titre=fichier.name,
                            defaults={
                                "id_format": format_pdf,
                                "id_nature": doc_nature,
                                "id_statut": statut_a_envoyer,
                                "description": f"{doc_nature.nature} du dossier {dossier.numero}",
                            }
                        )
    
    if created:
        DossierDocument.objects.create(id_dossier=dossier, id_document=doc)
        logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé : {fichier.name} ({doc_nature.nature} 'À envoyer') créé et lié au dossier")
    else:
        try :
            doc.id_statut = statut_a_envoyer
            doc.save()
            logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé : {fichier.name} ({doc_nature.nature}, {doc.id_statut.statut}) déjà existant – statut changé à 'À envoyer'")
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé ({request.user}) : Erreur lors de la MAJ au statut 'à envoyer' du document {doc.id} : {e}")


    # ---------------------------------
    # Création Document Rapport CA
    # ---------------------------------
    if fichier_rapportCA :

        doc_ca, created = Document.objects.get_or_create(
                                emplacement=dossier_path, titre=fichier_rapportCA.name,
                                defaults={
                                    "id_format": format_pdf,
                                    "id_nature": doc_nature_rapportCA,
                                    "description": f"{doc_nature_rapportCA.nature} du dossier {dossier.numero}",
                                }
                            )
        
        if created:
            DossierDocument.objects.create(id_dossier=dossier, id_document=doc_ca)
            logger.info(f"[DOSSIER {dossier.numero}] Acte prêt à être envoyé - Transmission du Rapport CA : {fichier.name} (Document {doc_ca.numero}) créé et lié au dossier")
        else:
            try :
                doc_ca.id_statut = statut_a_envoyer
                doc_ca.save()
                logger.warning(f"[DOSSIER {dossier.numero}] Transmission du Rapport CA par {request.user} : {fichier.name} (Document {doc_ca.numero}, Statut {doc_ca.id_statut.statut}) déjà existant – statut changé à 'À envoyer'")

            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Passage Étape 'Acte prêt à être envoyé' par {request.user} - Transmission du Rapport CA : Erreur lors de la MAJ au statut 'à envoyer' du document {doc_ca.id} existant : {e}")


    # Ajout du signataire au dossier
    err = set_dossier_role(DossierSignataire, dossier, signataire, "Signataire", request)
    if err:
        return err
    

    # Ajout de l'envoyeur d'acte au dossier
    err = set_dossier_role(DossierEnvoiActe, dossier, envoyeur, "Envoyeur d'acte", request)
    if err:
        return err
    
    # DossierEnvoiActe.objects.filter(id_dossier=dossier).delete()
    # DossierEnvoiActe.objects.create(id_dossier=dossier, id_instructeur=envoyeur)
    # logger.info(f"[DOSSIER {dossier.numero}] Envoyeur d'acte {envoyeur} ajouté au dossier.")


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




"""  
####################################################
DERNIERE FONCTION A CLEAN
####################################################
"""

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

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    
    if not dossier_id_ds or not instructeur :
            messages.error(request, f"❌ Données manquantes ou invalides : ID du dossier DS = {dossier_id_ds}, Instructeur.rice = {instructeur}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    

    publieur_raa = get_object_or_404(Instructeur, id=publieur_raa_id)
    if not publieur_raa:
        logger.error(f"Instructeur (ID {publieur_raa_id}) introuvable en base.")
        messages.error(request, f"❌ Instructeur (ID {publieur_raa_id}) introuvable en base.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    try:
        dossier = Dossier.objects.filter(id_ds=dossier_id_ds).first()
        # Construire l’emplacement de stockage
        dossier_path = f"{dossier.emplacement}"

        if not document_id :
            messages.error(request, f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier par {instructeur.email} : L'acte signé (Statut : À envoyer) est introuvable depuis l'application. Contactez l'administrateur.rice")
            logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier par {instructeur.email} : L'acte signé (Statut : À envoyer) est introuvable depuis l'application.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
                      
        document = Document.objects.get(id=document_id)
        emplacement_doc = os.path.join(dossier_path, 'Actes/', f"{document.titre}")
        full_path = os.path.join(os.environ.get("NAS_ROOT"), emplacement_doc)

        # Chercher si un document existe déjà avec même emplacement + titre
        doc_existant = Document.objects.filter(emplacement=os.path.join(dossier_path, 'Actes/'), titre=document.titre).first()

        chemin = os.path.join(os.getenv("NAS_ROOT"), document.emplacement, document.titre)
        format_str = document.id_format.format.lower()

        if format_str in ['jpg', 'jpeg']:
            content_type = 'image/jpeg'
        elif format_str == 'png':
            content_type = 'image/png'
        elif format_str == 'pdf':
            content_type = 'application/pdf'
        else:
            content_type = 'application/octet-stream'
        
        with open(chemin, 'rb') as f:
            fichier = SimpleUploadedFile(
                name=f"{document.titre}",
                content=f.read(),
                content_type=content_type
            )


        # Copie du Rapport CA (s'il existe) du dossier /Work à /Actes
        try:
            
            if rapportCA_id :
                nouv_emplacement = os.path.join(dossier_path, 'Actes/')
                # empla_rapportCA = os.path.join(dossier_path, 'Actes/', f"{document.titre}")
                docRapportCA = Document.objects.get(id=rapportCA_id)

                # Séparation du nom et extension
                nom_base, ext = os.path.splitext(docRapportCA.titre)
                titre_final = nom_base
                i = 1
                
                #  Boucle jusqu'à trouver un nom de fichier et d'enregistrement non existant
                repertoire_absolu = os.path.join(os.environ.get("NAS_ROOT"), nouv_emplacement)
                while True:
                    emplacement = os.path.join(repertoire_absolu, f"{titre_final}{ext}")

                    fichier_existe = smbclient.path.exists(emplacement)
                    enregistrement_existe = Document.objects.filter(emplacement=nouv_emplacement, titre=f"{titre_final}{ext}").exists()

                    if not fichier_existe and not enregistrement_existe:
                        break  # nom libre

                    i += 1
                    titre_final = f"{nom_base}_{i}"


                # Écrire le file dans ./actes

                # Copie du fichier sur disque
                emplacement_ancien_rapportCA =  os.path.join(os.environ.get("NAS_ROOT"), docRapportCA.emplacement, docRapportCA.titre) 

                if not ecrire_file_sur_nas(emplacement_ancien_rapportCA, emplacement): 
                    logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {docRapportCA.titre} sur {emplacement}")
                    raise Exception(f"Échec de l’écriture du fichier {docRapportCA.titre} sur {emplacement}")


                logger.info(f"[DOSSIER {dossier_numero}] Rapport CA ({fichier.name}) copié du dossier Work au dossier Actes.")
                # Changer l'emplacement /Work par /Actes
                docRapportCA.emplacement = nouv_emplacement
                docRapportCA.save()
        
        except Exception as e:
            messages.error(request, f"Echec de la copie du Rapport CA du dossier Work vers le dossier Actes : {e}")
            logger.error(f"[DOSSIER {dossier_numero}] Echec de la copie du Rapport CA du dossier Work vers le dossier Actes : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        
        if dossier.present_sur_ds :
            result = accepter_dossier_ds(dossier_id_ds, instructeur, motivation, fichier)
        
            if result["success"]:
                loggerDS.info(f"[DOSSIER {dossier_numero}] accepté avec succès par {instructeur.email}")

            else:
                logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l'acceptation du dossier sur DS par {instructeur.email} : {result['message']}")
                loggerDS.error(f"[DOSSIER {dossier_numero}] Erreur lors de l'acceptation du dossier sur DS par {instructeur.email} : {result['message']}")


        # Mettre à jour l'étape et l'état en BDD
        etape_raa = EtapeDossier.objects.filter(etape__iexact="À publier au RAA").first()
        etat_accepte = EtatDossier.objects.filter(nom__iexact="accepte").first()

        if dossier:
            if etape_raa and dossier.id_etape_dossier != etape_raa:
                changer_etape_si_differente(dossier, "À publier au RAA", request.user, request)

            if etat_accepte and dossier.id_etat_dossier != etat_accepte:
                changer_etat_si_different(dossier, 'accepte', request.user)
        
        # --- Enregistrer Action ---
        enregistrer_action(dossier, instructeur, "Acte envoyé")


        # -------------------------------------------------------
        # Ajout de la personne chargée de publier l'acte au RAA
        # ------------------------------------------------------

        # Supprime les anciens envoyeurs associés au dossier (s'ils existent)
        DossierPublicationRAA.objects.filter(id_dossier=dossier).delete()
        # On créé le nouveau
        DossierPublicationRAA.objects.create(id_dossier=dossier, id_instructeur=publieur_raa)
        logger.info(f"[DOSSIER {dossier.numero}] Publieur RAA {publieur_raa} ajouté au dossier.")


        # Créer le Document en physique
        if fichier and dossier:

            # Format : extraire l'extension
            nom, extension = os.path.splitext(fichier.name)
            ext = extension.lstrip('.').lower()
            format_obj = DocumentFormat.objects.filter(format__iexact=ext).first()

            # Nature : à partir du label sélectionné
            nature_obj = DocumentNature.objects.filter(nature__iexact=nature_document.strip()).first()

            if not format_obj or not nature_obj:
                logger.error(f"[DOSSIER {dossier_numero}] Format ({ext}) ou nature ({nature_document}) introuvable.")
            else:
                if doc_existant :
                    # Supprimer le lien avec le dossier
                    DossierDocument.objects.filter(id_document=doc_existant.id).delete()
                    # Supprimer l’objet Document
                    doc_existant.delete()
                    logger.warning(f"[DOSSIER {dossier_numero}] Suppression de l'ancien Document et DossierDocument {emplacement_doc}")
                
                # Logger l'écrasement du fichier
                if smbclient.path.exists(full_path):
                    logger.warning(f"[DOSSIER {dossier_numero}] Écrasement de {full_path}")



                if not ecrire_file_sur_nas(fichier, full_path): 
                    logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {emplacement}")
                    raise Exception(f"Échec de l’écriture du fichier {fichier.name} sur {emplacement}")
                

                logger.info(f"[DOSSIER {dossier_numero}] {nature_document} ({fichier.name}) écrit : {full_path}")

                # Récupérer l'objet statut "Envoyé"
                statut_envoye = DocumentStatut.objects.filter(statut__iexact="envoyé").first()

                # Par sécurité
                if not statut_envoye:
                    logger.error("Statut 'Envoyé' introuvable en base.")
                    messages.error(request, "Statut 'Envoyé' introuvable en base.")
                    return redirect(request.META.get("HTTP_REFERER", "/"))

                # Mise à jour des champs existants
                document.id_format = format_obj
                document.id_nature = nature_obj
                document.id_statut = statut_envoye
                document.emplacement = os.path.join(dossier_path, 'Actes/')
                document.description = f"{nature_document} pour le dossier {dossier.numero}"
                document.save()


        # -------------------------------------#
        # Envoyer une copie de l'acte par Mail
        # -------------------------------------#
        partager_par_mail = request.POST.get("partager_par_mail")  # "oui" ou "non"
        emails = request.POST.getlist("emails_copie[]")

        # Nouveaux contacts
        emails_nouveaux = request.POST.getlist("email_contact[]")
        noms = request.POST.getlist("nom_contact[]")
        prenoms = request.POST.getlist("prenom_contact[]")
        types = request.POST.getlist("type_contact[]")
        raisons = request.POST.getlist("raison_sociale[]")

        # --- Traiter les nouveaux contacts saisis dans le mini-form ---
        for i, email in enumerate(emails_nouveaux):
            email = (email or "").strip()
            if not email:
                continue

            try:
                validate_email(email)
            except ValidationError:
                logger.warning(f"[DOSSIER {dossier_numero}] Email invalide ignoré: {email}")
                continue

            nom = (noms[i] if i < len(noms) else "").strip()
            prenom = (prenoms[i] if i < len(prenoms) else "").strip()
            raison = (raisons[i] if i < len(raisons) else "").strip()
            type_id = types[i] if i < len(types) else None

            type_obj = None
            if type_id:
                type_obj = TypeContactExterne.objects.filter(id=type_id).first()
            if not type_obj:
                type_obj, _ = TypeContactExterne.objects.get_or_create(type="autre")

            contact, created = ContactExterne.objects.get_or_create(
                email=email,
                defaults={
                    "nom": nom,
                    "prenom": prenom,
                    "raison_sociale": raison,
                    "id_type": type_obj,
                }
            )
            if created:
                logger.info(f"[DOSSIER {dossier_numero}] Envoi de l'acte par mail : Nouveau ContactExterne créé via formulaire : {email}")

            # Ajouter ce mail aux destinataires
            emails.append(email)


        # Normalise + dédoublonne
        if partager_par_mail == "oui":
            
            emails_norm = []
            seen = set()
            for e in emails:
                e_norm = (e or "").strip()
                if not e_norm:
                    continue
                e_key = e_norm.lower()
                if e_key in seen:
                    continue
                # Valide l'email
                try:
                    validate_email(e_norm)
                except ValidationError:
                    logger.warning(f"[DOSSIER {dossier_numero}] Email invalide ignoré: {e_norm}")
                    continue
                seen.add(e_key)
                emails_norm.append(e_norm)

            if not emails_norm:
                logger.warning("Aucun email valide sélectionné pour l’envoi en copie.")
            else:

                sujet = f"{nature_document} – Dossier {dossier.numero}"
                dedupe = compute_dedupe_key(emails_norm, sujet, "libre", {"body": motivation})
            
                try:
                    outbox = EmailOutbox.objects.create(
                        to=emails_norm,
                        email_from=os.getenv("DEFAULT_FROM_EMAIL"),
                        type_mail = "Envoi de l'acte",
                        sujet=sujet,
                        template="libre",
                        dedupe_key=dedupe,
                        context={"body": motivation},
                        id_dossier=dossier,
                        id_document=document,
                    )
                    # logger.info(f"[DOSSIER {dossier_numero}] EmailOutbox créé pour {emails_norm}")

                except IntegrityError as e:
                    # Si c’est bien un conflit sur l’unicité partielle (ux_outbox_dedupe_pending)
                    is_unique_violation = (
                        (UniqueViolation and isinstance(getattr(e, "__cause__", None), UniqueViolation))
                        or "ux_outbox_dedupe_pending" in str(e)
                        or "unique" in str(e).lower()
                    )
                    if is_unique_violation:
                        # On récupère l'élément déjà en attente (cas « doublon »)
                        outbox = (
                            EmailOutbox.objects
                            .filter(dedupe_key=dedupe, statut__in=["À envoyer", "Échec"])
                            .order_by("-date_creation")
                            .first()
                        )
                        logger.warning(f"[DOSSIER {dossier_numero}] Email à envoyé ({outbox.sujet} -> {', '.join(outbox.to)}) ")


                # return (True, "") ou (False, "msg erreur")
                ok, err = envoi_mail(outbox.id)

                if ok:
                    logger.info(f"[DOSSIER {dossier_numero}] Email ({outbox.sujet}) envoyé à {', '.join(outbox.to)} ")
                else:
                    logger.error(f"[DOSSIER {dossier_numero}] Échec envoi email ({outbox.sujet}) à {', '.join(outbox.to)} : {err}")
                    messages.error(request, f"[DOSSIER {dossier_numero}] Échec envoi email ({outbox.sujet}) à {', '.join(outbox.to)} : {err}")


    except Exception as e:
        logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier par {instructeur.email}: {str(e)}")
        messages.error(request, f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier sur DS par {instructeur.email}: {str(e)}")

    return redirect(request.META.get("HTTP_REFERER", "/")
)

