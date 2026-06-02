from datetime import date, timedelta
import logging
import os
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import models
from django.db.models import Exists, OuterRef
import smbclient
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD

from autorisations.models.models_instruction import Demarche, Dossier, Message
from autorisations.models.models_avis import Avis, AvisDocument, AvisNature, AvisThematique, DossierAvis, Expert
from autorisations.models.models_utilisateurs import ContactExterne, DossierInstructeur, EmailOutbox, Instructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from autorisations.utils.nas_fonctions import creer_dossier_sur_nas, ecrire_file_sur_nas, supprimer_file_sur_nas
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from instruction.utils_instru import create_message_avis_bdd, enregistrer_document
from synchronisation.utils.model_helpers import update_fields
from pathlib import Path
from django.utils.timezone import localtime
from django.views.decorators.csrf import csrf_exempt
from django.core.files.uploadedfile import SimpleUploadedFile

from instruction.utils.avis_utils import (attach_pj_to_avis, get_expert_label,get_email_expert,count_unread_messages_for_avis,get_demandeur_label, get_or_create_expert_from_form,get_reponse_label,count_avis_with_unread_messages_for_dossier, thematiques_avis_liees_a_demarche)
from instruction.utils.dossier_utils import count_unread_messages_for_dossier, redirect_error

from synchronisation.utils.fichiers import nettoyer_nom_fichier

logger = logging.getLogger('ORM_DJANGO')


@login_required
def instruction_dossier_consultation(request, num_dossier) :

    # --- Récupération du dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[CONSULTATION] Dossier {num_dossier} introuvable en base — user={request.user}")
        return redirect_error(request, f"Le dossier {num_dossier} est introuvable. Contactez le support.")
        

    # --- Récupération de l'instructeur.rice ---
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[CONSULTATION DOSSIER] Utilisateur {request.user.email} sans profil instructeur")
        messages.warning(request,"Vous n'avez pas de profil 'Instructeur.trice'. Contactez le support.")

    dossiers_avis = DossierAvis.objects.filter(id_dossier=dossier).select_related(
        "id_avis",
        "id_avis__id_instructeur",
        "id_avis__id_expert",
        "id_avis__id_expert__id_instructeur",
        "id_avis__id_expert__id_contact_externe",
        "id_avis__id_avis_nature"
    )

    liste_avis = []
    nb_avis_avec_nouveau_mess = 0


    for da in dossiers_avis:
        avis = da.id_avis

        if not avis:
            logger.error(f"[CONSULTATION] Dossier {num_dossier} - DossierAvis {da.id} : Avis manquant")
            continue


        # EXPERT
        expert = get_expert_label(avis, num_dossier)
       
        # RÉPONSE AVIS
        reponse = get_reponse_label(avis)

        # EMAIL DE L’EXPERT
        email_expert = get_email_expert(avis, num_dossier)
       
        # MESSAGES (DE L'EXPERT) NON LUS
        nb_messages_non_lus_avis = count_unread_messages_for_avis(avis, email_expert, num_dossier)
        if nb_messages_non_lus_avis > 0:
            nb_avis_avec_nouveau_mess += 1

        # DEMANDEUR
        demandeur = get_demandeur_label(avis, num_dossier)
        

        # Construire le dictionnaire
        liste_avis.append({
            "statut": avis.statut,
            "expert": expert or "N/A",
            "numero": avis.id,
            "demandeur": demandeur,
            "date_demande": avis.date_demande_avis,
            "date_reponse": avis.date_reponse_avis,
            "favorable": reponse,
            "avis_nb_messages_non_lus": nb_messages_non_lus_avis,
        })


    # TRI DES AVIS
    try:
        liste_avis = sorted(
            liste_avis,
            key=lambda x: (x["statut"] == "Envoyé", x["date_demande"]),
            reverse=True
        )
    except Exception as e:
        logger.error(f"[CONSULTATION DOSSIER {dossier.numero}] Erreur lors du tri de la liste des avis : {e}")



    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus DOSSIER
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)



    return render(request, "instruction/instruction_dossier_consultation.html", {
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "dossier": dossier,
        "est_instructeur": instructeur,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "avis": liste_avis,
        "nb_avis_envoyes": nb_avis_envoyes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
    })


@login_required
def instruction_dossier_ajouter_avis(request, num_dossier, avis_id=None):
    
    # --- Récupération du dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[AJOUTER AVIS] Dossier {num_dossier} introuvable en base — user={request.user}")
        return redirect_error(request, f"Le dossier {num_dossier} est introuvable. Contactez le support.")
        


    # --- Récupération éventuelle de l'avis (édition) ---
    avis = None
    if avis_id is not None:
        avis = Avis.objects.filter(id=avis_id, id_dossier=dossier).first()
        if not avis:
            logger.error(f"[AJOUT AVIS] Dossier {num_dossier} — Avis {avis_id} introuvable ou non lié au dossier.")
            return redirect_error(request, f"L'avis {avis_id} est introuvable pour ce dossier. Contactez le support.")
            
        

    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")

    # thematiques = AvisThematique.objects.all().order_by("thematique")
    thematiques = thematiques_avis_liees_a_demarche(dossier.id_demarche)

    # --- Instructeur courant (user connecté) ---
    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur_connecte:
        logger.warning(f"[AJOUT AVIS] Utilisateur {request.user.email} sans profil instructeur")
        messages.warning(request, "Vous n'avez pas de profil 'Instructeur.trice'. Contactez le support.")


    # Tous les avis déjà envoyés pour ce dossier
    avis_existants = Avis.objects.filter(id_dossier=dossier, statut="Envoyé")

    # Extraire les instructeurs et contacts déjà utilisés
    instructeurs_utilises = avis_existants.filter(id_expert__id_instructeur__isnull=False) \
                                          .values_list("id_expert__id_instructeur__email", flat=True)
    contacts_utilises = avis_existants.filter(id_expert__id_contact_externe__isnull=False) \
                                      .values_list("id_expert__id_contact_externe__email", flat=True)


    # Instructeurs candidats
    instructeurs_qs = (
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email__exact="autorisations@reunion-parcnational.fr")
        .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=instructeurs_utilises)  # pas déjà utilisé
        .order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")
    )

    # Contacts externes candidats
    contacts_qs = (
        ContactExterne.objects
        .filter(email__isnull=False, id_type__type="Instance")
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=contacts_utilises)  # pas déjà utilisé
        .order_by("nom", "email")
    )

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_qs}.values()
    contacts_externes = {c.email: c for c in contacts_qs}.values()

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)


    # --- Nombre d'avis avec au moins un message non lu de l'expert ---
    nb_avis_avec_nouveau_mess = count_avis_with_unread_messages_for_dossier(dossier, num_dossier)

    # nb_avis_avec_nouveau_mess = 0
    # for da in DossierAvis.objects.filter(id_dossier=dossier).select_related("id_avis__id_expert"):
    #     avis_item = da.id_avis
    #     if not avis_item or not avis_item.id_expert:
    #         continue

    #     if avis_item.id_expert.est_interne:
    #         email_expert = avis_item.id_expert.id_instructeur.email
    #     else:
    #         email_expert = avis_item.id_expert.id_contact_externe.email

    #     nb_non_lus_avis = Message.objects.filter(
    #         id_avis=avis_item,
    #         lu=False,
    #         email_emetteur=email_expert
    #     ).count()

    #     if nb_non_lus_avis > 0:
    #         nb_avis_avec_nouveau_mess += 1


    return render(request, "instruction/instruction_dossier_ajouter_avis.html", {
        "dossier": dossier,
        "avis": avis,
        "natures": natures,
        "thematiques": thematiques, 
        "instructeurs": instructeurs,
        "contacts_externes": contacts_externes,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_avis_envoyes": nb_avis_envoyes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "NAS_ROOT": os.getenv('NAS_ROOT'),
    })


@login_required
def instruction_dossier_ajouter_avis_existant(request, num_dossier):
    
    # --- Récupération du dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[AJOUTER AVIS EXISTANT] Dossier {num_dossier} introuvable en base — user={request.user}")
        return redirect_error(request, f"Le dossier {num_dossier} est introuvable. Contactez le support.")
        

    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")
    thematiques = AvisThematique.objects.all().order_by("thematique")

    # Tous les instructeurs
    # tous_les_instructeurs = Instructeur.objects.all()
    tous_les_instructeurs = Instructeur.objects.select_related("id_agent_autorisations").order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")
    tous_les_experts = Expert.objects.all()


    # --- Instructeur courant (user connecté) ---
    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur_connecte:
        logger.warning(f"[AJOUTER AVIS EXISTANT] Utilisateur {request.user.email} sans profil instructeur")
        messages.warning(request, "Vous n'avez pas de profil 'Instructeur.trice'. Contactez le support.")

    # Tous les avis déjà envoyés pour ce dossier
    avis_existants = Avis.objects.filter(id_dossier=dossier, statut="Envoyé")

    # Extraire les instructeurs et contacts déjà utilisés
    instructeurs_utilises = avis_existants.filter(id_expert__id_instructeur__isnull=False) \
                                          .values_list("id_expert__id_instructeur__email", flat=True)
    
    # Instructeurs candidats
    instructeurs_qs = (
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email__exact="autorisations@reunion-parcnational.fr")
        # .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=instructeurs_utilises)  # pas déjà utilisé
        .order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")
    )

    # Contacts externes candidats
    contacts_qs = (
        ContactExterne.objects
        .filter(email__isnull=False, id_type__type="Instance")
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        # .exclude(email__in=contacts_utilises)  # pas déjà utilisé
        .exclude(id_type__type__in=["Demandeur intermédiaire", "Bénéficiaire"])
        .order_by("nom", "email")
    )

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_qs}.values()
    contacts_externes = {c.email: c for c in contacts_qs}.values()

    # --- Messages non lus DOSSIER ---
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)

    # --- Avis avec au moins un message non lu ---
    nb_avis_avec_nouveau_mess = count_avis_with_unread_messages_for_dossier(dossier, num_dossier)


    # ----------------------------
    # PARTIE RECHERCHE D’AVIS
    # ----------------------------
    avis_list = None

    try :
        if request.GET:  # seulement si une recherche est soumise
            avis_list = Avis.objects.all().select_related("id_avis_nature", "id_avis_thematique", "id_expert", "id_instructeur")

            numero = request.GET.get("numero")
            expert = request.GET.get("expert")
            demandeur = request.GET.get("demandeur")
            date_demande = request.GET.get("date_demande")
            date_reponse = request.GET.get("date_reponse")
            favorable = request.GET.get("favorable")
            thematique = request.GET.get("thematique")
            nature = request.GET.get("nature")
            deja_lie = request.GET.get("deja_lie")
            statut = request.GET.get("statut")

            if numero:
                avis_list = avis_list.filter(id=numero)
            if expert:
                avis_list = avis_list.filter(id_expert=expert)
            if demandeur:
                avis_list = avis_list.filter(id_instructeur=demandeur)
            if date_demande:
                avis_list = avis_list.filter(date_demande_avis__date=date_demande)
            if date_reponse:
                avis_list = avis_list.filter(date_reponse_avis__date=date_reponse)
            if favorable in ["true", "false"]:
                avis_list = avis_list.filter(favorable=(favorable == "true"))
            if thematique:
                avis_list = avis_list.filter(id_avis_thematique=thematique)
            if nature:
                avis_list = avis_list.filter(id_avis_nature=nature)
            if statut:
                avis_list = avis_list.filter(statut=statut)
            
            # Sous-requête : avis liés à CE dossier -> exclusion
            subquery_dossier = DossierAvis.objects.filter(id_avis=OuterRef("pk"), id_dossier=dossier)
            avis_list = avis_list.annotate(deja_lie_ce_dossier=Exists(subquery_dossier)).filter(deja_lie_ce_dossier=False)

            # Sous-requête pour vérifier l’existence d’un lien DossierAvis
            subquery = DossierAvis.objects.filter(id_avis=OuterRef("pk"))
            if deja_lie == "1":
                avis_list = avis_list.annotate(deja_lie=Exists(subquery)).filter(deja_lie=True)
            elif deja_lie == "0":
                avis_list = avis_list.annotate(deja_lie=Exists(subquery)).filter(deja_lie=False)

            # tri + limitation à 20 avis
            avis_list = avis_list.order_by("-date_demande_avis")[:20]

    except Exception as e:
        logger.error(f"[AJOUTER AVIS EXISTANT] Dossier {num_dossier} Erreur lors de la recherche d'avis — user={request.user} : {e}")
        messages.error(request, f"Une erreur est survenue au cours de la recherche de la demande d'avis existante. Contactez le support.")
    

    return render(request, "instruction/instruction_dossier_ajouter_avis_existant.html", {
        "dossier": dossier,
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "tous_les_instructeurs": tous_les_instructeurs,
        "contacts_externes": contacts_externes,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "avis_list": avis_list,
        "tous_les_experts": tous_les_experts,
    })



@login_required
def lier_dossier_avis(request, num_dossier, avis_id):

    # --- Récupération dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[LIER AVIS À DOSSIER] Dossier {num_dossier} introuvable — user={request.user.email}")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
        
    
    # --- Récupération avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[LIER AVIS À DOSSIER] Avis {avis_id} introuvable — dossier={num_dossier}")
        return redirect_error(request, f"L'avis {avis_id} est introuvable. Contactez le support.")
        
    


    if request.method == "POST":
        try:
            # Vérifie si déjà lié
            existe = DossierAvis.objects.filter(id_dossier=dossier, id_avis=avis).exists()
            if not existe:
                DossierAvis.objects.create(id_dossier=dossier, id_avis=avis)
            else:
                messages.warning(request, f"L'avis {avis.id} est déjà lié à ce dossier.")

        except Exception as e:
            logger.error(f"[LIER AVIS À DOSSIER] Erreur lors de l’association de l'Avis {avis_id} au Dossier {num_dossier} : {e}")
            return redirect_error(request, f"Une erreur est survenue lors de l’association de l’avis au dossier. Contactez le support.")
            

        # Redirection vers la consultation
        return redirect("instruction_dossier_consultation", num_dossier=dossier.numero)

    return redirect("instruction_dossier_ajouter_avis_existant", num_dossier=dossier.numero)



@login_required
def ajouter_avis_hors_appli(request, num_dossier):
    
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[AJOUT AVIS HORS APPLI] Dossier {num_dossier} introuvable")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
        

    if request.method == "POST":
        try:
            # 1. Récupérer les champs du formulaire
            nature_id = request.POST.get("nature")
            thematique_id = request.POST.get("thematique")
            mode_contact = request.POST.get("mode_contact")
            favorable = request.POST.get("favorable") == "true"
            note = request.POST.get("note_demandeur")
            date_demande_avis = parse_datetime(request.POST.get("date_demande_avis")) if request.POST.get("date_demande_avis") else None
            date_reponse_avis = parse_datetime(request.POST.get("date_reponse_avis")) if request.POST.get("date_reponse_avis") else None
            instructeur_demandeur_id = request.POST.get("demandeur_avis")
            expert_interne = request.POST.get("expert_interne")
            expert_externe = request.POST.get("expert_externe")
            

            # Normalisation nom_prenom expert + Recupération Expert
            expert = None
            if expert_externe:
                try:
                    contact = ContactExterne.objects.get(id=expert_externe)
                    if contact.nom and contact.prenom :
                        nom_prenom_expert = nettoyer_nom_fichier(f"{contact.nom}_{contact.prenom}")
                    elif contact.raison_sociale :
                        nom_prenom_expert = nettoyer_nom_fichier(f"{contact.raison_sociale}")
                    elif contact.organisation :
                        nom_prenom_expert = nettoyer_nom_fichier(f"{contact.organisation}")
                    else :
                        nom_prenom_expert = f""

                except Exception as e:
                    logger.error(f"[DOSSIER {dossier.numero}] Ajout Avis hors application : Erreur lors de la récupération de l'expert externe : {e}")
                    return redirect_error(request, f"Erreur lors de la récupération de l'expert externe. Contactez le support.")
                    
                
                expert, created = Expert.objects.get_or_create(
                    id_contact_externe_id=expert_externe,
                    defaults={"est_interne": False}
                )

                if created:
                        logger.info(f"[EXPERT] Nouvel expert externe créé : {contact}")
                
            elif expert_interne:

                try:
                    instru = Instructeur.objects.get(id=expert_interne)
                    nom_prenom_expert = nettoyer_nom_fichier(f"{instru.id_agent_autorisations.nom}_{instru.id_agent_autorisations.prenom}")

                except Exception as e:
                    logger.error(f"[DOSSIER {dossier.numero}] Ajout Avis hors application : Erreur lors de la récupération de l'expert interne : {e}")
                    return redirect_error(request, f"Erreur lors de la récupération de l'expert interne. Contactez le support.")
                    
                
                expert, created = Expert.objects.get_or_create(
                    id_instructeur=expert_interne,
                    defaults={"est_interne": True}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert interne créé : {instru}")

            
            instructeur_demandeur = None
            if instructeur_demandeur_id:
                instructeur_demandeur = Instructeur.objects.get(id=instructeur_demandeur_id)

            # Création emplacement
            emplacement = ""
            if nom_prenom_expert :  
                emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"


            # 2. Créer l’avis
            # Construire la formulation
            formulation = f"Avis demandé par {instructeur_demandeur} à {expert}."
            if mode_contact and mode_contact.lower() != "autre":
                formulation += f" La demande d'avis a été faite en dehors de l'application par {mode_contact}."

            avis = Avis.objects.create(
                id_avis_nature_id=nature_id,
                id_avis_thematique_id=thematique_id,
                id_dossier=dossier,
                id_expert=expert,
                emplacement=emplacement,
                id_instructeur=instructeur_demandeur,
                mode_contact=mode_contact,
                statut="Envoyé",
                formulation=formulation,
                favorable=favorable,
                note=note,
                date_demande_avis=date_demande_avis,
                date_reponse_avis=date_reponse_avis,
            )
            
            # Pour le cas ou le contact (expert) externe n'a ni nom, ni prénom, ni raison sociale, ni organisation
            if not avis.emplacement:
                avis.emplacement = f"{dossier.emplacement}Avis/Avis_{avis.id}/"
                avis.save(update_fields=["emplacement"])


            # Formulation = Message par défaut
            if formulation :
                try:
                    msg = Message.objects.create(
                        body=avis.formulation,
                        date_envoi=timezone.now(),
                        piece_jointe=False,
                        email_emetteur=request.user.email,
                        id_avis=avis,
                        lu=False,
                    )
                except Exception as e:
                    logger.warning(f"[DOSSIER {dossier.numero}] Ajout Avis {avis.id} hors application : Le message automatique (qui est égal à avis.formulation) n'a pas pu être créé")

    

            # 3. Associer l’avis au dossier
            DossierAvis.objects.create(
                id_dossier=dossier,
                id_avis=avis
            )


            # 4. Gestion des pièces jointes
            fichiers = request.FILES.getlist("pj_lie_avis")

            attach_pj_to_avis(avis, fichiers, emplacement, request, dossier.numero)

            # if fichiers :
            #     chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}Annexes/"
            #     creer_dossier_sur_nas(chemin_complet)
                
            #     # on parcourt les fichiers et on les écrit physiquement
            #     for pj in fichiers :
                    
            #         doc_pj = enregistrer_document(
            #             fichier=pj,
            #             nature_str="Annexe avis",
            #             description=f"Pièce jointe pour la demande d'avis {avis.id} effectuée en dehors de l'application",
            #             request=request,
            #             emplacement_avis = emplacement,
            #         )

            #         # Création AvisDocument
            #         if doc_pj:
            #             AvisDocument.objects.create(
            #                 id_avis=avis,
            #                 id_document=doc_pj
            #             )

            return redirect("instruction_dossier_consultation", num_dossier=dossier.numero)

        except Exception as e:
            logger.error(f"[AJOUT AVIS HORS APPLI] Dossier {num_dossier} : {e}")
            return redirect_error(request, f"Erreur lors de l'ajout de l'avis. Contactez le support.")
            



@login_required
def ajouter_pj_avis(request, avis_id):
    
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[AJOUT PJ AVIS] Avis {avis_id} introuvable")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")
        


    if request.method == "POST":
        fichiers = request.FILES.getlist("pj_avis")
        if not fichiers:
            return redirect_error(request, "⚠️ Aucun fichier sélectionné.")
        
        try:  
           attach_pj_to_avis(
                avis=avis,
                fichiers=fichiers,
                emplacement_avis=avis.emplacement,
                request=request,
                dossier_numero=None,
            )


        except Exception as e:
            logger.error(f"[AJOUT PJ AVIS] Avis {avis_id} : {e}")
            messages.error(request, f"Une erreur est survenue lors de l'ajout des pièces jointes. Contacter le support.")

        return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def supprimer_pj_avis(request, avis_id, document_id):
    
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[SUPPR PJ AVIS] Avis {avis_id} introuvable")
        return redirect_error(request, "L'avis est introuvable en base. Contactez le support.")
    
    avis_doc = AvisDocument.objects.filter(id_avis=avis, id_document_id=document_id).first()
    
    if not avis_doc:
        logger.warning(f"[SUPPR PJ AVIS] Relation AvisDocument introuvable — Avis {avis_id}, Document {document_id}")
        doc = Document.objects.get(id=document_id)
        doc.delete()
        logger.info(f"[SUPPR PJ AVIS] Le Document {document_id} a quand même été supprimé.")
        # return redirect_error(request, "La pièce jointe est introuvable. Contactez le support.")
        
        return redirect(request.META.get("HTTP_REFERER", "/"))


    # Supprime le lien Avis ↔ Document
    doc = avis_doc.id_document

    # Suppression relation
    try:
        avis_doc.delete()
    except Exception as e:
        logger.error(f"[SUPPR_PJ_AVIS] Erreur lors de la suppression du lien AvisDocument — Avis {avis_id}, Document {doc.id} : {e}")
        return redirect_error(request, f"Erreur lors de la suppression du document. Contactez le support.")
        


    # Suppression document (On ne le supprime pas physiquement pour garder une trace)
    try:
        doc.delete()
    except Exception as e:
        logger.error(f"[SUPPR_PJ_AVIS] Liaison AvisDocument bien supprimée. Erreur lors de la suppression du Document {doc.id} (Avis {avis_id}) : {e}")
        return redirect_error(request, f"Erreur lors de la suppression du document. Contactez le support.")
        

    logger.info(f"[AVIS {avis_id}] Pièce jointe {document_id} ({doc.titre}) supprimée par {request.user}")

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def instruction_dossier_confirmer_ajout_avis(request, num_dossier, avis_id=None):
    

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"Erreur lors de la récupération de l'instructeur pour le user {request.user} : {e}")
        return redirect_error(request, f"Aucun instructeur.rice n'est associé.e à votre profil. Contactez le support.")

    
    # --- Récupération dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {num_dossier} introuvable en base.")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
    

    # --- Récupération brouillon éventuel ---
    brouillon_avis = None
    if avis_id:
        brouillon_avis = Avis.objects.filter(id=avis_id, id_dossier=dossier).first()
        if not brouillon_avis:
            logger.error(f"[CONFIRMER AJOUT AVIS] Brouillon avis {avis_id} introuvable pour dossier {num_dossier}.")
            return redirect_error(request, "Le brouillon de l'avis est introuvable. Contactez le support.")
    

    # ---- Extraction expert interne/externe ---- #
    try :
        expert, nom_prenom_expert = get_or_create_expert_from_form(request)

    except Exception as e:
        logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {num_dossier}, {avis_id} : Erreur lors de la récupération de l'expert (get_or_create_expert_from_form) : {e}")
        return redirect_error(request, f"Erreur lors de la récupération de l’expert. Contactez le support.")


    if request.method == "POST":
        # Champs du formulaire
        nature_id = request.POST.get("nature")
        thematique_id = request.POST.get("thematique")
        note = request.POST.get("note_demandeur", "").strip()
        mode_contact = request.POST.get("mode_contact")
        formulation_avis = request.POST.get("formulation_avis")
        pj_projet_avis = request.FILES.get("pj_demande_avis")
        pj_projet_acte = request.FILES.get("pj_projet_acte")
        pj_rapport_cs = request.FILES.get("pj_rapport_cs")
        liste_autres_pj = request.FILES.getlist("pj_lie_avis")


        # --- Récupération nature ---
        try:
            nature = AvisNature.objects.get(id=nature_id)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la nature d'avis {nature_id} : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la nature d'avis. Contactez le support.")
            


        # --- Récupération thématique ---
        try:
            thematique = AvisThematique.objects.get(id=thematique_id)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la thématique de l'avis {thematique_id} : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la thématique de l'avis. Contactez le support.")
            

        
        # ---- On récupère l'emplacement physique de l'avis ----
        if brouillon_avis :
            if not brouillon_avis.emplacement :
                emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"
            else :
                emplacement = brouillon_avis.emplacement
        else :
            emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"
        
        doc_projet_acte = doc_rapport_instance = doc_projet_avis = None


        # ---- Création des folders
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs or liste_autres_pj :
            chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}Annexes/"
            creer_dossier_sur_nas(chemin_complet)



        #############################
        # ---- ÉCRITURE DES PJ ---- #
        #############################
        # Projet d'avis
        if pj_projet_avis :
            extension = Path(pj_projet_avis.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt"} :
                logger.warning(f"[CONFIRMER AJOUT AVIS] Le projet de demande d'avis a tenté d'être déposé au format {extension} par {request.user}. Formats autorisés : .doc, .docx, .odt")
                return redirect_error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_avis = enregistrer_document(
                fichier=pj_projet_avis,
                nature_str="Annexe avis",
                description=f"Projet de demande pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Projet d'acte
        if pj_projet_acte :
            extension = Path(pj_projet_acte.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt", ".pdf"} :
                logger.warning(f"[CONFIRMER AJOUT AVIS] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .doc, .docx, .odt, .pdf")
                return redirect_error(request, f"❌ Le projet d'acte doit etre au format .doc, .docx, .odt ou .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_acte = enregistrer_document(
                fichier=pj_projet_acte,
                nature_str="Annexe avis",
                description=f"Projet d’acte pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Rapport CS
        if pj_rapport_cs :
            extension = Path(pj_rapport_cs.name).suffix.lower()
            if extension != ".pdf" :
                logger.warning(f"[CONFIRMER AJOUT AVIS] Le rapport au CS a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .pdf")
                return redirect_error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_rapport_instance = enregistrer_document(
                fichier=pj_rapport_cs,
                nature_str="Annexe avis",
                description=f"Rapport Instance pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )

        # # Autres PJ
        # if liste_autres_pj :
        #     try :
            
        #         # Ecriture physique
        #         for pj in liste_autres_pj :

        #             if avis_id:
        #                 description = f"Pièce jointe déposée par {request.user} pour la demande d'avis {avis_id}"
        #             else:
        #                 description = f"Pièce jointe déposée par {request.user}"
                    
        #             doc_pj = enregistrer_document(
        #                 fichier=pj,
        #                 nature_str="Annexe avis",
        #                 description=description,
        #                 request=request,
        #                 emplacement_avis = emplacement,
        #             )

        #             # Création AvisDocument
        #             if doc_pj:
        #                 AvisDocument.objects.create(id_avis=avis, id_document=doc_pj)

        #     except Exception as e:
        #         logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis_id} : Echec du rattachement des autres pièces jointes à la demande d'avis par {request.user} : {e}")
        #         return redirect_error(request, f"Erreur lors du rattachement des pièces jointes annexes à la demande d'avis. Contactez le support.")
                       



        ####################################################
        # ---- CAS 1 : BROUILLON D'AVIS DÉJÀ EXISTANT ---- #
        ####################################################
        if brouillon_avis :

            fields_to_update = {
                "id_avis_nature": nature,
                "id_avis_thematique": thematique,
                "id_expert": expert,
                "id_demarche": dossier.id_demarche,
                "statut": "Envoyé",
                "date_demande_avis": timezone.now(),
                "note": note,
                "formulation": formulation_avis,
                "mode_contact": mode_contact,
                "emplacement": emplacement,
            }

            # Ajouter uniquement les docs non-nuls
            if doc_projet_acte:
                fields_to_update["id_projet_acte"] = doc_projet_acte
            if doc_rapport_instance:
                fields_to_update["id_rapport_instance"] = doc_rapport_instance
            if doc_projet_avis:
                fields_to_update["id_projet_avis"] = doc_projet_avis

            try:

                updated_fields = update_fields(brouillon_avis, fields_to_update)
                if updated_fields:
                    brouillon_avis.save(update_fields=updated_fields)
                    logger.info(f"[DOSSIER {dossier.numero}] Brouillon d'avis ({brouillon_avis}) mis à jour. Changements: {', '.join(updated_fields)}")
                avis = brouillon_avis

            except Exception as e:
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : Erreur lors de la mise à jour de l'avis : {e}")
                return redirect_error(request, f"Une erreur est survenue lors de la mise à jour de l'avis. Contactez le support.")
            

            # Create message (formulation) + projet demande d'avis en PJ si il existe
            try:
                msg = Message.objects.create(
                    body=brouillon_avis.formulation,
                    date_envoi=timezone.now(),
                    piece_jointe=True if doc_projet_avis else False,
                    email_emetteur=request.user.email,
                    id_avis=brouillon_avis,
                    lu=False,
                )

                # Joindre le projet de demande d'avis au message
                if doc_projet_avis :
                    MessageDocument.objects.create(id_message=msg, id_document=doc_projet_avis)

                logger.info(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : message par défaut envoyé à {brouillon_avis.id_expert} par {request.user}")

            except Exception as e:
                brouillon_avis.statut = "Brouillon"
                brouillon_avis.save()
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : Demande d'avis de {request.user} non transmise à {brouillon_avis.id_expert} - Erreur lors de la création du message par défaut (formulation avis) : {e}")
                return redirect_error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")

        
        
        #############################################################
        # ---- CAS 2 : NOUVEL AVIS (PAS DE BROUILLON EXISTANT) ---- #
        #############################################################
        else :
            try:

                avis = Avis.objects.create(
                        id_avis_nature=nature,
                        id_avis_thematique=thematique,
                        date_demande_avis=timezone.now(),
                        statut="Envoyé",
                        note=note,
                        formulation= formulation_avis,
                        mode_contact=mode_contact,
                        id_dossier=dossier,
                        id_demarche=dossier.id_demarche,
                        id_expert=expert,
                        id_instructeur=instructeur,
                        id_projet_acte=doc_projet_acte,
                        id_rapport_instance=doc_rapport_instance,
                        id_projet_avis=doc_projet_avis,
                        emplacement = emplacement,
                )

                logger.info(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero} : Avis {avis.id} créé par {request.user}")

            except Exception as e:
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero} : Erreur lors de la création de l'avis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création de l'avis. Contactez le support.")
        
            try:
                DossierAvis.objects.create(id_avis=avis,id_dossier=dossier)

            except Exception as e:
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création du DossierAvis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création du lien entre le dossier et l'avis. Contactez le support.")


            # Create message (formulation)
            if avis.formulation :
                try:
                    msg = Message.objects.create(
                        body=avis.formulation,
                        date_envoi=timezone.now(),
                        piece_jointe=True if doc_projet_avis else False,
                        email_emetteur=request.user.email,
                        id_avis=avis,
                        lu=False,
                    )

                    # Joindre le projet de demande d'avis au message
                    if doc_projet_avis :
                        MessageDocument.objects.create(id_message=msg, id_document=doc_projet_avis)

                    logger.info(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : message par défaut envoyé à {avis.id_expert} par {request.user}")


                except Exception as e:
                    avis.statut = "Brouillon"
                    avis.save()
                    logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Demande d'avis de {request.user} non transmise à {avis.id_expert} - Erreur lors de la création du message par défaut (formulation avis) : {e}")
                    return redirect_error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")

        # Autres PJ
        if liste_autres_pj :
            try :
            
                # Ecriture physique
                for pj in liste_autres_pj :

                    if avis_id:
                        description = f"Pièce jointe déposée par {request.user} pour la demande d'avis {avis_id}"
                    else:
                        description = f"Pièce jointe déposée par {request.user}"
                    
                    doc_pj = enregistrer_document(
                        fichier=pj,
                        nature_str="Annexe avis",
                        description=description,
                        request=request,
                        emplacement_avis = emplacement,
                    )

                    # Création AvisDocument
                    if doc_pj:
                        AvisDocument.objects.create(id_avis=avis, id_document=doc_pj)

            except Exception as e:
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Echec du rattachement des autres pièces jointes à la demande d'avis par {request.user} : {e}")
                return redirect_error(request, f"Erreur lors du rattachement des pièces jointes annexes à la demande d'avis. Contactez le support.")
            

        #################################
        # NOTIFICATION PAR MAIL à l'expert
        #################################
        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = [get_email_expert(avis)]
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]


        if (DossierAvis.objects.filter(id_avis=avis).exists() or avis.id_dossier) and avis.id_demarche.type :
            sujet = f"{avis.id_instructeur} vous demande votre avis sur le dossier n° {dossier.numero} ({dossier.id_demarche.type})"
        else :
            sujet = f"{avis.id_instructeur} vous demande votre avis"

        context = {
            "avis_numero": avis.id,
            "dossier_numero": dossier.numero,
            "demarche_type": avis.id_demarche.type,
            "demandeur": str(avis.id_instructeur),
            "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/",
        }
        template_name = "nouvelle_demande_avis_dossier" 

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")
            logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect('instruction_dossier_consultation', num_dossier=num_dossier)
        
        outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Notification")

        if outbox :
            ok, err = envoi_mail(outbox.id)
        else :
            logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création de l'EmailOutbox, {expert} n'a pas été notifié par mail.")
            messages.error(request, f"L'email de notification à {expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

        if ok:
            logger.info(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Notification Email {outbox.id} envoyée à {', '.join(outbox.to)} ")
        else:
            logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Échec envoi notification email {outbox.id} à {', '.join(outbox.to)} : {err}")
            messages.error(request, f"L'email de notification à {expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    else :
        logger.error(f"[CONFIRMER AJOUT AVIS] Erreur lors de la transmission du formulaire par {request.user} : méthode POST requise.")
        return redirect_error(request, f"Erreur lors de la transmission du formulaire : méthode POST requise. Contactez le support.")
    
    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)




@require_POST
@login_required
def instruction_dossier_enregistrer_brouillon_avis(request, num_dossier, avis_id=None):

    try:
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur:
            return redirect_error(request, f"Aucun instructeur.rice n'est associé.e à votre profil. Contactez le support")
            
    except Exception as e:
        return redirect_error(request, f"Erreur lors de la récupération de l'instructeur : {e}")
        

    # --- Récupération dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[SAVE BROUILLON AVIS] Dossier {num_dossier} introuvable")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
        

    # Si on reçoit un brouillon d'avis existant
    brouillon_avis = None
    if avis_id:
        brouillon_avis = Avis.objects.filter(id=avis_id, id_dossier=dossier).first()
        if not brouillon_avis:
            logger.error(f"[SAVE BROUILLON AVIS] Brouillon d'avis {avis_id} introuvable en base pour dossier {num_dossier}")
            return redirect_error(request, "Avis introuvable en base. Contactez le support.")
            
        

    if request.method == "POST":
        # Champs du formulaire
        nature_id = request.POST.get("nature")
        thematique_id = request.POST.get("thematique")
        note = request.POST.get("note_demandeur", "").strip()
        mode_contact = request.POST.get("mode_contact")
        formulation_avis = request.POST.get("formulation_avis")
        expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
        expert_externe_id = request.POST.get("expert_externe") # contact externe ici
        pj_projet_avis = request.FILES.get("pj_demande_avis")
        pj_projet_acte = request.FILES.get("pj_projet_acte")
        pj_rapport_cs = request.FILES.get("pj_rapport_cs")  
        liste_autres_pj = request.FILES.getlist("pj_lie_avis")
   

        try:
            nature = AvisNature.objects.get(id=nature_id)
        except Exception as e:
            logger.error(f"[SAVE BROUILLON AVIS] Nature {nature_id} introuvable : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la nature de l'avis. Contactez le suppport.")
            

        try:
            thematique = AvisThematique.objects.get(id=thematique_id)
        except Exception as e:
            logger.error(f"[SAVE BROUILLON AVIS] Thématique {thematique_id} introuvable : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la thématique de l'avis. Contactez le suppport.")

    
        if expert_interne_id:
            try:
                instru = Instructeur.objects.get(id=expert_interne_id)
                expert, created = Expert.objects.get_or_create(
                    id_instructeur=instru,
                    defaults={"est_interne": True}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert interne créé : {instru}")
                
                nom_prenom_expert = nettoyer_nom_fichier(f"{instru.id_agent_autorisations.nom}_{instru.id_agent_autorisations.prenom}")

            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Expert interne {expert_interne_id} introuvable : {e}")
                return redirect_error(request, f"Erreur lors de la récupération de l'expert interne. Contactez le suppport.")
        
            
        elif expert_externe_id:
            try:
                contact = ContactExterne.objects.get(id=expert_externe_id)
                expert, created = Expert.objects.get_or_create(
                    id_contact_externe=contact,
                    defaults={"est_interne": False}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert externe créé : {contact}")

                if contact.nom and contact.prenom :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.nom}_{contact.prenom}")
                elif contact.raison_sociale :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.raison_sociale}")
                elif contact.organisation :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.organisation}")
                else :
                    nom_prenom_expert = f"Avis_{avis_id}"

            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Expert externe {expert_externe_id} introuvable : {e}")
                return redirect_error(request, f"Erreur lors de la récupération de l'expert externe. Contactez le suppport.")
                
                

        # ---- On récupère l'emplacement physique de l'avis ----
        if brouillon_avis :
            if not brouillon_avis.emplacement :
                emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"
            else :
                emplacement = brouillon_avis.emplacement
        else :
            emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"


        # ---- Création des folders
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs or liste_autres_pj :
            chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}Annexes/"
            creer_dossier_sur_nas(chemin_complet)

            
        

        #############################
        # ---- ÉCRITURE DES PJ ---- #
        #############################
        doc_projet_acte = doc_rapport_instance = doc_projet_avis = None

        # Projet d'avis
        if pj_projet_avis :
            extension = Path(pj_projet_avis.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt"} :
                logger.warning(f"[SAVE BROUILLON AVIS] Le projet de demande d'avis a tenté d'être déposé au format {extension} par {request.user}. Formats autorisés : .doc, .docx, .odt")
                return redirect_error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_avis = enregistrer_document(
                fichier=pj_projet_avis,
                nature_str="Annexe avis",
                description=f"Projet de demande pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Projet d'acte
        if pj_projet_acte :
            extension = Path(pj_projet_acte.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt", ".pdf"} :
                logger.warning(f"[SAVE BROUILLON AVIS] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .doc, .docx, .odt ou .pdf")
                return redirect_error(request, f"❌ Le projet d'acte doit etre au format .doc, .docx, .odt ou .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_acte = enregistrer_document(
                fichier=pj_projet_acte,
                nature_str="Annexe avis",
                description=f"Projet d’acte pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Rapport CS
        if pj_rapport_cs :
            extension = Path(pj_rapport_cs.name).suffix.lower()
            if extension != ".pdf" :
                logger.warning(f"[SAVE BROUILLON AVIS] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .pdf")
                return redirect_error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_rapport_instance = enregistrer_document(
                fichier=pj_rapport_cs,
                nature_str="Annexe avis",
                description=f"Rapport Instance pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
                
        # Pour le moment : On ne sauvegarde pas les autres pj (liste_autres_pj) pour les brouillon d'avis.
        
        ####################################################
        # ---- CAS 1 : BROUILLON D'AVIS DÉJÀ EXISTANT ---- #
        ####################################################
        if brouillon_avis :
            fields_to_update = {
                "id_avis_nature": nature,
                "id_avis_thematique": thematique,
                "id_expert": expert,
                "note": note,
                "formulation": formulation_avis,
                "mode_contact": mode_contact,
                "emplacement": emplacement,
            }

            # Ajouter uniquement les docs non-nuls
            if doc_projet_acte:
                fields_to_update["id_projet_acte"] = doc_projet_acte
            if doc_rapport_instance:
                fields_to_update["id_rapport_instance"] = doc_rapport_instance
            if doc_projet_avis:
                fields_to_update["id_projet_avis"] = doc_projet_avis

            try:

                updated_fields = update_fields(brouillon_avis, fields_to_update)

                if updated_fields:
                    brouillon_avis.save(update_fields=updated_fields)
                    logger.info(
                        f"[DOSSIER {dossier.numero}] Brouillon d'avis ({brouillon_avis}) mis à jour. "
                        f"Changements: {', '.join(updated_fields)}"
                    )
            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : Erreur lors de la mise à jour de l'avis : {e}")
                return redirect_error(request, f"Erreur lors de la sauvegarde de l'avis. Contactez le support.")
                
        


        ###################################################################
        # ---- CAS 2 : NOUVEAU BROUILLON (PAS DE BROUILLON EXISTANT) ---- #
        ###################################################################
        else:
            try:
                avis = Avis.objects.create(
                        id_avis_nature=nature,
                        id_avis_thematique=thematique,
                        date_demande_avis=timezone.now(),
                        statut="Brouillon",
                        note=note,
                        formulation= formulation_avis,
                        mode_contact=mode_contact,
                        id_dossier=dossier,
                        id_expert=expert,
                        id_instructeur=instructeur,
                        id_projet_acte=doc_projet_acte,
                        id_rapport_instance=doc_rapport_instance,
                        id_projet_avis=doc_projet_avis,
                        emplacement = emplacement
                )

                logger.info(f"[DOSSIER {dossier.numero}] Brouillon de demande d'avis créé : {avis}")

                        
            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Dossier {dossier.numero} : Erreur lors de la création de l'avis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création de l'avis. Contactez le support.")
                
            
            try:
                DossierAvis.objects.create(id_avis=avis, id_dossier=dossier)

            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création du DossierAvis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création du lien entre le dossier et l'avis. Contactez le support.")
                
              
    else :
        logger.error(f"[SAVE BROUILLON AVIS] Erreur lors de la transmission du formulaire par {request.user} : méthode POST requise.")
        return redirect_error(request, f"Erreur lors de la transmission du formulaire : méthode POST requise. Contactez le support.")
        

    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)



@require_POST
@login_required
def supprimer_avis(request):

    avis_id = request.POST.get("avis_id")

    # Récupération AVIS
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[SUPPRESSION AVIS] Avis {avis_id} introuvable en base (user : {request.user}).")
        return redirect_error(request, f"L'avis {avis_id} est introuvable en base. Contactez le support.")

    # L'utilisateur doit être instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[SUPPRESSION AVIS] User {request.user.email} sans profil instructeur a tenté de supprimer l'avis {avis_id}")
        return redirect_error(request, "Vous n'avez pas de profil 'Instructeur.trice'. Contactez le support.")
    
    try:
        avis.delete()
        logger.info(f"Suppression de l'avis ({avis_id}) par {instructeur}")

    except Exception as e:
        logger.error(f"[SUPPRESSION AVIS] Erreur lors de la suppression de l'avis {avis_id} par {instructeur} : {e}")
        messages.error(request, f"Erreur lors de la suppression de l'avis. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def instruction_dossier_avis(request, num_dossier, avis_id):
    """
    Affiche la page de l'avis lié au dossier (Vision instructeur)
    """

    # --- Récupération dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[INSTRUCTION AVIS] Dossier {num_dossier} introuvable par {request.user}")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")


    # --- Récupération avis ---
    avis = Avis.objects.filter(id=avis_id, id_dossier=dossier).first()
    if not avis:
        logger.error(f"[INSTRUCTION AVIS] Avis {avis_id} introuvable par {request.user} pour le dossier {num_dossier}")
        return redirect_error(request, f"L'avis demandé est introuvable. Contactez le support.")


    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    # --- Instructeur du dossier ? ---
    est_instructeur_du_dossier = False
    if instructeur:
        est_instructeur_du_dossier = DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()

    est_demandeur = False
    if avis.id_instructeur == instructeur :
        est_demandeur = True

    # --- Email expert ---
    email_expert = None
    if avis.id_expert:
        if avis.id_expert.est_interne and avis.id_expert.id_instructeur:
            email_expert = avis.id_expert.id_instructeur.email
        elif avis.id_expert.id_contact_externe:
            email_expert = avis.id_expert.id_contact_externe.email

    if not email_expert:
        logger.error(f"[AVIS {avis.id}] Pas d'email expert trouvé")
        return redirect_error(request, f"Erreur lors de la récupération de l'email de l'expert. Contactez le support.")
    
    est_expert = False
    if email_expert == instructeur.email :
        est_expert = True

    # --- Messages non lus envoyés par l'expert ---
    messages_non_lus = (Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert))
    ids_non_lus = list(messages_non_lus.values_list("id", flat=True))
    
    # Mise à jour des mesages non lus --> lus
    if est_demandeur and messages_non_lus :
        nb = messages_non_lus.update(lu=True)
        if nb > 0:
            logger.info(f"[DOSSIER {dossier.numero}] {nb} message(s) non lus ont été marqués comme lus par {request.user}.")


    raw_messages = Message.objects.filter(id_avis=avis).order_by("date_envoi")
    messages_fmt = []

    for msg in raw_messages:  
        nouv_mess = 'non'
        if ids_non_lus != []:
            if msg.id in ids_non_lus :
                nouv_mess = 'oui'

        emetteur = msg.email_emetteur.lower().strip()
        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()

        # left = Message expert, right = Message émis par instructeur
        if est_expert :
            align = "left" if emetteur != email_expert.lower().strip() else "right"
        else :
            align = "right" if emetteur != email_expert.lower().strip() else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_title = pj_emplacement = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()
            if message_doc and message_doc.id_document:   
                pj_title, pj_emplacement = message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess, "emetteur": instru if instru else contact})


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

    resume_pdf_titre = f"dossier-{dossier.numero}.pdf"

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()
    # Messages du pétitionnaire non lus pour le dossier
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)
    # Nombre d'avis avec au moins un message non lu de l'expert
    nb_avis_avec_nouveau_mess = count_avis_with_unread_messages_for_dossier(dossier, num_dossier)


    return render(request, 'instruction/instruction_dossier_avis.html', {
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "dossier": dossier,
        "avis": avis,
        "avis_documents": avis_documents,
        "liste_avis_documents": liste_avis_documents,
        "avis_signes": avis_signes,
        "messages_avis": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_avis_envoyes": nb_avis_envoyes,
        "est_instructeur_du_dossier": est_instructeur_du_dossier,
        "nb_messages_non_lus": nb_messages_non_lus,
        "resume_pdf_titre": resume_pdf_titre,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "est_demandeur": est_demandeur,
        "est_expert": est_expert,
    })



@require_POST
@csrf_exempt
def envoyer_message_avis(request):
    """
    Envoi d’un message dans la messagerie d’un avis.
    Gère texte, PJ, log, notifications expert.
    """
    
    # Récupération message et PJ de l'instructeur
    avis_id = request.POST.get("avis_id")
    dossier_numero = request.POST.get("dossier_numero")
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    if not body:
        return redirect_error(request, "Message vide")
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        return redirect_error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
    

    # --- Récupération Avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[ENVOI MSG AVIS] Avis {avis_id} introuvable par {request.user}")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")

    # --- Récupération Dossier ---
    dossier = Dossier.objects.filter(numero=dossier_numero).first()
    if not dossier:
        logger.error(f"[ENVOI MSG AVIS] Avis {avis_id} : Dossier {dossier_numero} introuvable par {request.user}")
        return redirect_error(request, "Le dossier est introuvable. Contactez le support.")
    

    # Récupérer l'instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not instructeur :
        logger.warning(f"[ENVOI MSG AVIS] User {request.user.email} sans profil instructeur a tenté d'envoyer un message sur l'avis {avis.id} (Dossier {dossier_numero})")
        return redirect_error(request, f"Echec de l'envoi du message : Vous n'avez pas de profil 'Instructeur'. Contatez l'administration")

    # --- Création message ---
    try: 
        if fichier:

            fichier.seek(0)
            fichier_bdd = SimpleUploadedFile(
                name=fichier.name,
                content=fichier.read(),
                content_type=fichier.content_type
            )
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis,
                document_file=fichier_bdd,
                document_title=fichier.name,
                document_format_str=fichier.name.split('.')[-1].lower(),
                document_description=f"Pièce jointe instructeur dans la messagerie de l'avis {avis.id}",
            )

        else:
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis
            )

        
    except Exception as e:
        logger.error(f"[ENVOI MSG AVIS] Dossier {dossier_numero}, Avis {avis.id} : Erreur lors de l'envoi du message : {e}")
        return redirect_error(request, f"Erreur lors de l'envoi du message. Contactez le support.")

    
    
    ####################################
    # NOTIFICATION PAR MAIL A L'EXPERT
    ####################################
    email_expert = get_email_expert(avis, dossier_numero)
    if not email_expert:
        logger.error(f"[ENVOI MSG AVIS] Dossier {dossier_numero}, Avis {avis.id} : L'expert {avis.id_expert} n'a pas été notifié car son adresse mail n'a pas été trouvée.")
        return redirect_error(request, "Message envoyé, mais l’expert n’a pas pu être notifié par mail. Contactez le support pouren savoir plus.")

    # On notifie les agents dans le cadre d'une vraie instruction
    if NOTIFS_PROD :
        emails_norm = [get_email_expert(avis)]
    # Test de notification par mail à EMAIL_NOTIF_TEST   
    else :
        emails_norm = [EMAIL_NOTIF_TEST]


    sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : Vous avez un nouveau message"

    context = {
        "avis_numero": avis.id,
        "demarche_type": avis.id_demarche.type,
        "demandeur": str(avis.id_instructeur),
        "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
    }
    template_name = "nouveau_message_demandeur" 

    try :
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

    except Exception as e:
        logger.error(f"[ENVOI MSG AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
        return redirect_error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    
    # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
    existe_deja = EmailOutbox.objects.filter(
        dedupe_key=dedupe,
        date_creation__gte= timezone.now() - timedelta(hours=2)
    ).exists()

    if not existe_deja:
        outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Notification")

        if outbox :
            ok, err = envoi_mail(outbox.id)
        else :
            logger.error(f"[AVIS {avis.id}] Nouveau message demandeur : Erreur lors de la création de l'EmailOutbox, {avis.id_expert} n'a pas été notifié par mail.")
            messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

        if ok:
            logger.info(f"[AVIS {avis.id}] Notification Email {outbox.id} (Nouveau message demandeur) envoyée à {', '.join(outbox.to)} ")
        else:
            logger.error(f"[AVIS {avis.id}] Échec envoi notification email {outbox.id} (Nouveau message demandeur) à {', '.join(outbox.to)} : {err}")
            messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@csrf_exempt
def envoyer_message_avis_vision_expert(request):
    #Cette vue peut etre appelée par l'expert ou le demandeur

    avis_id = request.POST.get("avis_id")
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    # --- Avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis_id} introuvable par {request.user}")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")
        

    if not body:
        messages.error(request, "Message vide.")
        
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        return redirect_error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
        
 
    try: 
        if fichier:

            fichier.seek(0)
            fichier_bdd = SimpleUploadedFile(
                name=fichier.name,
                content=fichier.read(),
                content_type=fichier.content_type
            )
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis,
                document_file=fichier_bdd,
                document_title=fichier.name,
                document_format_str=fichier.name.split('.')[-1].lower(),
                document_description=f"Pièce jointe instructeur dans la messagerie de l'avis {avis.id}",
            )

        else:
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis
            )

        
    except Exception as e:
        logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis_id} : Erreur lors de l'envoi du message : {e}")
        return redirect_error(request, f"Erreur lors de l'envoi du message. Contactez le support.")
        
    


    email_expert = get_email_expert(avis, None)
    email_demandeur = avis.id_instructeur.email if avis.id_instructeur else None


    if email_expert == request.user.email :
        ####################################
        # NOTIFICATION PAR MAIL AU DEMANDEUR
        ####################################

        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = [email_demandeur]
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]


        sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : Nouveaux messages de l'expert.e"
        
        context = {
            "avis_numero": avis.id,
            "demarche_type": avis.id_demarche.type,
            "expert": str(avis.id_expert),
            "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
        }
        template_name = "nouveau_message_expert" 
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")
            

        # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
        existe_deja = EmailOutbox.objects.filter(
            dedupe_key=dedupe,
            date_creation__gte= timezone.now() - timedelta(hours=2)
        ).exists()

        if not existe_deja:
            outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

            if outbox :
                ok, err = envoi_mail(outbox.id)
            else :
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de l'EmailOutbox, {avis.id_instructeur} (demandeur) n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

            if ok:
                logger.info(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Notification Email {outbox.id} (Nouveau message de l'expert) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Échec envoi notification email {outbox.id} (Nouveau message de l'expert) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")


    else :
        ####################################
        # NOTIFICATION PAR MAIL A L'EXPERT
        ####################################

        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = [get_email_expert(avis)]
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]


        sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : Vous avez un nouveau message"

        context = {
            "avis_numero": avis.id,
            "demarche_type": avis.id_demarche.type,
            "demandeur": str(avis.id_instructeur),
            "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
        }
        template_name = "nouveau_message_demandeur" 

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")
            

        # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
        existe_deja = EmailOutbox.objects.filter(
            dedupe_key=dedupe,
            date_creation__gte= timezone.now() - timedelta(hours=2)
        ).exists()

        if not existe_deja:
            outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

            if outbox :
                ok, err = envoi_mail(outbox.id)
            else :
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de l'EmailOutbox, {avis.id_expert} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

            if ok:
                logger.info(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Notification Email {outbox.id} (Nouveau message du demandeur) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Échec envoi notification email {outbox.id} (Nouveau message du demandeur) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))




# @require_POST
# def supprimer_document_avis(request, avis_id, champ):
#     """
#     Supprime une pièce jointe d’un avis
#     """

#     # --- Récupération Avis ---
#     avis = Avis.objects.filter(id=avis_id).first()
#     if not avis:
#         logger.error(f"[SUPPRESSION DOC AVIS] Avis {avis_id} introuvable par {request.user}")
#         messages.error(request, "L'avis est introuvable. Contactez le support.")
#         return redirect(request.META.get("HTTP_REFERER", "/"))
    

#     if champ not in ["id_projet_acte", "id_rapport_instance", "id_projet_avis"]:
#         messages.error(request, "Champ de document invalide")
#         return redirect(request.META.get("HTTP_REFERER", "/"))

#     setattr(avis, champ, None)
#     avis.save(update_fields=[champ])

#     return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def mettre_a_jour_note_avis(request, avis_id):

    # --- Récupération avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[MAJ NOTE AVIS] Avis {avis_id} introuvable par {request.user}")
        return redirect_error(request, "L'avis est introuvable. Contactez le support.")
    
    # --- Validation instructeur ---
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[MAJ NOTE AVIS] User {request.user} sans profil instructeur a tenté de modifier la note de l'avis {avis_id}")
        return redirect_error(request, "Vous devez disposer d'un profil instructeur pour modifier cette note. Contactez le support.")
    
    try :
        note = request.POST.get("note", "").strip()
        avis.note = note
        avis.save()

    except Exception as e:
        logger.error(f"[MAJ NOTE AVIS] Erreur lors de la mise à jour de la note de l'avis {avis_id} par {request.user} : {e}")
        messages.error(request, "Erreur lors de la mise à jour de la note. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def nouvelle_demande_avis_generique(request):
    
    try :

        # Récupérer toutes les natures et thématiques
        natures = AvisNature.objects.all().order_by("nature")
        thematiques = AvisThematique.objects.all().order_by("thematique")
        demarches = Demarche.objects.all().order_by("type")

        # Instructeur courant (user connecté)
        instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur_connecte:
            logger.warning(f"[NOUVELLE DEMANDE AVIS GÉNÉRIQUE] User {request.user} a tenté une demande d'avis sans profil instructeur.")
            return redirect_error(request, "Vous devez disposer d'un profil instructeur pour créer une demande d’avis. Contactez le support.")

        # Instructeurs candidats
        instructeurs_ = Instructeur.objects.filter(email__isnull=False).exclude(email__exact="").exclude(email__exact="autorisations@reunion-parcnational.fr").order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")

        # Contacts externes candidats
        contacts_ = ContactExterne.objects.filter(email__isnull=False, id_type__type="Instance").exclude(email__exact="").order_by("nom", "email")

        # Supprimer les doublons d'email (si jamais)
        instructeurs = {i.email: i for i in instructeurs_}.values()
        contacts_externes = {c.email: c for c in contacts_}.values()

    except Exception as e:
        logger.error(f"[NOUVELLE DEMANDE GENERIQUE] Erreur inattendue (user {request.user}) : {e}")
        return redirect_error(request, "Erreur lors du chargement des données. Contactez le support.")
    

    return render(request, "instruction/avis_nouvelle_demande_generique.html", {
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "contacts_externes": contacts_externes,
        "demarches": demarches,
    })



@require_POST
@login_required
def avis_confirmer_nouvelle_demande_generique(request):
    

    # --- Récupération instructeur ---
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[CONFIRMER AVIS GENERIQUE] Le user {request.user} a tenté de confirmer une nouvelle demande d'avis générique sans profil Instructeur.")
        return redirect_error(request, "Vous devez disposer d'un profil instructeur pour créer une demande d’avis. Contactez le support.")
    
    
    # Champs du formulaire
    nature_id = request.POST.get("nature")
    demarche_id = request.POST.get("demarche")
    thematique_id = request.POST.get("thematique")
    note = request.POST.get("note_demandeur", "").strip()
    formulation_avis = request.POST.get("formulation_avis")
    expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
    expert_externe_id = request.POST.get("expert_externe") # contact externe ici
    pj_projet_avis = request.FILES.get("pj_demande_avis")
    pj_projet_acte = request.FILES.get("pj_projet_acte")
    pj_rapport_cs = request.FILES.get("pj_rapport_cs")
    pjs_avis = request.FILES.getlist("pj_lie_avis")

    
    # --- Récupération nature ---
    try:
        nature = AvisNature.objects.get(id=nature_id)
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de la nature d'avis {nature_id} (User {request.user}) : {e}")
        return redirect_error(request, "Erreur lors de la récupération de la nature d'avis. Contactez le support.")
    

    # --- Récupération thématique ---
    try:
        thematique = AvisThematique.objects.get(id=thematique_id)
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de la thématique {thematique_id} (User {request.user}) : {e}")
        return redirect_error(request, "Erreur lors de la récupération de la thématique. Contactez le support.")


    # --- Récupération démarche ---
    try:
        demarche = Demarche.objects.get(id=demarche_id)
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de la démarche {demarche_id} (User {request.user}) : {e}")
        return redirect_error(request, "Erreur lors de la récupération de la démarche. Contactez le support.")

    # --- EXPERT ---
    try:
        expert, nom_prenom_expert = get_or_create_expert_from_form(request)

    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de l'expert : {e}")
        return redirect_error(request, "Erreur lors de la récupération de l'expert. Contactez le support.")
        
    
    # --- Emplacement ---
    emplacement_avis = f"Avis/{nettoyer_nom_fichier(demarche.type)}/{date.today().year}/{nom_prenom_expert}_{date.today().strftime('%d_%m')}/"
    doc_projet_acte = doc_rapport_instance = doc_projet_avis = None
    jour_mois_annee = date.today().strftime("%d/%m/%Y")
    
    if pj_projet_avis or pj_projet_acte or pj_rapport_cs or pjs_avis :
        chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement_avis}Annexes/"
        creer_dossier_sur_nas(chemin_complet)


    # --- Écriture fichiers ---
    if pj_projet_avis :
        extension = Path(pj_projet_avis.name).suffix.lower()
        if extension not in {".doc", ".docx", ".odt"} :
            return redirect_error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
        
        doc_projet_avis = enregistrer_document(
            fichier=pj_projet_avis,
            nature_str="Annexe avis",
            description=f"Projet de demande pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
            request=request,
            emplacement_avis = emplacement_avis,
        )
    
    if pj_projet_acte :
        extension = Path(pj_projet_acte.name).suffix.lower()
        if extension not in {".doc", ".docx", ".odt", ".pdf"} :
            logger.error(f"[CONFIRMER AVIS GENERIQUE] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .doc, .docx, .odt, .pdf")
            return redirect_error(request, f"❌ Le projet d'acte doit etre au format .doc, .docx, .odt ou .pdf --> Type de fichier non autorisé : {extension}")
        
        doc_projet_acte = enregistrer_document(
            fichier=pj_projet_acte,
            nature_str="Annexe avis",
            description=f"Projet d’acte pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
            request=request,
            emplacement_avis = emplacement_avis,
        )
    
    if pj_rapport_cs :
        extension = Path(pj_rapport_cs.name).suffix.lower()
        if extension != ".pdf" :
            return redirect_error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
        
        doc_rapport_instance = enregistrer_document(
            fichier=pj_rapport_cs,
            nature_str="Annexe avis",
            description=f"Rapport Instance pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
            request=request,
            emplacement_avis = emplacement_avis,
        )



    # --- Création Avis ---
    try:

        avis = Avis.objects.create(
                id_avis_nature=nature,
                id_avis_thematique=thematique,
                date_demande_avis=timezone.now(),
                statut="Envoyé",
                note=note,
                formulation= formulation_avis,
                mode_contact="Application",
                id_demarche = demarche,
                id_expert=expert,
                id_instructeur=instructeur,
                id_projet_acte=doc_projet_acte,
                id_rapport_instance=doc_rapport_instance,
                id_projet_avis=doc_projet_avis,
                emplacement = emplacement_avis,
        )

        logger.info(f"[AVIS GENERIQUE {avis.id}] Avis créé par {request.user}")
    
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la création de l'avis : {e}")
        return redirect_error(request, "Erreur lors de la création de l'avis. Contactez le support.")
    

    # Pièces jointes annexes
    if pjs_avis :
        for pj in pjs_avis :
            # extension = Path(pj.name).suffix.lower()
            try :
                doc_pj_avis = enregistrer_document(
                    fichier=pj,
                    nature_str="Annexe avis",
                    description=f"Pièce jointe du demandeur pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
                    request=request,
                    emplacement_avis = emplacement_avis,
                )
                
                AvisDocument.objects.get_or_create(id_avis=avis, id_document=doc_pj_avis)
                
            except Exception as e:
                logger.error(f"[AVIS GENERIQUE {avis.id}] Erreur lors de l'enregistrement d'une pièce jointe : {e}")
                messages.error(request, "Erreur lors de l'enregistrement d'une pièce jointe. Contactez le support.")
                return redirect('avis_expert', avis_id=avis.id)


    # Create message (formulation)
    if avis.formulation :
        try:
            msg = Message.objects.create(
                body=avis.formulation,
                date_envoi=timezone.now(),
                piece_jointe=True if doc_projet_avis else False,
                email_emetteur=request.user.email,
                id_avis=avis,
                lu=False,
            )

            # Joindre le projet de demande d'avis au message
            if doc_projet_avis :
                MessageDocument.objects.create(id_message=msg, id_document=doc_projet_avis)

            logger.info(f"[AVIS GENERIQUE {avis.id}] : Message par défaut envoyé à {avis.id_expert}")

        except Exception as e:
            logger.error(f"[AVIS GENERIQUE {avis.id}] Erreur lors de la création du message initial : {e}")
            messages.error(request, "Erreur lors de la création du message initial. Contactez le support.")
            return redirect('avis_expert', avis_id=avis.id)

    
    #################################
    # NOTIFICATION PAR MAIL À L'EXPERT
    #################################

    # On notifie les agents dans le cadre d'une vraie instruction
    if NOTIFS_PROD :
        emails_norm = [get_email_expert(avis)]
    # Test de notification par mail à EMAIL_NOTIF_TEST   
    else :
        emails_norm = [EMAIL_NOTIF_TEST]


    # Demande générique non liée à un dossier
    if avis.id_demarche.type :
        sujet = f"{avis.id_instructeur} vous demande votre avis ({avis.id_demarche.type})"
    else :
        sujet = f"{avis.id_instructeur} vous demande votre avis"


    context = {
        "avis_numero": avis.id,
        "demarche_type": avis.id_demarche.type,
        "demandeur": str(avis.id_instructeur),
        "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
    }
    template_name = "nouvelle_demande_avis_generique" 


    try :
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

    except Exception as e:
        messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")
        logger.error(f"[AVIS GENERIQUE {avis.id}] Nouvelle demande : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
        return redirect('avis_expert', avis_id=avis.id)

    outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

    if outbox :
        ok, err = envoi_mail(outbox.id)
    else :
        logger.error(f"[NOUVELLE DEMANDE D'AVIS] Erreur lors de la création de l'EmailOutbox, {expert} n'a pas été notifié par mail.")
        messages.error(request, f"L'email de notification à {expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    if ok:
        logger.info(f"[NOUVELLE DEMANDE D'AVIS] Notification Email {outbox.id} (Nouvelle demande d'avis) envoyée à {', '.join(outbox.to)} ")
    else:
        logger.error(f"[NOUVELLE DEMANDE D'AVIS] Échec envoi notification email {outbox.id} (Nouvelle demande d'avis) à {', '.join(outbox.to)} : {err}")
        messages.error(request, f"L'email de notification à {expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    
    return redirect('avis_expert', avis_id=avis.id)



@login_required
def remplacer_document_avis(request):
    """
    Remplacement sécurisé d'un document (Projet d'avis, Projet d'acte, Rapport du conseil) lié à un avis.
    - Si le document est partagé par plusieurs avis → création d’un nouveau Document.
    - Sinon → remplacement du fichier + mise à jour de l’objet Document.
    """

    avis_id = request.POST.get("avis_id")
    document_id = request.POST.get("document_id")
    fichier = request.FILES.get("fichier")

    if not avis_id or not document_id or not fichier:
        logger.warning(f"[REMPLACER DOC AVIS] Tentative de remplacement de document lié à un avis par {request.user}. Information manquante.")
        return redirect_error(request, "❌ Données manquantes.")

    # --- Récupération Avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[REMPLACER DOC] Avis {avis_id} introuvable.")
        return redirect_error(request, "Avis introuvable. Contactez le support.")

    # --- Récupération Document ---
    document = Document.objects.filter(id=document_id).first()
    if not document:
        logger.error(f"[REMPLACER DOC] Avis {avis_id} : Document {document_id} introuvable.")
        return redirect_error(request, "Document introuvable. Contactez le support.")

    # --- Vérification extension ---
    ext = Path(fichier.name).suffix.lower()
    if ext not in [".pdf", ".doc", ".docx", ".odt"]:
        return redirect_error(request, f"❌ Format non autorisé ({ext}). Formats acceptés : .pdf, .doc, .docx, .odt")

    # --- Récupération Format ---
    format_obj = DocumentFormat.objects.filter(format__iexact=ext.lstrip(".")).first()
    if not format_obj:
        return redirect_error(request, f"❌ Format '{ext}' introuvable en base. Contactez le support.")


    root = os.environ.get("NAS_ROOT", "")
    creer_dossier_sur_nas(os.path.join(root, document.emplacement))

    # --- DOCUMENT PARTAGÉ ?
    utilisations = Avis.objects.filter(
        models.Q(id_projet_avis=document) |
        models.Q(id_projet_acte=document) |
        models.Q(id_rapport_instance=document)
    ).distinct()

    est_partage = utilisations.count() > 1


    try:
        # =====================================================
        #  CAS 1 : DOCUMENT PARTAGÉ → création d’un nouveau doc
        # =====================================================

        if est_partage:
            nom_base, ext = os.path.splitext(fichier.name)
            titre_final = nom_base
            i = 1
            repertoire_absolu = os.path.join(root, document.emplacement)

            # Boucle pour éviter doublons (fichier + enregistrement)
            while True:
                chemin_candidat = os.path.join(repertoire_absolu, f"{titre_final}{ext}")
                existe_fichier = smbclient.path.exists(chemin_candidat)
                existe_enregistrement = Document.objects.filter(
                    emplacement=document.emplacement,
                    titre=f"{titre_final}{ext}"
                ).exists()

                if not existe_fichier and not existe_enregistrement:
                    break  # nom libre

                i += 1
                titre_final = f"{nom_base}_{i}"

            # Écriture du fichier sur le NAS
            if not ecrire_file_sur_nas(fichier, chemin_candidat): 
                # logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {chemin_candidat}")
                raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {chemin_candidat}")

            logger.info(f"[AVIS {avis.id}] Nouveau fichier créé par {request.user} : {chemin_candidat}")

            # Création du nouvel enregistrement Document
            nouveau_doc = Document.objects.create(
                id_format=format_obj,
                id_nature=document.id_nature,
                id_statut=document.id_statut,
                url_ds=document.url_ds,
                emplacement=document.emplacement,
                description=f"Nouveau document pour l'avis {avis.id}",
                titre=f"{titre_final}{ext}",
                numero=document.numero,
            )

            # On détermine quel champ de l’avis doit être mis à jour
            if avis.id_projet_avis_id == document.id:
                avis.id_projet_avis = nouveau_doc
            elif avis.id_projet_acte_id == document.id:
                avis.id_projet_acte = nouveau_doc
            elif avis.id_rapport_instance_id == document.id:
                avis.id_rapport_instance = nouveau_doc

            avis.save()


        # =====================================================
        #  CAS 2 : DOCUMENT NON PARTAGÉ → on écrase l'ancien doc
        # ======================================================
        else:
            ancien_chemin = os.path.join(root, document.emplacement, document.titre)
            nouveau_chemin = os.path.join(root, document.emplacement, fichier.name)

            # Si doublon exact de nom → incrémentation aussi
            nom_base, ext = os.path.splitext(fichier.name)
            titre_final = nom_base
            i = 1

            while Document.objects.filter(emplacement=document.emplacement, titre=f"{titre_final}{ext}").exclude(id=document.id).exists():
                titre_final = f"{nom_base}_{i}"
                i += 1

            nouveau_chemin = os.path.join(root, document.emplacement, f"{titre_final}{ext}")

            # Étape 1 : Écriture du nouveau fichier
            if not ecrire_file_sur_nas(fichier, nouveau_chemin): 
                # logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {nouveau_chemin}")
                raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {nouveau_chemin}")
            
            # Étape 2 : Supprimer l’ancien fichier
            if not supprimer_file_sur_nas(ancien_chemin):
                logger.error(f"[AVIS {avis.id}] ❌ Erreur lors de la suppression de l'ancien fichier {ancien_chemin} par {request.user}")

            # Mise à jour document
            document.titre = f"{titre_final}{ext}"
            document.id_format = format_obj
            document.description = f"Remplacement du {document.id_nature.nature} pour l'avis {avis.id}"
            document.save()

            logger.info(f"[AVIS {avis.id}] Document remplacé par {request.user} : {nouveau_chemin}")

    except Exception as e:
        logger.error(f"[AVIS {avis.id}] Erreur lors du remplacement du document : {e}")
        messages.error(request, f"❌ Erreur lors du remplacement du document. Contatez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))