from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import localtime
from autorisations.models.models_instruction import Dossier, Message
from autorisations.models.models_documents import MessageDocument
from autorisations.models.models_utilisateurs import Instructeur, DossierInterlocuteur, DossierBeneficiaire
from instruction.services.messagerie_service import enregistrer_message_bdd, envoyer_message_ds, prepare_temp_file
from instruction.utils import format_etat_dossier
from DS.call_DS import suppr_msg_DS, get_msg_DS
from DS.graphql_client import GraphQLClient
from synchronisation.src.normalisation.norma_messages import message_normalize
from synchronisation.src.synchro.sync_messages import sync_messages
import logging, os

logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")

@login_required
def preinstruction_dossier_messagerie(request, numero):
    dossier = get_object_or_404(Dossier, numero=numero)
    raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")
    messages_fmt = []

    for msg in raw_messages:

        emetteur = msg.email_emetteur.lower().strip()

        # left = Message reçu du demandeur, right = Message émis par instructeur ou DS
        align = "right" if emetteur == 'contact@demarches-simplifiees.fr' or emetteur == request.user.email.lower() or emetteur.endswith("reunion-parcnational.fr") else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_url = pj_title = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()

            if message_doc and message_doc.id_document:
                
                pj_url, pj_title = message_doc.id_document.url_ds, message_doc.id_document.titre

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_url": pj_url, "pj_title": pj_title})

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
        "messages": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": True,
        "beneficiaire": beneficiaire,
        "demandeur": demandeur,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
    })



@login_required
def instruction_dossier_messagerie(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")
    messages_fmt = []

    for msg in raw_messages:

        emetteur = msg.email_emetteur.lower().strip()

        # left = Message reçu du demandeur, right = Message émis par instructeur ou DS
        align = "right" if emetteur == 'contact@demarches-simplifiees.fr' or emetteur == request.user.email.lower() or emetteur.endswith("reunion-parcnational.fr") else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_url = pj_title = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()

            if message_doc and message_doc.id_document:
                
                pj_url, pj_title = message_doc.id_document.url_ds, message_doc.id_document.titre

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_url": pj_url, "pj_title": pj_title})

    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
    demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None
    
    beneficiaire = None 
    benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
    if benef :
        beneficiaire = benef.id_beneficiaire if interlocuteur else None
    else:
        logger.warning(f"[DOSSIER {dossier.numero}] Affichage messagerie : Le dossier n'a pas de bénéficaire de renseigné")

    return render(request, 'instruction/instruction_dossier_messagerie.html', {
        "dossier": dossier,
        "messages": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": True,
        "beneficiaire": beneficiaire,
        "demandeur": demandeur,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
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
        logger.warning(f"[DOSSIER {dossier.numero}] Message vide envoyé par {request.user}")
        return HttpResponseBadRequest("Message vide")
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        messages.error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
        logger.warning(f"[DOSSIER {dossier.numero}] {request.user} a voulu joindre un document > 20Mo à son message.")
        return redirect('preinstruction_dossier_messagerie', numero=numero)
    
    # Récupérer le dossier
    dossier = get_object_or_404(Dossier, numero=numero)

    # Récupérer l'instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not dossier.id_ds or not instructeur or not instructeur.id_ds:
        logger.error(f"[DOSSIER {dossier.numero}] Soit l'id DS du dossier n'est pas renseignée soit l'instructeur ({request.user}) n'existe pas")
        return HttpResponse("Session incomplète", status=401)
    
    tmp_file_path = None
    # PUT Message sur D-S
    try:
        if fichier:

            tmp_file_path = prepare_temp_file(fichier)
            result_API_DS = envoyer_message_ds(dossier.id_ds, instructeur.id_ds, body, fichier, fichier.content_type, tmp_file_path, numero, correction=correction)

        else:

            result_API_DS = envoyer_message_ds(dossier.id_ds, instructeur.id_ds, body, num_dossier=numero, correction=correction)


            
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
            return HttpResponse(f"Dossier {numero} : Erreur envoi message DS (le dossier n'a pas été trouvé sur DS)", status=500)
        
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
        return HttpResponseForbidden("Vous n'êtes pas autorisé à supprimer ce message car vous n'en n'êtes pas l'auteur'")
    
    # Suppression côté D-S
    try:
        suppr_msg_DS(message)
        message.delete()
        logger.info(f"[DOSSIER {message.id_dossier.numero}] Message {id} supprimé de la BDD")
        return redirect('preinstruction_dossier_messagerie', numero=message.id_dossier.numero)
    
    except Exception as e:
        logger.error(f"[DOSSIER {message.id_dossier.numero}] Erreur lors de la suppression du message {id} par {request.user}: {e}")
        return HttpResponse(f"Erreur : {e}", status=500)



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
        return redirect('preinstruction_dossier_messagerie', numero=numero)
    
    except Exception as e:
        logger.exception(f"[DOSSIER {numero}] Échec de l'actualisation des messages par {request.user}: {e}")
        return HttpResponse(f"Erreur lors de l'actualisation des messages du dossier {numero} par {request.user} : {e}", status=500)
    
