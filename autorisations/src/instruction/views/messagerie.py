from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import localtime
from autorisations.models.models_instruction import Dossier, Message
from autorisations.models.models_documents import MessageDocument
from autorisations.models.models_utilisateurs import ContactExterne, DossierInstructeur, Instructeur, DossierInterlocuteur, DossierBeneficiaire
from autorisations.models.models_avis import DossierAvis
from notifications.service import _render_message, envoi_mail
from instruction.services.messagerie_service import enregistrer_message_bdd, envoyer_message_ds, prepare_temp_file
from instruction.utils_instru import format_etat_dossier
from DS.call_DS import suppr_msg_DS, get_msg_DS
from DS.graphql_client import GraphQLClient
from synchronisation.src.normalisation.norma_messages import message_normalize
from synchronisation.src.synchro.sync_messages import sync_messages
import logging, os
from django.utils import timezone
from datetime import timedelta

from django.template.loader import render_to_string
from autorisations.models.models_utilisateurs import EmailOutbox

logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")

@login_required
def preinstruction_dossier_messagerie(request, numero):
    dossier = get_object_or_404(Dossier, numero=numero)

    # Mise à jour des mesages non lus --> lus
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    ids_non_lus = []

    est_instructeur_du_dossier = DossierInstructeur.objects.filter(
        id_dossier=dossier,
        id_instructeur=instructeur
    ).exists()

    est_receptionniste = request.user.groups.filter(name__in=["Réception SAADD", "Réception SPPN"]).exists()

    messages_non_lus = Message.objects.filter(id_dossier=dossier, lu=False).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    )

    nb_messages_non_lus = messages_non_lus.count()

    ids_non_lus = list(messages_non_lus.values_list('id', flat=True))

    if est_instructeur_du_dossier:
        nb = messages_non_lus.update(lu=True)
        if nb > 0:
            logger.info(f"[DOSSIER {dossier.numero}] {nb} message(s) non lus ont été marqués comme lus par {request.user}.")

    raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")
    messages_fmt = []

    for msg in raw_messages:

        nouv_mess = 'non'
        if ids_non_lus != []:
            if msg.id in ids_non_lus :
                nouv_mess = 'oui'

        emetteur = msg.email_emetteur.lower().strip()

        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()

        # left = Message reçu du demandeur, right = Message émis par instructeur ou DS
        align = "right" if emetteur == 'contact@demarches-simplifiees.fr' or emetteur == request.user.email.lower() or emetteur.endswith("reunion-parcnational.fr") else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_url = pj_title = pj_emplacement = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()

            if message_doc and message_doc.id_document:
                
                pj_url, pj_title, pj_emplacement = message_doc.id_document.url_ds, message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_url": pj_url, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess, "emetteur": instru if instru else contact})
        
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
    demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None

    beneficiaire = None 
    benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
    if benef :
        beneficiaire = benef.id_beneficiaire
    else:
        logger.warning(f"[DOSSIER {dossier.numero}] Affichage messagerie : Le dossier n'a pas de bénéficaire de renseigné")

    return render(request, 'instruction/preinstruction_dossier_messagerie.html', {
        "dossier": dossier,
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
    })



@login_required
def instruction_dossier_messagerie(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    # Mise à jour des mesages non lus --> lus
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    ids_non_lus = []

    est_instructeur_du_dossier = DossierInstructeur.objects.filter(
        id_dossier=dossier,
        id_instructeur=instructeur
    ).exists()

    messages_non_lus = Message.objects.filter(id_dossier=dossier, lu=False).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    )

    nb_messages_non_lus = messages_non_lus.count()

    ids_non_lus = list(messages_non_lus.values_list('id', flat=True))

    if est_instructeur_du_dossier:
        nb = messages_non_lus.update(lu=True)
        if nb > 0:
            logger.info(f"[DOSSIER {dossier.numero}] {nb} message(s) non lus ont été marqués comme lus par {request.user}.")

    # Affichage messages
    raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")
    messages_fmt = []
    
    for msg in raw_messages:
        
        nouv_mess = 'non'
        if ids_non_lus != []:
            if msg.id in ids_non_lus :
                nouv_mess = 'oui'

        emetteur = msg.email_emetteur.lower().strip()

        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()

        # left = Message reçu du demandeur, right = Message émis par instructeur ou DS
        align = "right" if emetteur == 'contact@demarches-simplifiees.fr' or emetteur == request.user.email.lower() or emetteur.endswith("reunion-parcnational.fr") else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_url = pj_title = pj_emplacement = None
        if msg.piece_jointe:
            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()

            if message_doc and message_doc.id_document:
                pj_url, pj_title, pj_emplacement = message_doc.id_document.url_ds, message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_url": pj_url, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess, "emetteur": instru if instru else contact})
        
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
    demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None
    
    beneficiaire = None
    benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
    if benef :
        beneficiaire = benef.id_beneficiaire if interlocuteur else None
    else:
        logger.warning(f"[DOSSIER {dossier.numero}] Affichage messagerie : Le dossier n'a pas de bénéficaire de renseigné")

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()


    # Compter le nombre d'avis avec au moins un message non lu de l'expert
    nb_avis_avec_nouveau_mess = 0
    for da in DossierAvis.objects.filter(id_dossier=dossier).select_related("id_avis__id_expert"):
        avis = da.id_avis
        if not avis or not avis.id_expert:
            continue

        if avis.id_expert.est_interne:
            email_expert = avis.id_expert.id_instructeur.email
        else:
            email_expert = avis.id_expert.id_contact_externe.email

        nb_non_lus_avis = Message.objects.filter(
            id_avis=avis,
            lu=False,
            email_emetteur=email_expert
        ).count()

        if nb_non_lus_avis > 0:
            nb_avis_avec_nouveau_mess += 1


    return render(request, 'instruction/instruction_dossier_messagerie.html', {
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "dossier": dossier,
        "messages_doss": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": True,
        "beneficiaire": beneficiaire,
        "demandeur": demandeur,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "nb_avis_envoyes": nb_avis_envoyes,
        "est_instructeur_du_dossier": est_instructeur_du_dossier,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
    })



@require_POST
@csrf_exempt
def envoyer_message_dossier(request, numero):

    if request.POST.get("correction") :
        correction = request.POST.get("correction")
    else:
        correction = False

    # Récupération message et PJ de l'instructeur
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    if not body:
        messages.error(request, "Message vide.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        messages.error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
        logger.warning(f"[DOSSIER {dossier.numero}] {request.user} a voulu joindre un document > 20Mo à son message.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Récupérer le dossier
    dossier = get_object_or_404(Dossier, numero=numero)

    # Récupérer l'instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not dossier.id_ds or not instructeur :
        logger.error(f"[DOSSIER {dossier.numero}] Erreur envoi du message : Soit l'id DS du dossier n'est pas renseignée soit l'instructeur ({request.user}) n'existe pas")
        return HttpResponse(f"Session incomplète [DOSSIER {dossier.numero}] Erreur envoi du message : Soit l'id DS du dossier n'est pas renseignée soit l'instructeur ({request.user}) n'existe pas", status=401)
    
    tmp_file_path = None
    # PUT Message sur D-S
    try:
        if fichier:

            tmp_file_path = prepare_temp_file(fichier)
            result_API_DS = envoyer_message_ds(dossier.id_ds, instructeur, body, fichier, fichier.content_type, tmp_file_path, numero, correction=correction)

        else:
            result_API_DS = envoyer_message_ds(dossier.id_ds, instructeur, body, num_dossier=numero, correction=correction)

            
        if result_API_DS.get("data"):
            msg_ds = None
            dossier_env_msg = result_API_DS["data"].get("dossierEnvoyerMessage")

            if dossier_env_msg is not None:
                msg_ds = dossier_env_msg.get('message')

        if msg_ds and msg_ds.get('id'):
            url_ds = get_msg_DS(numero, msg_ds['id']) if fichier else None
            enregistrer_message_bdd(dossier, request.user.email, body, fichier, id_ds=msg_ds['id'], url_ds=url_ds)

        else:
            loggerDS.error(f"[DOSSIER {dossier.numero}] Erreur envoi message DS (le dossier n'a pas été trouvé sur DS)")
            return HttpResponse(f"Dossier {numero} : Erreur lors de l'envoi du message sur Démarches Simplifiées (Le dossier n'a pas été trouvé)", status=500)
        
    except Exception as e:

        logger.error(f"[DOSSIER {dossier.numero}] Erreur envoi message sur DS : {e}")
        return HttpResponse(f"Erreur : {e}", status=500)
    
    finally:

        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def supprimer_message(request, id):

    message = get_object_or_404(Message, id=id)

    # Vérifie si l'utilisateur est bien l'émetteur
    if message.email_emetteur.lower() != request.user.email.lower():
        messages.error(request, f"❌ Vous n'êtes pas autorisé.e à supprimer ce message car vous n'en n'êtes pas l'auteur.rice")
        return redirect(request.META.get("HTTP_REFERER", "/"))
        # return HttpResponseForbidden("Vous n'êtes pas autorisé à supprimer ce message car vous n'en n'êtes pas l'auteur")
    
    # Suppression côté D-S
    try:
        suppr_msg_DS(message)
        message.delete()
        logger.info(f"[DOSSIER {message.id_dossier.numero}] Message {id} supprimé de la BDD")
        referer = request.META.get("HTTP_REFERER", "")
        if "preinstruction" in referer:
            return redirect("preinstruction_dossier_messagerie", numero=message.id_dossier.numero)
        else:
            return redirect("instruction_dossier_messagerie", num_dossier=message.id_dossier.numero)
    
    except Exception as e:
        logger.error(f"[DOSSIER {message.id_dossier.numero}] Erreur lors de la suppression du message {id} par {request.user}: {e}")
        messages.error(request, f"❌ Erreur lors de la suppression du message {id} par {request.user}: {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
        # return HttpResponse(f"Erreur : {e}", status=500)
    
    
@login_required
def supprimer_message_avis(request, id):

    dossier_numero = request.POST.get("dossier_numero")
    avis_id = request.POST.get("avis_id")
    message = get_object_or_404(Message, id=id)

    # Vérifie si l'utilisateur est bien l'émetteur
    if message.email_emetteur.lower() != request.user.email.lower():
        messages.error(request, "Vous n'êtes pas autorisé à supprimer ce message car vous n'en n'êtes pas l'auteur.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
        
    try:
        message.delete()
        logger.info(f"[DOSSIER {dossier_numero}] Avis {avis_id} : Message {id} supprimé.")
        return redirect("instruction_dossier_avis", num_dossier=dossier_numero, avis_id=avis_id)
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier_numero}] Avis {avis_id} : Erreur lors de la suppression du message {id} par {request.user}: {e}")
        messages.error(request, f"Erreur lors de la suppression du message {id} par {request.user}: {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    

@login_required
def supprimer_message_avis_vision_expert(request, id):

    # dossier_numero = request.POST.get("dossier_numero")
    avis_id = request.POST.get("avis_id")
    message = get_object_or_404(Message, id=id)

    # Vérifie si l'utilisateur est bien l'émetteur
    if message.email_emetteur.lower() != request.user.email.lower():
        messages.error(request, "Vous n'êtes pas autorisé à supprimer ce message car vous n'en n'êtes pas l'auteur.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
        
    try:
        message.delete()
        logger.info(f"[AVIS {avis_id}] Message {id} supprimé.")
        return redirect("avis_expert", avis_id=avis_id)
    
    except Exception as e:
        logger.error(f"[AVIS {avis_id}] Erreur lors de la suppression du message {id} par {request.user}: {e}")
        messages.error(request, f"Erreur lors de la suppression du message {id} par {request.user}: {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def actualiser_messages(request, numero):
    dossier = get_object_or_404(Dossier, numero=numero)
    client = GraphQLClient()

    try:
        # Appel API DS pour récupérer les messages
        result = client.execute_query("DS/queries/get_message.graphql", {"number": dossier.numero})

        if "errors" in result and result["errors"]:
            raise Exception(f"Erreur(s) GraphQL (Actualisation de la messagerie pour le dossier {numero}): {result['errors']}")

        # Normalisation
        messages_norm = message_normalize({"messages": result["data"]["dossier"]["messages"], "number": dossier.numero, "usager": {}, "demandeur": {}}, dossier.emplacement)
        
        # Synchronisation en base
        sync_messages(messages_norm, dossier.id)

        logger.info(f"[DOSSIER {numero}] Actualisation des messages réussie par {request.user}.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    except Exception as e:
        logger.exception(f"[DOSSIER {numero}] Échec de l'actualisation des messages par {request.user}: {e}")
        return HttpResponse(f"Erreur lors de l'actualisation des messages du dossier {numero} par {request.user} : {e}", status=500)
    
    

@login_required
def previsualiser_email(request, email_id):
    email = get_object_or_404(EmailOutbox, pk=email_id)

    try:
        text, html = _render_message(email)

    except Exception as e:
        html = f"<p style='color:red;'>Erreur lors du rendu du template : {e}</p>"

    return render(request, "instruction/email_preview.html", {
        "email": email,
        "corps_html": html,
    })



@login_required
@require_POST
def envoyer_mail_en_copie(request, email_id):
    email = get_object_or_404(EmailOutbox, pk=email_id)
    if email.type_mail != "Envoi de l'acte":
        email.update(type_mail = "Envoi de l'acte")
        email.save()

    dossier = Dossier.objects.filter(id=email.id_dossier.id).first()

    # Tentative >=3 et dernière tentative date de moins de 2h
    if email.try_count >= 3 and (timezone.now() - email.derniere_tentative_envoi) < timedelta(hours=2) :

        logger.error(f"[DOSSIER {dossier.numero}] {email.try_count} tentatives d'envoi de mail échouées à {', '.join(email.to)}.")
        messages.error(request, f"Déjà {email.try_count} tentatives d'envoi de mail échouées à {', '.join(email.to)}. Contactez l'administrateur.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    ok, err = envoi_mail(email_id)

    if ok:
        logger.info(f"[DOSSIER {dossier.numero}] Email ({email.sujet}) envoyé à {', '.join(email.to)} ")
    else:
        logger.error(f"[DOSSIER {dossier.numero}] Tentative {email.try_count} : Échec envoi email à {', '.join(email.to)} : {err}")

        if email.try_count < 3 :
            messages.error(request, f"Tentative {email.try_count} : Échec de l'envoi du mail à {', '.join(email.to)}. Ré-essayez dans quelques minutes, si l'erreur persiste contactez l'administrateur.")
        else :
            messages.error(request, f"Tentative {email.try_count} : Échec de l'envoi du mail à {', '.join(email.to)}. Contactez l'administrateur.")

    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@require_POST
def supprimer_mail(request, email_id):
    email = get_object_or_404(EmailOutbox, pk=email_id)
    dossier = Dossier.objects.filter(id=email.id_dossier.id).first()
    email.delete()
    
    logger.info(f"[DOSSIER {dossier.numero}] Email ({email.statut}) supprimé avec succès : ({email.sujet}) à destination de {', '.join(email.to)} ")
    return redirect(request.META.get("HTTP_REFERER", "/"))
