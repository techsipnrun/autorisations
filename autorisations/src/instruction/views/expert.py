from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import Instructeur
from autorisations.models.models_documents import Document
from autorisations.models.models_avis import Avis, Expert

from django.contrib import messages
import logging


logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  


@login_required(login_url='/login/')
def avis(request):

    # Expert connecté ?
    expert = Expert.objects.filter(id_instructeur__email=request.user.email).first()

    if not expert:
        expert = Expert.objects.filter(id_contact_externe__email=request.user.email).first()

    # if not expert:
    #     messages.error(request, "Vous n'avez pas de profil Expert, rapprochez-vous de l'admin")
    #     return render(request, "instruction/avis.html", {"avis_list": []})

    # Instructeur connecté ?
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    avis_list = []
    demandes_avis = []

    # Avis à rendre (en tant qu’expert)
    if expert:
        avis_list = (
            Avis.objects.filter(id_expert=expert)
            .select_related("id_demarche", "id_dossier", "id_instructeur", "id_expert")
            .order_by("-date_demande_avis")
        )

    # Mes demandes d’avis (en tant qu’instructeur demandeur)
    if instructeur:
        demandes_avis = (
            Avis.objects.filter(id_instructeur=instructeur)
            .select_related("id_demarche", "id_dossier", "id_expert", "id_avis_nature")
            .order_by("-date_demande_avis")
        )

    return render(request, "instruction/avis.html", {
                                                    "avis_list": avis_list,
                                                    "demandes_avis": demandes_avis,
                                                     })



import datetime
from django.db.models import Q
from django.db.models.functions import ExtractYear


@login_required(login_url='/login/')
def avis2(request):
    # Expert connecté ?
    expert = Expert.objects.filter(id_instructeur__email=request.user.email).first()
    if not expert:
        expert = Expert.objects.filter(id_contact_externe__email=request.user.email).first()

    # Instructeur connecté ?
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    avis_list = []
    demandes_avis = []
    current_year = datetime.date.today().year
    selected_year = int(request.GET.get("annee", current_year))

    ###################################
    # Avis à rendre/rendu (en tant qu’expert)
    ###################################
    avis_a_rendre = (
        Avis.objects.filter(id_expert=expert, favorable__isnull=True)
        .select_related("id_demarche", "id_dossier", "id_instructeur", "id_avis_nature")
        .order_by("-date_demande_avis")
    )

    # Avis archivés de l’année
    avis_rendus = (
        Avis.objects.filter(id_expert=expert, favorable__isnull=False, date_reponse_avis__year=selected_year)
        .select_related("id_demarche", "id_dossier", "id_instructeur", "id_avis_nature")
        .order_by("-date_reponse_avis")
    )

    # Années disponibles
    annees_disponibles_expert = Avis.objects.filter(
        id_expert=expert, date_reponse_avis__isnull=False
    ).dates("date_reponse_avis", "year", order="DESC")


    ##############################################################
    # Mes demandes d’avis en cours/traitées (en tant que demandeur)
    ##############################################################
    if instructeur:

        # Demandes en cours
        demandes_en_cours = Avis.objects.filter(id_instructeur=instructeur, favorable__isnull=True
                            ).select_related("id_demarche", "id_dossier", "id_expert", "id_avis_nature").order_by("-date_demande_avis")

        # Demandes traitées
        demandes_traitees = Avis.objects.filter(id_instructeur=instructeur,favorable__isnull=False,date_reponse_avis__year=selected_year,
                            ).select_related(
                                "id_demarche", "id_dossier", "id_expert", "id_avis_nature"
                            ).order_by("-date_reponse_avis")

        # Années disponibles
        annees_disponibles_demandeur = Avis.objects.filter(
            id_instructeur=instructeur, date_reponse_avis__isnull=False
        ).dates("date_reponse_avis", "year", order="DESC")

    return render(
        request,
        "instruction/avis2.html",
        {
            "annee_selectionnee": selected_year,
            # Expert
            "avis_a_rendre": avis_a_rendre,
            "avis_rendus": avis_rendus,
            "annees_disponibles_expert": annees_disponibles_expert,
            # Demandeur
            "demandes_en_cours": demandes_en_cours,
            "demandes_traitees": demandes_traitees,
            "annees_disponibles_demandeur": annees_disponibles_demandeur,
        },
    )
