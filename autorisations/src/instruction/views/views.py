from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from synchronisation.src.main import lancer_normalisation_et_synchronisation
from threading import Thread, Lock
import logging


logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  


@login_required(login_url='/login/')
def avis(request):
    return render(request, 'instruction/avis.html')


@login_required(login_url='/login/')
def suivi(request):
    return render(request, 'instruction/suivi.html')

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
            print("Synchro déjà en cours – nouvelle tentative ignorée.")
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
                "message": "Une actualisation est déjà en cours."
            })
        return JsonResponse({"status": "ok", "message": "Synchronisation lancée."})
    return JsonResponse({"status": "error", "message": "Requête invalide"})


@login_required
def etat_actualisation(request):
    return JsonResponse({"en_cours": etat_sync["en_cours"]})



# @login_required(login_url='/login/')
# def preinstruction(request):
#     # Récupérer l'ID correspondant à "en_construction"
#     etat_en_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()

#     dossiers = Dossier.objects.filter(id_etat_dossier=etat_en_construction) \
#         .select_related("id_demarche") \
#         .order_by("date_depot")

#     dossier_infos = []
#     for dossier in dossiers:

#         # Chercher le demandeur via DossierInterlocuteur
#         interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
#         demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None

#         if not demandeur:
#             dossier_beneficiaire = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first() if interlocuteur else None
#             demandeur = dossier_beneficiaire.id_beneficiaire if dossier_beneficiaire else None

#         dossier_infos.append({
#             "demarche": dossier.id_demarche.type,
#             "date_depot": dossier.date_depot,
#             "demandeur": f"{demandeur.prenom} {demandeur.nom}" if demandeur else "N/A",
#             "nom_projet": dossier.nom_dossier,
#             "numero": dossier.numero,
#         })

#     return render(request, 'instruction/preinstruction.html', {
#         "dossier_infos": dossier_infos,
#     })



# @login_required
# def preinstruction_dossier(request, numero):
#     dossier = get_object_or_404(Dossier, numero=numero)

#     champs_prepares = []

#     # Charger le fond de carte GeoJSON (une seule fois)
#     fond_carte_path = os.path.join(settings.BASE_DIR, "instruction", "static", "instruction", "carto", "fond_coeur_de_parc.geojson")
#     with open(fond_carte_path, encoding="utf-8") as f:
#         fond_de_carte_geojson = json.load(f)

#     for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type").order_by("id"):

#         champ_type = champ.id_champ.id_champ_type.type
#         nom = champ.id_champ.nom

#         # ignorer les champs de type explication
#         if champ_type == "explication":
#             continue

#         # Exclure seulement les checkbox qui commencent par "Je certifie" ou "J'atteste"
#         if champ_type == "checkbox" and (nom.startswith("Je certifie") or nom.startswith("J'atteste")):
#             continue

#         # Traduction spécifique pour les champs yes_no
#         if champ_type == "yes_no":
#             valeur = (champ.valeur or "").strip().lower()
#             if valeur == "true":
#                 valeur_affichee = "Oui"
#             elif valeur == "false":
#                 valeur_affichee = "Non"
#             else:
#                 valeur_affichee = "Non renseigné"

#             champs_prepares.append({"type": "champ", "nom": nom, "valeur": valeur_affichee})
#             continue


#         # if valeur == None or valeur == "":
#         #     valeur = "Non renseigné"

#         if champ_type == "carte" and champ.geometrie:
#             champs_prepares.append({
#             "type": "carte",
#             "nom": nom,
#             "geojson": json.dumps(champ.geometrie)

#         })
#         elif champ_type == "header_section":
#             champs_prepares.append({"type": "header", "titre": nom})
#         else:
#             valeur = champ.valeur or "Non renseigné"
#             champs_prepares.append({"type": "champ", "nom": nom, "valeur": valeur})

#     #Récupérer tous les noms de groupes instructeurs pour la démarche en question
#     from autorisations.models.models_utilisateurs import Groupeinstructeur, GroupeinstructeurDemarche

#     groupes_instructeurs = Groupeinstructeur.objects.filter(
#         groupeinstructeurdemarche__id_demarche=dossier.id_demarche
#     ).order_by("nom")


#     return render(request, 'instruction/preinstruction_dossier.html', {
#         "dossier": dossier,
#         "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
#         "champs": champs_prepares,
#         "fond_de_carte_data": fond_de_carte_geojson,
#         "is_formulaire_active": True,
#         "is_messagerie_active": False,
#         "groupes_instructeurs": groupes_instructeurs,
#     })




# @login_required(login_url='/login/')
# def accueil(request):
#     # Récupérer les états
#     etat_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()
#     etat_instruction = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
#     etats_termines = EtatDossier.objects.filter(nom__in=["accepte", "refuse", "sans_suite"])

#     current_year = date.today().year

#     # Récupérer toutes les démarches
#     demarches = Demarche.objects.all().order_by("titre")

#     dossier_infos = []
#     for demarche in demarches:
#         pre_instruction_count = Dossier.objects.filter(id_demarche=demarche, id_etat_dossier=etat_construction).count()
#         suivis_count = Dossier.objects.filter(id_demarche=demarche, id_etat_dossier=etat_instruction).count()
#         traites_count = Dossier.objects.filter(
#             id_demarche=demarche,
#             id_etat_dossier__in=etats_termines,
#             date_fin_instruction__year=current_year
#         ).count()

#         dossier_infos.append({
#             "demarche": demarche.type,
#             "nb_pre_instruction": pre_instruction_count,
#             "nb_suivis": suivis_count,
#             "nb_traites": traites_count,
#         })

#     return render(request, 'instruction/instruction.html', {
#         "dossier_infos": dossier_infos
#     })


# @login_required
# def preinstruction_dossier_messagerie(request, numero):
#     dossier = get_object_or_404(Dossier, numero=numero)

#     raw_messages = Message.objects.filter(id_dossier=dossier).order_by("date_envoi")

#     messages = []
#     for msg in raw_messages:
#         emetteur = msg.email_emetteur.lower().strip()
#         if emetteur == 'contact@demarches-simplifiees.fr' or emetteur == request.user.email.lower() or emetteur.endswith("reunion-parcnational.fr"):
#             align = "right"  # Message émis par moi ou DS
#         else:
#             align = "left"   # Message reçu du demandeur
        
#         formatted_date = formatted_date = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if isinstance(msg.date_envoi, (date, timezone.datetime)) else "Date inconnue"
        
#         # Recherche de la pièce jointe liée au message
#         pj_url = None
#         pj_title = None
#         if msg.piece_jointe:
#             message_document = MessageDocument.objects.filter(id_message=msg).select_related('id_document').first()
#             if message_document and message_document.id_document:
#                 pj_url = message_document.id_document.url_ds
#                 pj_title = message_document.id_document.titre

        
#         messages.append({
#             "id": msg.id,
#             "body": msg.body,
#             "date_envoi": formatted_date,
#             "align": align,
#             "pj_url": pj_url,
#             "pj_title":pj_title,
#         })

#     # Chercher le demandeur via DossierInterlocuteur
#     interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
#     demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None

#     # Chercher le bénéficiaire via DossierBeneficiaire
#     beneficiaire = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first().id_beneficiaire if interlocuteur else None


#     return render(request, 'instruction/preinstruction_dossier_messagerie.html', {
#         "dossier": dossier,
#         "messages": messages,
#         "is_formulaire_active": False,
#         "is_messagerie_active": True,
#         "beneficiaire": beneficiaire,
#         "demandeur": demandeur,
#         "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
#     })



# @require_POST
# @csrf_exempt
# def envoyer_message_dossier(request, numero):
#     from DS.call_DS import envoyer_message_avec_pj
#     from DS.graphql_client import GraphQLClient
#     from django.core.files.uploadedfile import SimpleUploadedFile
#     from django.contrib import messages

#     # Récupéraion message et PJ de l'instructeur
#     body = request.POST.get("body")
#     fichier = request.FILES.get("piece_jointe")

#     if not body:
#         logger.warning(f"[ENVOI MESSAGE] Message vide envoyé par {request.user.email}")
#         return HttpResponseBadRequest("Message vide")
    
#     # Vérification taille fichier (20 Mo max)
#     if fichier and fichier.size > 20 * 1024 * 1024:  # 20 Mo en octets
#         logger.warning(f"[ENVOI MESSAGE] Fichier trop volumineux ({fichier.size} octets) par {request.user.email}")
#         messages.error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
#         return redirect(reverse("preinstruction_dossier_messagerie", kwargs={"numero": numero}))

#     # Récupérer le dossier
#     dossier = get_object_or_404(Dossier, numero=numero)
#     dossier_id_ds = dossier.id_ds

#     # Récupérer l'instructeur
#     instructeur = Instructeur.objects.filter(email=request.user.email).first()
#     instructeur_id_ds = instructeur.id_ds if instructeur else None

#     if not dossier_id_ds or not instructeur_id_ds:
#         logger.error(f"[ENVOI MESSAGE] ID manquant — dossier_id_ds: {dossier_id_ds}, instructeur_id_ds: {instructeur_id_ds}")
#         return HttpResponse("Session incomplète", status=401)

#     # Par défaut, aucun fichier temporaire
#     tmp_file_path = None


#     # PUT Message sur D-S
#     try:
#         if fichier:
#             tmp_file_path = prepare_temp_file(fichier)
#             result_API_DS = envoyer_message_ds(dossier_id_ds, instructeur_id_ds, body, fichier, fichier.content_type, tmp_file_path, numero)
#             # Recup url DS et l'ajouter au document
#         else:
#             result_API_DS = envoyer_message_ds(dossier_id_ds, instructeur_id_ds, body, num_dossier=numero)
        
#         message_ds = result_API_DS["data"]['dossierEnvoyerMessage'].get('message')
        
#         if message_ds and message_ds.get('id'):
#             id_msg_ds = message_ds['id']
#             loggerDS.info(f"Message {id_msg_ds} envoyé sur D-S")
#             logger.info(f"Message {id_msg_ds} envoyé sur D-S")
#         else:
#             erreurs = result_API_DS["data"]['dossierEnvoyerMessage'].get('errors')
#             erreurs_str = "; ".join(err['message'] for err in erreurs) if erreurs else "Erreur inconnue"
#             loggerDS.error(f"Message (dossier {numero}) pas envoyé sur D-S : {erreurs_str}")
#             logger.error(f"Message (dossier {numero}) pas envoyé sur D-S : {erreurs_str}")
            
#             return HttpResponse(f"Erreur envoi message D-S (dossier {numero}) : {erreurs_str}", status=500)


#     except Exception as e:
#         logger.exception(f"[API DS] Erreur lors de l'envoi du message via l'API DS (dossier {numero})")
#         if tmp_file_path and os.path.exists(tmp_file_path):
#             os.remove(tmp_file_path)
#         return HttpResponse(f"Erreur d'envoi : {e}", status=500)



#     # Enregistrement local en BDD
#     try:
        

#         if fichier:
#             url_ds = get_msg_DS(numero, message_ds['id'])
#             enregistrer_message_bdd(dossier, request.user.email, body, fichier, id_ds=id_msg_ds, url_ds=url_ds)
#         else:
#             enregistrer_message_bdd(dossier, request.user.email, body, None, id_ds=id_msg_ds)



#     except Exception as e:
#         logger.exception(f"[BDD] Erreur lors de l'enregistrement local")
#         return HttpResponse(f"Erreur d'enregistrement en base : {e}", status=500)

#     finally:
#         if tmp_file_path and os.path.exists(tmp_file_path):
#             os.remove(tmp_file_path)

#     return redirect(reverse("preinstruction_dossier_messagerie", kwargs={"numero": numero}))



# @login_required
# def supprimer_message(request, id):

#     try :
#         message = get_object_or_404(Message, id=id)

#         # Vérifie si l'utilisateur est bien l'émetteur
#         if message.email_emetteur.lower() != request.user.email.lower():
#             logger.warning(f"Tentative non autorisée de suppression du message {id} par {request.user.email}")   
#             return HttpResponseForbidden("Vous n'êtes pas autorisé à supprimer ce message.")
        

#         # Suppression côté D-S
#         try:
#             suppr_msg_DS(message)
#             loggerDS.info(f"Message {message.id_ds} supprimé sur D-S (Dossier {message.id_dossier.numero})")
#         except Exception as e:
#             loggerDS.error(f"Erreur suppression message {message.id_ds} sur D-S (Dossier {message.id_dossier.numero}): {e}")


#         message.delete()
#         logger.info(f"Message {id} (Dossier {message.id_dossier.numero}) supprimé de la BDD")
#         return redirect('preinstruction_dossier_messagerie', numero=message.id_dossier.numero)
    
#     except Exception as e:
#             logger.exception(f"Erreur inattendue lors de la suppression du message {id}")
#             return HttpResponse(f"Erreur lors de la suppression : {e}", status=500)
    


# @login_required
# def actualiser_messages(request, numero):
    

#     dossier = get_object_or_404(Dossier, numero=numero)
#     client = GraphQLClient()

#     try:
#         # Appel API DS pour récupérer les messages
#         variables = {"number": dossier.numero}
#         result = client.execute_query("DS/mutations/get_message.graphql", variables)
#         messages_bruts = result["data"]["dossier"]["messages"]

#         # Normalisation
#         #Peut etre qu'il faut renseigner email benef et demandeur inter ici
#         messages_norm = message_normalize({"messages": messages_bruts, "number": dossier.numero, "usager": {}, "demandeur": {}}, dossier.emplacement)

#         # Synchronisation en base
#         sync_messages(messages_norm, dossier.id)

#         logger.info(f"[MESSAGERIE] Actualisation des messages du dossier {numero} réussie.")
#     except Exception as e:
#         logger.exception(f"[MESSAGERIE] Échec de l'actualisation des messages pour le dossier {numero} : {e}")
#         return HttpResponse(f"Erreur lors de l'actualisation : {e}", status=500)

#     return redirect('preinstruction_dossier_messagerie', numero=numero)




# from django.views.decorators.http import require_POST
# from django.shortcuts import redirect
# from django.contrib import messages
# from DS.call_DS import change_groupe_instructeur_ds

# @require_POST
# def changer_groupe_instructeur(request):
#     dossier_id = request.POST.get("dossierId")
#     groupe_id = request.POST.get("groupeInstructeurId")

#     from autorisations.models.models_utilisateurs import GroupeinstructeurDemarche

#     groupe_id_ds = GroupeinstructeurDemarche.objects.filter(
#         id_groupeinstructeur=groupe_id
#     ).values_list("id_groupeinstructeur_ds", flat=True).first()



#     if not dossier_id or not groupe_id_ds:
#         messages.error(request, "Champs manquants.")
#         return redirect(request.META.get('HTTP_REFERER', '/'))

#     print(f"groupe_id : {groupe_id_ds}")
#     print(f"dossier_id : {dossier_id}")
#     result = change_groupe_instructeur_ds(dossier_id, groupe_id_ds)

#     if result["success"]:
#         logger.info("[UPDATE] Groupe Instructeur changé avec succès")
#     else:
#         logger.error("Echec du changement de Groupe Instructeur")

#     return redirect(request.META.get('HTTP_REFERER', '/'))