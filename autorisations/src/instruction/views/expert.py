import os
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
import datetime
from django.utils.timezone import localtime
from pathlib import Path

from autorisations.models.models_instruction import Dossier, Message
from autorisations.models.models_utilisateurs import ContactExterne, DossierInstructeur, EmailOutbox, Instructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from autorisations.models.models_avis import Avis, AvisDocument, DossierAvis, Expert

from django.contrib import messages
import logging

from autorisations.utils.nas_fonctions import creer_dossier_sur_nas
from instruction.utils.avis_utils import get_email_expert, get_expert_from_user
from instruction.utils.dossier_utils import redirect_error
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from instruction.utils_instru import enregistrer_document

logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  


@login_required(login_url='/login/')
def avis(request):

    # --- Profils associés au user ---
    expert = get_expert_from_user(request.user)
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not expert and not instructeur :
        messages.error(request, f"❌ Vous n'avez ni un profil 'Expert.e', ni un profil 'Instructeur.rice' : Contactez l'administrateur.rice si besoin.")
        return render(request, "instruction/avis.html")
    
    # --- Année sélectionnée ---
    current_year = datetime.date.today().year
    selected_year = int(request.GET.get("annee", current_year))


    # =============================
    # ========== EXPERT ===========
    # =============================
    avis_a_rendre = []
    avis_rendus = []
    annees_disponibles_expert = []

    if expert :
        # Avis à rendre
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


        # Messages non lus en tant qu'expert
        for liste_avis in [avis_a_rendre, avis_rendus]:
            for a in liste_avis:
                a.nb_messages_non_lus = Message.objects.filter(id_avis=a, lu=False).exclude(email_emetteur=request.user.email).count()


    # ================================
    # ========== DEMANDEUR ===========
    # ================================
    demandes_en_cours = []
    demandes_traitees = []
    demandes_avis_a_publier_au_RAA = []
    annees_disponibles_demandeur = []

    if instructeur:
        # Demandes en cours
        demandes_en_cours = Avis.objects.filter(id_instructeur=instructeur, favorable__isnull=True
                            ).select_related("id_demarche", "id_dossier", "id_expert", "id_avis_nature").order_by("-date_demande_avis")

        # Demandes traitées
        demandes_traitees = Avis.objects.filter(id_instructeur=instructeur,favorable__isnull=False,date_reponse_avis__year=selected_year,
                            ).select_related(
                                "id_demarche", "id_dossier", "id_expert", "id_avis_nature"
                            ).order_by("-date_reponse_avis")
        
        # Demandes à publier au RAA
        demandes_avis_a_publier_au_RAA = Avis.objects.filter(favorable=True
                                        ).exclude(publie_au_raa=True
                                        ).filter(avisdocument__id_document__id_nature__nature__iexact="Avis instance"
                                        ).distinct()
        """
        ############################
        # On filtrera sur expert = CS
        ############################
        """

        # Années disponibles
        annees_disponibles_demandeur = Avis.objects.filter(
            id_instructeur=instructeur, date_reponse_avis__isnull=False
        ).dates("date_reponse_avis", "year", order="DESC")


        # Messages non lus en tant que demandeur
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
            "demandes_avis_a_publier_au_RAA": demandes_avis_a_publier_au_RAA,
            "annees_disponibles_demandeur": annees_disponibles_demandeur,
        },
    )



@login_required
def avis_expert(request, avis_id):

    email_user = request.user.email

    avis = Avis.objects.filter(id=avis_id).select_related("id_instructeur","id_expert","id_demarche",).first()
    if not avis:
        logger.error(f"[AVIS EXPERT] Avis {avis_id} introuvable — User {request.user}")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")

    instructeur = Instructeur.objects.filter(email=email_user).first()

    est_un_instructeur = bool(instructeur)
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
    if avis.id_instructeur and avis.id_instructeur.email:
        if avis.id_instructeur.email == email_user:
            est_demandeur = True
  
    if not est_demandeur and instructeur:
        # Instructeur associé à au moins un dossier lié à cet avis
        if instructeurs_dossiers.filter(id=instructeur.id).exists():
            est_demandeur = True

    # Est-ce l'expert ?
    email_expert = get_email_expert(avis, None)
    if not email_expert :
        logger.error(f"[AVIS {avis.id}] L'expert {avis.id_expert} n'a pas d'email en BDD.")


    if email_expert and email_user == email_expert:
        est_expert = True
        est_demandeur = False


    ##############################################################
    # Messages
    ##############################################################
    # Messages non lus envoyés par l'expert
    if email_expert:
        messages_de_expert_non_lus = (Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert))
    else:
        messages_de_expert_non_lus = Message.objects.none()

    ids_msg_de_expert_non_lus = list(messages_de_expert_non_lus.values_list("id", flat=True))

    # Messages non lus envoyés par demandeur
    if email_expert:
        messages_de_demandeur_non_lus = (Message.objects.filter(id_avis=avis, lu=False).exclude(email_emetteur=email_expert))
    else:
        # Si on ne connaît pas l'email de l'expert, on considère tous les non-lus comme "demandeur"
        messages_de_demandeur_non_lus = Message.objects.filter(id_avis=avis, lu=False)

    ids_msg_de_demandeur_non_lus = list(messages_de_demandeur_non_lus.values_list("id", flat=True))


    # Mise à jour des messages non lus --> lus
    if est_expert :
        nb_msg_de_demandeur_non_lus = messages_de_demandeur_non_lus.update(lu=True)
        if nb_msg_de_demandeur_non_lus > 0:
            logger.info(f"[AVIS {avis.id}] {nb_msg_de_demandeur_non_lus} message(s) non lus ont été marqués comme lus par {request.user}.")

    if est_demandeur:
        nb_msg_de_expert_non_lus = messages_de_expert_non_lus.update(lu=True)
        if nb_msg_de_expert_non_lus > 0:
            logger.info(f"[AVIS {avis.id}] {nb_msg_de_expert_non_lus} message(s) non lus ont été marqués comme lus par {request.user}.")
    

    # Récupération et formatage des messages
    raw_messages = Message.objects.filter(id_avis=avis).order_by("date_envoi")
    messages_fmt = []

    for msg in raw_messages:
        emetteur = msg.email_emetteur.lower().strip()
        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()

        nouv_mess = 'non'
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # VISION EXPERT
        if est_expert:
            if ids_msg_de_demandeur_non_lus != []:
                if msg.id in ids_msg_de_demandeur_non_lus :
                    nouv_mess = 'oui'
            # left = Message émis par demandeur, right = Message expert
            align = "left" if emetteur != email_expert.lower().strip() else "right"

        # VISION DEMANDEUR
        else :
            if ids_msg_de_expert_non_lus != []:
                if msg.id in ids_msg_de_expert_non_lus :
                    nouv_mess = 'oui'
            # left = Message expert, right = Message émis par demandeur
            align = "right" if emetteur != email_expert.lower().strip() else "left"
            

        # Recherche de la pièce jointe éventuelle liée au message
        pj_title = pj_emplacement = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()
            if message_doc and message_doc.id_document:   
                pj_title, pj_emplacement = message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess, "emetteur": instru if instru else contact})


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
        if ad.id_document
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
        "NAS_ROOT": os.getenv('NAS_ROOT'),
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





"""
#############################################
CLEAN A FINIR
#############################################
"""

@login_required
@require_POST
def donner_son_avis(request, avis_id):

    avis = Avis.objects.filter(id=avis_id).select_related("id_instructeur","id_expert","id_demarche",).first()
    if not avis:
        logger.error(f"[DONNER SON AVIS] Avis {avis_id} introuvable — User {request.user}")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")

    # favorable = request.POST.get("favorable") == "true"
    pj_avis_signe = request.FILES.get("avis_signe")
    reponse = request.POST.get("reponse_expert")



    # ============================
    #  MAJ AVIS (Favorable / Défavorable)
    # ============================
    try :
        avis.favorable = reponse != "Défavorable"
        avis.sous_reserve = (reponse == "Favorable sous réserve")
        avis.date_reponse_avis = timezone.now()
        avis.save()

    except Exception as e:
        logger.error(f"[AVIS {avis.id}] Erreur pour Donner son avis (User {request.user}) : Erreur lors de la mise à jour de l'Avis : {e}  ")
        return redirect_error(request, f"❌ Erreur lors de la mise à jour de l'Avis en base. Contactez le support.")



    # ===================================
    #  ENREGISTRER AVIS SIGNÉ (si présent)
    # ===================================
    doc_avis_signe = None
    avis_signe_existant = None

    if pj_avis_signe:

        # Vérification extension
        extension = Path(pj_avis_signe.name).suffix.lower()
        if extension != ".pdf" :
            return redirect_error(request, f"❌ L'avis signé doit être au format PDF --> Type de fichier non autorisé : {extension}")
        
        # Vérification nature
        nature_annexe_avis = DocumentNature.objects.filter(nature__iexact="Annexe avis").first()
        if not nature_annexe_avis:
            return redirect_error(request, "❌ La nature 'Annexe avis' n'existe pas en base. Contactez le support.")
          
        # Vérification de l’emplacement de l’avis
        emplacement = avis.emplacement
        if not emplacement :
            return redirect_error(request, f"❌ L'avis n'a aucun emplacement de renseigné")
        

        # Création du répertoire NAS si nécessaire
        try:
            chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}"
            creer_dossier_sur_nas(chemin_complet)
        except Exception as e:
            logger.error(f"[AVIS {avis.id}] Erreur pour Donner son avis (User {request.user}) : Erreur lors de la création du dossier '{chemin_complet}' : {e}")
            return redirect_error(request, f"❌ Erreur lors de la création du dossier '{chemin_complet}'. Contactez le support.")


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
        
        if not doc_avis_signe :
            logger.error(f"[AVIS {avis.id}] Erreur pour Donner son avis (User {request.user}) - Erreur lors de l'enregistrement ou de l'écriture de l'avis signé.")
            # On revient sur la page pour afficher les messages d'erreurs (spécifiés dans enregistrer_document)
            return redirect(request.META.get("HTTP_REFERER", "/"))

        try :
            AvisDocument.objects.get_or_create(id_avis=avis,id_document=doc_avis_signe)

        except Exception as e:
            logger.error(f"[AVIS {avis.id}] Erreur pour Donner son avis (User {request.user}) - Erreur lors de la création de l'AvisDocument : {e}")
            return redirect_error(request, "❌ Erreur lors de la liaision entre le document et l'avis. Contactez le support.")
        



    """
    #############################################
    FINIR DE CLEAN
    #############################################
    
    """

    # Message automatique Acceptation/Refus + Avis signé
    try:
        if (reponse == "Favorable" or reponse == "Favorable sous réserve") and doc_avis_signe :
            
                # Compte le nombre de documents "Avis instance" associés à cet avis
                nb_avis_instance = AvisDocument.objects.filter(
                    id_avis=avis,
                    id_document__id_nature__nature__iexact="Avis instance"
                ).count()

                if avis_signe_existant and nb_avis_instance > 1 :
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
                MessageDocument.objects.create(id_message=msg,id_document=doc_avis_signe)

        elif (reponse == "Défavorable") :
            msg_reponse_expert = "La demande d'avis a reçu une réponse défavorable."
            # Message automatique pour le refus
            msg = Message.objects.create(
                body=msg_reponse_expert,
                date_envoi=timezone.now(),
                piece_jointe=False,
                email_emetteur=request.user.email,
                id_avis=avis,
                lu=False,
            )




    except Exception as e:
        logger.warning(f"[AVIS {avis.id}] : Echec lors de l'envoi du message automatique (Acceptation/Refus de l'expert) : {e}")

    avis.save()

    ####################################
    # NOTIFICATION PAR MAIL AU DEMANDEUR
    ####################################

    # emails_norm = [avis.id_instructeur.email]
    emails_norm = ["louis.calu@reunion-parcnational.fr"]

    # if (DossierAvis.objects.filter(id_avis=avis).exists() or avis.id_dossier):
    sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : {avis.id_expert} a rendu son avis"
    
    context = {
            "avis_numero": avis.id,
            "expert": str(avis.id_expert),
            "demarche_type": avis.id_demarche.type,
            "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
        }

    template_name = "avis_rendu" 
    dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
    outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

    if outbox :
        ok, err = envoi_mail(outbox.id)
    else :
        logger.error(f"[AVIS {avis.id}] Avis rendu par {avis.id_expert} : Erreur lors de la création de l'EmailOutbox, {avis.id_instructeur} n'a pas été notifié par mail.")
        messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    if ok:
        logger.info(f"[AVIS {avis.id}] Notification Email {outbox.id} (Avis rendu) envoyée à {', '.join(outbox.to)} ")
    else:
        logger.error(f"[AVIS {avis.id}] Échec envoi notification email {outbox.id} (Avis rendu) à {', '.join(outbox.to)} : {err}")
        messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

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

            ####################################
            # NOTIFICATION PAR MAIL AU DEMANDEUR
            ####################################

            # emails_norm = [avis.id_instructeur.email]
            emails_norm = ["louis.calu@reunion-parcnational.fr"]

            # if (DossierAvis.objects.filter(id_avis=avis).exists() or avis.id_dossier):
            sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : {avis.id_expert} a remplacé son avis signé"
            
            context = {
                    "avis_numero": avis.id,
                    "expert": str(avis.id_expert),
                    "demarche_type": avis.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
                }

            template_name = "avis_remplace" 
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

            # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
            existe_deja = EmailOutbox.objects.filter(
                dedupe_key=dedupe,
                date_creation__date= timezone.now() - datetime.timedelta(hours=2)
            ).exists()

            if not existe_deja:
                outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")
                if outbox :
                    ok, err = envoi_mail(outbox.id)
                else :
                    logger.error(f"[AVIS {avis.id}] Avis modifié par {avis.id_expert} : Erreur lors de la création de l'EmailOutbox, {avis.id_instructeur} n'a pas été notifié par mail.")
                    messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

                if ok:
                    logger.info(f"[AVIS {avis.id}] Notification Email {outbox.id} (Avis modifié) envoyée à {', '.join(outbox.to)} ")
                else:
                    logger.error(f"[AVIS {avis.id}] Échec envoi notification email {outbox.id} (Avis modifié) à {', '.join(outbox.to)} : {err}")
                    messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

        else :
            # On revient sur la page pour afficher les messages d'erreurs
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
    except Exception as e:
        messages.error(request, f"❌ Erreur : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
def deposer_avis_signe(request):
    avis_id = request.POST.get("avis_id")
    fichier = request.FILES.get("fichier")

    avis = Avis.objects.get(id=avis_id)
    try:
       
        # Sauvegarde du nouvel avis signé 
        doc_avis_signe = enregistrer_document(
                fichier=fichier,
                nature_str="Avis instance",
                description=f"Dépot de l'avis signé par {request.user} pour la Demande d'avis {avis_id}",
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
            logger.info(f"[AVIS {avis.id}] : Avis signé déposé avec succès par l'expert {request.user}")
            messages.success(request, "✅ Avis signé déposé avec succès.")

            ####################################
            # NOTIFICATION PAR MAIL AU DEMANDEUR
            ####################################

            # emails_norm = [avis.id_instructeur.email]
            emails_norm = ["louis.calu@reunion-parcnational.fr"]

            # if (DossierAvis.objects.filter(id_avis=avis).exists() or avis.id_dossier):
            sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : {avis.id_expert} a déposé son avis signé"
            
            context = {
                    "avis_numero": avis.id,
                    "expert": str(avis.id_expert),
                    "demarche_type": avis.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
                }

            template_name = "avis_depose" 
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
            outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

            if outbox :
                ok, err = envoi_mail(outbox.id)
            else :
                logger.error(f"[AVIS {avis.id}] Avis rendu par {avis.id_expert} : Erreur lors de la création de l'EmailOutbox, {avis.id_instructeur} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

            if ok:
                logger.info(f"[AVIS {avis.id}] Notification Email {outbox.id} (Avis rendu) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[AVIS {avis.id}] Échec envoi notification email {outbox.id} (Avis rendu) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

            return redirect("avis_expert", avis_id=avis.id)





        else :
            # On revient sur la page pour afficher les messages d'erreurs
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
    except Exception as e:
        messages.error(request, f"❌ Erreur : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def enregistrer_date_transmission_cs(request, avis_id):

    avis = get_object_or_404(Avis, id=avis_id)
    date_str = request.POST.get("date_transmission_cs")

    if not date_str:
        messages.error(request, "Veuillez saisir une date valide.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    try:
        avis.date_transmission_cs = timezone.datetime.strptime(date_str, "%Y-%m-%d")
        avis.save()
    except Exception as e:
        logger.error(f"[AVIS {avis.id}] Erreur enregistrement date_transmission_cs : {e}")
        messages.error(request, "Erreur lors de l'enregistrement de la date.")

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def publier_avis_raa(request, avis_id):

    avis = get_object_or_404(Avis, id=avis_id)

    try:
        avis.publie_au_raa = True
        avis.save()
        logger.info(f"[AVIS {avis.id}] Publication au RAA validée par {request.user}.")
    except Exception as e:
        messages.error(request, f"❌ Erreur lors de la validation de la publication au RAA : {e}")
        logger.error(f"[AVIS {avis.id}] Erreur mise à jour publie_au_raa : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))
