import json
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import urllib
from autorisations.models.models_instruction import Dossier, DossierChamp, EtapeDossier
from autorisations.models.models_utilisateurs import DossierInstructeur, Instructeur
from synchronisation.src.main import lancer_normalisation_et_synchronisation
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


@require_POST
def changer_etape_dossier(request):
    dossier_id = request.POST.get("dossierId")
    etape_id = request.POST.get("etapeDossierId")

    dossier = get_object_or_404(Dossier, id_ds=dossier_id)
    nouvelle_etape = get_object_or_404(EtapeDossier, id=etape_id)

    ancienne_etape = dossier.id_etape_dossier  # sauvegarde avant modification

    dossier.id_etape_dossier = nouvelle_etape
    dossier.save()

    logger.info(
        f"[ETAPE] Dossier {dossier.nom_dossier} (n° {dossier.numero}) : étape changée de "
        f"{ancienne_etape.etape if ancienne_etape else 'Non définie'} → {nouvelle_etape.etape}"
    )

    return redirect(request.META.get("HTTP_REFERER", "/"))



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

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def enregistrer_geom(request):
    try:
        # dossier_id = request.POST.get("dossier_id")
        dossier_numero = request.POST.get("dossier_numero")
        geojson_str = request.POST.get("geojson_geom")
        print(f"Valeur reçue pour geojson_geom: {geojson_str}")

        dossier = get_object_or_404(Dossier, numero=dossier_numero)


        if not geojson_str:
            msg = "Aucune géométrie reçue (champ geojson_geom vide)."
            logger.warning(f"[ENREGISTREMENT GEOMETRIE] {msg} — POST = {dict(request.POST)}")
            return redirect(
                f"{reverse('edit_carto', kwargs={'numero_dossier': dossier_numero})}?status=error&msg={urllib.parse.quote(msg)}"
            )

        geojson_data = json.loads(geojson_str)

        # MAJ champ
        champ = DossierChamp.objects.filter(id_dossier=dossier, id_champ__id_champ_type__type="carte").first()
        if not champ:
            msg = "Champ carte non trouvé."
            logger.error(f"[ENREGISTREMENT GEOMETRIE] Erreur sur le dossier {dossier.numero} : {msg}")
            return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier.numero})}?status=error&msg={urllib.parse.quote(msg)}")

        champ.geometrie = geojson_data
        champ.save()

        # MAJ geometrie dossier
        dossier.geometrie_modif = geojson_data
        dossier.save()
        msg = "Géométrie mise à jour avec succès."
        logger.info(f"{msg} pour le dossier {dossier.numero}")
        return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier.numero})}?status=ok&msg={urllib.parse.quote(msg)}")

    except Exception as e:
        logger.error(f"[ENREGISTREMENT GEOMETRIE] Erreur sur le dossier {request.POST.get('dossier_id')} : {e}")
        return redirect(f"/instruction/{request.POST.get('dossier_numero')}/edit_carto?status=error&msg={urllib.parse.quote(str(e))}")



#Vue de test
@login_required(login_url='/login/')
def carto_test(request):
    return render(request, 'edit_carto.html')


@login_required
def edit_carto(request, numero_dossier):
    dossier = get_object_or_404(Dossier, numero=numero_dossier)
    
    geojson_source = dossier.geometrie_modif or dossier.geometrie
    geojson = json.dumps(geojson_source) if geojson_source else "{}"


    return render(request, 'edit_carto.html', {"numero_dossier": numero_dossier, "geojson": geojson})


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


