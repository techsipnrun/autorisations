from datetime import date
import json
import os
from django.utils import timezone
from django.utils.timezone import localtime
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required

from autorisations.models.models_documents import DocumentFormat
from autorisations.models.models_instruction import Demarche, Dossier, EtatDossier, Message
from autorisations.models.models_utilisateurs import DossierInterlocuteur, DossierBeneficiaire
from autorisations import settings

from django.http import JsonResponse
from instruction.utils import format_etat_dossier
from synchronisation.src.utils import lancer_normalisation_et_synchronisation
from threading import Thread, Lock



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