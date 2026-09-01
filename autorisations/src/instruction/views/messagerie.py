from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import localtime
from autorisations.models.models_instruction import Dossier, DossierManifSportive, Message
from autorisations.models.models_documents import MessageDocument
from autorisations.models.models_utilisateurs import ContactExterne, DossierInstructeur, Instructeur, DossierInterlocuteur, DossierBeneficiaire
from autorisations.models.models_avis import DossierAvis
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD
from instruction.utils.avis_utils import count_avis_with_unread_messages_for_dossier
from instruction.utils.dossier_utils import get_chemin_complet_dossier, redirect_error
from notifications.service import _render_message, compute_dedupe_key, create_EmailOutbox, create_EmailOutbox_DM, envoi_mail
from instruction.services.messagerie_service import enregistrer_message_bdd, envoyer_message_ds, prepare_temp_file
from instruction.utils_instru import format_etat_dossier
from DS.call_DS import suppr_msg_DS, get_msg_DS
from DS.graphql_client import GraphQLClient
from synchronisation.normalisation.norma_messages import message_normalize
from synchronisation.synchro.sync_messages import sync_messages
import logging, os
import smbclient
from django.utils import timezone
from datetime import timedelta

from django.template.loader import render_to_string
from autorisations.models.models_utilisateurs import EmailOutbox

logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")


def _get_message_signature(instructeur):
    agent = instructeur.id_agent_autorisations if instructeur else None
    if agent:
        identite = " ".join(
            valeur for valeur in [agent.prenom, agent.nom] if valeur
        )
    else:
        identite = str(instructeur) if instructeur else ""

    return f"{identite}\nParc national de La Réunion"


@login_required
def preinstruction_dossier_messagerie(request, numero):

    dossier = Dossier.objects.filter(numero=numero).first()
    if not dossier:
        logger.error(f"[PRE-INSTRUCTION MESSAGERIE] Dossier {numero} introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")

    # -----------------------------------
    # 1. Instructeur & autorisations
    # -----------------------------------
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    est_instructeur_du_dossier = False
    if instructeur:
        est_instructeur_du_dossier = DossierInstructeur.objects.filter(id_dossier=dossier,id_instructeur=instructeur).exists()

    est_receptionniste = request.user.groups.filter(name__in=["Réception SAADD", "Réception SPPN"]).exists()

    # -----------------------------------
    # 2. Messages non lus
    # -----------------------------------
    messages_non_lus = Message.objects.filter(id_dossier=dossier, lu=False).exclude(
        email_emetteur__in=[
                    "contact@demarches-simplifiees.fr",
                    "contact@demarche.numerique.gouv.fr",
                ]
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    )

    nb_messages_non_lus = messages_non_lus.count()
    ids_non_lus = list(messages_non_lus.values_list('id', flat=True))

    if est_instructeur_du_dossier:
        try:
            nb = messages_non_lus.update(lu=True)
            if nb > 0:
                logger.info(f"[DOSSIER {dossier.numero}] {nb} message(s) non lus ont été marqués comme lus par {request.user}.")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Pré-Instruction Messagerie, Échec mise à jour en 'lus' des messages 'non lus' par {request.user} : {e}")

    # -----------------------------------
    # 3. Liste des messages
    # -----------------------------------
    raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")
    messages_fmt = []

    for msg in raw_messages:

        est_nouveau = msg.id in ids_non_lus
        emetteur = (msg.email_emetteur or "").lower().strip()
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # left = Message reçu du demandeur, right = Message émis par instructeur ou DS
        align = (
            "right"
            if emetteur in [ "contact@demarches-simplifiees.fr", "contact@demarche.numerique.gouv.fr", request.user.email.lower()] or emetteur.endswith("reunion-parcnational.fr")
            else "left"
        )

        # Déterminer si émetteur est un instructeur ou un contact externe
        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()
        emetteur_obj = instru if instru else contact


        # Recherche de la pièce jointe liée au message
        # pj = None
        # if msg.piece_jointe:

        #     message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()

        #     if message_doc and message_doc.id_document:
        #         pj = {
        #             "url": message_doc.id_document.url_ds,
        #             "titre": message_doc.id_document.titre,
        #             "emplacement": message_doc.id_document.emplacement,
        #         }
                

        # messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, 
        #                     "pj_url": pj["url"] if pj else None, "pj_title": pj["titre"] if pj else None, "pj_emplacement": pj["emplacement"] if pj else None, 
        #                     "nouv_mess": "oui" if est_nouveau else "non", "emetteur": emetteur_obj})

        pjs = []

        if msg.piece_jointe:
            message_docs = (
                MessageDocument.objects
                .filter(id_message=msg)
                .select_related("id_document")
            )

            for message_doc in message_docs:
                if message_doc.id_document:
                    pjs.append({
                        "url": message_doc.id_document.url_ds,
                        "titre": message_doc.id_document.titre,
                        "emplacement": message_doc.id_document.emplacement,
                    })

        messages_fmt.append({
            "id": msg.id,
            "body": msg.body,
            "date_envoi": date_fmt,
            "align": align,
            "pjs": pjs,
            "nouv_mess": "oui" if est_nouveau else "non",
            "emetteur": emetteur_obj,
        })

    
    # -----------------------------------
    # 4. Bénéficiaire & demandeur
    # -----------------------------------
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
    demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None

    beneficiaire = None 
    if interlocuteur:
        benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
        if benef :
            beneficiaire = benef.id_beneficiaire
        else:
            logger.warning(f"[DOSSIER {dossier.numero}] Affichage Pré-Instruction Messagerie : Bénéficaire non renseigné")


    return render(request, 'instruction/preinstruction_dossier_messagerie.html', {
        "dossier": dossier,
        "chemin_complet": get_chemin_complet_dossier(dossier),
        "messages_doss": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": True,
        "beneficiaire": beneficiaire,
        "demandeur": demandeur,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "est_instructeur_du_dossier": est_instructeur_du_dossier,
        "est_receptionniste": est_receptionniste,
        "nb_messages_non_lus": nb_messages_non_lus,
        "signature_message": _get_message_signature(instructeur),
    })



@login_required
def instruction_dossier_messagerie(request, num_dossier):

    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[INSTRUCTION MESSAGERIE] Dossier {num_dossier} introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")
    
    # -----------------------------------
    # 1. Instructeur & autorisations
    # -----------------------------------
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    est_instructeur_du_dossier = False
    if instructeur:
        est_instructeur_du_dossier = DossierInstructeur.objects.filter(id_dossier=dossier,id_instructeur=instructeur).exists()

    est_receptionniste = request.user.groups.filter(
        name__in=["Réception SAADD", "Réception SPPN"]
    ).exists()


    # -----------------------------------
    # 2. Messages non lus
    # -----------------------------------
    messages_non_lus = Message.objects.filter(id_dossier=dossier, lu=False).exclude(
        email_emetteur__in=[
                    "contact@demarches-simplifiees.fr",
                    "contact@demarche.numerique.gouv.fr",
                ]
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    )

    nb_messages_non_lus = messages_non_lus.count()
    ids_non_lus = list(messages_non_lus.values_list('id', flat=True))

    if est_instructeur_du_dossier or est_receptionniste:
        try:
            nb = messages_non_lus.update(lu=True)
            if nb > 0:
                logger.info(f"[DOSSIER {dossier.numero}] {nb} message(s) non lus ont été marqués comme lus par {request.user}.")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Instruction Messagerie, Échec mise à jour en 'lus' des messages 'non lus' par {request.user} : {e}")


    # -----------------------------------
    # 3. Liste des messages
    # -----------------------------------
    raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")
    messages_fmt = []
    
    for msg in raw_messages:

        est_nouveau = msg.id in ids_non_lus
        emetteur = (msg.email_emetteur or "").lower().strip()
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"
        
        # left = Message reçu du demandeur, right = Message émis par instructeur ou DS
        align = (
            "right"
            if emetteur in [ "contact@demarches-simplifiees.fr", "contact@demarche.numerique.gouv.fr", request.user.email.lower()] or emetteur.endswith("reunion-parcnational.fr")
            else "left"
        )

        # Déterminer si émetteur est un instructeur ou un contact externe
        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()
        emetteur_obj = instru if instru else contact

        # Recherche de la pièce jointe liée au message
        pj = None

        # if msg.piece_jointe:

        #     message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()

        #     if message_doc and message_doc.id_document:
        #         pj = {
        #             "url": message_doc.id_document.url_ds,
        #             "titre": message_doc.id_document.titre,
        #             "emplacement": message_doc.id_document.emplacement,
        #         }
                

        # messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, 
        #                     "pj_url": pj["url"] if pj else None, "pj_title": pj["titre"] if pj else None, "pj_emplacement": pj["emplacement"] if pj else None, 
        #                     "nouv_mess": "oui" if est_nouveau else "non", "emetteur": emetteur_obj})

        pjs = []

        if msg.piece_jointe:
            message_docs = (
                MessageDocument.objects
                .filter(id_message=msg)
                .select_related("id_document")
            )

            for message_doc in message_docs:
                if message_doc.id_document:
                    pjs.append({
                        "url": message_doc.id_document.url_ds,
                        "titre": message_doc.id_document.titre,
                        "emplacement": message_doc.id_document.emplacement,
                    })

        messages_fmt.append({
            "id": msg.id,
            "body": msg.body,
            "date_envoi": date_fmt,
            "align": align,
            "pjs": pjs,
            "nouv_mess": "oui" if est_nouveau else "non",
            "emetteur": emetteur_obj,
        })

        


    # -----------------------------------
    # 4. Bénéficiaire & demandeur
    # -----------------------------------
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
    demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None
    
    beneficiaire = None
    benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
    if benef :
        beneficiaire = benef.id_beneficiaire if interlocuteur else None
    else:
        logger.warning(f"[DOSSIER {dossier.numero}] Affichage Instruction Messagerie : Le dossier n'a pas de bénéficaire de renseigné")


    # -----------------------------------
    # 5. Avis : nouveaux messages experts
    # -----------------------------------

    # Nombre d'avis envoyés pour le dossier
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()
    # Nombre d'avis avec nouveaux messages
    nb_avis_avec_nouveau_mess = count_avis_with_unread_messages_for_dossier(dossier)


    return render(request, 'instruction/instruction_dossier_messagerie.html', {
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "dossier": dossier,
        "chemin_complet": get_chemin_complet_dossier(dossier),
        "messages_doss": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": True,
        "beneficiaire": beneficiaire,
        "demandeur": demandeur,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "nb_avis_envoyes": nb_avis_envoyes,
        "est_instructeur_du_dossier": est_instructeur_du_dossier,
        "est_receptionniste": est_receptionniste,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "signature_message": _get_message_signature(instructeur),
    })



@require_POST
@login_required
def envoyer_message_dossier(request, numero):

    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")
    correction = request.POST.get("correction") or False
    message_signe = request.POST.get("message_signe") == "oui"

    # ----------------------------
    # Vérification
    # ----------------------------
    if not body:
        return redirect_error(request, "❌ Votre message est vide.")
    
    # Récupérer le dossier
    dossier = Dossier.objects.filter(numero=numero).first()
    if not dossier:
        logger.error(f"[ENVOI MESSAGE] Dossier {numero} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")
    
    if not dossier.id_ds :
        logger.error(f"[DOSSIER {numero}] Erreur envoi du message par {request.user} : id_ds manquant — impossible d’envoyer le message DS.")
        return redirect_error(request, "❌ Échec de l'envoi du message. L'id Démarche Numérique du dossier est introuvable. Contactez le support.")
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        logger.warning(f"[DOSSIER {dossier.numero}] {request.user} a voulu joindre un document > 20Mo à son message.")
        return redirect_error(request, "❌ Fichier trop volumineux. Taille maximale : 20 Mo.")
    
    
    # Récupérer l'instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {numero}] User {request.user} sans profil instructeur a tenté d’envoyer un message.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")

    # Signature du message
    if message_signe:
        body = f"{body}\n\n\n{_get_message_signature(instructeur)}"

    # ----------------------------
    # Envoi vers DS
    # ----------------------------
    tmp_file_path = None
    try:
        if fichier:
            tmp_file_path = prepare_temp_file(fichier)
            result_API_DS = envoyer_message_ds(dossier.id_ds, instructeur, body, fichier, fichier.content_type, tmp_file_path, numero, correction=correction)

        else:
            result_API_DS = envoyer_message_ds(dossier.id_ds, instructeur, body, num_dossier=numero, correction=correction)

        # ----------------------------
        # Vérification réponse DS
        # ----------------------------

        ds_data = result_API_DS.get("data", {})
        dossier_env = ds_data.get("dossierEnvoyerMessage")

        if not dossier_env or not dossier_env.get("message"):
            logger.error(f"[DOSSIER {numero}] Erreur lors de l'envoi d'un message sur DS par {request.user}.")
            return redirect_error(request, "❌ Erreur lors de l'envoi du message sur Démarche Numérique. Contactez le support")

        msg_ds = dossier_env["message"]
        msg_id_ds = msg_ds.get("id")

        # Récupération URL DS si PJ
        url_ds = get_msg_DS(numero, msg_id_ds) if fichier else None
        enregistrer_message_bdd(dossier, request.user.email, body, fichier, id_ds=msg_ds['id'], url_ds=url_ds)

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'envoi d'un message sur DS par {request.user} : {e}")
        return redirect_error(request, "❌ Erreur lors de l'envoi du message sur Démarche Numérique. Contactez le support")
    
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
            except Exception as e:
                logger.warning(f"[DOSSIER {numero}] Impossible de supprimer tmp file {tmp_file_path} : {e}")


    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def supprimer_message(request, id):

    # -----------------
    # Vérifications
    # -----------------
    message = Message.objects.filter(id=id).first()
    if not message:
        logger.error(f"[SUPPRESSION MESSAGE] Message {id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le message est introuvable. Contactez le support.")
    
    dossier = message.id_dossier
    if not dossier:
        logger.error(f"[SUPPRESSION MESSAGE] Message {id} sans dossier lié — User {request.user}")
        return redirect_error(request, "❌ Le dossier lié au message est introuvable. Contactez le support.")
    
    # Vérifie si l'utilisateur est bien l'émetteur
    email_user = (request.user.email or "").lower().strip()
    email_message = (message.email_emetteur or "").lower().strip()

    if email_message != email_user:
        logger.warning(f"[DOSSIER {dossier.numero}] Suppression message {id} refusée — User {request.user.email} n'est pas l'auteur.")
        return redirect_error(request, "❌ Vous ne pouvez supprimer que vos propres messages.")

   
    # ------------------------
    # Suppression côté D-S
    # ------------------------    
    try:
        suppr_msg_DS(message)

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Échec suppression DS du message {id} par {request.user} : {e}")
        return redirect_error(request, "❌ Erreur lors de la suppression du message sur Démarche Numérique. Contactez le support.")
    

    # ------------------------
    # Suppression en BDD
    # ------------------------  
    try:
        message.delete()
        logger.info(f"[DOSSIER {message.id_dossier.numero}] Message {id} supprimé par {request.user}")
        
    except Exception as e:
        logger.error(f"[DOSSIER {message.id_dossier.numero}] Erreur lors de la suppression du message {id} en BDD par {request.user} : {e}")
        return redirect_error(request, f"❌ Erreur lors de la suppression du message {id} en base. Contactez le support.")
       

    # Redirection selon origine
    referer = (request.META.get("HTTP_REFERER") or "").lower()
    if "preinstruction" in referer:
        return redirect("preinstruction_dossier_messagerie", numero=message.id_dossier.numero)

    return redirect("instruction_dossier_messagerie", num_dossier=message.id_dossier.numero)

    
    
@login_required
def supprimer_message_avis(request, id):

    dossier_numero = request.POST.get("dossier_numero")
    avis_id = request.POST.get("avis_id")

    # -----------------
    # Vérifications
    # -----------------
    message = Message.objects.filter(id=id).first()
    if not message:
        logger.error(f"[SUPPRESSION MESSAGE AVIS] Message {id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le message est introuvable. Contactez le support.")

    if not dossier_numero or not avis_id:
        logger.error(f"[SUPPRESSION MESSAGE AVIS] Paramètres manquants : dossier={dossier_numero}, avis={avis_id} — User {request.user}")
        return redirect_error(request, "❌ Paramètres manquants pour supprimer le message. Contactez le support.")

    # Vérifie si l'utilisateur est bien l'émetteur
    email_user = (request.user.email or "").lower().strip()
    email_message = (message.email_emetteur or "").lower().strip()

    if email_message != email_user:
        logger.warning(f"[DOSSIER {dossier_numero}] Avis {avis_id} : Suppression message {id} refusée — User {request.user.email} n'est pas l'auteur.")
        return redirect_error(request, "❌ Vous ne pouvez supprimer que vos propres messages.")


    # --------------------
    # Suppression message
    # --------------------
    try:
        message.delete()
        logger.info(f"[DOSSIER {dossier_numero}] Avis {avis_id} : Message {id} supprimé par {request.user}.")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier_numero}] Avis {avis_id} : Erreur lors de la suppression du message {id} par {request.user}: {e}")
        return redirect_error(request, "❌ Erreur lors de la suppression du message. Contactez le support.")
    
    return redirect("instruction_dossier_avis", num_dossier=dossier_numero, avis_id=avis_id)


 
@login_required
def supprimer_message_avis_vision_expert(request, id):

    avis_id = request.POST.get("avis_id")

    # -----------------
    # Vérifications
    # -----------------
    if not avis_id:
        logger.error(f"[SUPPRESSION MESSAGE AVIS EXPERT] Paramètre avis_id manquant pour message {id} — User {request.user}")
        return redirect_error(request, "❌ Erreur lors de l'identification de l'avis. Contactez le support.")

    message = Message.objects.filter(id=id).first()
    if not message:
        logger.error(f"[SUPPRESSION MESSAGE AVIS] Message {id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le message est introuvable. Contactez le support.")


    # Vérifie si l'utilisateur est bien l'émetteur
    email_user = (request.user.email or "").lower().strip()
    email_message = (message.email_emetteur or "").lower().strip()

    if email_message != email_user:
        logger.warning(f"[AVIS {avis_id}] : Suppression message {id} refusée — User {request.user.email} n'est pas l'auteur.")
        return redirect_error(request, "❌ Vous ne pouvez supprimer que vos propres messages.")


    # --------------------
    # Suppression message
    # --------------------
    try:
        message.delete()
        logger.info(f"[AVIS {avis_id}] : Message {id} supprimé par {request.user}.")

    except Exception as e:
        logger.error(f"[AVIS {avis_id}] : Erreur lors de la suppression du message {id} par {request.user}: {e}")
        return redirect_error(request, "❌ Erreur lors de la suppression du message. Contactez le support.")

    return redirect("avis_expert", avis_id=avis_id)



@login_required
def actualiser_messages(request, numero):

    dossier = Dossier.objects.filter(numero=numero).first()
    if not dossier:
        logger.error(f"[ACTUALISATION MESSAGES] Dossier {numero} introuvable — User {request.user}")
        return redirect_error(request, "❌ Échec de l'actualisation de la messagerie. Le dossier associé est introuvable. Contactez le support.")

    client = GraphQLClient()

    # Appel API DS pour récupérer les messages
    try:
        result = client.execute_query("DS/queries/get_message.graphql", {"number": dossier.numero})

        if result.get("errors"):
            raise Exception(f"Erreur(s) GraphQL (Actualisation de la messagerie pour le dossier {numero}) : {result['errors']}")

    except Exception as e:
        logger.error(f"[DOSSIER {numero}] Échec requête DS pour actualisation messages — User {request.user} : {e}")
        return redirect_error(request,"❌ Erreur lors de la récupération des messages sur Démarche Numérique. Contactez le support.")
       
    # Normalisation
    try :
        data_ds = result.get("data", {}).get("dossier", {})
        messages_bruts = data_ds.get("messages", [])
        messages_norm = message_normalize(data_ds, dossier.emplacement)
        
    except Exception as e:
        logger.error(f"[DOSSIER {numero}] Échec de l'actualisation des messages par {request.user} - Erreur lors de normalisation des messages récupérés sur DS : {e}")
        return redirect_error(request,"❌ Erreur lors de la normalisation des messages récupérés sur Démarche Numérique. Contactez le support.")
    

    # Synchronisation
    try:
        sync_messages(messages_norm, dossier.id)
        logger.info(f"[DOSSIER {numero}] Actualisation des messages effectuée par {request.user}.")

    except Exception as e:
        logger.error(f"[DOSSIER {numero}] Actualisation de la messagerie par {request.user} : Erreur lors de la synchronisation des messages : {e}")
        return redirect_error(request, "❌ Échec lors de la synchronisation des messages. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))
    
    

@login_required
def previsualiser_email(request, email_id):

    # email = get_object_or_404(EmailOutbox, pk=email_id)
    email = EmailOutbox.objects.filter(id=email_id).first()
    if not email:
        logger.error(f"[PREVIEW EMAIL] EmailOutbox {email_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ L’email demandé est introuvable. Contactez le support.")
    
    try:
        text, html = _render_message(email)

    except Exception as e:
        logger.error(f"[PREVIEW EMAIL] Erreur lors dela visualisation de l'email {email_id} par {request.user} : {e}")
        html = f"<p style='color:red;'>Erreur lors du rendu du template : {e}</p>"

    annexes_supplementaires = []
    if isinstance(email.context, dict):
        for annexe in email.context.get("pieces_jointes_supplementaires", []) or []:
            chemin = annexe.get("chemin", "")
            emplacement, titre_stockage = os.path.split(chemin)
            chemin_absolu = os.path.join(os.getenv("NAS_ROOT", ""), chemin)
            try:
                disponible = bool(chemin and smbclient.path.exists(chemin_absolu))
            except Exception as exc:
                logger.warning(
                    f"[PREVIEW EMAIL {email_id}] Disponibilité de l'annexe "
                    f"'{annexe.get('nom', chemin)}' impossible à vérifier : {exc}"
                )
                disponible = False
            annexes_supplementaires.append({
                **annexe,
                "emplacement": emplacement,
                "titre_stockage": titre_stockage,
                "disponible": disponible,
            })

    return render(request, "instruction/email_preview.html", {
        "email": email,
        "corps_html": html,
        "annexes_supplementaires": annexes_supplementaires,
    })



@login_required
@require_POST
def envoyer_mail_en_copie(request, email_id):

    # email = get_object_or_404(EmailOutbox, pk=email_id)
    email = EmailOutbox.objects.filter(id=email_id).first()
    if not email:
        logger.error(f"[ENVOI MAIL COPIE] EmailOutbox {email_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Email introuvable en base. Contactez le support.")

    # dossier = Dossier.objects.filter(id=email.id_dossier.id).first()
    dossier = Dossier.objects.filter(id=email.id_dossier_id).first()
    if not dossier:
        logger.error(f"[ENVOI MAIL COPIE] Email {email_id} : dossier {email.id_dossier_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le dossier lié à cet email est introuvable. Contactez le support.")
    
    

    if email.type_mail != "Envoi de l'acte":
        try:
            email.type_mail = "Envoi de l'acte"
            email.save()

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Envoi mail en copie par {request.user} - Email {email.id} impossible de mettre à jour (type_mail) : {e}")
            return redirect_error(request, "❌ Échec de l'envoi du mail. Contactez le support.")


    # Tentative >=3 et dernière tentative date de moins de 2h
    limite_temps = timedelta(hours=2)

    if email.try_count >= 3 and (timezone.now() - email.derniere_tentative_envoi) < limite_temps :

        logger.error(f"[DOSSIER {dossier.numero}] {email.try_count} tentatives d'envoi de mail échouées à {', '.join(email.to)}.")
        return redirect_error(request, f"Déjà {email.try_count} tentatives d'envoi de mail échouées à {', '.join(email.to)}. Contactez le support.")

    ok, err = envoi_mail(email_id)

    if ok:
        logger.info(f"[DOSSIER {dossier.numero}] Email ({email.id}) envoyé par {request.user} à {', '.join(email.to)} ")
    else:
        logger.error(f"[DOSSIER {dossier.numero}] Tentative {email.try_count} : Échec envoi email par {request.user} à {', '.join(email.to)} : {err}")

        if email.try_count < 3 :
            messages.error(request, f"Tentative {email.try_count} : Échec de l'envoi du mail à {', '.join(email.to)}. Ré-essayez dans quelques minutes, si l'erreur persiste contactez le support.")
        else :
            messages.error(request, f"Tentative {email.try_count} : Échec de l'envoi du mail à {', '.join(email.to)}. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
@require_POST
def renvoyer_mail_relance(request, email_id):

    # email = get_object_or_404(EmailOutbox, pk=email_id)
    email = EmailOutbox.objects.filter(id=email_id).first()
    if not email:
        logger.error(f"[ENVOI MAIL COPIE] EmailOutbox {email_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Email introuvable en base. Contactez le support.")

    # dossier = Dossier.objects.filter(id=email.id_dossier.id).first()
    dossier_dm = DossierManifSportive.objects.filter(id=email.id_dossier_dm_id).first()
    if not dossier_dm:
        logger.error(f"[ENVOI MAIL COPIE] Email {email_id} : dossier DM {email.id_dossier_dm_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le dossier DM lié à cet email est introuvable. Contactez le support.")
    
    numero_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations
    

    # Tentative >=3 et dernière tentative date de moins de 2h
    limite_temps = timedelta(hours=2)

    if email.try_count >= 3 and (timezone.now() - email.derniere_tentative_envoi) < limite_temps :

        logger.error(f"[DOSSIER DM {numero_dossier_dm}] {email.try_count} tentatives d'envoi de mail échouées à {', '.join(email.to)}.")
        return redirect_error(request, f"Déjà {email.try_count} tentatives d'envoi de mail échouées à {', '.join(email.to)}. Contactez le support.")

    ok, err = envoi_mail(email_id)

    if ok:
        logger.info(f"[DOSSIER DM {numero_dossier_dm}] Email ({email.id}) envoyé par {request.user} à {', '.join(email.to)} ")
    else:
        logger.error(f"[DOSSIER DM {numero_dossier_dm}] Tentative {email.try_count} : Échec envoi email par {request.user} à {', '.join(email.to)} : {err}")

        if email.try_count < 3 :
            messages.error(request, f"Tentative {email.try_count} : Échec de l'envoi du mail à {', '.join(email.to)}. Ré-essayez dans quelques minutes, si l'erreur persiste contactez le support.")
        else :
            messages.error(request, f"Tentative {email.try_count} : Échec de l'envoi du mail à {', '.join(email.to)}. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))




@login_required
@require_POST
def envoi_manuel_mail_relance(request, id_dm):
    """
    Envoyer un autre mail de relance manuellement depuis l'application

    Args :
        id_dm : DossierManifSportive.id

    """

    ########################
    # Récupération des infos
    ########################

    dossier_dm = DossierManifSportive.objects.filter(id=id_dm).first()
    if not dossier_dm:
        logger.error(f"[ENVOI MAIL RELANCE DM] DossierManifSportive (id = {id_dm}) introuvable — User {request.user}")
        return redirect_error(request, "❌ Le dossier Déclaration Manifestations est introuvable. Contactez le support.")

    numero_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations


    if NOTIFS_PROD :
        emails_norm = [e.strip() for e in request.POST.getlist("emails[]") if e and e.strip()]

    else :
        emails_norm = [EMAIL_NOTIF_TEST]

    emails_txt = ", ".join(emails_norm)

    sujet = (request.POST.get("objet") or "").strip()
    body = (request.POST.get("body") or "").strip()
    context = {"body": body}
    template_name = "mail_relance_manif_sportive_2"

    ##################
    # Vérifications
    ##################
    if not emails_norm:
        logger.warning(f"[DOSSIER DM {numero_dossier_dm}] Envoi manuel mail relance sans destinataire — User {request.user}")
        return redirect_error(request, "❌ Veuillez renseigner au moins un destinataire.")

    if not sujet:
        logger.warning(f"[DOSSIER DM {numero_dossier_dm}] Envoi manuel mail relance sans sujet — User {request.user}")
        return redirect_error(request, "❌ Veuillez renseigner un objet de mail.")

    if not body:
        logger.warning(f"[DOSSIER DM {numero_dossier_dm}] Envoi manuel mail relance sans corps — User {request.user}")
        return redirect_error(request, "❌ Veuillez renseigner le corps du mail.")


    # PRINT DEBUG
    print({
        "to": emails_norm,
        "sujet": sujet,
        "body": body,
    })


    ##################
    # Envoi du mail
    ##################
    try :
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

    except Exception as e:
        messages.error(request, f"L'email de relance à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")
        logger.error(f"[DOSSIER DM {numero_dossier_dm}] Échec de l'envoi du mail de relance à {emails_txt} par {request.user} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
        return
    

    outbox = create_EmailOutbox_DM(emails_norm, sujet, template_name, dedupe, context, dossier_dm, type_mail = "Relance")
        
    if outbox :
        ok, err = envoi_mail(outbox.id)
    else :
        logger.error(f"[DOSSIER DM {numero_dossier_dm}] Échec de l'envoi du mail de relance à {emails_txt} par {request.user} : Erreur lors de la création de l'EmailOutbox")
        messages.error(request, f"L'email de relance à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")
        return
    
    if ok:
        logger.info(f"[DOSSIER DM {numero_dossier_dm}] Email de relance envoyé par {request.user} à {emails_txt}")
        messages.success(request, f"Mail de relance envoyé à {emails_txt}.")
    else:
        logger.error(f"[DOSSIER DM {numero_dossier_dm}] Échec de l'envoi du mail de relance par {request.user} à {emails_txt} : {err}")


        # ici email.try_count n’est plus fiable en mémoire après update dans envoi_mail()
        outbox.refresh_from_db()

        if outbox.try_count < 3:
            messages.error(request, f"Tentative {outbox.try_count} : échec de l'envoi du mail à {emails_txt}. "
                                    f"Réessayez dans quelques minutes, si l'erreur persiste contactez le support."
                            )
        else:
            messages.error(request, f"Tentative {outbox.try_count} : échec de l'envoi du mail à {emails_txt}. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))






@login_required
@require_POST
def supprimer_mail(request, email_id):

    # email = get_object_or_404(EmailOutbox, pk=email_id)
    email = EmailOutbox.objects.filter(id=email_id).first()
    if not email:
        logger.error(f"[SUPPRESSION EMAIL] EmailOutbox {email_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ L’email est introuvable. Contactez le support.")

    # dossier = Dossier.objects.filter(id=email.id_dossier.id).first()
    dossier = Dossier.objects.filter(id=email.id_dossier_id).first()
    if not dossier:
        logger.error(f"[SUPPRESSION EMAIL] Email {email_id} : Dossier {email.id_dossier_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le dossier associé à cet email est introuvable. Contactez le support.")
    
    try :
        email.delete()
        logger.info(f"[DOSSIER {dossier.numero}] Email ({email.id}) supprimé avec succès par {request.user}.")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la suppression de l’email {email_id} par {request.user} : {e}")
        return redirect_error(request,"❌ Une erreur s’est produite lors de la suppression de l’email. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))
