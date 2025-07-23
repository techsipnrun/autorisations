import logging
import os
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from autorisations.models.models_instruction import Dossier, EtapeDossier, EtatDossier, DossierAction, Action
from autorisations.models.models_utilisateurs import GroupeinstructeurInstructeur, Instructeur, DossierInstructeur
from DS.call_DS import accepter_dossier_ds, get_msg_DS, passer_en_instruction_ds,classer_sans_suite_ds, refuser_dossier_ds, repasser_en_instruction_ds
from autorisations import settings
from instruction.services.messagerie_service import envoyer_message_ds, prepare_temp_file, enregistrer_message_bdd
from instruction.utils import changer_etape_si_differente, changer_etat_si_different, enregistrer_action
from django.views.decorators.http import require_POST
from django.utils import timezone
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DocumentStatut, DossierDocument
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from docx2pdf import convert
from pathlib import Path
import shutil
from django.utils.text import slugify
import uuid
import win32com.client
import pythoncom
from instruction.utils import convertir_docx_en_pdf_libreoffice


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

         # Si l'étape est 'En pré-instruction' et l'état 'en_construction' --> passer l'état à en_instruction
        if dossier.id_etat_dossier.nom == 'en_construction' and dossier.id_etape_dossier.etape == 'En pré-instruction' :
            passer_en_instruction_ds(dossier.id_ds, instructeur.id_ds)

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

        # Maj Dossier en BDD
        # dossier.date_fin_instruction = timezone.now()
        # dossier.save()

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
        enregistrer_action(dossier, instructeur, "Envoyé pour validation")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



# @login_required
# def envoyer_pour_validation_avant_signature(request):
#     if request.method == "POST":
#         dossier_id_ds = request.POST.get("dossierId")
#         if not dossier_id_ds:
#             return HttpResponseBadRequest("ID dossier manquant.")

#         # Changer Etape
#         dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
#         changer_etape_si_differente(dossier, "À valider avant signature", request.user)

#         # Dossier Action
#         instructeur = Instructeur.objects.filter(email=request.user.email).first()
#         enregistrer_action(dossier, instructeur, "Envoyé pour validation")


#         return redirect(request.META.get("HTTP_REFERER", "/"))

#     return HttpResponseBadRequest("Méthode non autorisée.")

@login_required
def envoyer_pour_validation_avant_signature(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        nature = request.POST.get("nature_document")
        fichier = request.FILES.get("piece_jointe")

        # Vérification que l'extension du fil est .doc, .docx, .pdf, .odt
        extension = Path(fichier.name).suffix.lower()
        if extension not in {".pdf", ".doc", ".docx", ".odt"} :
            messages.error(request, f"❌ Le fichier joint doit etre .pdf ou .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        if not dossier_id_ds or not nature or not fichier:
            raise Http404(f"Données manquantes ou invalides : id_dossier_ds = {dossier_id_ds}, nature_doc = {nature}, fichier = {fichier.name}")

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
            # Enregistrement physique
            with open(filepath, 'wb+') as destination:
                for chunk in fichier.chunks():
                    destination.write(chunk)

            # Récupérer la nature, le format et le statut
            nature_obj = get_object_or_404(DocumentNature, nature=nature)
            extension = os.path.splitext(fichier.name)[1].lower().lstrip('.')
            format_obj = get_object_or_404(DocumentFormat, format=extension)
            statut_obj = get_object_or_404(DocumentStatut, statut="À valider")

            # Enregistrer en BDD
            # Document.objects.create(
            #     id_format=format_obj,
            #     id_nature=nature_obj,
            #     id_statut=statut_obj,
            #     emplacement=dossier_path,
            #     titre=fichier.name,
            #     description=f"{nature_obj.nature} du dossier {dossier.numero}",
            # )

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

        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseRedirect("/")



@login_required
def avis_envoye(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
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
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer Etape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
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
        enregistrer_action(dossier, instructeur, "Envoyé pour relecture qualité")


        return redirect(request.META.get("HTTP_REFERER", "/"))

    return HttpResponseBadRequest("Méthode non autorisée.")



@login_required
def valider_et_envoyer_pour_relecture_qualite(request):
    if request.method == "POST":
        dossier_id_ds = request.POST.get("dossierId")
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

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
            if doc.id_statut and doc.id_statut.statut.lower() == "à valider":
                
                doc.id_statut = statut_relire
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → À relire.")


                '''
                # Vérifie que le document est en .docx
                if doc.id_format.format.lower() == "docx" or doc.id_format.format.lower() == "odt":
                    try:

                        # Chemin du fichier source
                        root_folder = os.getenv("ROOT_FOLDER")
                        emplacement_doc = os.path.join(root_folder, doc.emplacement)
                        word_full_path = os.path.join(emplacement_doc, doc.titre)

                        # Détermine les noms de fichiers
                        nom_sans_ext = Path(doc.titre).stem
                        ext = Path(doc.titre).suffix
                        nom_slug = slugify(nom_sans_ext)

                        if nom_sans_ext != nom_slug:
                            # Renommer le fichier dans le dossier
                            nouveau_nom = f"{nom_slug}{ext}"
                            nouveau_chemin = os.path.join(emplacement_doc, nouveau_nom)

                            os.rename(word_full_path, nouveau_chemin)
                            # logger.info(f"[DOSSIER {dossier.numero}] Fichier renommé → {nouveau_nom}")

                            # Mettre à jour le champ en base
                            doc.titre = nouveau_nom
                            doc.save()

                            # Met à jour le chemin de travail
                            word_full_path = nouveau_chemin


                        titre_pdf = f"{nom_slug}.pdf"
                        emplacement_pdf = os.path.join(emplacement_doc, titre_pdf)

                        # unique_suffix = uuid.uuid4().hex[:6]
                        # temp_docx_path = os.path.join(emplacement_doc, f"{slugify(nom_sans_ext)}_{unique_suffix}.docx")

                       # Supprimer s'il existe déjà
                        # if os.path.exists(temp_docx_path):
                        #     os.remove(temp_docx_path)

                        # shutil.copy(word_full_path, temp_docx_path)

                        logger.info(f"Conversion DOCX vers PDF : {doc.titre}")
                        
                        # Suppression du PDF s'il existe déjà
                        if os.path.exists(emplacement_pdf):
                            os.remove(emplacement_pdf)


                        # Conversion Libre Office -> PDF
                        convertir_docx_en_pdf_libreoffice(word_full_path, emplacement_doc, dossier.numero, logger)



                        # Supprimer le .docx temporaire une fois le PDF généré
                        # os.remove(temp_docx_path)

                        # Enregistrer le nouveau document PDF en base
                        format_pdf = DocumentFormat.objects.filter(format__iexact="pdf").first()
                        if not format_pdf:
                            logger.warning(f"[DOSSIER {dossier.numero}] Erreur lors de la conversion Word → PDF : Format PDF introuvable en base.")
                        else:
                            doc_pdf = Document.objects.create(
                                id_format=format_pdf,
                                id_nature=doc.id_nature,
                                id_statut=doc.id_statut,
                                titre=titre_pdf,
                                emplacement=doc.emplacement,
                                description=f"PDF généré automatiquement à partir de {doc.titre}"
                            )
                            DossierDocument.objects.create(id_dossier=dossier, id_document=doc_pdf)
                            logger.info(f"[DOSSIER {dossier.numero}] PDF '{titre_pdf}' généré et ajouté au dossier.")

                    except Exception as e:
                        return redirect(request.META.get("HTTP_REFERER", "/"))
                        # logger.error(f"[DOSSIER {dossier.numero}] Erreur de conversion Word → PDF pour '{doc.titre}' : {e}")
                '''

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
        if not dossier_id_ds:
            return HttpResponseBadRequest("ID dossier manquant.")

        # Changer l'étape
        dossier = get_object_or_404(Dossier, id_ds=dossier_id_ds)
        changer_etape_si_differente(dossier, "Acte à envoyer", request.user)

         # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        enregistrer_action(dossier, instructeur, "Acte signé")

        # Récupérer l'objet statut "À envoyer"
        statut_a_envoyer = DocumentStatut.objects.filter(statut__iexact="à envoyer").first()

        # Par sécurité
        if not statut_a_envoyer:
            logger.error("Statut 'À envoyer' introuvable en base.")
            messages.error("Statut 'À envoyer' introuvable en base.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        # Récupération des documents du dossier
        documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

        # Mise à jour Doc "À signer" --> "À envoyer"
        for lien in documents_du_dossier:
            doc = lien.id_document
            if doc.id_statut and doc.id_statut.statut.lower() == "à signer":
                doc.id_statut = statut_a_envoyer
                doc.save()
                logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → À envoyer.")
        

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
    # fichier = request.FILES.get("piece_jointe")
    document_id = request.POST.get("document_id_existant")
    nature_document = request.POST.get("nature_document")

    # confirm_ecrasement = request.POST.get("confirm_ecrasement") == "true"



    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not dossier_id_ds or not instructeur or not instructeur.id_ds:
        return HttpResponse(f"Echec de l'acceptation du dossier {dossier_numero} (dossier_id_ds = {dossier_id_ds}, motivation = {motivation}, fichier = {fichier})", status=401)

    try:

        dossier = Dossier.objects.filter(id_ds=dossier_id_ds).first()
        # Construire l’emplacement de stockage
        now = timezone.now()
        dossier_path = f"{dossier.emplacement}"

        document = Document.objects.get(id=document_id)

        emplacement_doc = os.path.join(dossier_path, 'Actes/', f"{document.titre}")
        full_path = os.path.join(os.environ.get("ROOT_FOLDER"), emplacement_doc)

        # Chercher si un document existe déjà avec même emplacement + titre
        doc_existant = Document.objects.filter(emplacement=os.path.join(dossier_path, 'Actes/'), titre=document.titre).first()
        
        # Si document déjà existant ET pas de confirmation explicite
        # if doc_existant and not confirm_ecrasement:
        #     messages.warning(request, f"Un document nommé « {document.titre} » existe déjà dans le dossier Actes. Vous devez confirmer son écrasement dans le POP UP le cas échéant.")
        #     return redirect(request.META.get("HTTP_REFERER", "/"))

        chemin = os.path.join(os.getenv("ROOT_FOLDER"), document.emplacement, document.titre)
        # print(chemin)
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

                    # Créer le Document
                    # doc = Document.objects.create(
                    #     id_format=format_obj,
                    #     id_nature=nature_obj,
                    #     url_ds=None,
                    #     emplacement=os.path.join(dossier_path, 'Actes/'),
                    #     description=f"{nature_document} pour le dossier {dossier.numero}",
                    #     numero=None,
                    #     titre=(fichier.name)
                    # )

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

                    # Lier au dossier
                    # DossierDocument.objects.create(id_dossier=dossier, id_document=doc)

                    # logger.info(f"[DOSSIER {dossier_numero}] {nature_document} créé(e) et lié(e) au dossier (id : {doc.id})")
            

            

            # Récupération des documents du dossier
            # documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

            # Mise à jour Doc "À envoyer" --> "Envoyé"
            # for lien in documents_du_dossier:
            #     doc = lien.id_document
            #     if doc.id_statut and doc.id_statut.statut.lower() == "à envoyer":
            #         doc.id_statut = statut_envoye
            #         doc.save()
            #         logger.info(f"[DOSSIER {dossier.numero}] Statut du document '{doc.titre}' mis à jour → Envoyé.")
        

        else:
            loggerDS.error(f"[DOSSIER {dossier_numero}] Erreur lors de l'acceptation du dossier sur DS par {instructeur.email} : {result['message']}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier_numero}] Erreur lors de l’acceptation du dossier sur DS par {instructeur.email}: {str(e)}")

    return redirect(request.META.get("HTTP_REFERER", "/")
)

