from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required

from autorisations.models.models_instruction import Dossier
from autorisations.models.models_avis import AvisNature, AvisThematique
from autorisations.models.models_utilisateurs import ContactExterne, Instructeur



@login_required
def instruction_dossier_ajouter_avis(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    # print(f'La vue instruction_dossier_ajouter_avis est appelée (Dossier {num_dossier})')


    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")
    thematiques = AvisThematique.objects.all().order_by("thematique")

    # Contacts externes
    contacts_externes = list((
        ContactExterne.objects
        .filter(email__isnull=False)
        .exclude(email__exact='')
        .order_by('nom', 'email')
    ))

    # Instructeurs
    instructeurs = list(
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact='')
        .order_by('email')
    )


    return render(request, "instruction/instruction_dossier_ajouter_avis.html", {
        "dossier": dossier,
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "contacts_externes": contacts_externes,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
    })



@login_required
def instruction_dossier_confirmer_ajout_avis(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    # print(f'La vue instruction_dossier_confirmer_ajout_avis est appelée (Dossier {num_dossier})')

    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)

