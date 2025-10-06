import os
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
import datetime
from django.utils.timezone import localtime
from pathlib import Path

from autorisations.models.models_instruction import Dossier, Message
from autorisations.models.models_utilisateurs import DossierInstructeur, Instructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from autorisations.models.models_avis import Avis, AvisDocument, DossierAvis, Expert

from django.contrib import messages
import logging

from instruction.views.avis import enregistrer_document

logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  


@login_required(login_url='/login/')
def avis(request):
    # Expert connecté ?
    expert = Expert.objects.filter(id_instructeur__email=request.user.email).first()
    if not expert:
        expert = Expert.objects.filter(id_contact_externe__email=request.user.email).first()

    # Instructeur connecté ?
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    avis_list = []
    demandes_avis = []
    current_year = datetime.date.today().year
    selected_year = int(request.GET.get("annee", current_year))

    # nb_messages_non_lus_avis = Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert).count()

    ###################################
    # Avis à rendre/rendu (en tant qu’expert)
    ###################################
    avis_a_rendre = (
        Avis.objects.filter(id_expert=expert, favorable__isnull=True)
        .select_related("id_demarche", "id_dossier", "id_instructeur", "id_avis_nature")
        .order_by("-date_demande_avis")
    )

    # Avis archivés de l’année
    avis_rendus = (
        Avis.objects.filter(id_expert=expert, favorable__isnull=False, date_reponse_avis__year=selected_year)
        .select_related("id_demarche", "id_dossier", "id_instructeur", "id_avis_nature")
        .order_by("-date_reponse_avis")
    )

    # Années disponibles
    annees_disponibles_expert = Avis.objects.filter(
        id_expert=expert, date_reponse_avis__isnull=False
    ).dates("date_reponse_avis", "year", order="DESC")


    ##############################################################
    # Mes demandes d’avis en cours/traitées (en tant que demandeur)
    ##############################################################
    if instructeur:

        # Demandes en cours
        demandes_en_cours = Avis.objects.filter(id_instructeur=instructeur, favorable__isnull=True
                            ).select_related("id_demarche", "id_dossier", "id_expert", "id_avis_nature").order_by("-date_demande_avis")

        # Demandes traitées
        demandes_traitees = Avis.objects.filter(id_instructeur=instructeur,favorable__isnull=False,date_reponse_avis__year=selected_year,
                            ).select_related(
                                "id_demarche", "id_dossier", "id_expert", "id_avis_nature"
                            ).order_by("-date_reponse_avis")

        # Années disponibles
        annees_disponibles_demandeur = Avis.objects.filter(
            id_instructeur=instructeur, date_reponse_avis__isnull=False
        ).dates("date_reponse_avis", "year", order="DESC")

    
    ##############################################################
    # Le nombre de message non lu pour chaque avis
    ##############################################################
    # Messages non lus en tant qu'expert
    for liste_avis in [avis_a_rendre, avis_rendus]:
        for a in liste_avis:
           
            a.nb_messages_non_lus = Message.objects.filter(id_avis=a, lu=False).exclude(email_emetteur=request.user.email).count()

    # Messages non lus en tant que demandeur

    #  expert = Expert.objects.filter(id_instructeur__email=request.user.email).first()
    # if not expert:
    #     expert = Expert.objects.filter(id_contact_externe__email=request.user.email).first()

    for liste_avis in [demandes_en_cours, demandes_traitees]:
        for a in liste_avis:
            if a.id_expert.est_interne :
                email_expert = a.id_expert.id_instructeur.email
            else :
                email_expert = a.id_expert.id_contact_externe.email
            a.nb_messages_non_lus = Message.objects.filter(id_avis=a, lu=False, email_emetteur=email_expert).count()


    return render(
        request,
        "instruction/avis.html",
        {
            "annee_selectionnee": selected_year,
            # Expert
            "avis_a_rendre": avis_a_rendre,
            "avis_rendus": avis_rendus,
            "annees_disponibles_expert": annees_disponibles_expert,
            # Demandeur
            "demandes_en_cours": demandes_en_cours,
            "demandes_traitees": demandes_traitees,
            "annees_disponibles_demandeur": annees_disponibles_demandeur,
        },
    )


@login_required
def avis_expert(request, avis_id):

    email_user = request.user.email
    avis = get_object_or_404(Avis, id=avis_id)
    instructeur = Instructeur.objects.filter(email=email_user).first()

    est_un_instructeur = False
    est_demandeur = False
    est_expert = False

    ##############################################################
    # AvisDossier
    ##############################################################
    # Tous les dossiers liés à cet avis
    dossiers_lies = Dossier.objects.filter(
        dossieravis__id_avis=avis
    ).distinct()

    # Tous les instructeurs associés à ces dossiers
    instructeurs_dossiers = Instructeur.objects.filter(
        dossierinstructeur__id_dossier__in=dossiers_lies
    ).distinct()

    # Ajouter un champ virtuel resume_pdf_titre à chaque dossier
    for dossier in dossiers_lies:
        dossier.resume_pdf_titre = f"dossier-{dossier.numero}.pdf"

    ##############################################################
    # Identification Demandeur et Expert
    ##############################################################
    # Est-ce le demandeur ?
    if avis.id_instructeur.email == email_user :
        est_demandeur = True
    elif instructeur and instructeurs_dossiers.filter(id=instructeur.id).exists():
        est_demandeur = True

    # Est-ce un instructeur ?
    elif instructeur :
        est_un_instructeur = True

    # Est-ce l'expert ?
    est_expert = None
    if avis.id_expert.est_interne :
        email_expert = avis.id_expert.id_instructeur.email
        if avis.id_expert.id_instructeur.email == email_user :
            est_expert = True      
    else :
        email_expert = avis.id_expert.id_contact_externe.email
        if avis.id_expert.id_contact_externe.email == email_user :
            est_expert = True

    ##############################################################
    # Messages
    ##############################################################
    # Messages non lus envoyés par l'expert
    messages_de_expert_non_lus = (Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert))
    ids_msg_de_expert_non_lus = list(messages_de_expert_non_lus.values_list("id", flat=True))

    # Messages non lus envoyés par demandeur
    messages_de_demandeur_non_lus = (Message.objects.filter(id_avis=avis, lu=False).exclude(email_emetteur=email_expert))
    ids_msg_de_demandeur_non_lus = list(messages_de_demandeur_non_lus.values_list("id", flat=True))

    # Affichage messages
    raw_messages = Message.objects.filter(id_avis=avis).order_by("date_envoi")
    messages_fmt = []

    # Mise à jour des messages non lus --> lus
    if est_expert :
        nb_msg_de_demandeur_non_lus = messages_de_demandeur_non_lus.update(lu=True)
        if nb_msg_de_demandeur_non_lus > 0:
            logger.info(f"[AVIS {avis.id}] {nb_msg_de_demandeur_non_lus} message(s) non lus ont été marqués comme lus par {request.user}.")

    if est_demandeur:
        nb_msg_de_expert_non_lus = messages_de_expert_non_lus.update(lu=True)
        if nb_msg_de_expert_non_lus > 0:
            logger.info(f"[AVIS {avis.id}] {nb_msg_de_expert_non_lus} message(s) non lus ont été marqués comme lus par {request.user}.")
    
    for msg in raw_messages:
        emetteur = msg.email_emetteur.lower().strip()
        nouv_mess = 'non'
        # VISION DEMANDEUR
        if est_demandeur:
            if ids_msg_de_expert_non_lus != []:
                if msg.id in ids_msg_de_expert_non_lus :
                    nouv_mess = 'oui'
            # left = Message expert, right = Message émis par demandeur
            align = "right" if emetteur != email_expert.lower().strip() else "left"
            date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # VISION EXPERT
        if est_expert:
            if ids_msg_de_demandeur_non_lus != []:
                if msg.id in ids_msg_de_demandeur_non_lus :
                    nouv_mess = 'oui'
            # left = Message émis par demandeur, right = Message expert
            align = "left" if emetteur != email_expert.lower().strip() else "right"
            date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_title = pj_emplacement = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()
            if message_doc and message_doc.id_document:   
                pj_title, pj_emplacement = message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess})

    ##############################################################
    # Documents
    ##############################################################
    # Avis Document
    avis_documents = (
        AvisDocument.objects.filter(id_avis=avis)
        .select_related("id_document", "id_document__id_nature")
        .exclude(id_document__id_nature__nature="Avis instance") #pour ne pas prendre l'avis signé
    )

    # Liste avis_documents
    liste_avis_documents = [
        {
            "titre": ad.id_document.titre,
            "emplacement": ad.id_document.emplacement,
            "format": ad.id_document.id_format.format,
            "nature": ad.id_document.id_nature.nature,
        }
        for ad in avis_documents
    ]

    # Avis signés
    avis_signes = (
        Document.objects.filter(
            id__in=AvisDocument.objects.filter(
                id_avis=avis,
                id_document__id_nature__nature="Avis instance"
            ).values_list("id_document", flat=True)
        )
    )


    return render(request, 'instruction/avis_expert.html', {
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "avis": avis,
        "avis_documents": avis_documents,
        "liste_avis_documents": liste_avis_documents,
        "avis_signes": avis_signes,
        "messages_avis": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "est_expert": est_expert,
        "est_demandeur": est_demandeur,
        "est_un_instructeur": est_un_instructeur,
        "dossiers_lies": dossiers_lies,
    })



@login_required
@require_POST
def donner_son_avis(request, avis_id):

    avis = get_object_or_404(Avis, id=avis_id)

    favorable = request.POST.get("favorable") == "true"
    pj_avis_signe = request.FILES.get("avis_signe")


    # Mise à jour de l'avis
    avis.favorable = favorable
    avis.date_reponse_avis = timezone.now()

    # Enregistrer l'avis signé si présent
    if pj_avis_signe:
       
        extension = Path(pj_avis_signe.name).suffix.lower()
        if extension != ".pdf" :
            messages.error(request, f"❌ L'avis signé doit être au format PDF --> Type de fichier non autorisé : {extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        nature_annexe_avis = DocumentNature.objects.filter(nature__iexact="Annexe avis").first()
        if not nature_annexe_avis:
            messages.error(request, "⚠️ La nature 'Annexe avis' n'existe pas en base, reclassification impossible. Contactez l'administrateur.")

        # Sauvegarder le fichier physiquement  
        emplacement = avis.emplacement
        if not emplacement :
            messages.error(request, f"❌ L'avis n'a aucun emplacement de renseigné")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}"
        os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)

        # --- Vérifie si un avis signé existait déjà ---
        avis_signe_existant = AvisDocument.objects.filter(
            id_avis=avis,
            id_document__id_nature__nature__iexact="Avis instance"
        ).select_related("id_document").first()

        # Les vérifs sur la Nature et le Format du doc sont faits dans la fonction ci-dessous
        doc_avis_signe = enregistrer_document(
                fichier=pj_avis_signe,
                nature_str="Avis instance",
                description=f"Avis signé pour la Demande d'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
                annexe=False
            )

        if doc_avis_signe :
            # Créer AvisDocument
            AvisDocument.objects.create(
                id_avis=avis,
                id_document=doc_avis_signe,
            )

        else :
            # On revient sur la page pour afficher les messages d'erreurs
            return redirect(request.META.get("HTTP_REFERER", "/"))
        

    # Message automatique Acceptation/Refus + Avis signé
    if favorable and doc_avis_signe :
        try:
            if avis_signe_existant :
                ancien_doc = avis_signe_existant.id_document
                ancien_doc.id_nature = nature_annexe_avis
                ancien_doc.save()
                logger.info(f"[AVIS {avis.id}] Ancien avis signé reclassé en 'Annexe avis' par {request.user}.")
                msg_reponse_expert = "Modification de l'avis signé par l'expert, vous trouverez ci-joint le nouvel avis signé"
            else :
                msg_reponse_expert = "La demande d'avis a reçu une réponse favorable, vous trouverez ci-joint l'avis signé."
            

            msg = Message.objects.create(
                body=msg_reponse_expert,
                date_envoi=timezone.now(),
                piece_jointe=True,
                email_emetteur=request.user.email,
                id_avis=avis,
                lu=False,
            )

            # Joindre l'avis signé au message
            MessageDocument.objects.create(
                id_message=msg,
                id_document=doc_avis_signe
            )

        except Exception as e:
            logger.warning(f"[AVIS {avis.id}] : Echec lors de l'envoi du message automatique (Acceptation/Refus de l'expert) : {e}")

    avis.save()
    return redirect("avis_expert", avis_id=avis.id)




@require_POST
def remplacer_avis_signe(request):
    avis_id = request.POST.get("avis_id")
    document_id = request.POST.get("document_id")
    fichier = request.FILES.get("fichier")

    avis_doc = get_object_or_404(AvisDocument, id_avis=avis_id, id_document=document_id)
    avis = avis_doc.id_avis

    try:
        # L'ancien document devient Annexe instance
        nature_annexe = DocumentNature.objects.get(nature="Annexe avis")
        ancien_doc = avis_doc.id_document
        ancien_doc.id_nature = nature_annexe
        ancien_doc.save()

        # Sauvegarde du nouvel avis signé 
        doc_avis_signe = enregistrer_document(
                fichier=fichier,
                nature_str="Avis instance",
                description=f"Remplacement de l'avis signé pour la Demande d'avis {avis_id}",
                request=request,
                emplacement_avis = avis.emplacement,
                annexe=False
            )
        
        if doc_avis_signe :
            # Créer AvisDocument
            AvisDocument.objects.get_or_create(
                id_avis=avis,
                id_document=doc_avis_signe,
            )
            logger.info(f"[AVIS {avis.id}] : Avis signé remplacé avec succès par l'expert {request.user}")
            messages.success(request, "✅ Avis signé remplacé avec succès.")
        else :
            # On revient sur la page pour afficher les messages d'erreurs
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
    except Exception as e:
        messages.error(request, f"❌ Erreur : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))
