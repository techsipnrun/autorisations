import logging
import os
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from autorisations.models.models_instruction import Dossier, EtapeDossier, EtatDossier, DossierAction, Action
from autorisations.models.models_utilisateurs import Instructeur
from DS.call_DS import accepter_dossier_ds, get_msg_DS, passer_en_instruction_ds,classer_sans_suite_ds, refuser_dossier_ds, repasser_en_instruction_ds
from instruction.services.messagerie_service import envoyer_message_ds, prepare_temp_file, enregistrer_message_bdd
from instruction.utils import changer_etape_si_differente, changer_etat_si_different, enregistrer_action
from django.views.decorators.http import require_POST

logger = logging.getLogger('ORM_DJANGO')
loggerDS = logging.getLogger("API_DS")

@login_required
def passer_en_pre_instruction(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)

        changer_etape_si_differente(dossier,"En pré-instruction", request.user)

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

        # Appel API GraphQL
        result = classer_sans_suite_ds(dossier.id_ds, instructeur.id_ds, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Classement sans suite DS échoué : {result.get('message')}")
            return HttpResponseBadRequest("Erreur DS : classement sans suite échoué.")

        # Mettre à jour étape + état si besoin
        changer_etape_si_differente(dossier, "Non soumis à autorisation", request.user)
        changer_etat_si_different(dossier, "sans_suite", request.user)

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

        # Appel de l'API DS
        result = refuser_dossier_ds(dossier.id_ds, instructeur.id_ds, motivation)
        if not result.get("success"):
            logger.error(f"[DOSSIER {dossier.numero}] Echec de refus du dossier sur DS : {result.get('message')}")
            return HttpResponseBadRequest("Erreur Démarches Simplifiées : refus échoué.")

        # Mettre à jour étape + état si besoin
        changer_etape_si_differente(dossier, "Refusé", request.user)
        changer_etat_si_different(dossier, "refuse", request.user)

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


    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def envoyer_pour_validation_avant_demande_avis(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        # Changer Etape
        changer_etape_si_differente(dossier, "À valider avant demande d'avis", request.user)

        # Dossier Action
        enregistrer_action(dossier, instructeur, "Validé avant demande d'avis")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def envoyer_pour_validation_avant_signature(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer Etape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "À valider avant signature", request.user)

        # Dossier Action
        # instructeur = Instructeur.objects.filter(email=request.user.email).first()
        # enregistrer_action(dossier, instructeur, "Validé avant signature")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def avis_envoye(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En attente réponse d'avis", request.user)

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def valider_le_modele_de_demande_d_avis_et_le_projet_d_acte(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Avis à envoyer", request.user)

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

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def envoyer_pour_relecture_qualite(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En relecture qualité",request.user)

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Relecture qualité")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def envoyer_les_modifications_pour_validation(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "À valider avant signature", request.user)

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


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def acte_pret_a_etre_envoye(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Acte à envoyer", request.user)

         # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Acte signé")
        

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

        #Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Classé comme accepté")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
@require_POST
def envoyer_l_acte(request):
    dossier_id_ds = request.POST.get("dossierId")
    dossier_numero = request.POST.get("dossier_numero")
    motivation = request.POST.get("motivation", "Votre demande a été acceptée.")
    fichier = request.FILES.get("piece_jointe")

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not dossier_id_ds or not instructeur or not instructeur.id_ds:
        return HttpResponse(f"Echec de l'acceptation du dossier {dossier_numero} (dossier_id_ds = {dossier_id_ds}, motivation = {motivation}, fichier = {fichier})", status=401)

    try:
        result = accepter_dossier_ds(dossier_id_ds, instructeur.id_ds, motivation, fichier)
        if result["success"]:
            loggerDS.info(f"[DOSSIER {dossier_numero}] accepté avec succès par {instructeur.email}")
            # Mettre à jour l'étape et l'état en BDD
            dossier = Dossier.objects.filter(id_ds=dossier_id_ds).first()
            etape_raa = EtapeDossier.objects.filter(etape__iexact="À publier au RAA").first()
            etat_accepte = EtatDossier.objects.filter(nom__iexact="accepte").first()

            if dossier:

                if etape_raa and dossier.id_etape_dossier != etape_raa:
                    changer_etape_si_differente(dossier, "À publier au RAA", request.user)

                if etat_accepte and dossier.id_etat_dossier != etat_accepte:
                    changer_etat_si_different(dossier, 'accepte', request.user)
            
            # Dossier Action
            enregistrer_action(dossier, instructeur, "Acte envoyé")



        else:
            loggerDS.error(f"[DOSSIER {dossier_numero}] Erreur lors de l'acceptation du dossier sur DS par {instructeur.email} : {result['message']}")

    except Exception as e:
        logger.error(request, f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier sur DS par {instructeur.email}: {str(e)}")

    return redirect(request.META.get("HTTP_REFERER", "/"))

