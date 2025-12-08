from datetime import datetime, date, timedelta
import time
from django.utils import timezone
import json
import os
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.http import FileResponse, Http404, JsonResponse
import urllib

import smbclient
from autorisations.models.models_instruction import Dossier, DossierChamp, DossierManifSportive, EtapeDossier, Message, SynchronisationEtat
from autorisations.models.models_utilisateurs import ContactExterne, DossierEnvoiActe, DossierInstructeur, DossierIntermediaireSignature, DossierPublicationRAA, DossierRelecteurQualite, DossierValideur, EmailOutbox, GroupeinstructeurInstructeur, Instructeur, Groupeinstructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument
from autorisations.models.models_avis import Avis, Expert
from autorisations.utils.nas_fonctions import ecrire_file_sur_nas, supprimer_file_sur_nas
from instruction.utils.dossier_utils import redirect_error, safe_enregistrer_action
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from instruction.utils_instru import dossiers_action_a_faire, dossiers_reception_action_a_faire, enregistrer_action
from synchronisation.src.main import lancer_normalisation_et_synchronisation, lancer_normalisation_et_synchronisation_pour_une_demarche
from threading import Lock
import threading
import subprocess
import sys
from mimetypes import guess_type
from django.contrib import messages
import logging
from django.db.models import Q
from django.utils.timezone import now
from autorisations import settings
from django.db import close_old_connections
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator


logger = logging.getLogger("ORM_DJANGO")
loggerSynchro = logging.getLogger("SYNCHRONISATION")
loggerDS = logging.getLogger("API_DS")  


# @login_required(login_url='/login/')
# def requetes(request):
#     return render(request, 'instruction/requetes.html')


def lancer_en_arriere_plan2():
    """
    Démarre la synchro si et seulement si le flag en BDD est à False.
    Retourne True si démarré, False si déjà en cours.
    """
    # S'assurer que la ligne existe
    SynchronisationEtat.objects.get_or_create(id=1, defaults={"en_cours": False})

    # Tentative atomique: on passe en True seulement si c'est actuellement False
    rows = (SynchronisationEtat.objects
            .filter(id=1, en_cours=False)
            .update(en_cours=True, date_derniere_tentative=timezone.localtime(timezone.now())))

    if rows == 0:
        logger.warning("Synchro déjà en cours – nouvelle tentative ignorée (BDD).")
        return False

    def lancement_et_suivi():
        close_old_connections()
        try:

            with open("logs/synchronisation.log", "a", buffering=1) as f:
                process = subprocess.Popen(
                    [sys.executable, "synchronisation/src/lancer_synchronisation.py"],
                    stdout=f, stderr=f,
                )

        except Exception:
            logger.exception("Erreur lors du sous-processus de synchronisation.")

        finally:
            close_old_connections()

    threading.Thread(target=lancement_et_suivi).start()
    return True



@login_required
def actualiser_donnees(request):
    if request.method == "POST":
        lancé = lancer_en_arriere_plan2()
        if not lancé:
            return JsonResponse({
                "status": "already_running",
                "message": "Une actualisation est déjà en cours."
            })
        return JsonResponse({"status": "ok", "message": "Synchronisation lancée."})
    return JsonResponse({"status": "error", "message": "Requête invalide"})



@login_required
def etat_actualisation(request):
    etat = SynchronisationEtat.objects.filter(id=1).first()

    # Timeout de sécurité : si ça dépasse 1h, on force en_cours=False
    TIMEOUT_RESET_FLAG = 60
    if ( etat.en_cours and etat.date_derniere_tentative and timezone.localtime(etat.date_derniere_tentative) < timezone.localtime(timezone.now()) - timedelta(minutes=TIMEOUT_RESET_FLAG)):
        
        loggerSynchro.warning(f"Réinitialisation forcée du flag 'en_cours' (timeout de {TIMEOUT_RESET_FLAG} minutes dépassé) – dernière tentative : {timezone.localtime(etat.date_derniere_tentative)}")
        etat.en_cours = False
        etat.save(update_fields=["en_cours"])

    if not etat:
        return JsonResponse({"en_cours": False, "dernier_statut": "inconnu", "date_maj": None, "date_derniere_tentative": None})

    return JsonResponse({
        "en_cours": etat.en_cours,
        "dernier_statut": etat.dernier_statut,
        "date_maj": etat.date_maj.isoformat() if etat.date_maj else None,
        "date_derniere_tentative": etat.date_derniere_tentative.isoformat() if etat.date_derniere_tentative else None,
    })



@login_required
def rediriger_vers_dossier_precedent(request, num_dossier_precedent):
    """
    Redirige vers le dossier précédent si celui-ci existe,
    sinon affiche un message d’erreur et revient sur la page d’origine.
    """
    try:
        numero = int(num_dossier_precedent)
    except ValueError:
        messages.error(request, f"Le numéro '{num_dossier_precedent}' n’est pas valide.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    dossier_prec = Dossier.objects.filter(numero=numero).first()
    if dossier_prec:
        return redirect("instruction_dossier", num_dossier=dossier_prec.numero)
    else:
        messages.error(request, f"Aucun dossier trouvé en base avec le numéro {numero}.")
        return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def se_declarer_instructeur(request):
    
    dossier_id = request.POST.get("dossier_id")
    instructeur_id = request.POST.get("instructeur_id")
    email_user = request.user.email or ""

    # -----------------
    # Vérifications
    # -----------------
    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[AJOUT INSTRUCTEUR] Dossier id={dossier_id} introuvable — User : {email_user}")
        return redirect_error(request, "❌ Dossier introuvable. Contactez le support.")
    
    instructeur_request = Instructeur.objects.filter(email=email_user).first()
    if not instructeur_request:
        logger.error(f"[DOSSIER {dossier.numero}] Le user {request.user} a voulu ajouter un instructeur au dossier, or il n'a pas de profil 'Instructeur'.")
        return redirect_error(request, "❌ Vous n’avez pas de profil Instructeur. Contactez le support si besoin.")

    instructeur = Instructeur.objects.filter(id=instructeur_id).first()
    if not instructeur:
        logger.error(f"[DOSSIER {dossier.numero}] User : {email_user}, Ajout instructeur impossible — instructeur_id={instructeur_id} inexistant.")
        return redirect_error(request, "❌ Instructeur introuvable. Contactez le support.")

    if not dossier.id_groupeinstructeur:
        logger.error(f"[DOSSIER {dossier.numero}] User : {email_user}, Ajout de l'instructeur {instructeur} impossible — aucun groupe instructeur affecté.")
        return redirect_error(request, "❌ Aucun groupe instructeur n’est affecté au dossier. Contactez le support.")

    # L'instructeur doit appartenir au groupe instructeur
    instructeurs_du_groupe = set(dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.values_list("id_instructeur_id", flat=True))

    if instructeur.id not in instructeurs_du_groupe:
        logger.error(f"[DOSSIER {dossier.numero}] Ajout instructeur refusé — {instructeur} n'appartient pas au groupe {dossier.id_groupeinstructeur.nom}")
        return redirect_error(request,"❌ Vous ne pouvez pas ajouter cet instructeur : il n’appartient pas au groupe instructeur du dossier.")


    DossierInstructeur.objects.get_or_create(id_dossier=dossier, id_instructeur=instructeur)
    logger.info(f"[DOSSIER {dossier.numero}] Instructeur {instructeur} ajouté par {request.user}.")

    # nom_prenom = instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom
    nom_prenom = (
        f"{instructeur.id_agent_autorisations.nom} {instructeur.id_agent_autorisations.prenom}"
        if instructeur.id_agent_autorisations
        else instructeur.email
    )
    
    # Dossier Action
    # enregistrer_action(dossier, instructeur_request, "Instructeur.e ajouté.e", nom_prenom)
    safe_enregistrer_action(dossier, instructeur_request, "Instructeur.e ajouté.e", request, description=nom_prenom)


    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    if email_user != instructeur.email :
        emails_norm = [instructeur.email]
        # print(f"Instructeur à notifier : {emails_norm2}")

        # emails_norm = ["louis.calu@reunion-parcnational.fr"]
        sujet = f"Dossier {dossier.numero} - Vous avez été ajouté.e comme instructeur.rice"
        
        context = {
            "dossier_numero": dossier.numero,
            "demarche_type": dossier.id_demarche.type,
            "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
        }

        template_name = "ajouter_a_instruction" 
        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Ajout de l'instructeur {instructeur} par {request.user} : Erreur lors de la création de la clé unique (compute_dedupe_key), pas d'email de notification : {e}")
            return redirect_error(request, f"L'email de notification à {instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")


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
                logger.error(f"[DOSSIER {dossier.numero}] Instruteur ajouté : Erreur lors de la création de l'EmailOutbox, {instructeur} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Ajout instructeur) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Instructeur ajouté) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")


    return redirect(request.META.get("HTTP_REFERER", "/"))




@require_POST
@login_required
def retirer_instructeur(request):

    dossier_id = request.POST.get("dossier_id")
    instructeur_id = request.POST.get("instructeur_id")
    email_user = request.user.email or ""

    # ---------------------
    # Vérifications
    # ---------------------
    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[RETIRER INSTRUCTEUR] Dossier id={dossier_id} introuvable — User : {email_user}")
        return redirect_error(request, "❌ Dossier introuvable. Contactez le support.")

    instructeur = Instructeur.objects.filter(id=instructeur_id).first()
    if not instructeur:
        logger.error(f"[DOSSIER {dossier_id}] Retrait instructeur impossible — instructeur_id={instructeur_id} inexistant.")
        request.session["retirer_instructeur_message"] = "Instructeur introuvable."
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    instructeur_en_cours = Instructeur.objects.filter(email=email_user).first()
    if not instructeur_en_cours:
        logger.error(f"[DOSSIER {dossier_id}] Le user {request.user} a tenté de retirer l'instructeur {instructeur} sans profil instructeur.")
        request.session["retirer_instructeur_message"] = "Instructeur introuvable."
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # L'instructeur visé est-il instructeur du dossier
    instructeurs_ids = list(DossierInstructeur.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True))
    if instructeur.id not in instructeurs_ids:
        request.session["retirer_instructeur_message"] = "Cet instructeur n'est pas affecté à ce dossier."
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # Simuler le retrait
    instructeurs_restants_ids = [i for i in instructeurs_ids if i != instructeur.id]

    if not instructeurs_restants_ids:
        request.session["retirer_instructeur_message"] = "Impossible de retirer l'instructeur : il faut au moins un autre instructeur affecté au dossier."
        return redirect(request.META.get("HTTP_REFERER", "/"))

    groupe = dossier.id_groupeinstructeur
    if not groupe:
        request.session["retirer_instructeur_message"] = "Aucun groupe instructeur n’est défini pour ce dossier. Contactez le support."
        return redirect(request.META.get("HTTP_REFERER", "/"))

    instructeurs_groupe_ids = set(GroupeinstructeurInstructeur.objects.filter(id_groupeinstructeur=groupe).values_list("id_instructeur", flat=True))

    if not (set(instructeurs_restants_ids) & instructeurs_groupe_ids):
        request.session["retirer_instructeur_message"] = ("Impossible de retirer l'instructeur : aucun instructeur restant n'appartient au groupe instructeur.")
        return redirect(request.META.get("HTTP_REFERER", "/"))


    # ---------------------
    # Retrait autorisé
    # ---------------------
    DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).delete()
    logger.info(f"[DOSSIER {dossier.numero}] {instructeur_en_cours} a retiré l'instructeur {instructeur}.")

    nom_prenom = (
        f"{instructeur.id_agent_autorisations.nom} {instructeur.id_agent_autorisations.prenom}"
        if instructeur.id_agent_autorisations
        else instructeur.email
    )

    # Dossier Action
    safe_enregistrer_action(dossier, instructeur_en_cours, "Instructeur.e retiré.e", request, description=nom_prenom)


    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    if email_user != instructeur.email :
        emails_norm = [instructeur.email]
        # print(f"Instructeur à notifier : {emails_norm2}")

        # emails_norm = ["louis.calu@reunion-parcnational.fr"]
        sujet = f"Dossier {dossier.numero} - Vous avez été retiré.e de l'instruction"

        context = {
            "dossier_numero": dossier.numero,
            "demarche_type": dossier.id_demarche.type,
            "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
        }
        template_name = "retirer_de_instruction"

        try:
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Retrait instructeur : {instructeur} n'a pas été notifié par mail. Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

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
                logger.error(f"[DOSSIER {dossier.numero}] Instruteur retiré : Erreur lors de la création de l'EmailOutbox, {instructeur} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                
            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Instructeur retiré) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Instructeur retiré) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def changer_valideur(request):
    dossier_id = request.POST.get("dossier_id")
    new_valideur_id = request.POST.get("new_valideur_id")

    # ---------------------
    # Vérifications
    # ---------------------
    if not dossier_id:
        logger.error(f"[CHANGER VALIDEUR] User={request.user} : ID du dossier manquant dans le formulaire.")
        request.session["changer_valideur_message"] = ("L'id du dossier est manquant. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    if not new_valideur_id:
        logger.error(f"[CHANGER VALIDEUR] User={request.user} : ID du valideur manquant dans le formulaire.")
        request.session["changer_valideur_message"] = ("L'id du nouveau validant est manquant. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[CHANGER VALIDEUR] Dossier id={dossier_id} introuvable — User={request.user}")
        request.session["changer_valideur_message"] = ("Dossier introuvable.  Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    instructeur_en_cours = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur_en_cours:
        logger.error(f"[DOSSIER {dossier.numero}] Le user {request.user} sans profil instructeur a tenté de changer un validant.")
        request.session["changer_valideur_message"] = ("Vous devez disposer d’un profil Instructeur. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    new_valideur = Instructeur.objects.filter(id=new_valideur_id).first()
    if not new_valideur:
        logger.error(f"[DOSSIER {dossier_id}] Changer de validant - User : {request.user}. Nouveau validant id={new_valideur_id} introuvable")
        request.session["changer_valideur_message"] = ("Nouveau validant introuvable. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # Ancien valideur
    id_old_valideur = DossierValideur.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True).first()
    old_valideur = Instructeur.objects.filter(id=id_old_valideur).first()

    # S'assurer que le nouveau valideur est différent
    if old_valideur and old_valideur.id == new_valideur.id:
        request.session["changer_valideur_message"] = ("Le/la validant·e sélectionné·e est déjà affecté·e à ce dossier.")
        return redirect(request.META.get("HTTP_REFERER", "/"))


    # -----------------------
    # Mise à jour BDD
    # -----------------------
    try :
        # Suppression de l'ancien valideur
        if old_valideur:
            DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=old_valideur).delete()

        # Ajout du nouveau valideur
        DossierValideur.objects.get_or_create(id_dossier=dossier, id_instructeur=new_valideur)
        logger.info(f"[DOSSIER {dossier.numero}] Validant changé : {old_valideur} → {new_valideur} (par {request.user})")
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] User : {request.user}. Erreur lors du changement de validant ({old_valideur} → {new_valideur}) : {e}")
        return redirect_error(request, "❌ Erreur lors du changement de validant. Contactez le support.")

    # Dossier Action
    safe_enregistrer_action(dossier, instructeur_en_cours, "Validant.e changé.e", request, description=f"→ {new_valideur}")


    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    if instructeur_en_cours != new_valideur :

        emails_norm = [new_valideur.email]
        # print(f"Valideur à notifier : {emails_norm2}")

        # emails_norm = ["louis.calu@reunion-parcnational.fr"]
        sujet = f"Dossier {dossier.numero} - Vous êtes désormais le-la validant.e du dossier"

        context = {
                    "dossier_numero": dossier.numero,
                    "demarche_type": dossier.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
                }
        template_name = "changer_validant"

        try:
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] User : {request.user} - Changer de validant. {new_valideur} n'a pas été notifié par mail. Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {new_valideur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

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
                logger.error(f"[DOSSIER {dossier.numero}] Nouveau validant : Erreur lors de la création de l'EmailOutbox, {new_valideur} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {new_valideur} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                
            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Nouveau validant) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Nouveau validant) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {new_valideur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def changer_relecteur(request):

    dossier_id = request.POST.get("dossier_id")
    new_relecteur_id = request.POST.get("new_relecteur_id")
    email_user = request.user.email or ""

    # -----------------
    # Vérifications 
    # -----------------
    if not dossier_id:
        logger.error(f"[CHANGER RELECTEUR] User={request.user} : dossier_id manquant.")
        request.session["changer_relecteur_qualite_message"] = ("Identifiant du dossier manquant. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    if not new_relecteur_id:
        logger.error(f"[CHANGER RELECTEUR] User={request.user} : new_relecteur_id manquant.")
        request.session["changer_relecteur_qualite_message"] = ("Identifiant du nouveau relecteur manquant. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[CHANGER RELECTEUR] Dossier id={dossier_id} introuvable — User : {email_user}")
        request.session["changer_relecteur_qualite_message"] = ("Dossier introuvable. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    instructeur_en_cours = Instructeur.objects.filter(email=email_user).first()
    if not instructeur_en_cours:
        logger.error(f"[DOSSIER {dossier.numero}] User {request.user} sans profil instructeur a tenté de modifier un relecteur.")
        request.session["changer_relecteur_qualite_message"] = ("Vous devez disposer d’un profil Instructeur. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    new_relecteur = Instructeur.objects.filter(id=new_relecteur_id).first()
    if not new_relecteur:
        logger.error(f"[DOSSIER {dossier.numero}] Nouveau relecteur id={new_relecteur_id} introuvable — User : {instructeur_en_cours}")
        request.session["changer_relecteur_qualite_message"] = ("Nouveau relecteur introuvable. Contactez le support.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Ancien relecteur
    id_old_relecteur = DossierRelecteurQualite.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True).first()
    old_relecteur = Instructeur.objects.filter(id=id_old_relecteur).first()

    # S'assurer que le nouveau relecteur est différent
    if old_relecteur and old_relecteur.id == new_relecteur.id:
        request.session["changer_relecteur_qualite_message"] = ("Le/la relecteur.rice sélectionné·e est déjà affecté·e à ce dossier.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # -------------------------
    # Mise à jour BDD
    # -------------------------
    try :
        # Suppression de l'ancien relecteur (s'il existe)
        if old_relecteur:
            DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=old_relecteur).delete()
        # Ajout du nouveau valideur
        DossierRelecteurQualite.objects.get_or_create(id_dossier=dossier, id_instructeur=new_relecteur)
        logger.info(f"[DOSSIER {dossier.numero}] Relecteur Qualité changé par {instructeur_en_cours} : {old_relecteur} → {new_relecteur}")
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur MAJ relecteur qualité en BDD ({old_relecteur} → {new_relecteur}) : {e}")
        return redirect_error(request, "❌ Erreur lors du changement de relecteur. Contactez le support.")
    
    # Action dossier
    safe_enregistrer_action(dossier, instructeur_en_cours, "Relecteur.rice changé.e", request, description=f"→ {new_relecteur}")


    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    if instructeur_en_cours != new_relecteur :

        emails_norm = [new_relecteur.email]
        # print(f"Relecteur à notifier : {emails_norm2}")

        # emails_norm = ["louis.calu@reunion-parcnational.fr"]
        sujet = f"Dossier {dossier.numero} - Vous êtes désormais le-la relecteur.rice du dossier"

        context = {
                    "dossier_numero": dossier.numero,
                    "demarche_type": dossier.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
                }
        template_name = "changer_relecteur"

        try:
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] User : {instructeur_en_cours} - Changer de relecteur. {new_relecteur} n'a pas été notifié par mail. Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {new_relecteur} n'a pas été envoyé. Contactez le support.")
        
     
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
                logger.error(f"[DOSSIER {dossier.numero}] Nouveau relecteur : Erreur lors de la création de l'EmailOutbox, {new_relecteur} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {new_relecteur} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                
            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Nouveau relecteur) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Nouveau relecteur) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {new_relecteur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def changer_intermediaire_signature(request):

    dossier_id = request.POST.get("dossier_id")
    new_intermediaire_id = request.POST.get("new_intermediaire_id")
    email_user = request.user.email or ""

    # ----------------
    # Vérifications
    # ----------------
    if not dossier_id:
        logger.error(f"[CHANGER INTERMEDIAIRE SIGNATURE] User={request.user} : dossier_id manquant.")
        return redirect_error(request, "Identifiant du dossier manquant. Contactez le support.")

    if not new_intermediaire_id:
        logger.error(f"[CHANGER INTERMEDIAIRE SIGNATURE] User={request.user} : new_intermediaire_id manquant.")
        return redirect_error(request, "Identifiant du nouvel intermédiaire manquant. Contactez le support.")
    
    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[CHANGER INTERMEDIAIRE SIGNATURE] Dossier id={dossier_id} introuvable — User={request.user}")
        return redirect_error(request, "Dossier introuvable. Contactez le support.")

    instructeur_en_cours = Instructeur.objects.filter(email=email_user).first()
    if not instructeur_en_cours:
        logger.error(f"[DOSSIER {dossier.numero}] User {email_user} sans profil instructeur a tenté de changer l'intermédiaire signature.")
        return redirect_error(request, "Vous devez disposer d’un profil Instructeur. Contactez le support si besoin.")

    new_intermediaire = Instructeur.objects.filter(id=new_intermediaire_id).first()
    if not new_intermediaire:
        logger.error(f"[DOSSIER {dossier.numero}] Nouvel intermédiaire id={new_intermediaire_id} introuvable — User={instructeur_en_cours}")
        return redirect_error(request, "Nouvel intermédiaire introuvable. Contactez le support.")

    # Ancien intermédiaire
    id_old_intermediaire = DossierIntermediaireSignature.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True).first()
    old_intermediaire = Instructeur.objects.filter(id=id_old_intermediaire).first()

    # S'assurer que le nouveau intermédiaire est différent
    if old_intermediaire and old_intermediaire.id == new_intermediaire.id:
        return redirect_error(request, f"L'intermédiaire sélectionné·e est déjà affecté·e à ce dossier.")


    # -------------------------
    # Mise à jour BDD
    # -------------------------
    try :
        # Suppression de l'ancien intermédiaire (s'il existe)
        if old_intermediaire:
            DossierIntermediaireSignature.objects.filter(id_dossier=dossier, id_instructeur=old_intermediaire).delete()

        # Ajout du nouveau intermédiaire
        DossierIntermediaireSignature.objects.get_or_create(id_dossier=dossier, id_instructeur=new_intermediaire)
        logger.info(f"[DOSSIER {dossier.numero}] Changement d'intermédiaire pour la signature : {old_intermediaire} --> {new_intermediaire}")
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Changement d'intermédiaire pour la signature, User={instructeur_en_cours} - Erreur MAJ intermédiaire signature ({old_intermediaire} → {new_intermediaire}) : {e}")
        return redirect_error(request, "❌ Erreur lors du changement de l’intermédiaire. Contactez le support.")

    # Action dossier
    safe_enregistrer_action(dossier, instructeur_en_cours, "Intermédiaire signature changé.e", request, description=f"→ {new_intermediaire}")

    
    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    if instructeur_en_cours != new_intermediaire :

        emails_norm = [new_intermediaire.email]
        # print(f"Intermédiaire à notifier : {emails_norm2}")

        # emails_norm = ["louis.calu@reunion-parcnational.fr"]
        sujet = f"Dossier {dossier.numero} - Vous faites désormais l'intermédiaire pour la signature"

        context = {
                    "dossier_numero": dossier.numero,
                    "demarche_type": dossier.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
                }
        template_name = "changer_intermediaire"

        try:
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] User : {instructeur_en_cours} - Changer d'intermédiaire signature. {new_intermediaire} n'a pas été notifié par mail. Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request,f"L'email de notification à {new_intermediaire} n'a pas été envoyé. Contactez le support.")

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
                logger.error(f"[DOSSIER {dossier.numero}] Nouveau intermédiaire pour la signature : Erreur lors de la création de l'EmailOutbox, {new_intermediaire} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {new_intermediaire} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                
            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Nouveau intermédiaire pour la signature) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Nouveau intermédiaire pour la signature) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {new_intermediaire} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def changer_envoyeur_acte(request):

    dossier_id = request.POST.get("dossier_id")
    new_envoyeur_id = request.POST.get("new_envoyeur_id")
    email_user = request.user.email or ""

    # ----------------
    # Vérifications
    # ----------------
    if not dossier_id:
        logger.error(f"[CHANGER ENVOYEUR ACTE] User={request.user} : dossier_id manquant.")
        return redirect_error(request, "Identifiant du dossier manquant. Contactez le support.")

    if not new_envoyeur_id:
        logger.error(f"[CHANGER ENVOYEUR ACTE] User={request.user} : new_envoyeur_id manquant.")
        return redirect_error(request, "Identifiant de l’envoyeur d’acte manquant. Contactez le support.")

    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[CHANGER ENVOYEUR ACTE] Dossier id={dossier_id} introuvable — User={request.user}")
        return redirect_error(request, "Dossier introuvable. Contactez le support.")

    instructeur_en_cours = Instructeur.objects.filter(email=email_user).first()
    if not instructeur_en_cours:
        logger.error(f"[DOSSIER {dossier.numero}] User={request.user} sans profil instructeur a tenté de changer l'envoyeur d'acte.")
        return redirect_error(request, "Vous devez disposer d’un profil Instructeur. Contactez le support si besoin.")

    new_envoyeur = Instructeur.objects.filter(id=new_envoyeur_id).first()
    if not new_envoyeur:
        logger.error(f"[DOSSIER {dossier.numero}] Nouvel envoyeur id={new_envoyeur_id} introuvable — User={instructeur_en_cours}")
        return redirect_error(request, "Nouvel envoyeur d’acte introuvable. Contactez le support.")

    # Ancien envoyeur
    id_old_envoyeur = DossierEnvoiActe.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True).first()
    old_envoyeur = Instructeur.objects.filter(id=id_old_envoyeur).first()

    if old_envoyeur and old_envoyeur.id == new_envoyeur.id:
        return redirect_error(request, "L'envoyeur.se d'acte sélectionné·e est déjà affecté·e à ce dossier.")


    # -------------------------
    # Mise à jour BDD
    # -------------------------
    try :
        # Suppression de l'ancien envoyeur d'acte (s'il existe)
        if old_envoyeur:
            DossierEnvoiActe.objects.filter(id_dossier=dossier, id_instructeur=old_envoyeur).delete()

        # Ajout du nouveau envoyeur d'acte
        DossierEnvoiActe.objects.get_or_create(id_dossier=dossier, id_instructeur=new_envoyeur)
        logger.info(f"[DOSSIER {dossier.numero}] Changement d'envoyeur.se d'acte par {instructeur_en_cours} : {old_envoyeur} --> {new_envoyeur}")
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Changement d'envoyeur.se d'acte par {instructeur_en_cours} - MAJ envoyeur acte échouée ({old_envoyeur} → {new_envoyeur}) : {e}")
        return redirect_error(request, "❌ Erreur lors du changement de l’envoyeur.se d’acte. Contactez le support.")

    # Dossier Action
    safe_enregistrer_action(dossier, instructeur_en_cours, "Envoyeur.se d'acte changé.e", request, description=f"→ {new_envoyeur}")
    


    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    if instructeur_en_cours != new_envoyeur :

        emails_norm = [new_envoyeur.email]
        # print(f"Envoyeur à notifier : {emails_norm2}")


        # emails_norm = ["louis.calu@reunion-parcnational.fr"]
        sujet = f"Dossier {dossier.numero} - Vous êtes désormais chargé.e d'envoyer l'acte"

        context = {
                    "dossier_numero": dossier.numero,
                    "demarche_type": dossier.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
                }
        template_name = "changer_envoyeur"

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
        
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] User : {instructeur_en_cours} - Changer d'envoyeur d'acte. {new_envoyeur} n'a pas été notifié par mail. Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request,f"L'email de notification à {new_envoyeur} n'a pas été envoyé. Contactez le support.")


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
                logger.error(f"[DOSSIER {dossier.numero}] Nouveau envoyeur d'acte : Erreur lors de la création de l'EmailOutbox, {new_envoyeur} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {new_envoyeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                
            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Nouveau envoyeur d'acte) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Nouveau envoyeur d'acte) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {new_envoyeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def changer_publieur_raa(request):
    
    dossier_id = request.POST.get("dossier_id")
    new_publieur_id = request.POST.get("new_publieur_raa_id")
    email_user = request.user.email or ""

    # ----------------
    # Vérifications
    # ----------------
    if not dossier_id:
        logger.error(f"[CHANGER PUBLIEUR RAA] User={request.user} : dossier_id manquant.")
        return redirect_error(request, "Identifiant du dossier manquant. Contactez le support.")

    if not new_publieur_id:
        logger.error(f"[CHANGER PUBLIEUR RAA] User={request.user} : new_publieur_raa_id manquant.")
        return redirect_error(request, "Identifiant du nouveau publieur RAA manquant. Contactez le support.")

    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[CHANGER PUBLIEUR RAA] Dossier id={dossier_id} introuvable — User={request.user}")
        return redirect_error(request, "Dossier introuvable. Contactez le support.")

    instructeur_en_cours = Instructeur.objects.filter(email=email_user).first()
    if not instructeur_en_cours:
        logger.error(f"[DOSSIER {dossier_id}] User={request.user} sans profil instructeur a tenté de changer le publieur RAA.")
        return redirect_error(request, "Vous devez disposer d’un profil Instructeur. Contactez le support.")

    new_publieur = Instructeur.objects.filter(id=new_publieur_id).first()
    if not new_publieur:
        logger.error(f"[DOSSIER {dossier.numero}] Publieur id={new_publieur_id} introuvable — User={instructeur_en_cours}")
        return redirect_error(request, "Nouveau publieur RAA introuvable. Contactez le support.")

    # Ancien publieur
    id_old_publieur = DossierPublicationRAA.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True).first()
    old_publieur = Instructeur.objects.filter(id=id_old_publieur).first()

    # S'assurer que le nouveau publieur d'acte au RAA est différent
    if old_publieur and old_publieur.id == new_publieur.id:
        return redirect_error(request, f"Le ou la publieur.se d'acte au RAA sélectionné·e est déjà affecté·e à ce dossier.")


    # -------------------------
    # Mise à jour BDD
    # -------------------------
    try:

        # Suppression de l'ancien publieur d'acte au RAA (s'il existe)
        if old_publieur:
            DossierPublicationRAA.objects.filter(id_dossier=dossier, id_instructeur=old_publieur).delete()
        # Ajout du nouveau publieur d'acte au RAA
        DossierPublicationRAA.objects.get_or_create(id_dossier=dossier, id_instructeur=new_publieur)
        logger.info(f"[DOSSIER {dossier.numero}] Changement de publieur.se d'acte au RAA par {instructeur_en_cours} : {old_publieur} --> {new_publieur}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Changement de publieur RAA par {instructeur_en_cours} - MAJ publieur échouée ({old_envoyeur} → {new_envoyeur}) : {e}")
        return redirect_error(request, "❌ Erreur lors du changement de publieur.se RAA. Contactez le support.")

    # Action dossier
    safe_enregistrer_action(dossier, instructeur_en_cours, "Publieur.se RAA changé.e", request, description=f"→ {new_publieur}")
    

    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    if instructeur_en_cours != new_publieur :

        emails_norm = [new_publieur.email]
        # print(f"Publieur à notifier : {emails_norm2}")

        # emails_norm = ["louis.calu@reunion-parcnational.fr"]
        sujet = f"Dossier {dossier.numero} - Vous êtes désormais chargé.e d'envoyer l'acte"

        context = {
                    "dossier_numero": dossier.numero,
                    "demarche_type": dossier.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
                }
        template_name = "changer_publieur"

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
        
        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] User : {instructeur_en_cours} - Changer de publieur RAA. {new_publieur} n'a pas été notifié par mail. Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request,f"L'email de notification à {new_publieur} n'a pas été envoyé. Contactez le support.")

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
                logger.error(f"[DOSSIER {dossier.numero}] Nouveau publieur.se d'acte au RAA : Erreur lors de la création de l'EmailOutbox, {new_publieur} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {new_publieur} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                
            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Nouveau publieur.se d'acte au RAA) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Nouveau publieur.se d'acte au RAA) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {new_publieur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))









""" 
##################################
CLEAN A FINIR 
##################################
"""
@require_POST
@login_required
def enregistrer_geom(request):
    try:
        dossier_numero = request.POST.get("dossier_numero")
        geojson_str = request.POST.get("geojson_geom")
        id_champ = request.POST.get("id_champ")
        nb_cartes = request.POST.get("nb_cartes")

        dossier = get_object_or_404(Dossier, numero=dossier_numero)
        champ = get_object_or_404(DossierChamp, id=id_champ, id_dossier=dossier, id_champ__id_champ_type__type__in=["carte", "drop_down_list"])

        if not geojson_str:
            msg = "Aucune géométrie reçue (champ geojson_geom vide)."
            logger.warning(f"[DOSSIER {dossier.numero}] Enregistrement géométrie par {request.user}: {msg}")

            return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier_numero})}?status=error&msg={urllib.parse.quote(msg)}")

        geojson_data = json.loads(geojson_str)

        # MAJ champ
        if not champ:
            msg = "Champ carte non trouvé."
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'nregistrement de la géométrie par {request.user} : {msg}")
            return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier.numero, 'id_champ': request.POST.get('id_champ')})}?status=error&msg={urllib.parse.quote(msg)}")

        champ.geometrie_modif = geojson_data
        champ.save()

        # MAJ géométrie dossier seulement s'il n'existe qu'un champ de type carte
        if nb_cartes == 1:
            dossier.geometrie_modif = geojson_data
            dossier.save()

        # Il y a au moins 2 champs cartes
        else:
            # Récupération de tous les champs carte du dossier
            champs_cartes = DossierChamp.objects.filter(
                id_dossier=dossier,
                id_champ__id_champ_type__type="carte"
            )

            features = []

            # On fusionne les geojson recupérés pour n'en faire qu'un
            for c in champs_cartes:
                geo = c.geometrie_modif or c.geometrie
                if geo:
                    # S'assurer que c'est bien un Feature ou FeatureCollection
                    if geo.get("type") == "Feature":
                        features.append(geo)
                    elif geo.get("type") == "FeatureCollection":
                        features.extend(geo.get("features", []))
                    else:
                        logger.warning(f"[DOSSIER {dossier.numero}] Géométrie ignorée : type inattendu ({geo.get('type')}) dans champ {c.id}")

            if features:
                geojson_fusionne = {
                    "type": "FeatureCollection",
                    "features": features
                }
                # Mise à jour de dossier.geometrie_modif si valeur différente
                if dossier.geometrie_modif != geojson_fusionne:
                    dossier.geometrie_modif = geojson_fusionne
                    dossier.save()

        msg = "Géométrie mise à jour avec succès."
        logger.info(f"[DOSSIER {dossier.numero}] {msg} par {request.user}")
        return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier.numero, 'id_champ': id_champ})}?status=ok&msg={urllib.parse.quote(msg)}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'enregistrement de la géométrie par {request.user} : {e}")
        return redirect(f"/instruction/{request.POST.get('dossier_numero')}/edit_carto/{request.POST.get('id_champ')}?status=error&msg={urllib.parse.quote(str(e))}")



@login_required
def edit_carto(request, numero_dossier, id_champ):
    dossier = get_object_or_404(Dossier, numero=numero_dossier)
    
    # Récupère tous les champs carte
    # nb_cartes = dossier.dossierchamp_set.filter(id_champ__id_champ_type__type="carte").count()
    
    nb_cartes = dossier.dossierchamp_set.filter(
        Q(id_champ__id_champ_type__type="carte") |
        Q(id_champ__id_champ_type__type="drop_down_list", geometrie_a_saisir=True)
    ).count()


    champ = get_object_or_404(
            DossierChamp,
            id=id_champ,
            id_dossier=dossier,
            id_champ__id_champ_type__type__in=["carte", "drop_down_list"]
        )
        
    geojson_source = champ.geometrie_modif or champ.geometrie
    if not geojson_source:
        geojson_source = {
            "type": "FeatureCollection",
            "features": []
        }
    

    geojson = json.dumps(geojson_source)


    return render(request, 'edit_carto.html', {
                                                "numero_dossier": numero_dossier, 
                                                "geojson": geojson, 
                                                "etape_dossier": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else None,
                                                "nb_cartes": nb_cartes,
                                                'id_champ': id_champ,
                                                'now': now(),
                                               })



def mes_dossiers_a_traiter_count(request):
    if not request.user.is_authenticated:
        return {}

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        return {}

    # Dossiers (en cours d'instruction) où l’utilisateur intervient
    dossiers = (
        Dossier.objects.filter(
            Q(dossierinstructeur__id_instructeur=instructeur) |
            Q(dossierrelecteurqualite__id_instructeur=instructeur) |
            Q(dossiervalideur__id_instructeur=instructeur) |
            Q(dossierrelecteur__id_instructeur=instructeur) |
            Q(dossiersignataire__id_instructeur=instructeur) |
            Q(dossierintermediairesignature__id_instructeur=instructeur) |
            Q(dossierpublicationraa__id_instructeur=instructeur) |
            Q(dossierenvoiacte__id_instructeur=instructeur)
        )
        .exclude(id_etape_dossier__etape__in=["À affecter"])
        .distinct()
    )

    dossiers_actions = dossiers_action_a_faire(dossiers, instructeur)
    return {"nb_dossiers_instruction": len(dossiers_actions)}



def mes_dossiers_a_receptionner_count(request):
    if not request.user.is_authenticated:
        return {}

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        return {}

    # Dossiers (en reception) où l’utilisateur intervient
    dossiers = Dossier.objects.filter(id_etape_dossier__etape="À affecter")

    dossiers_actions = dossiers_reception_action_a_faire(dossiers, request.user)
    return {"nb_dossiers_reception": len(dossiers_actions)}



def mes_avis_action_a_faire(request):
    """
    Renvoie un dictionnaire contenant le nombre d'avis où l'utilisateur
    a une action à faire :
      - Avis où il est expert (interne ou externe) et favorable is null
      - Avis où il est expert (interne ou externe) et favorable not null
        mais avec des messages non lus dont il n'est pas l'émetteur
      - Avis où il est demandeur et a des messages non lus de l'expert
    """
    if not request.user.is_authenticated:
        return {}

    liste_avis_avec_action_a_faire = []
    email_user = request.user.email
    nb_avis_action = 0

    # ----------------------------------------------------------
    # 1️⃣ Identifier l’utilisateur comme instructeur et/ou expert
    # ----------------------------------------------------------
    instructeur = Instructeur.objects.filter(email=email_user).first()

    expert = (
        Expert.objects.filter(id_instructeur=instructeur).first()
        if instructeur
        else Expert.objects.filter(id_contact_externe__email=email_user).first()
    )

    # ----------------------------------------------------------
    # 2️⃣ Cas où l’utilisateur est EXPERT (interne ou externe)
    # ----------------------------------------------------------
    if expert:
        # (a) Avis à rendre → favorable is null
        nb_avis_a_rendre = Avis.objects.filter(id_expert=expert, favorable__isnull=True)

        liste_avis_avec_action_a_faire.extend(nb_avis_a_rendre)

        # (b) Avis rendus avec messages non lus dont il n’est pas l’émetteur
        avis_rendus = Avis.objects.filter(
            id_expert=expert, favorable__isnull=False
        )
        for avis in avis_rendus:
            nb_non_lus = Message.objects.filter(
                id_avis=avis, lu=False
            ).exclude(email_emetteur=email_user).count()
            if nb_non_lus > 0:
                nb_avis_action += 1
                if avis not in liste_avis_avec_action_a_faire:
                    liste_avis_avec_action_a_faire.append(avis)

        nb_avis_action += nb_avis_a_rendre.count()

    # ----------------------------------------------------------
    # 3️⃣ Cas où l’utilisateur est DEMANDEUR d’avis
    # ----------------------------------------------------------
    if instructeur:
        avis_demandes = Avis.objects.filter(id_instructeur=instructeur)
        for avis in avis_demandes:
            # récupérer l’adresse mail de l’expert associé
            if avis.id_expert.est_interne:
                email_expert = avis.id_expert.id_instructeur.email
            else:
                email_expert = avis.id_expert.id_contact_externe.email

            nb_non_lus = Message.objects.filter(
                id_avis=avis, lu=False, email_emetteur=email_expert
            ).count()

            if nb_non_lus > 0:
                nb_avis_action += 1
                if avis not in liste_avis_avec_action_a_faire:
                    liste_avis_avec_action_a_faire.append(avis)
                    

    # -----------------------------------------------------------------------
    # 4 Cas où l’utilisateur est CHARGÉ DE PUBLIER LES AVIS INSTANCES AU RAA
    # -----------------------------------------------------------------------
    if instructeur and request.user.groups.filter(name="Publication RAA Avis CS").exists():

        # On filtre sur les avis du CS uniquement
        avis_en_attente_de_publi_RAA = (
            Avis.objects.filter(favorable=True, id_expert__est_interne=False, id_expert__id_contact_externe__raison_sociale__iexact="Conseil Scientifique")
            .exclude(publie_au_raa=True)
            .filter(avisdocument__id_document__id_nature__nature__iexact="Avis instance")
            .distinct()
        )
        ############################
        # On filtrera sur expert = CS
        ############################
   

        for avis in avis_en_attente_de_publi_RAA :
            if avis not in liste_avis_avec_action_a_faire:
                liste_avis_avec_action_a_faire.append(avis)
    

    return {"nb_avis_action_a_faire": len(liste_avis_avec_action_a_faire)}
    # return {"nb_avis_action_a_faire": nb_avis_action}



@login_required(login_url='/login/')
def ajouter_annexe_dossier(request, dossier_id):

    dossier = get_object_or_404(Dossier, id=dossier_id)

    if request.method == "POST" and request.FILES.get('annexe'):
        fichier = request.FILES['annexe']

        # Vérification de la taille (max 20 Mo)
        if fichier.size > 20 * 1024 * 1024:
            logger.warning(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) Taille > 50 Mo pour {fichier.name}")
            messages.error(request, f"Annexe refusée ({request.user}) Taille > 20 Mo pour {fichier.name}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        # Extension du fichier
        nom, extension = os.path.splitext(fichier.name)
        extension = extension.lstrip('.').lower()

        # Récupérer le format
        format_obj = DocumentFormat.objects.filter(format__iexact=extension).first()
        if not format_obj:
            logger.warning(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) car le format n'est pas reconnu : {fichier.name}.{extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        # Nature "Annexe instructeur"
        nature_obj = DocumentNature.objects.filter(nature__iexact="Annexe instructeur").first()
        if not nature_obj:
            logger.error(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) La nature 'Annexe instructeur' est introuvable en BDD.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        
        # Création du Document
        emplacement = f"{dossier.emplacement}Annexes/{fichier.name}"
        # chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}"
        chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}"

        # Vérification si un Document avec le même emplacement existe déjà en base, si on est ici c'est qu'on a confirmé l'écrasement dans le pop up JS
        if Document.objects.filter(emplacement=f"{dossier.emplacement}Annexes/", titre=fichier.name).exists():
            
            try:
                ancien_doc = Document.objects.get(emplacement=f"{dossier.emplacement}Annexes/", titre=fichier.name)
                # Supprimer le lien avec le dossier
                DossierDocument.objects.filter(id_document=ancien_doc).delete()
                # Supprimer le document lui-même
                ancien_doc.delete()
            except Document.DoesNotExist:
                pass  # Aucun doc à supprimer, donc on ignore

            logger.info(f"[DOSSIER {dossier.numero}] Annexe {fichier.name} écrasée par {request.user} — ancien document supprimé.")

        doc = Document.objects.create(
            id_format=format_obj,
            id_nature=nature_obj,
            titre=fichier.name,
            emplacement=f"{dossier.emplacement}Annexes/",
            description=f"Annexe ajouté par l'instructeur {request.user} sur le dossier {dossier.numero}"
        )


        # Lien avec le Dossier
        DossierDocument.objects.create(id_dossier=dossier, id_document=doc)

        # Enregistrement physique
        # os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)


        # Si un fichier du même nom existe déjà, on le supprime
        # if os.path.exists(chemin_complet):
        #     os.remove(chemin_complet)

        # 1) Supprimer si un fichier du même nom existe déjà
        try:
            if smbclient.path.exists(chemin_complet):
                if not supprimer_file_sur_nas(chemin_complet):
                    messages.error(request, f"Erreur lors du remplacement de l'ancien fichier {fichier.name} sur le NAS.")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
        except Exception as e:
            logger.error(f"[NAS] Erreur en vérifiant/supprimant l'existant : {e}")
            messages.error(request, "Erreur lors de la vérification du fichier existant sur le NAS.")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        # TEST ECRITURE NAS
        # 2) Écrire l’upload directement sur le NAS
        if not ecrire_file_sur_nas(fichier, chemin_complet):
            logger.error(f"[NAS] Erreur lors de l'écriture de l'annexe sur le NAS : {e}")
            messages.error(request, "Erreur lors de l'écriture de l'annexe sur le NAS.")
            return redirect(request.META.get("HTTP_REFERER", "/"))



        # try:
        #     with open(chemin_complet, 'wb+') as destination:
        #         for chunk in fichier.chunks():
        #             destination.write(chunk)

        #     logger.info(f"[DOSSIER {dossier.numero}] Annexe {fichier.name} ajoutée avec succès par {request.user}")
        #     return redirect(request.META.get("HTTP_REFERER", "/"))

        # except Exception as e:
        #     logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'écriture de l'annexe instructeur (Note) : {e}")
        #     messages.error(request, "Une erreur est survenue lors de l’enregistrement du fichier. Veuillez réessayer.")
        #     return redirect(request.META.get("HTTP_REFERER", "/"))


    logger.warning(f"[DOSSIER {dossier.numero}] Annexe non ajoutée par {request.user} : Aucune pièce jointe reçue.")
    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def synchroniser_demarche(request, num_demarche):
    if request.method == "POST":
        try:
            l = lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
        except Exception as e:
            loggerSynchro.error(f"Erreur de synchronisation pour la démarche {num_demarche} : {e}")
    return redirect("instruction_demarche", num_demarche=num_demarche)


@login_required
def synchroniser_demarche_depuis_reception(request, num_demarche):
    if request.method == "POST":
        try:
            l = lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
        except Exception as e:
            loggerSynchro.error(f"Erreur de synchronisation pour la démarche {num_demarche} : {e}")
    return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))


@login_required
def afficher_annexe(request, chemin, titre=None):
    try:
        if titre :
            chemin_entier = os.path.join(os.environ.get("NAS_ROOT"), chemin, titre)
        else :
            chemin_entier = os.path.join(os.environ.get("NAS_ROOT"), chemin)

        if not smbclient.path.exists(chemin_entier):
            raise Http404("Fichier introuvable")

        content_type, _ = guess_type(chemin_entier)
        if not content_type:
            content_type = 'application/octet-stream'  # type par défaut
        
        response = FileResponse(smbclient.open_file(chemin_entier, 'rb'), content_type=content_type)
        return response


    except Exception as e:
        raise Http404("Erreur d'accès au fichier : " + str(e))


@require_POST
@login_required
def supprimer_annexe_instructeur(request):
    document_id = request.POST.get("document_id")
    dossier_id = request.POST.get("dossier_id")

    doc = get_object_or_404(Document, id=document_id, id_nature__nature__iexact="Annexe instructeur")
    dossier = get_object_or_404(Dossier, id=dossier_id)

    try:
        # Supprimer le lien
        DossierDocument.objects.filter(id_dossier=dossier, id_document=doc).delete()

        # Supprimer le fichier physique
        chemin_fichier = os.path.join(os.getenv("NAS_ROOT"), doc.emplacement, doc.titre)
        if smbclient.path.exists(chemin_fichier):
            if not supprimer_file_sur_nas(chemin_fichier):
                logger.error(f"[NAS] ❌ Erreur lors de la suppression de l'ancien fichier {doc.titre} sur {chemin_fichier}")
                raise Exception(f"[NAS] ❌ Erreur lors de la suppression de l'ancien fichier {doc.titre} sur {chemin_fichier}")

        # Supprimer le document
        doc.delete()

        logger.info(f"[DOSSIER {dossier.numero}] Annexe instructeur supprimée : {doc.titre} par {request.user}")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur suppression annexe instructeur ({doc.titre}) par {request.user} : {e}")
        raise




@login_required
def dossier_manif_sportive_sans_ds(request, numero):


    doss_manif_sportive = get_object_or_404(DossierManifSportive, numero_dossier_declaration_manifestations=numero)

     # Récupération de l'avis lié (OneToOne → un seul)
    try:
        avis_manif_sportive = doss_manif_sportive.avis  # grâce à related_name='avis'
    except Exception:
        avis_manif_sportive = None  # Aucun avis encore associé

    # Charger le fond de carte GeoJSON (une seule fois)
    fond_coeur_de_parc = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/fond_coeur_de_parc.geojson")
    with open(fond_coeur_de_parc, encoding="utf-8") as f:
        fond_coeur_de_parc = json.load(f)

    fond_aire_adhesion = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/aire_adhesion.geojson")
    with open(fond_aire_adhesion, encoding="utf-8") as f:
        fond_aire_adhesion = json.load(f)

    return render(request, 'instruction/dossier_manif_sportive_sans_ds.html', {
        "doss_manif_sportive": doss_manif_sportive,
        "avis_manif_sportive": avis_manif_sportive,
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
    })



@login_required
def gestion_groupes(request):
    if request.method == "POST":
        action = request.POST.get("action")
        type_objet = request.POST.get("type")  # "groupe" ou "groupe_instructeur"
        groupe_id = request.POST.get("groupe_id")
        user_id = request.POST.get("user_id")

        if type_objet == "groupe":  # Groupes Django classiques
            groupe = get_object_or_404(Group, id=groupe_id)
            if action == "add":
                user = get_object_or_404(User, id=user_id)
                groupe.user_set.add(user)
                messages.success(request, f"Utilisateur {user.username} ajouté au groupe {groupe.name}.")
            elif action == "remove":
                user = get_object_or_404(User, id=user_id)
                groupe.user_set.remove(user)
                messages.success(request, f"Utilisateur {user.username} retiré du groupe {groupe.name}.")

        elif type_objet == "groupe_instructeur":  # Groupes instructeurs
            groupe = get_object_or_404(Groupeinstructeur, id=groupe_id)
            instructeur = get_object_or_404(Instructeur, id=user_id)

            if action == "add":
                GroupeinstructeurInstructeur.objects.get_or_create(
                    id_groupeinstructeur=groupe, id_instructeur=instructeur
                )
                messages.success(request, f"Instructeur {instructeur} ajouté au groupe instructeur {groupe.nom}.")
            elif action == "remove":
                GroupeinstructeurInstructeur.objects.filter(
                    id_groupeinstructeur=groupe, id_instructeur=instructeur
                ).delete()
                messages.success(request, f"Instructeur {instructeur} retiré du groupe instructeur {groupe.nom}.")

        return redirect("gestion_groupes")
    
    user = request.user
    param = request.GET.get("mes_groupes")
    if param is None:
        if request.user.is_superuser :
            show_only_mine = False
        else :
            # Aucun paramètre → on coche par défaut
            show_only_mine = True
    else:
        # Si présent → on suit la valeur ("1" = coché, tout le reste = décoché)
        show_only_mine = (param == "1")

    # Groupes Django
    groupes = Group.objects.all().prefetch_related("user_set")
    if show_only_mine:
        groupes = [g for g in groupes if user in g.user_set.all()]


    users = User.objects.all()

    # Séparation des groupes
    groupes_saadd = [g for g in groupes if "SAADD" in g.name.upper()]
    groupes_sppn = [g for g in groupes if "SPPN" in g.name.upper()]
    groupes_general = [g for g in groupes if "SAADD" not in g.name.upper() and "SPPN" not in g.name.upper()]

    # Groupes instructeurs
    groupes_instructeurs = Groupeinstructeur.objects.all().order_by("nom").prefetch_related(
        "groupeinstructeurinstructeur_set__id_instructeur__id_agent_autorisations"
    )

    if show_only_mine:
        groupes_instructeurs = [
            g for g in groupes_instructeurs
            if g.groupeinstructeurinstructeur_set.filter(id_instructeur__email=user.email).exists()
        ]

    # on construit un dict {groupe_id: [ids instructeurs déjà dedans]}
    instructeurs_groupes_map = {
        g.id: [lien.id_instructeur.id for lien in g.groupeinstructeurinstructeur_set.all()]
        for g in groupes_instructeurs
    }

    instructeurs = Instructeur.objects.select_related("id_agent_autorisations").all()


    return render(request, "instruction/gestion_groupes.html", {
        "groupes_saadd": groupes_saadd,
        "groupes_sppn": groupes_sppn,
        "groupes_general": groupes_general,
        "groupes_instructeurs": groupes_instructeurs,
        "instructeurs_groupes_map": instructeurs_groupes_map,
        "instructeurs": instructeurs,
        "users": users,  # pour liste déroulante d’ajout
        "show_only_mine": show_only_mine,
    })




@login_required
def gestion_contacts(request):
    """
    Affiche et permet de modifier les contacts externes et les instructeurs.
    """
    if request.method == "POST":
        type_objet = request.POST.get("type_objet")
        obj_id = request.POST.get("id")

        if type_objet == "contact":
            contact = get_object_or_404(ContactExterne, id=obj_id)
            contact.nom = request.POST.get("nom")
            contact.prenom = request.POST.get("prenom")
            contact.email = request.POST.get("email")
            contact.telephone = request.POST.get("telephone")
            contact.organisation = request.POST.get("organisation")
            contact.raison_sociale = request.POST.get("raison_sociale")
            contact.adresse = request.POST.get("adresse")
            contact.save()
            messages.success(request, f"✅ Contact {contact.get_display_name()} mis à jour.")

        elif type_objet == "instructeur":
            instructeur = get_object_or_404(Instructeur, id=obj_id)
            agent = instructeur.id_agent_autorisations
            agent.nom = request.POST.get("nom")
            agent.prenom = request.POST.get("prenom")
            agent.mail_1 = request.POST.get("email")
            agent.acronyme = request.POST.get("acronyme")
            agent.actif = "actif" in request.POST
            agent.save()
            messages.success(request, f"✅ Instructeur {agent.nom} {agent.prenom} mis à jour.")

        return redirect("gestion_contacts")

    instructeurs = Instructeur.objects.select_related("id_agent_autorisations").all().order_by("id_agent_autorisations__nom")
    contacts = ContactExterne.objects.select_related("id_type").all().order_by("nom", "prenom")

    return render(request, "instruction/gestion_contacts.html", {
        "instructeurs": instructeurs,
        "contacts": contacts,
    })







def recent_log_activity(file_path):
    """
    Retourne :
    {
        "error": int,
        "warning": int
    }
    """
    if not os.path.exists(file_path):
        return {"error": 0, "warning": 0}

    now = datetime.now()
    threshold = now - timedelta(days=5)

    error_count = 0
    warning_count = 0

    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line in f.readlines()[-5000:]:
            try:
                date_str = line.split(" ")[0] + " " + line.split(" ")[1]
                timestamp = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S,%f")
            except:
                continue

            if timestamp < threshold:
                continue

            if "ERROR" in line or "Exception" in line or "Traceback" in line:
                error_count += 1
            elif "WARNING" in line:
                warning_count += 1

    return {"error": error_count, "warning": warning_count}





LOG_FILES = {
    "LDAP_LOGS": "logs/active_directory.log",
    "APP": "logs/app.log",
    "API_DS": "logs/apiDS.log",
    "API_PG": "logs/apiPG.log",
    "API_DM": "logs/apiDM.log",
    "MAIL": "logs/mails.log",
    "INSTRUCTION": "logs/instruction.log",
    "SYNCHRONISATION": "logs/synchronisation.log",
}


def gestion_logs(request):
    log_type = request.GET.get("type", "APP")
    search = request.GET.get("search", "")
    page = request.GET.get("page", 1)

    date_filter = request.GET.get("date")
    if date_filter in (None, "", "None"):
        date_filter = ""

    
    raw_levels = request.GET.getlist("level")
    if len(raw_levels) == 1 and "," in raw_levels[0]:
        raw_levels = raw_levels[0].split(",")

    selected_levels = [lvl.upper() for lvl in raw_levels if lvl]


    print(f"search= {search}, date= {date_filter}, page= {page}, log_type= {log_type}, selected_levels= {selected_levels}")


    file_path = LOG_FILES.get(log_type)
    lines = []

    if file_path and os.path.exists(file_path):

        # Sécurisation UTF-8
        with open(file_path, encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()

        # Inverser pour afficher les plus récentes d'abord
        raw_lines.reverse()

        # Filtrage
        for line in raw_lines:

            if search.lower() not in line.lower():
                continue
            if date_filter and not line.startswith(date_filter):
                continue
            if selected_levels:
                if not any(level in line for level in selected_levels):
                    continue

            lines.append(line)

    # Pagination (max 400 lignes par page)
    paginator = Paginator(lines, 400)
    page_obj = paginator.get_page(page)

    # Générer les indicateurs pour chaque fichier
    activity = {}
    for key, path in LOG_FILES.items():
        activity[key] = recent_log_activity(path)


    return render(request, "gestion_logs.html", {
        "logs": page_obj,
        "activity": activity,
        "page_obj": page_obj,
        "log_type": log_type,
        "search": search,
        "date_filter": date_filter,
        "selected_levels": selected_levels,
        "log_files": LOG_FILES.keys(),
    })