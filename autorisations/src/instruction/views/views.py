import json
import os
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import urllib
from autorisations.models.models_instruction import Dossier, DossierChamp, EtapeDossier
from autorisations.models.models_utilisateurs import DossierInstructeur, Instructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument
from instruction.utils import enregistrer_action
from synchronisation.src.main import lancer_normalisation_et_synchronisation, lancer_normalisation_et_synchronisation_pour_une_demarche
from threading import Thread, Lock
import logging


logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  


@login_required(login_url='/login/')
def avis(request):
    return render(request, 'instruction/avis.html')


@login_required(login_url='/login/')
def requetes(request):
    return render(request, 'instruction/requetes.html')

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


# @require_POST
# def changer_etape_dossier(request):
#     dossier_id = request.POST.get("dossierId")
#     etape_id = request.POST.get("etapeDossierId")

#     dossier = get_object_or_404(Dossier, id_ds=dossier_id)
#     nouvelle_etape = get_object_or_404(EtapeDossier, id=etape_id)

#     ancienne_etape = dossier.id_etape_dossier  # sauvegarde avant modification

#     dossier.id_etape_dossier = nouvelle_etape
#     dossier.save()

#     logger.info(
#         f"[ETAPE] Dossier {dossier.nom_dossier} (n° {dossier.numero}) : étape changée de "
#         f"{ancienne_etape.etape if ancienne_etape else 'Non définie'} → {nouvelle_etape.etape}"
#     )

#     return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@login_required
def se_declarer_instructeur(request):
    
    dossier_id = request.POST.get("dossier_id")
    dossier = get_object_or_404(Dossier, id=dossier_id)

    instructeur_id = request.POST.get("instructeur_id")

    # instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()
    instructeur = get_object_or_404(Instructeur, id=instructeur_id)

    if instructeur and dossier.id_groupeinstructeur:
        instructeurs_du_groupe = dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.values_list("id_instructeur_id", flat=True)
        if instructeur.id in instructeurs_du_groupe:
            DossierInstructeur.objects.get_or_create(id_dossier=dossier, id_instructeur=instructeur)
            logger.info(f"[DOSSIER {dossier.numero}] Affectation à l'instructeur {instructeur.email}")

            nom_prenom = '(' + instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom + ')'

            # Dossier Action
            enregistrer_action(dossier, instructeur, "Instructeur.e ajouté.e", nom_prenom)


    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def retirer_instructeur(request):
    from autorisations.models.models_utilisateurs import DossierInstructeur, Instructeur
    from autorisations.models.models_instruction import Dossier

    dossier_id = request.POST.get("dossier_id")
    instructeur_id = request.POST.get("instructeur_id")

    dossier = get_object_or_404(Dossier, id=dossier_id)
    instructeur = get_object_or_404(Instructeur, id=instructeur_id)

    DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).delete()
    logger.info(f"[DOSSIER {dossier.numero}] On retire l'instructeur {instructeur.email} du dossier.")

    # Dossier Action
    nom_prenom = '(' + instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom + ')'
    enregistrer_action(dossier, instructeur, "Instructeur.e retiré.e", nom_prenom)

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def enregistrer_geom(request):
    try:
        dossier_numero = request.POST.get("dossier_numero")
        geojson_str = request.POST.get("geojson_geom")
        id_champ = request.POST.get("id_champ")
        nb_cartes = request.POST.get("nb_cartes")

        dossier = get_object_or_404(Dossier, numero=dossier_numero)
        champ = get_object_or_404(DossierChamp, id=id_champ, id_dossier=dossier, id_champ__id_champ_type__type="carte")

        if not geojson_str:
            msg = "Aucune géométrie reçue (champ geojson_geom vide)."
            logger.warning(f"[DOSSIER {dossier.numero}] Enregistrement géométrie par {request.user}: {msg}")

            return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier_numero})}?status=error&msg={urllib.parse.quote(msg)}")

        geojson_data = json.loads(geojson_str)

        # # MAJ champ
        # champ = DossierChamp.objects.filter(id_dossier=dossier, id_champ__id_champ_type__type="carte").first()
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

        msg = "Géométrie mise à jour avec succès."
        logger.info(f"[DOSSIER {dossier.numero}] {msg} par {request.user}")
        return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier.numero, 'id_champ': id_champ})}?status=ok&msg={urllib.parse.quote(msg)}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'nregistrement de la géométrie par {request.user} : {e}")
        return redirect(f"/instruction/{request.POST.get('dossier_numero')}/edit_carto/{request.POST.get('id_champ')}?status=error&msg={urllib.parse.quote(str(e))}")



#Vue de test
# @login_required(login_url='/login/')
# def carto_test(request):
#     return render(request, 'edit_carto.html')


@login_required
def edit_carto(request, numero_dossier, id_champ):
    dossier = get_object_or_404(Dossier, numero=numero_dossier)
    
    # Récupère tous les champs carte
    nb_cartes = dossier.dossierchamp_set.filter(id_champ__id_champ_type__type="carte").count()

    champ = get_object_or_404(
            DossierChamp,
            id=id_champ,
            id_dossier=dossier,
            id_champ__id_champ_type__type="carte"
        )
        
    geojson_source = champ.geometrie_modif or champ.geometrie or {}
    

    # geojson_source = dossier.geometrie_modif or dossier.geometrie
    geojson = json.dumps(geojson_source) if geojson_source else "{}"


    return render(request, 'edit_carto.html', {
                                                "numero_dossier": numero_dossier, 
                                                "geojson": geojson, 
                                                "etape_dossier": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else None,
                                                "nb_cartes": nb_cartes,
                                                'id_champ': id_champ,
                                               })



def mes_dossiers_a_traiter_count(request):
    if not request.user.is_authenticated:
        return {}

    instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()
    if not instructeur:
        return {}

    groupes = instructeur.groupeinstructeurinstructeur_set.values_list("id_groupeinstructeur_id", flat=True)

    dossiers = Dossier.objects.filter(
        id_groupeinstructeur_id__in=groupes
    ).exclude(
        id_etape_dossier__etape="À affecter"
    ).exclude(
        id_etat_dossier__nom__in=["accepte", "refuse", "sans_suite"]
    )

    return {"nb_dossiers_instruction": dossiers.count()}


@login_required(login_url='/login/')
def ajouter_annexe_dossier(request, dossier_id):

    dossier = get_object_or_404(Dossier, id=dossier_id)

    if request.method == "POST" and request.FILES.get('annexe'):
        fichier = request.FILES['annexe']

        # Vérification de la taille (max 50 Mo)
        if fichier.size > 50 * 1024 * 1024:
            logger.warning(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) Taille > 50 Mo pour {fichier.name}")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))

        # Extension du fichier
        nom, extension = os.path.splitext(fichier.name)
        extension = extension.lstrip('.').lower()

        # Récupérer le format
        format_obj = DocumentFormat.objects.filter(format__iexact=extension).first()
        if not format_obj:
            logger.warning(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) car le format n'est pas reconnu : {fichier.name}.{extension}")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))


        # Nature "Annexe instructeur"
        nature_obj = DocumentNature.objects.filter(nature__iexact="Annexe instructeur").first()
        if not nature_obj:
            logger.error(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) La nature 'Annexe instructeur' est introuvable en BDD.")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))
        

        # Création du Document
        dossier = get_object_or_404(Dossier, pk=dossier_id)
        emplacement = f"{dossier.emplacement}/Annexes/{fichier.name}"
        chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}"

        # Vérification si un Document avec le même emplacement existe déjà en base, si on est ici c'est qu'on a confirmé l'écrasement dans le pop up JS
        if Document.objects.filter(emplacement=emplacement).exists():
            
            #ancien document
            ancien_doc = Document.objects.filter(emplacement=emplacement).first()
            # Supprimer le lien avec le dossier
            DossierDocument.objects.filter(id_document=ancien_doc).delete()
            # Supprimer le document lui-même
            ancien_doc.delete()

            logger.info(f"[DOSSIER {dossier.numero}] Annexe {fichier.name} (.{extension}) écrasée par {request.user} — ancien document supprimé.")


        doc = Document.objects.create(
            id_format=format_obj,
            id_nature=nature_obj,
            titre=fichier.name,
            emplacement=emplacement,
            description=f"Annexe ajouté par l'instructeur sur le dossier {dossier.numero}"
        )


        # Lien avec le Dossier
        DossierDocument.objects.create(id_dossier=dossier, id_document=doc)

      # Enregistrement physique
        os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)
        with open(chemin_complet, 'wb+') as destination:
            for chunk in fichier.chunks():
                destination.write(chunk)

        logger.info(f"[DOSSIER {dossier.numero}] Annexe {fichier.name} ajoutée avec succès par {request.user}")
        return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))


    logger.warning(f"[DOSSIER {dossier.numero}] Annexe non ajoutée par {request.user} : Aucune pièce jointe reçue.")
    return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))



@login_required
def synchroniser_demarche(request, num_demarche):
    if request.method == "POST":
        try:
            lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
        except Exception as e:
            logger.error(f"Erreur de synchronisation pour la démarche {num_demarche} : {e}")
    return redirect("instruction_demarche", num_demarche=num_demarche)


