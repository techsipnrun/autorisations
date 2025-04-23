from datetime import date
import json
import os
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import localtime
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required

from autorisations.models.models_documents import DocumentFormat
from autorisations.models.models_instruction import Demarche, Dossier, EtatDossier, Message
from autorisations.models.models_utilisateurs import DossierInstructeur, DossierInterlocuteur, DossierBeneficiaire, Instructeur
from autorisations import settings

from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from BDD.pg_functions import create_message_bdd
from instruction.services.messagerie_service import enregistrer_message_bdd, envoyer_message_ds, prepare_temp_file
from instruction.utils import format_etat_dossier
from synchronisation.src.utils import lancer_normalisation_et_synchronisation
from threading import Thread, Lock

import tempfile
from django.core.files.uploadedfile import UploadedFile
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

import logging
logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  



# @login_required(login_url='/login/')
# def accueil(request):
#     return render(request, 'instruction/instruction.html')

@login_required(login_url='/login/')
def avis(request):
    return render(request, 'instruction/avis.html')

@login_required(login_url='/login/')
def suivi(request):

    # from django.db import connection
    # doc = DocumentFormat(id=26, format="test format")
    # doc.save()
  
    return render(request, 'instruction/suivi.html')


# from django.db.models import Prefetch



@login_required(login_url='/login/')
def preinstruction(request):
    # Récupérer l'ID correspondant à "en_construction"
    etat_en_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()

    dossiers = Dossier.objects.filter(id_etat_dossier=etat_en_construction) \
        .select_related("id_demarche") \
        .order_by("date_depot")

    dossier_infos = []
    for dossier in dossiers:

        # Chercher le demandeur via DossierInterlocuteur
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
        demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None

        if not demandeur:
            dossier_beneficiaire = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first() if interlocuteur else None
            demandeur = dossier_beneficiaire.id_beneficiaire if dossier_beneficiaire else None

        dossier_infos.append({
            "demarche": dossier.id_demarche.type,
            "date_depot": dossier.date_depot,
            "demandeur": f"{demandeur.prenom} {demandeur.nom}" if demandeur else "N/A",
            "nom_projet": dossier.nom_dossier,
            "numero": dossier.numero,
        })

    return render(request, 'instruction/preinstruction.html', {
        "dossier_infos": dossier_infos,
    })


@login_required
def preinstruction_dossier(request, numero):
    dossier = get_object_or_404(Dossier, numero=numero)

    champs_prepares = []

    # Charger le fond de carte GeoJSON (une seule fois)
    fond_carte_path = os.path.join(settings.BASE_DIR, "instruction", "static", "instruction", "carto", "fond_coeur_de_parc.geojson")
    with open(fond_carte_path, encoding="utf-8") as f:
        fond_de_carte_geojson = json.load(f)

    for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type").order_by("id"):

        champ_type = champ.id_champ.id_champ_type.type
        nom = champ.id_champ.nom

        # ignorer les champs de type explication
        if champ_type == "explication":
            continue

        # Exclure seulement les checkbox qui commencent par "Je certifie" ou "J'atteste"
        if champ_type == "checkbox" and (nom.startswith("Je certifie") or nom.startswith("J'atteste")):
            continue

        # Traduction spécifique pour les champs yes_no
        if champ_type == "yes_no":
            valeur = (champ.valeur or "").strip().lower()
            if valeur == "true":
                valeur_affichee = "Oui"
            elif valeur == "false":
                valeur_affichee = "Non"
            else:
                valeur_affichee = "Non renseigné"

            champs_prepares.append({"type": "champ", "nom": nom, "valeur": valeur_affichee})
            continue


        # if valeur == None or valeur == "":
        #     valeur = "Non renseigné"

        if champ_type == "carte" and champ.geometrie:
            champs_prepares.append({
            "type": "carte",
            "nom": nom,
            "geojson": json.dumps(champ.geometrie)

        })
        elif champ_type == "header_section":
            champs_prepares.append({"type": "header", "titre": nom})
        else:
            valeur = champ.valeur or "Non renseigné"
            champs_prepares.append({"type": "champ", "nom": nom, "valeur": valeur})


    return render(request, 'instruction/preinstruction_dossier.html', {
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "champs": champs_prepares,
        "fond_de_carte_data": fond_de_carte_geojson,
        "is_formulaire_active": True,
        "is_messagerie_active": False,
    })


@login_required(login_url='/login/')
def accueil(request):
    # Récupérer les états
    etat_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()
    etat_instruction = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
    etats_termines = EtatDossier.objects.filter(nom__in=["accepte", "refuse", "sans_suite"])

    current_year = date.today().year

    # Récupérer toutes les démarches
    demarches = Demarche.objects.all().order_by("titre")

    dossier_infos = []
    for demarche in demarches:
        pre_instruction_count = Dossier.objects.filter(id_demarche=demarche, id_etat_dossier=etat_construction).count()
        suivis_count = Dossier.objects.filter(id_demarche=demarche, id_etat_dossier=etat_instruction).count()
        traites_count = Dossier.objects.filter(
            id_demarche=demarche,
            id_etat_dossier__in=etats_termines,
            date_fin_instruction__year=current_year
        ).count()

        dossier_infos.append({
            "demarche": demarche.type,
            "nb_pre_instruction": pre_instruction_count,
            "nb_suivis": suivis_count,
            "nb_traites": traites_count,
        })

    return render(request, 'instruction/instruction.html', {
        "dossier_infos": dossier_infos
    })


@login_required
def preinstruction_dossier_messagerie(request, numero):
    dossier = get_object_or_404(Dossier, numero=numero)

    raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")

    messages = []
    for msg in raw_messages:
        emetteur = msg.email_emetteur.lower().strip()
        if emetteur == 'contact@demarches-simplifiees.fr' or emetteur == request.user.email.lower() or emetteur.endswith("reunion-parcnational.fr"):
            align = "right"  # Message émis par moi ou DS
        else:
            align = "left"   # Message reçu du demandeur
        
        formatted_date = formatted_date = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if isinstance(msg.date_envoi, (date, timezone.datetime)) else "Date inconnue"
        messages.append({
            "body": msg.body,
            "date_envoi": formatted_date,
            "align": align,
        })

    return render(request, 'instruction/preinstruction_dossier_messagerie.html', {
        "dossier": dossier,
        "messages": messages,
        "is_formulaire_active": False,
        "is_messagerie_active": True,
    })



# Synchronisation et Normalisation en arrière plan 

etat_sync = {"en_cours": False}
sync_lock = Lock()


def lancer_en_arriere_plan():
    def job():
        try:
            lancer_normalisation_et_synchronisation()
        finally:
            with sync_lock:
                etat_sync["en_cours"] = False

    with sync_lock:
        if etat_sync["en_cours"]:
            print("⚠️ Synchro déjà en cours – nouvelle tentative ignorée.")
            return False  # signaler qu’on ne lance pas

        etat_sync["en_cours"] = True
        Thread(target=job).start()
        return True



@login_required
def actualiser_donnees(request):
    if request.method == "POST":
        lancé = lancer_en_arriere_plan()
        if not lancé:
            return JsonResponse({
                "status": "already_running",
                "message": "⚠️ Une actualisation est déjà en cours."
            })
        return JsonResponse({"status": "ok", "message": "Synchronisation lancée."})
    return JsonResponse({"status": "error", "message": "Requête invalide"})




@login_required
def etat_actualisation(request):
    return JsonResponse({"en_cours": etat_sync["en_cours"]})





@require_POST
@csrf_exempt
def envoyer_message_dossier(request, numero):
    from DS.call_DS import envoyer_message_avec_pj
    from DS.graphql_client import GraphQLClient
    from django.core.files.uploadedfile import SimpleUploadedFile

    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    if not body:
        logger.warning(f"[ENVOI MESSAGE] Message vide envoyé par {request.user.email}")
        return HttpResponseBadRequest("Message vide")

    # 🔍 Récupérer le dossier
    dossier = get_object_or_404(Dossier, numero=numero)
    dossier_id_ds = dossier.id_ds

    # 🔍 Récupérer l'instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    instructeur_id_ds = instructeur.id_ds if instructeur else None

    if not dossier_id_ds or not instructeur_id_ds:
        logger.error(f"[ENVOI MESSAGE] ID manquant — dossier_id_ds: {dossier_id_ds}, instructeur_id_ds: {instructeur_id_ds}")
        return HttpResponse("Session incomplète", status=401)

    # Par défaut, aucun fichier temporaire
    tmp_file_path = None



    # PUT Message sur D-S
    try:
        # if fichier:
        #     loggerDS.info(f" Envoi message AVEC pièce jointe pour dossier {numero}")
        #     # Créer et écrire fichier temporaire
        #     # LE PROBLEME EST ICI (HASH INVALIDE) ET MALGRÉ CELA CA ECRIT EN BDD!!! IL FAUT QU'ON ECRIVE LE DOC AUSSI...
        #     with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(fichier.name)[1]) as tmp_file:
        #         tmp_file.write(fichier.read())
        #         tmp_file_path = tmp_file.name

        #     # Appel à DS
        #     envoyer_message_avec_pj(
        #         dossier_id=dossier_id_ds,
        #         instructeur_id=instructeur_id_ds,
        #         chemin_fichier_original=tmp_file_path,
        #         content_type=fichier.content_type
        #     )

        # # SANS PJ
        # else:
        #     loggerDS.info(f"Envoi message SANS pièce jointe pour dossier {numero}")
        #     client = GraphQLClient()
        #     variables = {
        #         "input": {
        #             "dossierId": dossier_id_ds,
        #             "instructeurId": instructeur_id_ds,
        #             "body": body
        #         }
        #     }
        #     result = client.execute_query("DS/mutations/send_message.graphql", variables)
        #     # {'data': {'dossierEnvoyerMessage': {'message': {'id': 'Q29tbWVudGFpcmUtNTYwNzU2Nzg=', 'body': 'message sans pj2'}, 'errors': None}}}
        #     if result["data"]:
        #         id_msg_ds = result["data"]['dossierEnvoyerMessage']['message']['id']
        #         loggerDS.info(f"Message (sans PJ) {id_msg_ds} envoyé")

        if fichier:
            tmp_file_path = prepare_temp_file(fichier)
            result_API_DS = envoyer_message_ds(dossier_id_ds, instructeur_id_ds, body, fichier, fichier.content_type, tmp_file_path, numero)
        else:
            result_API_DS = envoyer_message_ds(dossier_id_ds, instructeur_id_ds, body, num_dossier=numero)
        
        message_ds = result_API_DS["data"]['dossierEnvoyerMessage'].get('message')
        
        if message_ds and message_ds.get('id'):
            id_msg_ds = message_ds['id']
            loggerDS.info(f"Message {id_msg_ds} envoyé sur D-S")
            logger.info(f"Message {id_msg_ds} envoyé sur D-S")
        else:
            erreurs = result_API_DS["data"]['dossierEnvoyerMessage'].get('errors')
            erreurs_str = "; ".join(err['message'] for err in erreurs) if erreurs else "Erreur inconnue"
            loggerDS.error(f"Message (dossier {numero}) pas envoyé sur D-S : {erreurs_str}")
            logger.error(f"Message (dossier {numero}) pas envoyé sur D-S : {erreurs_str}")
            
            return HttpResponse(f"Erreur envoi message D-S (dossier {numero}) : {erreurs_str}", status=500)



            
    except Exception as e:
        logger.exception(f"[API DS] Erreur lors de l'envoi du message via l'API DS (dossier {numero})")
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
        return HttpResponse(f"Erreur d'envoi : {e}", status=500)



    # ✅ Enregistrement local en BDD
    try:
        # if fichier and tmp_file_path and os.path.exists(tmp_file_path):
        #     with open(tmp_file_path, "rb") as temp_read_file:
        #         fichier_bdd = SimpleUploadedFile(
        #             name=fichier.name,
        #             content=temp_read_file.read(),
        #             content_type=fichier.content_type
        #         )

        #     create_message_bdd(
        #         body=body,
        #         email_emetteur=request.user.email,
        #         dossier_obj=dossier,
        #         date_envoi=timezone.now(),
        #         document_file=fichier_bdd,
        #         document_title=fichier.name,
        #         document_format_str=fichier.name.split('.')[-1].lower()
        #     )
        # else:
        #     # Message sans pièce jointe
        #     create_message_bdd(
        #         body=body,
        #         email_emetteur=request.user.email,
        #         dossier_obj=dossier,
        #         date_envoi=timezone.now()
        #     )

        if fichier:
            enregistrer_message_bdd(dossier, request.user.email, body, fichier, id_ds=id_msg_ds)
        else:
            enregistrer_message_bdd(dossier, request.user.email, body, None, id_ds=id_msg_ds)

        logger.info(f"Message {id_msg_ds} enregistré en BDD (dossier {numero}) par {request.user.email}")

    except Exception as e:
        logger.exception(f"[BDD] Erreur lors de l'enregistrement local")
        return HttpResponse(f"Erreur d'enregistrement en base : {e}", status=500)

    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

    return redirect(reverse("preinstruction_dossier", kwargs={"numero": numero}))
