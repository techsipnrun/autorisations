import logging
import os
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from autorisations.models.models_instruction import Dossier, EtapeDossier, EtatDossier
from autorisations.models.models_utilisateurs import Instructeur
from DS.call_DS import get_msg_DS, passer_en_instruction_ds,classer_sans_suite_ds, refuser_dossier_ds, repasser_en_instruction_ds
from instruction.services.messagerie_service import envoyer_message_ds, prepare_temp_file, enregistrer_message_bdd
from instruction.utils import changer_etape_si_differente

logger = logging.getLogger('ORM_DJANGO')

@login_required
def passer_en_pre_instruction(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)

        nouvelle_etape = get_object_or_404(EtapeDossier, etape="En pré-instruction")
        dossier.id_etape_dossier = nouvelle_etape
        dossier.save()

        logger.info(f"Étape du dossier {dossier.numero} mise à jour → En pré-instruction")

    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@login_required
def demander_des_complements(request):
    if request.method == "POST":
        numero = request.POST.get("numero_dossier")  # à ajouter dans le form
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
                etape_attente = EtapeDossier.objects.filter(etape="En attente de compléments").first()
                etat_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()

                if etape_attente:
                    dossier.id_etape_dossier = etape_attente

                if etat_construction and dossier.id_etat_dossier.nom.lower() != "en_construction":
                    dossier.id_etat_dossier = etat_construction

                dossier.save()
                logger.info(f"[Demande de compléments] Dossier {dossier.numero} : étape='En attente de compléments', état='{dossier.id_etat_dossier.nom}'")


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
            logger.error("Instructeur introuvable ou non connecté à DS.")
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à Démarches Simplifiées.")

        # Appel API GraphQL
        result = classer_sans_suite_ds(dossier.id_ds, instructeur.id_ds, motivation)
        if not result.get("success"):
            logger.error(f"Classement sans suite DS échoué : {result.get('message')}")
            return HttpResponseBadRequest("Erreur DS : classement sans suite échoué.")

        # Étape locale : changer l'état et l'étape
        etat = EtatDossier.objects.filter(nom__iexact="sans_suite").first()
        if etat:
            dossier.id_etat_dossier = etat

        etape = EtapeDossier.objects.filter(etape__iexact="Non soumis à autorisation").first()
        if etape:
            dossier.id_etape_dossier = etape

        dossier.save()
        logger.info(f"[LOCAL] Dossier {dossier.numero} mis à jour : état='sans_suite', étape='Non soumis à autorisation'")

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
            logger.error("Instructeur introuvable ou non connecté à DS.")
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à Démarches Simplifiées.")

        # Appel de l'API DS
        result = refuser_dossier_ds(dossier.id_ds, instructeur.id_ds, motivation)
        if not result.get("success"):
            logger.error(f"[DS] Refus échoué pour dossier {dossier.numero} : {result.get('message')}")
            return HttpResponseBadRequest("Erreur Démarches Simplifiées : refus échoué.")

        # Mise à jour de l'état et de l'étape
        etat = EtatDossier.objects.filter(nom__iexact="refuse").first()
        if etat:
            dossier.id_etat_dossier = etat

        etape = EtapeDossier.objects.filter(etape__iexact="Refusé").first()
        if etape:
            dossier.id_etape_dossier = etape

        dossier.save()
        logger.info(f"[REFUS] Dossier {dossier.numero} → état='refuse', étape='Refusé'")

        return redirect(reverse('instruction_dossier', kwargs={'num_dossier': dossier.numero}))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def passer_en_instruction(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        if not instructeur or not instructeur.id_ds:
            logger.error("Instructeur introuvable ou non connecté à DS.")
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à Démarches Simplifiées.")


        # Appel API Démarches Simplifiées
        result = passer_en_instruction_ds(dossier.id_ds, instructeur.id_ds)
        if not result.get("success"):
            logger.error(f"[DS] Passage en instruction échoué côté DS pour {dossier.numero} : {result.get('message')}")


        # Changer l'étape
        nouvelle_etape = EtapeDossier.objects.filter(etape="En instruction").first()
        if nouvelle_etape:
            dossier.id_etape_dossier = nouvelle_etape

        # Si état actuel = en_construction, on le passe à en_instruction
        if dossier.id_etat_dossier.nom.lower() == "en_construction":
            nouvel_etat = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
            if nouvel_etat:
                dossier.id_etat_dossier = nouvel_etat
        
        dossier.save()
        logger.info(f"Dossier {dossier.numero} → étape : En instruction / état : {dossier.id_etat_dossier.nom}")

    return redirect(request.META.get("HTTP_REFERER", "/"))




@login_required
def envoyer_pour_validation_avant_demande_avis(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "À valider avant demande d'avis")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def envoyer_pour_validation_avant_signature(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "À valider avant signature")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def avis_envoye(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En attente réponse d'avis")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def valider_le_modele_de_demande_d_avis_et_le_projet_d_acte(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Avis à envoyer")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def repasser_en_instruction(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        instructeur = Instructeur.objects.filter(email=request.user.email).first()

        if not instructeur or not instructeur.id_ds:
            return HttpResponseBadRequest("Instructeur introuvable ou non connecté à DS.")

        # Appel GraphQL uniquement si l'état n'est pas déjà 'en_instruction'
        if dossier.id_etat_dossier.nom.lower() != "en_instruction":
            result = repasser_en_instruction_ds(dossier.id_ds, instructeur.id_ds)
            if not result.get("success"):
                logger.error(f"[DS] Échec du repassage en instruction du dossier {dossier.numero} : {result.get('message')}")
                return HttpResponseBadRequest("Erreur côté DS lors du repassage en instruction.")

        # Mise à jour État
        nouvel_etat = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
        if nouvel_etat and dossier.id_etat_dossier != nouvel_etat:
            dossier.id_etat_dossier = nouvel_etat

        # Mise à jour Étape
        nouvelle_etape = EtapeDossier.objects.filter(etape__iexact="En instruction").first()
        if nouvelle_etape and dossier.id_etape_dossier != nouvelle_etape:
            dossier.id_etape_dossier = nouvelle_etape

        dossier.save()
        logger.info(f"[REPASSAGE] Dossier {dossier.numero} → état='en_instruction', étape='En instruction'")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def envoyer_pour_relecture_qualite(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En relecture qualité")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def envoyer_les_modifications_pour_validation(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "À valider avant signature")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def envoyer_pour_signature(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "En attente de signature")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def envoyer_l_acte(request):
    print("On est dans la vue Envoyer l'acte")
    # GraphQL : Accepter un dossier et y joindre un justificatif (une PJ)
    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
def acte_pret_a_etre_envoye(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Acte à envoyer")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")


@login_required
def classer_le_dossier_comme_accepte(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Accepté")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")

