from datetime import date
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from autorisations.models.models_instruction import Demarche, Dossier, EtatDossier
from autorisations.models.models_utilisateurs import DossierBeneficiaire, DossierInterlocuteur

def get_dossier_counts(demarche, etat_construction, etat_instruction, etats_termines, current_year):
    return {
        "demarche": demarche,
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


@login_required
def instruction_demarche(request, num_demarche):

    demarche = get_object_or_404(Demarche, numero=num_demarche)

    # Récupérer l'ID de l'état "en_instruction"
    etat = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
    print('etat: ', etat)
    dossiers = Dossier.objects.filter(
                id_etat_dossier=etat,
                id_demarche=demarche.id
            ).select_related(
                "id_dossier_type",
                "id_groupeinstructeur"
            ).order_by("date_depot")

    dossier_infos = []
    for dossier in dossiers:

        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()
        beneficiaire = None
        if interlocuteur:
            dossier_beneficiaire = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            if dossier_beneficiaire:
                beneficiaire = dossier_beneficiaire.id_beneficiaire

        dossier_infos.append({
            "nom_dossier": dossier.nom_dossier,
            "type": dossier.id_dossier_type.type if dossier.id_dossier_type else "N/A",
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A"
        })

    return render(request, "instruction/instruction_demarche.html", {
    "demarche": demarche,
    "dossiers": dossier_infos,
})



@login_required
def instruction_dossier(request, num_dossier):

    return render(request, 'instruction/instruction_dossier.html', {})