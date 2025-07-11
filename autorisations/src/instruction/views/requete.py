from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from autorisations.models.models_instruction import Dossier, EtapeDossier, Demarche
from autorisations.models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierInterlocuteur, Groupeinstructeur, Instructeur
from django.contrib.auth.decorators import login_required
from django.db.models.functions import ExtractYear, Coalesce
from django.db.models import Value, F
from django.db.models.functions import Concat



@login_required
def requete_dossiers(request):
    dossiers = Dossier.objects.all().select_related("id_demarche", "id_groupeinstructeur", "id_etape_dossier")

    numero = request.GET.get("numero")
    date_depot = request.GET.get("date_depot")
    type_demarche = request.GET.get("type_demarche")
    groupe = request.GET.get("groupe")
    etape = request.GET.get("etape")
    nom = request.GET.get("nom")
    annee = request.GET.get("annee")
    instructeur = request.GET.get("instructeur")


    if annee:
        dossiers = dossiers.filter(date_depot__year=annee)

    if numero:
        dossiers = dossiers.filter(numero=numero)

    if date_depot:
        dossiers = dossiers.filter(date_depot__date=date_depot)

    if type_demarche:
        dossiers = dossiers.filter(id_demarche__type__icontains=type_demarche)

    if groupe:
        dossiers = dossiers.filter(id_groupeinstructeur__nom__icontains=groupe)

    if etape:
        dossiers = dossiers.filter(id_etape_dossier__etape__icontains=etape)

    if instructeur:
        dossiers = dossiers.annotate(
            nom_complet_instructeur=Concat(
                F("dossierinstructeur__id_instructeur__id_agent_autorisations__nom"),
                Value(" "),
                F("dossierinstructeur__id_instructeur__id_agent_autorisations__prenom")
            )
        ).filter(
            Q(nom_complet_instructeur__iexact=instructeur)
        ).distinct()

    if nom:
        dossiers = dossiers.annotate(
            nom_complet_beneficiaire=Concat(
                F("dossierinterlocuteur__dossierbeneficiaire__id_beneficiaire__nom"),
                Value(" "),
                F("dossierinterlocuteur__dossierbeneficiaire__id_beneficiaire__prenom")
            )
        ).filter(
            Q(dossierinterlocuteur__dossierbeneficiaire__id_beneficiaire__raison_sociale__iexact=nom) |
            Q(nom_complet_beneficiaire__iexact=nom)
        ).distinct()

    dossiers = dossiers.order_by('-date_depot')

    dossiers = dossiers.order_by('-date_depot')

    # Ajout du champ 'lien' pour chaque dossier
    for d in dossiers:
        if d.id_etape_dossier and d.id_etape_dossier.etape == "À affecter":
            d.lien = f"/preinstruction/{d.numero}/"
        else:
            d.lien = f"/instruction/{d.numero}/"
            

    # Menus déroulant
    etapes_dossier = EtapeDossier.objects.all().order_by('etape')
    demarches = Demarche.objects.all().order_by('type')
    groupes = Groupeinstructeur.objects.all().order_by('nom')
    annees = Dossier.objects.annotate(annee=ExtractYear("date_depot")) \
                        .values_list("annee", flat=True).distinct().order_by("-annee")


    recherche_effectuee = bool(request.GET)

    context = {
        "dossiers": dossiers,
        "etapes": EtapeDossier.objects.all(),
        "demarches": Demarche.objects.all(),
        'etapes_dossier': etapes_dossier,
        "demarches": demarches,
        "groupes": groupes,
        'recherche_effectuee': recherche_effectuee,
        "annees": annees,
    }
    return render(request, "instruction/requetes.html", context)


@login_required
def autocomplete_numero_dossier(request):
    query = request.GET.get("term", "").strip()
    if not query.isdigit():
        return JsonResponse([], safe=False)

    suggestions = Dossier.objects.filter(numero__startswith=query) \
                                 .order_by("numero")[:5]

    resultats = [{"value": d.numero} for d in suggestions]
    return JsonResponse(resultats, safe=False)


# @login_required
# def autocomplete_nom_beneficiaire(request):
#     query = request.GET.get("term", "").strip()
#     if not query:
#         return JsonResponse([], safe=False)

#     # Récupère les bénéficiaires dont nom ou raison sociale contient la requête
#     beneficiaires = ContactExterne.objects.filter(
#         dossierbeneficiaire__isnull=False
#     ).annotate(
#         nom_affiche=Coalesce("raison_sociale", "nom", "prenom")
#     ).filter(
#         nom_affiche__icontains=query
#     ).values_list("nom_affiche", flat=True).distinct().order_by("nom_affiche")[:5]

#     data = [{"value": nom} for nom in beneficiaires]
#     return JsonResponse(data, safe=False)

from django.db.models import Value
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from autorisations.models.models_utilisateurs import ContactExterne

@login_required
def autocomplete_nom_beneficiaire(request):
    query = request.GET.get("term", "").strip()
    if not query:
        return JsonResponse([], safe=False)

    beneficiaires = ContactExterne.objects.filter(
        dossierbeneficiaire__isnull=False
    ).filter(
        Q(raison_sociale__icontains=query) |
        Q(nom__icontains=query) |
        Q(prenom__icontains=query)
    ).values("raison_sociale", "nom", "prenom").distinct()

    results = []
    for b in beneficiaires:
        if b["raison_sociale"]:
            display = b["raison_sociale"]
        elif b["nom"] and b["prenom"]:
            display = f"{b['nom']} {b['prenom']}"
        # elif b["nom"]:
        #     display = b["nom"]
        else:
            continue

        results.append({"value": display})

    return JsonResponse(results[:5], safe=False)



@login_required
def autocomplete_instructeur(request):
    term = request.GET.get("term", "").strip()
    if not term:
        return JsonResponse([], safe=False)

    instructeurs = Instructeur.objects.filter(
        Q(id_agent_autorisations__nom__icontains=term) |
        Q(id_agent_autorisations__prenom__icontains=term)
    ).annotate(
        nom_complet=Concat(
            F("id_agent_autorisations__nom"),
            Value(" "),
            F("id_agent_autorisations__prenom")
        )
    ).values_list("nom_complet", flat=True).distinct().order_by("nom_complet")[:5]


    data = [{"value": nom} for nom in instructeurs]
    return JsonResponse(data, safe=False)
