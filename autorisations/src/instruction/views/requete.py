from django.db.models import Q, Value
from django.http import JsonResponse
from django.shortcuts import render
from autorisations.models.models_instruction import Dossier, EtapeDossier, Demarche
from autorisations.models.models_avis import Expert
from autorisations.models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierInterlocuteur, Groupeinstructeur, Instructeur
from django.contrib.auth.decorators import login_required
from django.db.models.functions import ExtractYear, Coalesce
from django.db.models import Value, F
from django.db.models.functions import Concat
from autorisations.models.models_avis import Avis
from django.db.models.functions import ExtractYear, ExtractMonth



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


    context = {
        "dossiers": dossiers,
        "etapes": EtapeDossier.objects.all(),
        "demarches": Demarche.objects.all(),
        'etapes_dossier': etapes_dossier,
        "demarches": demarches,
        "groupes": groupes,
        "recherche_dossier_effectuee": bool(request.GET),
        "recherche_avis_effectuee": False,
        "annees": annees,
    }
    return render(request, "instruction/requetes.html", context)




@login_required
def requete_avis(request):

    # --- Base queryset ---
    avis_list = Avis.objects.select_related(
        "id_dossier",
        "id_demarche",
        "id_instructeur",
        "id_expert",
    ).filter(statut="Envoyé")

    # --- Récupération des filtres GET ---
    num_avis = request.GET.get("num_avis")
    mois = request.GET.get("mois")
    annee = request.GET.get("annee")
    reponse = request.GET.get("reponse")
    demandeur = request.GET.get("demandeur")
    expert = request.GET.get("expert")
    num_dossier = request.GET.get("num_dossier")
    type_demarche = request.GET.get("type_demarche")
    publie_raa = request.GET.get("publie_raa")  # Nouveau filtre

    # --- Application des filtres ---
    if num_avis:
        avis_list = avis_list.filter(id=num_avis)

    if mois:
        avis_list = avis_list.filter(date_demande_avis__month=mois)

    if annee:
        avis_list = avis_list.filter(date_demande_avis__year=annee)

    if reponse:
        reponse = reponse.strip()
        if reponse == "En attente":
            avis_list = avis_list.filter(favorable__isnull=True)
        elif reponse == "Favorable":
            avis_list = avis_list.filter(favorable=True, sous_reserve=False)
        elif reponse == "Favorable sous réserve":
            avis_list = avis_list.filter(favorable=True, sous_reserve=True)
        elif reponse == "Défavorable":
            avis_list = avis_list.filter(favorable=False)

    if publie_raa:
        if publie_raa.lower() == "oui":
            avis_list = avis_list.filter(publie_au_raa=True)
        elif publie_raa.lower() == "non":
            avis_list = avis_list.filter(Q(publie_au_raa=False) | Q(publie_au_raa__isnull=True))

    if demandeur:
        avis_list = avis_list.annotate(
            nom_complet_demandeur=Concat(
                Coalesce(F("id_instructeur__id_agent_autorisations__prenom"), Value("")),
                Value(" "),
                Coalesce(F("id_instructeur__id_agent_autorisations__nom"), Value("")),
            )
        ).filter(
            Q(nom_complet_demandeur__icontains=demandeur)
            | Q(id_instructeur__email__icontains=demandeur)  # si l'instructeur n’a pas d’agent_autorisations
        ).distinct()


    if expert:
        avis_list = avis_list.annotate(
            nom_complet_expert=Concat(
                Coalesce(F("id_expert__id_instructeur__id_agent_autorisations__prenom"), Value("")),
                Value(" "),
                Coalesce(F("id_expert__id_instructeur__id_agent_autorisations__nom"), Value("")),
            ),
            nom_complet_externe=Concat(
                Coalesce(F("id_expert__id_contact_externe__prenom"), Value("")),
                Value(" "),
                Coalesce(F("id_expert__id_contact_externe__nom"), Value("")),
            ),
        ).filter(
            Q(nom_complet_expert__icontains=expert)
            | Q(nom_complet_externe__icontains=expert)
        ).distinct()

    if num_dossier:
        avis_list = avis_list.filter(
            Q(id_dossier__numero=num_dossier)
            | Q(avisdossier__id_dossier__numero=num_dossier)
        ).distinct()


    if type_demarche:
        avis_list = avis_list.filter(id_dossier__id_demarche__type__icontains=type_demarche)

    avis_list = avis_list.order_by("-date_demande_avis")

    # --- Données pour les menus déroulants ---
    annees = Avis.objects.annotate(annee=ExtractYear("date_demande_avis")) \
        .values_list("annee", flat=True).distinct().order_by("-annee")
    mois_list = Avis.objects.annotate(mois=ExtractMonth("date_demande_avis")) \
        .values_list("mois", flat=True).distinct().order_by("mois")
    demarches = Demarche.objects.all().order_by("type")

    # --- Contexte pour le template ---
    context = {
        "avis_list": avis_list,
        "recherche_avis_effectuee": bool(request.GET),
        "recherche_dossier_effectuee": False,
        "annees": annees,
        "mois_list": mois_list,
        "demarches": demarches,
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



@login_required
def autocomplete_demandeur(request):
    """
    Retourne la liste des instructeurs (demandeurs d'avis envoyés)
    """
    term = request.GET.get("term", "").strip()

    results = (
        Instructeur.objects.filter(
            avis__statut="Envoyé",  # instructeurs liés à des avis envoyés
        )
        .filter(
            Q(id_agent_autorisations__nom__icontains=term)
            | Q(id_agent_autorisations__prenom__icontains=term)
        )
        .select_related("id_agent_autorisations")
        .distinct()[:15]
    )

    suggestions = [
        {
            "label": f"{i.id_agent_autorisations.prenom or ''} {i.id_agent_autorisations.nom or ''}".strip(),
            "value": f"{i.id_agent_autorisations.prenom or ''} {i.id_agent_autorisations.nom or ''}".strip(),
        }
        for i in results
        if i.id_agent_autorisations
    ]

    return JsonResponse(suggestions, safe=False)



@login_required
def autocomplete_expert(request):
    """
    Retourne la liste des experts (internes et externes) liés à des avis envoyés.
    """
    term = request.GET.get("term", "").strip()

    results = (
        Expert.objects.filter(avis__statut="Envoyé")
        .filter(
            Q(id_instructeur__id_agent_autorisations__nom__icontains=term)
            | Q(id_instructeur__id_agent_autorisations__prenom__icontains=term)
            | Q(id_contact_externe__nom__icontains=term)
            | Q(id_contact_externe__prenom__icontains=term)
        )
        .select_related(
            "id_instructeur__id_agent_autorisations",
            "id_contact_externe"
        )
        .distinct()[:15]
    )

    suggestions = []
    for e in results:
        if e.id_instructeur and e.id_instructeur.id_agent_autorisations:
            a = e.id_instructeur.id_agent_autorisations
            nom = f"{a.prenom or ''} {a.nom or ''}".strip()
        elif e.id_contact_externe:
            c = e.id_contact_externe
            nom = f"{c.prenom or ''} {c.nom or ''}".strip()
        else:
            continue

        suggestions.append({"label": nom, "value": nom})

    return JsonResponse(suggestions, safe=False)

