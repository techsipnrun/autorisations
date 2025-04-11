from datetime import date
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required

from autorisations.models.models_documents import DocumentFormat
from autorisations.models.models_instruction import Demarche, Dossier, EtatDossier, Message
from autorisations.models.models_utilisateurs import DossierInterlocuteur, DossierBeneficiaire



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
    for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type").order_by("id"):
        champ_type = champ.id_champ.id_champ_type.type

        # ignorer les champs de type explication
        if champ_type == "explication":
            continue

        nom = champ.id_champ.nom
        valeur = champ.valeur

        # Exclure seulement les checkbox qui commencent par "Je certifie" ou "J'atteste"
        if champ_type == "checkbox" and (nom.startswith("Je certifie") or nom.startswith("J'atteste")):
            continue

        valeur_affichee = valeur

        # Traduction spécifique pour les champs yes_no
        if champ_type == "yes_no":
            if valeur_affichee is True or valeur_affichee == "true":
                valeur_affichee = "Oui"
            elif valeur_affichee is False or valeur_affichee == "false":
                valeur_affichee = "Non"

        if valeur_affichee == None or valeur_affichee == "":
            valeur_affichee = "Non renseigné"

        # print (valeur_affichee)
        if champ_type == "header_section":
            champs_prepares.append({
                "type": "header",
                "titre": nom
            })
        else:
            champs_prepares.append({
                "type": "champ",
                "nom": nom,
                "valeur": valeur_affichee
            })

    return render(request, 'instruction/preinstruction_dossier.html', {
        "dossier": dossier,
        "champs": champs_prepares,
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
        if emetteur == 'contact@demarches-simplifiees.fr' or emetteur == request.user.email.lower():
            align = "right"  # Message émis par moi ou DS
        else:
            align = "left"   # Message reçu du demandeur
        
        formatted_date = msg.date_envoi.strftime("%d/%m/%Y %H:%M") if isinstance(msg.date_envoi, (date, timezone.datetime)) else "Date inconnue"

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

