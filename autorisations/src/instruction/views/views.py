from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from autorisations.models.models_instruction import Dossier, EtapeDossier
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

