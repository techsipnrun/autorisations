from datetime import date
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from autorisations.models.models_instruction import Demarche, Dossier, EtatDossier

def get_dossier_counts(demarche, etat_construction, etat_instruction, etats_termines, current_year):
    return {
        "demarche": demarche.type,
        "nb_pre_instruction": Dossier.objects.filter(id_demarche=demarche, id_etat_dossier=etat_construction).count(),
        "nb_suivis": Dossier.objects.filter(id_demarche=demarche, id_etat_dossier=etat_instruction).count(),
        "nb_traites": Dossier.objects.filter(id_demarche=demarche, id_etat_dossier__in=etats_termines, date_fin_instruction__year=current_year).count(),
    }

@login_required
def accueil(request):
    etat_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()
    etat_instruction = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
    etats_termines = EtatDossier.objects.filter(nom__in=["accepte", "refuse", "sans_suite"])

    current_year = date.today().year
    demarches = Demarche.objects.all().order_by("titre")
    dossier_infos = [get_dossier_counts(d, etat_construction, etat_instruction, etats_termines, current_year) for d in demarches]

    return render(request, 'instruction/instruction.html', {"dossier_infos": dossier_infos})
