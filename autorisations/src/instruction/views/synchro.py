import os

from django.shortcuts import redirect
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import close_old_connections, transaction

from datetime import timedelta
import logging
import threading
import subprocess
import sys


from DS.graphql_client import GraphQLClient


from autorisations.models.models_instruction import Demarche, Dossier, DossierManifSportive, DossierManifestationLiaison, SynchronisationEtat
from autorisations.models.models_utilisateurs import Instructeur


from declaration_manifestations.call_api_dm import recup_un_seul_dossier
from instruction.utils.dossier_utils import actualisation_demarche_est_bloquee, actualisation_dossier_est_bloquee, clear_etat_actualisation_demarche, clear_etat_actualisation_dossier, get_etat_actualisation_demarche, get_etat_actualisation_dossier, redirect_error, safe_enregistrer_action, set_etat_actualisation_demarche, set_etat_actualisation_dossier

from synchronisation.main import lancer_normalisation_et_synchronisation_pour_une_demarche
from synchronisation.normalisation.norma_contacts_externes import contact_externe_normalize
from synchronisation.normalisation.norma_declaration_manifestations import dossiers_declaration_manifestations_normalize
from synchronisation.normalisation.norma_dossier import dossier_normalize
from synchronisation.normalisation.norma_dossier_champs import dossiers_champs_normalize
from synchronisation.synchro.sync_declaration_manifestations import sync_declaration_manifestations
from synchronisation.utils.fichiers import construire_emplacement_dossier
from synchronisation.normalisation.norma_demandes import demande_normalize
from synchronisation.normalisation.norma_dossier_document import dossier_document_normalize
from synchronisation.normalisation.norma_dossier_interlocuteur import dossier_interlocuteur_normalize
from synchronisation.normalisation.norma_messages import message_normalize
from synchronisation.synchro.sync_dossiers import sync_dossiers

from django.views.decorators.http import require_POST
from threading import Thread



logger = logging.getLogger("ORM_DJANGO")
loggerSynchro = logging.getLogger("SYNCHRONISATION")
loggerDS = logging.getLogger("API_DS")  


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
                    [sys.executable, "synchronisation/lancer_synchronisation.py"],
                    stdout=f, stderr=f, encoding="utf-8", errors="replace",
                )

        except Exception:
            logger.exception("Erreur lors du sous-processus de synchronisation.")

        finally:
            close_old_connections()

    threading.Thread(target=lancement_et_suivi).start()
    return True



@login_required
def actualiser_donnees(request):
    """
    Tente de lancer une actualisation en arrière plan.
    Fonctionne seulement si une actualisation n'est pas déjà en cours.
    """
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
    """
    Regarde si une actualisation est en cours
    Si une actualisation est en cours depuis lus d'1h, on reset le Flag en BDD.
    """
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



def synchroniser_demarche_job(num_demarche, user_display):
    try:

        success = lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
        
        if success:
            set_etat_actualisation_demarche(num_demarche, "success", "Actualisation terminée avec succès.")
        else:
            set_etat_actualisation_demarche(num_demarche,"error","Erreur lors de l'actualisation de la démarche.")

    except Exception as e:
        loggerSynchro.exception(f"[DEMARCHE {num_demarche}] Échec de l'actualisation par {user_display}: {e}")
        set_etat_actualisation_demarche(num_demarche,"error","Erreur inattendue lors de l'actualisation.")

        
@login_required
def etat_actualisation_demarche(request, num_demarche):
    """
    Regarde l'état d'actualisation d'une démarche
    """
    etat = get_etat_actualisation_demarche(num_demarche)

    return JsonResponse(etat)

# @login_required
# def synchroniser_demarche(request, num_demarche):
#     """
#     Synchronise les dossiers d'une démarche. 
#     Fonction appelée depuis la Vue d'ensemble
#     """
#     if request.method == "POST":
#         try:
#             l = lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
#         except Exception as e:
#             loggerSynchro.error(f"Erreur de synchronisation pour la démarche {num_demarche} : {e}")
#     return redirect("instruction_demarche", num_demarche=num_demarche)



@login_required
@require_POST
def synchroniser_demarche(request, num_demarche):
    """
    Synchronisation de la Demarche depuis le module 'Vue d'ensemble'
    """
    demarche = Demarche.objects.filter(numero=num_demarche).first()

    if not demarche:
        return redirect("instruction_demarche", num_demarche=num_demarche)

    if actualisation_demarche_est_bloquee(demarche):
        loggerSynchro.warning(f"[DEMARCHE {num_demarche}] Actualisation bloquée détectée, reset de l'état.")
        clear_etat_actualisation_demarche(num_demarche)
        demarche.refresh_from_db()

    if demarche.actualisation_statut == "running":
        return redirect("instruction_demarche", num_demarche=num_demarche)

    set_etat_actualisation_demarche(num_demarche, "running", "Actualisation en cours...")

    Thread(target=synchroniser_demarche_job, args=(num_demarche, str(request.user)), daemon=True,).start()

    return redirect("instruction_demarche", num_demarche=num_demarche)



@login_required
@require_POST
def synchroniser_demarche_depuis_reception(request, num_demarche):
    """
    Synchronisation de la Demarche depuis la Réception
    """
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    demarche = Demarche.objects.filter(numero=num_demarche).first()

    if not demarche:
        if is_ajax:
            return JsonResponse({"status": "error", "message": "Démarche introuvable."}, status=404)
        return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))

    etat_global = SynchronisationEtat.objects.filter(id=1).first()
    if etat_global and etat_global.en_cours:
        if is_ajax:
            return JsonResponse({"status": "blocked_global","message": "Une synchronisation globale est déjà en cours."}, status=409)
        return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))
    
    if actualisation_demarche_est_bloquee(demarche):
        loggerSynchro.warning(f"[DEMARCHE {num_demarche}] Actualisation bloquée détectée, passage en erreur.")
        set_etat_actualisation_demarche(num_demarche, "error", "Synchronisation interrompue ou bloquée.")
        demarche.refresh_from_db()

    if demarche.actualisation_statut == "running":
        if is_ajax:
            return JsonResponse({"status": "already_running","message": "Une synchronisation de cette démarche est déjà en cours."}, status=409)
        return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))

    set_etat_actualisation_demarche(num_demarche, "running", "Actualisation en cours...")

    Thread(target=synchroniser_demarche_job, args=(num_demarche, str(request.user)), daemon=True,).start()

    if is_ajax:
        return JsonResponse({"status": "ok", "message": "Synchronisation lancée."})

    return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))


# @login_required
# def synchroniser_demarche_depuis_reception(request, num_demarche):
#     """
#     Synchronise les dossiers d'une démarche. 
#     Fonction appelée depuis la Réception
#     """
#     if request.method == "POST":
#         try:
#             l = lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
#         except Exception as e:
#             loggerSynchro.error(f"Erreur de synchronisation pour la démarche {num_demarche} : {e}")
#     return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))



@login_required
def etat_actualisation_dossier(request, num_dossier):
    """
    Regarde l'état d'actualisation d'un dossier
    """
    return JsonResponse(get_etat_actualisation_dossier(num_dossier))



def actualiser_dossier_job(num_dossier, user_display):
    """
    Job executé en arrière plan pour actualiser un dossier.
    """
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        loggerSynchro.error(f"[ACTUALISER DOSSIER] Dossier {num_dossier} introuvable — User : {user_display}")
        set_etat_actualisation_dossier(num_dossier, statut="error", message=f"Le dossier {num_dossier} est introuvable.")
        return

    client = GraphQLClient()

    try:
        set_etat_actualisation_dossier(num_dossier, statut="running", message="Actualisation en cours...")
        loggerSynchro.info("\n\n")
        loggerSynchro.info(f" --- ACTUALISATION DU DOSSIER {num_dossier} ---")


        # ---------------
        # 1. APPEL API DS
        # ---------------
        try:
            result = client.execute_query("DS/queries/get_dossier.graphql", {"number": num_dossier})
        except Exception as api_err:

            loggerSynchro.error(f"[ACTUALISER DOSSIER {num_dossier}] Erreur API DS (get_dossier.graphql) : {api_err}")
            set_etat_actualisation_dossier(num_dossier, statut="error", message="Erreur lors de l'appel à l'API DS.")
            return

        if "errors" in result and result["errors"]:
            erreur = result["errors"][0]

            if erreur and erreur.get("message") == "Dossier not found":
                instructeur = Instructeur.objects.order_by("id").first()
                dossier.present_sur_ds = False
                dossier.save()

                if instructeur:
                    safe_enregistrer_action(dossier, instructeur, "Dossier supprimé de Démarche Numérique", request=None)

                loggerSynchro.warning(f"[ACTUALISER DOSSIER {num_dossier}] Le dossier n'existe plus sur Démarche Numérique : BDD mise à jour")
                set_etat_actualisation_dossier(num_dossier, statut="success", message="Le dossier n'existe plus sur Démarche Numérique.")
                return

            raise Exception(f"Erreur(s) GraphQL lors de l'actualisation du dossier {num_dossier} : {result['errors']}")
        

        # -------------------------
        # 2. NORMALISATION
        # -------------------------
        doss = result["data"].get("dossier")

        if doss.get("demandeur", {}).get("__typename") == "PersonneMoraleIncomplete":
            loggerSynchro.warning(f"Le dossier {doss['number']} ne peut pas être actualisé : services INSEE momentanément indisponibles")
            set_etat_actualisation_dossier(num_dossier, statut="error", message="Les services INSEE sont momentanément indisponibles.")
            return

        contact_beneficiaire = doss.get("demandeur")
        demarche = dossier.id_demarche
        id_demarche = demarche.id
        titre_demarche = demarche.titre


        # ------------------------------------------------
        # 2.1 Déclaration Manifestations (norma + synchro)
        # ------------------------------------------------
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier.id).first()

        if liaison and os.getenv("SYNCHRO_DM", "false") == "True":
            loggerSynchro.info("")
            loggerSynchro.info(f"###### NORMALISATION {liaison.id_dossier_manif.nom_dossier} (Déclaration Manifestations) ######")
            doss_dm = recup_un_seul_dossier(liaison.id_dossier_manif.numero_dossier_declaration_manifestations)
            doss_dm_norma = dossiers_declaration_manifestations_normalize(doss_dm)

            loggerSynchro.info("")
            loggerSynchro.info(f"###### SYNCHRONISATION {doss_dm_norma[0]['nom_dossier']} (Déclaration Manifestations) ######")

            for ddm in doss_dm_norma:
                doss_manif_sportive, doss_lie = sync_declaration_manifestations(ddm, loggerSynchro)

            loggerSynchro.info("---")
            loggerSynchro.info(f"###### NORMALISATION DOSSIER {doss_dm_norma[0]['nom_dossier']} (Démarche Numérique) ######")
        else:
            loggerSynchro.info("")
            loggerSynchro.info(f"###### NORMALISATION DOSSIER {doss['number']} (Démarche Numérique) ######")


        # ------------------------------------
        # 2.2 Démarche Numérique
        # ------------------------------------
        try:
            # contact_beneficiaire = doss["demandeur"]
            # emplacement_dossier = construire_emplacement_dossier(doss, contact_beneficiaire, titre_demarche)
            emplacement_dossier = dossier.emplacement
            c_e_n = contact_externe_normalize(doss, None)
            d_c_n, c_e_n_complete = dossiers_champs_normalize(doss, emplacement_dossier, c_e_n)

            c_e_n_complete.pop("demandeur_pers_morale", None)

            dico_dossier = {
                "dossier": dossier_normalize(id_demarche, doss, emplacement_dossier),
                "contacts_externes": c_e_n_complete,
                "dossier_interlocuteur": dossier_interlocuteur_normalize(doss),
                "dossier_champs": d_c_n,
                "dossier_document": dossier_document_normalize(doss, emplacement_dossier),
                "messages": message_normalize(doss, emplacement_dossier),
                "demandes": demande_normalize(id_demarche, titre_demarche, doss)
            }

        except Exception as e:
            loggerSynchro.error(f"[ACTUALISER DOSSIER {num_dossier}] User {user_display} - Erreur normalisation : {e}")
            set_etat_actualisation_dossier(num_dossier, statut="error", message="Erreur lors de la normalisation du dossier.")
            return
        

        # -------------------------
        # 3. SYNCHRONISATION
        # -------------------------
        try:
            if liaison:
                loggerSynchro.info("")
                loggerSynchro.info(f"###### SYNCHRONISATION DOSSIER {doss_dm_norma[0]['nom_dossier']} (Démarche Numérique) ######")
            else:
                loggerSynchro.info("")
                loggerSynchro.info(f"###### SYNCHRONISATION DOSSIER {dico_dossier['dossier']['nom_dossier']} (Démarche Numérique) ######")

            dico_notifs = {}
            sync_dossiers([dico_dossier], demarche.numero, True, dico_notifs)

        except Exception as sync_err:
            loggerSynchro.error(f"[ACTUALISER DOSSIER {num_dossier}] User {user_display} - Échec lors de la synchronisation : {sync_err}")
            set_etat_actualisation_dossier(num_dossier, statut="error", message="Erreur lors de la synchronisation du dossier.")
            return

        loggerSynchro.info(f"[ACTUALISER DOSSIER {num_dossier}] Actualisation terminée — User : {user_display}")
        set_etat_actualisation_dossier(num_dossier, statut="success", message="Actualisation terminée avec succès.")

    except Exception as e:
        loggerSynchro.error(f"[DOSSIER] Échec de l'actualisation complète du dossier {num_dossier} par {user_display} : {e}")
        set_etat_actualisation_dossier(num_dossier, statut="error", message="Erreur lors de l'actualisation du dossier.")



@require_POST
@login_required
def actualiser_dossier(request, num_dossier):
    """
    Synchronisation d'un Dossier
    """
    dossier = Dossier.objects.filter(numero=num_dossier).first()

    if not dossier:
        logger.error(f"[ACTUALISER DOSSIER] Dossier {num_dossier} introuvable — User : {request.user}")
        return redirect_error(request, f"❌ Le dossier {num_dossier} est introuvable. Contactez le support.")

    if actualisation_dossier_est_bloquee(dossier):
        logger.warning(f"[ACTUALISER DOSSIER {num_dossier}] Actualisation bloquée détectée, reset de l'état.")
        clear_etat_actualisation_dossier(num_dossier)
        dossier.refresh_from_db()

    if dossier.actualisation_statut == "running":
        return redirect(request.META.get("HTTP_REFERER", "/"))

    set_etat_actualisation_dossier(num_dossier, statut="running", message="Actualisation en cours...")

    Thread(target=actualiser_dossier_job, args=(num_dossier, str(request.user)), daemon=True).start()

    return redirect(request.META.get("HTTP_REFERER", "/"))

