from datetime import datetime
import logging
import os
from django.db import IntegrityError
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from autorisations.models.models_instruction import Dossier, EtapeDossier, EtatDossier, DossierAction, Action
from autorisations.models.models_utilisateurs import ContactExterne, DossierRelecteurQualite, DossierSignataire, EmailOutbox, GroupeinstructeurInstructeur, Instructeur, DossierInstructeur, DossierValideur, TypeContactExterne
from DS.call_DS import accepter_dossier_ds, get_msg_DS, passer_en_instruction_ds,classer_sans_suite_ds, refuser_dossier_ds, repasser_en_instruction_ds
from autorisations import settings
from autorisations.models.models_avis import Avis, DossierAvis
from notifications.service import compute_dedupe_key, send_outbox_now
from instruction.services.messagerie_service import envoyer_message_ds, prepare_temp_file, enregistrer_message_bdd
from instruction.utils import changer_etape_si_differente, changer_etat_si_different, enregistrer_action
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

# @login_required
# def passer_en_pre_instruction(request):
#     if request.method == "POST":
#         dossier_id_ds = request.POST.get("dossierId")
#         dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)

#         changer_etape_si_differente(dossier,"En pré-instruction", request.user)

#         instructeur = Instructeur.objects.filter(email=request.user.email).first()
        
#         # Enregistrer Dossier Action
#         enregistrer_action(dossier, instructeur, "Passage en pré-instruction")


#     return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@login_required
def passer_en_pre_instruction(request):
    if request.method != "POST":
        return redirect("/")

    dossier_id_ds = request.POST.get("dossierId")
    dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)

    # IDs des instructeurs affectés à ce dossier
    instructeurs_dossier_ids_qs = DossierInstructeur.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True)

    if not instructeurs_dossier_ids_qs.exists():
        request.session["preinstruction_message"] = "Vous devez assigner un instructeur au dossier pour pouvoir le passer en pré-instruction."
        return redirect(reverse("preinstruction_dossier", kwargs={"numero": dossier.numero}))

    instructeurs_dossier_ids = set(instructeurs_dossier_ids_qs)

    groupe = dossier.id_groupeinstructeur
    if not groupe:
        request.session["preinstruction_message"] = "Aucun groupe instructeur n’est défini pour ce dossier."
        return redirect(reverse("preinstruction_dossier", kwargs={"numero": dossier.numero}))

    instructeurs_groupe_ids = set(
        GroupeinstructeurInstructeur.objects.filter(id_groupeinstructeur=groupe)
        .values_list("id_instructeur", flat=True)
    )
    intersection = instructeurs_dossier_ids & instructeurs_groupe_ids

    if not intersection:
        request.session["preinstruction_message"] = (
            "Le dossier n’est associé à aucun instructeur appartenant au groupe instructeur."
        )
        return redirect(reverse("preinstruction_dossier", kwargs={"numero": dossier.numero}))

    # ✅ Passage autorisé
    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()
    changer_etape_si_differente(dossier, "En pré-instruction", request.user)
    enregistrer_action(dossier, instructeur_connecte, "Passage en pré-instruction")

    request.session.pop("preinstruction_message", None)
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))




@login_required
def demander_des_complements(request):
    if request.method == "POST":
        numero = request.POST.get("numero_dossier")
        body = request.POST.get("body")
        fichier = request.FILES.get("piece_jointe")

        dossier = get_object_or_404(Dossier, numero=numero)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        if not (dossier.id_ds and instructeur and instructeur.id_ds and body):
            return HttpResponseBadRequest("Echec de la demande de compléments : Informations manquantes")

        tmp_file_path = None
        try:
            if fichier:
                tmp_file_path = prepare_temp_file(fichier)
                result = envoyer_message_ds(dossier.id_ds, instructeur.id_ds, body, fichier, fichier.content_type, tmp_file_path, numero, correction=True)
            else:
                result = envoyer_message_ds(dossier.id_ds, instructeur.id_ds, body, num_dossier=numero, correction=True)

            if result.get("data"):
                id_ds_msg = result["data"]["dossierEnvoyerMessage"]["message"]["id"]
                url_ds = get_msg_DS(int(numero), id_ds_msg) if fichier else None
                enregistrer_message_bdd(dossier, request.user.email, body, fichier, id_ds=id_ds_msg, url_ds=url_ds)

                # Mettre à jour étape + état si besoin
                changer_etape_si_differente(dossier, "En attente de compléments", request.user)
                changer_etat_si_different(dossier, "en_construction", request.user)

                # Dossiers Actions
                enregistrer_action(dossier, instructeur, "Demande de compléments")

          
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    return redirect(reverse('instruction_dossier_messagerie', args=[dossier.numero]))



@login_required
def dossier_non_soumis_a_autorisation(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        motivation = request.POST.get("motivation", "").strip()

        if not motivation:
            return HttpResponseBadRequest("Une justification est requise pour classer sans suite.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        if not instructeur or not instructeur.id_ds:
            logger.error(f"[DOSSIER {dossier.numero}] Echec classement 'Non soumis à autorisation' : Instructeur introuvable ou non présent sur DS.")
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à Démarches Simplifiées.")

         # Si l'étape est 'En pré-instruction' ou 'À affecter' et l'état 'en_construction' --> passer l'état à en_instruction
        if dossier.id_etat_dossier.nom == 'en_construction' and (dossier.id_etape_dossier.etape == 'En pré-instruction' or dossier.id_etape_dossier.etape == 'À affecter') :
            passer_en_instruction_ds(dossier.id_ds, instructeur.id_ds)

        # Appel API GraphQL
        result = classer_sans_suite_ds(dossier.id_ds, instructeur.id_ds, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Classement sans suite DS échoué : {result.get('message')}")
            return HttpResponseBadRequest("Erreur DS : classement sans suite échoué.")

        # Mettre à jour étape + état si besoin
        changer_etape_si_differente(dossier, "Non soumis à autorisation", request.user)
        changer_etat_si_different(dossier, "sans_suite", request.user)

        # Maj Date Fin Instruction
        dossier.date_fin_instruction = timezone.now()
        dossier.save()

        # Dossiers Actions
        enregistrer_action(dossier, instructeur, "Classé sans suite")


    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def refuse_le_dossier(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        motivation = request.POST.get("motivation", "").strip()

        if not motivation:
            return HttpResponseBadRequest("Une justification est requise pour refuser le dossier.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        if not instructeur or not instructeur.id_ds:
            logger.error(f"[DOSSIER {dossier.numero}] Echec de refus du dossier : Instructeur introuvable ou non connecté à DS.")
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à Démarches Simplifiées.")

        # Si l'étape est 'En pré-instruction' et l'état 'en_construction' --> passer l'état à en_instruction
        if dossier.id_etat_dossier.nom == 'en_construction' and dossier.id_etape_dossier.etape == 'En pré-instruction' :
            passer_en_instruction_ds(dossier.id_ds, instructeur.id_ds)

        # Appel de l'API DS
        result = refuser_dossier_ds(dossier.id_ds, instructeur.id_ds, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Echec de refus du dossier sur DS : {result.get('message')}")
            return HttpResponseBadRequest("Erreur Démarches Simplifiées : refus échoué.")

        # Mettre à jour étape + état si besoin
        changer_etape_si_differente(dossier, "Refusé", request.user)
        changer_etat_si_different(dossier, "refuse", request.user)

        # Maj Date Fin Instruction
        dossier.date_fin_instruction = timezone.now()
        dossier.save()

        # Dossier Action
        enregistrer_action(dossier, instructeur, "Classé comme refusé")


        return redirect(reverse('instruction_dossier', kwargs={'num_dossier': dossier.numero}))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def passer_en_instruction(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        etat_actuel_dossier = get_object_or_404(EtatDossier, id=dossier.id_etat_dossier_id)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        if not instructeur or not instructeur.id_ds:
            logger.error(f"[DOSSIER {dossier.numero}] Echec du passage en instruction : Instructeur introuvable ou non connecté à DS.")
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à Démarches Simplifiées.")

        # Appel GraphQL uniquement si l'état n'est pas déjà 'en_instruction'
        if etat_actuel_dossier.nom.lower() != "en_instruction":
            result = passer_en_instruction_ds(dossier.id_ds, instructeur.id_ds)
            if not result.get("success"):
                logger.error(f"[DOSSIER {dossier.numero}] Échec du passage en instruction sur DS : {result.get('message')}")

        # Changer l'étape et l'état si besoin
        changer_etape_si_differente(dossier, "En instruction", request.user)
        changer_etat_si_different(dossier, "en_instruction", request.user)
        
        # Enregistrer dossier action
        enregistrer_action(dossier, instructeur, "Passage en instruction")

        # Mettre à jour la date de début d'instruction
        dossier.date_debut_instruction = timezone.now()
        dossier.save()

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def envoyer_pour_validation_avant_demande_avis(request):

    if request.method == "POST":

        dossier_id_ds = request.POST.get("dossierId")
        nature = request.POST.get("nature_document")
        validant = request.POST.get("choix-validant") #Objet Instructeur
        fichier = request.FILES.get("piece_jointe")
        ids_selectionnes = request.POST.getlist("avis_selectionnes")
        
        extension = Path(fichier.name).suffix.lower()
        if extension not in {".doc", ".docx", ".odt"} :
            messages.error(request, f"❌ Le fichier joint doit etre .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not dossier_id_ds :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : L'id du dossier est manquant.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not nature :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : La nature du projet d'acte est manquante.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not fichier :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : Le projet d'acte n'a pas été joint.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not validant :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : Aucun validant sélectionné.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not ids_selectionnes :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : Aucun avis sélectionné.")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        avis_selectionnes = Avis.objects.filter(id__in=ids_selectionnes)
        if not avis_selectionnes:
            messages.error(request, f"❌ Aucun avis trouvé avec les id : {ids_selectionnes}.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        if not dossier:
            messages.error(request, f"❌ Aucun dossier trouvé avec l'id DS : {dossier_id_ds}.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur:
            messages.error(request, f"❌ Aucun instructeur trouvé avec l'adresse mail : {request.user.email}.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        # Définir le chemin de destination
        dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")
        full_path = os.path.join(os.environ.get("ROOT_FOLDER"), dossier_path)
        os.makedirs(full_path, exist_ok=True)
        filepath = os.path.join(full_path, fichier.name)

        # Vérification que le file sélectionné est bien dans le sous dossier Work
        if not os.path.exists(filepath):
            messages.error(request, "❌ Le projet d’acte doit être placé dans le sous-dossier 'Work' du dossier concerné.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        # Avis Maj du statut : À valider
        for avis in avis_selectionnes:
            avis.statut = "À valider"
            avis.save()

        # Ajout du validant au dossier
        try:
            # Suppression des valideurs du dossier (si existants)
            deleted_count, _ = DossierValideur.objects.filter(id_dossier=dossier).delete()
            if deleted_count > 0:
                logger.info(f"[DOSSIER {dossier.numero}] {deleted_count} validant(s) existant(s) supprimé(s) du dossier.")
            validant_obj = get_object_or_404(Instructeur, id=validant)
            DossierValideur.objects.get_or_create(id_dossier=dossier, id_instructeur=validant_obj)
            logger.info(f"[DOSSIER {dossier.numero}] Validant·e {validant_obj} affecté·e au dossier.")
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'affectation du validant·e {validant} : {e}")



        try:
            # # Enregistrement physique ??
            # with open(filepath, 'wb+') as destination:
            #     for chunk in fichier.chunks():
            #         destination.write(chunk)

            # Récupérer la nature, le format et le statut
            nature_obj = get_object_or_404(DocumentNature, nature=nature)
            extension = os.path.splitext(fichier.name)[1].lower().lstrip('.')
            format_obj = get_object_or_404(DocumentFormat, format=extension)
            statut_obj = get_object_or_404(DocumentStatut, statut="À valider")

            # Enregistrer en BDD
            doc, created = Document.objects.get_or_create(
                                emplacement=dossier_path, titre=fichier.name,
                                defaults={
                                    "id_format": format_obj,
                                    "id_nature": nature_obj,
                                    "id_statut": statut_obj,
                                    "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                                }
                            )

            if created:
                DossierDocument.objects.create(
                    id_dossier=dossier,
                    id_document=doc
                )
                logger.info(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {fichier.name} créé dans le dossier Work")
            else:
                doc.id_statut = statut_obj
                doc.save()
                logger.warning(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {fichier.name} déjà existant dans le dossier Work – aucune création")


        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] {nature_obj.nature} : Erreur lors de la création du Document ou de l'écriture physique dans le dossier Work ({str(e)})")

        

        # Changer Etape
        changer_etape_si_differente(dossier, "À valider avant demande d'avis", request.user)

        # Dossier Action
        enregistrer_action(dossier, instructeur, "Envoyé pour validation")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def envoyer_pour_validation_avant_signature(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        nature = request.POST.get("nature_document")
        validant = request.POST.get("choix-validant") #Objet Instructeur
        fichier = request.FILES.get("piece_jointe")

        # Vérification que l'extension du fil est .doc, .docx, .pdf, .odt
        extension = Path(fichier.name).suffix.lower()
        if extension not in {".doc", ".docx", ".odt"} :
            messages.error(request, f"❌ Le fichier joint doit etre .pdf ou .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        if not dossier_id_ds :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : L'id du dossier est manquant.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not nature :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : La nature du projet d'acte est manquante.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not fichier :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : Le projet d'acte n'a pas été joint.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        if not validant :
            messages.error(request, f"❌ Envoi pour validation avant demande d'avis : Aucun validant sélectionné.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)

        # Définir le chemin de destination
        dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")

        full_path = os.path.join(os.environ.get("ROOT_FOLDER"), dossier_path)
        os.makedirs(full_path, exist_ok=True)
        filepath = os.path.join(full_path, fichier.name)

        # Vérification que le file sélectionné est bien dans le sous dossier Work
        if not os.path.exists(filepath):
            messages.error(request, "❌ Le projet d’acte doit être placé dans le sous-dossier 'Work' du dossier concerné.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        try:
            # Enregistrement physique ??
            with open(filepath, 'wb+') as destination:
                for chunk in fichier.chunks():
                    destination.write(chunk)

            # Récupérer la nature, le format et le statut
            nature_obj = get_object_or_404(DocumentNature, nature=nature)
            extension = os.path.splitext(fichier.name)[1].lower().lstrip('.')
            format_obj = get_object_or_404(DocumentFormat, format=extension)
            statut_obj = get_object_or_404(DocumentStatut, statut="À valider")

            # Enregistrer en BDD
            doc, created = Document.objects.get_or_create(
                                emplacement=dossier_path, titre=fichier.name,
                                defaults={
                                    "id_format": format_obj,
                                    "id_nature": nature_obj,
                                    "id_statut": statut_obj,
                                    "description": f"{nature_obj.nature} du dossier {dossier.numero}",
                                }
                            )

            if created:
                DossierDocument.objects.create(
                    id_dossier=dossier,
                    id_document=doc
                )
                logger.info(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {fichier.name} créé dans le dossier Work")
            else:
                doc.id_statut = statut_obj
                doc.save()
                logger.warning(f"[DOSSIER {dossier.numero}] {nature_obj.nature} {fichier.name} déjà existant dans le dossier Work – aucune création")


        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] {nature_obj.nature} : Erreur lors de la création du Document ou de l'écriture physique dans le dossier Work ({str(e)})")

        # Changer Etape
        changer_etape_si_differente(dossier, "À valider avant signature", request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Envoyé pour validation")

        # Ajout du validant au dossier
        try:
            # Suppression des valideurs du dossier (si existants)
            deleted_count, _ = DossierValideur.objects.filter(id_dossier=dossier).delete()
            if deleted_count > 0:
                logger.info(f"[DOSSIER {dossier.numero}] {deleted_count} validant(s) existant(s) supprimé(s) du dossier.")
            validant_obj = get_object_or_404(Instructeur, id=validant)

            DossierValideur.objects.get_or_create(id_dossier=dossier, id_instructeur=validant_obj)
            logger.info(f"[DOSSIER {dossier.numero}] Validant·e {validant_obj} affecté·e au dossier.")
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'affectation du validant·e {validant} : {e}")



        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseRedirect("/")



@login_required
def avis_envoye(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")

        if not dossier_id_ds :
            messages.error(request, f"❌ Envoi de l'avis impossible : Données manquantes ou invalides (ID du dossier DS = {dossier_id_ds})")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)

        # Check qu'il ne reste pas d'avis non envoyés
        avis_a_envoyer = Avis.objects.filter(
            id__in=DossierAvis.objects.filter(
                id_dossier=dossier,  # en supposant que Demande → Dossier
                id_avis__statut="À envoyer"
            ).values_list("id_avis", flat=True)
        ).count()

        if avis_a_envoyer > 0 :
            messages.error(request, "Il reste un/des avis à envoyer.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        changer_etape_si_differente(dossier, "En attente réponse d'avis", request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Avis demandé")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def valider_le_modele_de_demande_d_avis_et_le_projet_d_acte(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")

        if not dossier_id_ds :
            messages.error(request, f"❌ Données manquantes ou invalides : ID du dossier DS = {dossier_id_ds}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)

        # Statut Doc A valider --> Validé avant demande d'avis
        statut_a_valider = DocumentStatut.objects.filter(statut="À valider").first()
        statut_valide_avant_demande_avis = DocumentStatut.objects.filter(statut="Validé avant demande d'avis").first()
        docs_a_valider = DossierDocument.objects.filter(id_dossier=dossier, id_document__id_statut=statut_a_valider)
        for doc in docs_a_valider :
            d = doc.id_document
            d.id_statut = statut_valide_avant_demande_avis
            d.save()

        # Statut Avis A valider --> A envoyer
        avis_a_valider = Avis.objects.filter(
            id__in=DossierAvis.objects.filter(
                id_dossier=dossier,  # en supposant que Demande → Dossier
                id_avis__statut="À valider"
            ).values_list("id_avis", flat=True)
        )

        for avis in avis_a_valider:
            avis.statut = "À envoyer"
            avis.save()

        # Changer Etape
        changer_etape_si_differente(dossier, "Avis à envoyer", request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        nom_prenom = '(' + instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom + ')'

        enregistrer_action(dossier, instructeur, "Validé avant demande d'avis", nom_prenom)

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def repasser_en_instruction(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        etat_actuel_dossier = get_object_or_404(EtatDossier, id=dossier.id_etat_dossier_id)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        if not instructeur or not instructeur.id_ds:
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à DS.")
   
        # Appel GraphQL uniquement si l'état n'est pas déjà 'en_instruction'
        if etat_actuel_dossier.nom.lower() != "en_instruction":
            result = repasser_en_instruction_ds(dossier.id_ds, instructeur.id_ds)

            if not result.get("success"):
                if result.get('message') == "Le dossier est déjà en instruction" :
                    logger.warning(f"[DOSSIER {dossier.numero}] Le dossier n'a pas été repassé en instruction sur DS car il est déjà en instruction : {result.get('message')}")
                else:
                    logger.error(f"[DOSSIER {dossier.numero}] Échec du repassage en instruction du dossier {dossier.numero} : {result.get('message')}")
                    return HttpResponseBadRequest("Erreur côté DS lors du repassage en instruction.")

        # Changer l'étape et l'état si besoin
        changer_etape_si_differente(dossier, "En instruction", request.user)
        changer_etat_si_different(dossier, "en_instruction", request.user)

        # Enregistrer dossier action
        enregistrer_action(dossier, instructeur, "Repassage en instruction")

        # Maj Statut Documents
        # 1. Récupérer les statuts concernés (en minuscule pour robustesse)
        statuts_cibles = {"à envoyer", "à signer", "à relire", "à valider"}

        # 2. Récupérer tous les DossierDocument liés au dossier
        documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

        # 3. Parcourir et mettre à jour
        for lien in documents_du_dossier:
            doc = lien.id_document
            statut_actuel = doc.id_statut.statut.lower() if doc.id_statut else ""

            if statut_actuel in statuts_cibles:
                doc.id_statut = None
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' remis à NULL.")

        # Supprimer les DossierSignataire, DossierRelecteurQualite, DossierValideur du dossier
        DossierSignataire.objects.filter(id_dossier=dossier).delete()
        DossierRelecteurQualite.objects.filter(id_dossier=dossier).delete()
        DossierValideur.objects.filter(id_dossier=dossier).delete()

        # Maj statut Avis
        avis_a_reinitialiser = Avis.objects.filter(id_dossier=dossier, statut="À valider")

        for avis in avis_a_reinitialiser:
            avis.statut = "Brouillon"
            try:
                avis.save()  # déclenche clean() + validation
                logger.info(f"[DOSSIER {dossier.numero}] Avis {avis.id} remis en statut 'Brouillon'")
            except ValidationError as e:
                logger.error(f"[DOSSIER {dossier.numero}] Impossible de remettre l'avis {avis.id} en 'Brouillon' : {e}")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def acte_inchange_envoyer_pour_relecture_qualite(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        # relecteur = request.POST.get("choix-relecteur") #Objet Instructeur

        if not dossier_id_ds :
            messages.error(request, f"❌ Données manquantes ou invalides : ID du dossier DS = {dossier_id_ds}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    

        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En relecture qualité",request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Envoyé pour relecture qualité")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def valider_et_envoyer_pour_relecture_qualite(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        relecteur = request.POST.get("choix-relecteur") #Objet Instructeur

        if not dossier_id_ds or not relecteur:
            messages.error(request, f"❌ Données manquantes ou invalides : ID du dossier DS = {dossier_id_ds}, Relecteur.rice = {relecteur}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        

        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En relecture qualité",request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        nom_prenom = '(' + instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom + ')'

        enregistrer_action(dossier, instructeur, "Validé avant signature", nom_prenom)

       
        # Récupérer l'objet statut "À relire"
        statut_relire = DocumentStatut.objects.filter(statut__iexact="à relire").first()

        # Par sécurité
        if not statut_relire:
            logger.error("Statut 'À relire' introuvable en base.")
            messages.error("Statut 'À relire' introuvable en base.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        # Récupération des documents du dossier
        documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

        # Mise à jour Doc "À valider" --> "À relire"
        for lien in documents_du_dossier:
            doc = lien.id_document
            if doc.id_statut and (doc.id_statut.statut.lower() == "à valider" or doc.id_statut.statut.lower() == "validé avant demande d'avis"):
                
                doc.id_statut = statut_relire
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → À relire.")

    
        # Ajout du relecteur au dossier
        try:
            relecteur_obj = get_object_or_404(Instructeur, id=relecteur)
            DossierRelecteurQualite.objects.get_or_create(id_dossier=dossier, id_instructeur=relecteur_obj)
            logger.info(f"[DOSSIER {dossier.numero}] Relecteur.rice {relecteur_obj} affecté·e au dossier.")
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'affectation du relecteur.rice {relecteur} : {e}")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def envoyer_les_modifications_de_l_acte_pour_validation(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")

        if not dossier_id_ds:
            messages.error(request, f"❌ Données manquantes ou invalides : ID du dossier DS = {dossier_id_ds}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        
        # Doc Statut Validé avant demande d'avis --> À valider
        statut_a_valider = DocumentStatut.objects.filter(statut="À valider").first()
        statut_valide_avant_demande_avis = DocumentStatut.objects.filter(statut="Validé avant demande d'avis").first()
        docs_valide_avant_demande_avis = DossierDocument.objects.filter(id_dossier=dossier, id_document__id_statut=statut_valide_avant_demande_avis)
        for doc in docs_valide_avant_demande_avis :
            d = doc.id_document
            d.id_statut = statut_a_valider
            d.save()
        

        # Changer l'étape
        changer_etape_si_differente(dossier, "À valider avant signature", request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Envoyé pour validation")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def envoyer_pour_signature(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En attente de signature", request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Envoyé pour signature")

        # Récupérer l'objet statut "À signer"
        statut_a_signer = DocumentStatut.objects.filter(statut__iexact="à signer").first()

        # Par sécurité
        if not statut_a_signer:
            logger.error("Statut 'À signer' introuvable en base.")
            messages.error("Statut 'À signer' introuvable en base.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        # Récupération des documents du dossier
        documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

        # Mise à jour Doc "À relire" --> "À signer"
        for lien in documents_du_dossier:
            doc = lien.id_document
            if doc.id_statut and doc.id_statut.statut.lower() == "à relire":
                doc.id_statut = statut_a_signer
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → À signer.")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def acte_pret_a_etre_envoye(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        fichier = request.FILES.get("piece_jointe")
        signataire_id = request.POST.get("choix-signataire") # id Instructeur
        nature_document = request.POST.get("nature_document")
        numero_acte = request.POST.get("numero_acte")

        if not dossier_id_ds:
            raise Http404(f"[Transmission acte signé] ID dossier DS manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)


        # ----------------------------------------------------------------------
        # Vérification que le file sélectionné est bien dans le sous dossier Work et au format PDF
        # ----------------------------------------------------------------------
        extension = Path(fichier.name).suffix.lower()
        if extension not in {".pdf", ".doc", ".docx", ".odt"} :
            messages.error(request, f"❌ Le fichier joint doit etre .pdf ou .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        dossier_path = os.path.join(dossier.emplacement, "Work/").replace("\\", "/")
        full_path = os.path.join(os.environ.get("ROOT_FOLDER"), dossier_path)
        os.makedirs(full_path, exist_ok=True)
        filepath = os.path.join(full_path, fichier.name)

        if not os.path.exists(filepath):
            messages.error(request, "❌ Le projet d’acte doit être placé dans le sous-dossier 'Work' du dossier concerné.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        # --------------------------------------------
        # Vérification existence Statut, Nature, Format, Signataire
        # ---------------------------------------------
        statut_a_envoyer = DocumentStatut.objects.filter(statut__iexact = "à envoyer").first()
        if not statut_a_envoyer:
            logger.error("Statut 'À envoyer' introuvable en base.")
            messages.error(request, "❌ Statut 'À envoyer' introuvable en base.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        doc_nature = DocumentNature.objects.filter(nature__iexact = nature_document).first()
        if not doc_nature:
            logger.error(f"Nature {doc_nature} introuvable en base.")
            messages.error(request, f"❌ Nature {doc_nature} introuvable en base.")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        format_pdf = DocumentFormat.objects.filter(format__iexact = "pdf").first()
        if not format_pdf:
            logger.error("Format PDF introuvable en base.")
            messages.error(request, "❌ Format PDF introuvable en base.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        
        signataire = get_object_or_404(Instructeur, id=signataire_id)
        if not signataire:
            logger.error(f"Instructeur (ID {signataire_id}) introuvable en base.")
            messages.error(request, f"❌ Instructeur (ID {signataire_id}) introuvable en base.")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        # -------------------------------
        # Mise à jour des Docs  --> None     
        # -------------------------------
        
        statuts_cibles = {"à envoyer", "à signer", "à relire", "à valider"}
        documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

        for lien in documents_du_dossier:
            doc = lien.id_document
            statut_actuel = doc.id_statut.statut.lower() if doc.id_statut else ""

            if statut_actuel in statuts_cibles:
                doc.id_statut = None
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Transmission de l'acte signé, statut du document '{doc.titre}' remis à NULL.")


        # messages.error(request, "GOOD POUR LE MOMENT")
        # return redirect(request.META.get("HTTP_REFERER", "/"))


        # ---------------------------
        # Création du doc "À envoyer" 
        # ---------------------------
        doc_path = os.path.join(dossier_path)

        doc, created = Document.objects.get_or_create(
                                emplacement=doc_path, titre=fichier.name,
                                defaults={
                                    "id_format": format_pdf,
                                    "id_nature": doc_nature,
                                    "id_statut": statut_a_envoyer,
                                    "description": f"{doc_nature.nature} du dossier {dossier.numero}",
                                    "numero": numero_acte,
                                }
                            )
        
        if created:
            DossierDocument.objects.create(
                id_dossier=dossier,
                id_document=doc
            )
            logger.info(f"[DOSSIER {dossier.numero}] Transmission du doc signé : {fichier.name} ({doc_nature.nature} 'À envoyer') créé et lié au dossier")
        else:
            doc.id_statut = statut_a_envoyer
            doc.save()
            logger.warning(f"[DOSSIER {dossier.numero}] Transmission du doc signé : {fichier.name} ({doc_nature.nature}, {doc.id_statut.statut}) déjà existant – statut changé À envoyer ")
        


        # -----------------------------
        # Ajout du signataire au dossier
        # -----------------------------
        existe_deja = DossierSignataire.objects.filter(
            id_dossier=dossier,
            id_instructeur=signataire
        ).exists()

        if existe_deja:
            logger.info(f"[DOSSIER {dossier.numero}] Signataire {signataire} déjà enregistré pour ce dossier.")
        else:
            DossierSignataire.objects.create(
                id_dossier=dossier,
                id_instructeur=signataire
            )
            logger.info(f"[DOSSIER {dossier.numero}] Signataire {signataire} ajouté au dossier.")



        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Acte à envoyer", request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        signataire_nom_prenom = f"({signataire.id_agent_autorisations.nom} {signataire.id_agent_autorisations.prenom})"

        enregistrer_action(dossier, instructeur, "Acte signé", signataire_nom_prenom)


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def classer_le_dossier_comme_accepte(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer Etape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Accepté", request.user)

        # Maj Date Fin Instruction
        dossier.date_fin_instruction = timezone.now()
        dossier.save()

        #Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Classé comme accepté")

        #Document publié au RAA --> True
        documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

        # Mise à jour Doc "publie_au_raa"
        for lien in documents_du_dossier:
            doc = lien.id_document
            if doc.id_statut and doc.id_statut.statut.lower() == "envoyé" and not doc.publie_au_raa:
                doc.publie_au_raa = True
                doc.save()

        return redirect(request.META.get("HTTP_REFERER", "/"))
    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
@require_POST
def envoyer_l_acte(request):

    dossier_id_ds = request.POST.get("dossierId")
    dossier_numero = request.POST.get("dossier_numero")
    motivation = request.POST.get("motivation", "Votre demande a été acceptée.")
    document_id = request.POST.get("document_id_existant")
    nature_document = request.POST.get("nature_document")


    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    
    if not dossier_id_ds or not instructeur or not instructeur.id_ds:
            messages.error(request, f"❌ Données manquantes ou invalides : ID du dossier DS = {dossier_id_ds}, Instructeur.rice = {instructeur}")
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
        full_path = os.path.join(os.environ.get("ROOT_FOLDER"), emplacement_doc)

        # Chercher si un document existe déjà avec même emplacement + titre
        doc_existant = Document.objects.filter(emplacement=os.path.join(dossier_path, 'Actes/'), titre=document.titre).first()
        

        chemin = os.path.join(os.getenv("ROOT_FOLDER"), document.emplacement, document.titre)
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
        

        result = accepter_dossier_ds(dossier_id_ds, instructeur.id_ds, motivation, fichier)
        if result["success"]:

            loggerDS.info(f"[DOSSIER {dossier_numero}] accepté avec succès par {instructeur.email}")

            # Mettre à jour l'étape et l'état en BDD
            etape_raa = EtapeDossier.objects.filter(etape__iexact="À publier au RAA").first()
            etat_accepte = EtatDossier.objects.filter(nom__iexact="accepte").first()

            if dossier:
                if etape_raa and dossier.id_etape_dossier != etape_raa:
                    changer_etape_si_differente(dossier, "À publier au RAA", request.user)

                if etat_accepte and dossier.id_etat_dossier != etat_accepte:
                    changer_etat_si_different(dossier, 'accepte', request.user)
            
            # Dossier Action
            enregistrer_action(dossier, instructeur, "Acte envoyé")

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
                    if os.path.exists(full_path):
                        logger.warning(f"[DOSSIER {dossier_numero}] Écrasement de {full_path}")

                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'wb+') as dest:
                        for chunk in fichier.chunks():
                            dest.write(chunk)
                    logger.info(f"[DOSSIER {dossier_numero}] {nature_document} ({fichier.name}) écrit : {full_path}")

                    # Récupérer l'objet statut "Envoyé"
                    statut_envoye = DocumentStatut.objects.filter(statut__iexact="envoyé").first()

                    # Par sécurité
                    if not statut_envoye:
                        logger.error("Statut 'Envoyé' introuvable en base.")
                        messages.error("Statut 'Envoyé' introuvable en base.")
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
                    logger.warning(request, "Aucun email valide sélectionné pour l’envoi en copie.")
                else:

                    sujet = f"{nature_document} – Dossier {dossier.numero}"
                    dedupe = compute_dedupe_key(emails_norm, sujet, "libre", {"body": motivation})
                   
                    try:
                        outbox = EmailOutbox.objects.create(
                            to=emails_norm,
                            email_from=os.getenv("DEFAULT_FROM_EMAIL"),
                            sujet=sujet,
                            template="libre",
                            dedupe_key=dedupe,
                            context={"body": motivation},
                            id_dossier=dossier,
                            id_document=document,
                        )
                        logger.info(f"[DOSSIER {dossier_numero}] EmailOutbox créé pour {emails_norm}")

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
                            logger.warning(f"[DOSSIER {dossier_numero}] Email à envoyé ({outbox.sujet} -> {", ".join(outbox.to)}) ")


                    # return (True, "") ou (False, "msg erreur")
                    ok, err = send_outbox_now(outbox.id)

                    if ok:
                        logger.info(f"[DOSSIER {dossier_numero}] Email ({outbox.sujet}) envoyé à {", ".join(outbox.to)} ")
                    else:
                        logger.error(f"[DOSSIER {dossier_numero}] Échec envoi email ({outbox.sujet}) à {", ".join(outbox.to)} : {err}")
                        messages.error(request, f"[DOSSIER {dossier_numero}] Échec envoi email ({outbox.sujet}) à {", ".join(outbox.to)} : {err}")

        else:
            logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l'acceptation du dossier sur DS par {instructeur.email} : {result['message']}")
            loggerDS.error(f"[DOSSIER {dossier_numero}] Erreur lors de l'acceptation du dossier sur DS par {instructeur.email} : {result['message']}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier par {instructeur.email}: {str(e)}")
        messages.error(request, f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier sur DS par {instructeur.email}: {str(e)}")

    return redirect(request.META.get("HTTP_REFERER", "/")
)

