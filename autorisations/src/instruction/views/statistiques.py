from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, ExpressionWrapper, F, Q, fields
from django.db.models.functions import ExtractYear, TruncMonth
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from autorisations.models.models_instruction import (
    Demarche, Dossier, DossierAction, DossierManifestationLiaison, DossierManifSportive, EtapeDossier,
)
from autorisations.models.models_utilisateurs import (
    DossierEnvoiActe,
    DossierInstructeur,
    DossierManifSportiveInstructeur,
    DossierPublicationRAA,
    DossierRelecteur,
    DossierRelecteurQualite,
    DossierSignataire,
    DossierValideur,
    Groupeinstructeur,
    Instructeur,
)
from autorisations.models.models_avis import Avis, DossierAvis, Expert


TYPE_MANIFESTATIONS_SPORTIVES = "Manifestations sportives"
ROLES_DOSSIER = {
    "instructeur": ("Instructeur", (DossierInstructeur,)),
    "valideur": ("Valideur", (DossierValideur,)),
    "relecteur": ("Relecteur", (DossierRelecteur, DossierRelecteurQualite)),
    "signataire": ("Signataire", (DossierSignataire,)),
    "reception": ("Réception", ()),
    "publieur_raa": ("Publieur RAA", (DossierPublicationRAA,)),
    "envoi_acte": ("Envoi de l’acte", (DossierEnvoiActe,)),
}


def _verifier_acces_statistiques(user):
    est_instructeur = bool(
        user.email and Instructeur.objects.filter(email__iexact=user.email.strip()).exists()
    )
    if not (user.is_superuser or est_instructeur):
        raise PermissionDenied("Cette page est réservée aux instructeurs.")


def _liste_entiers(request, nom, minimum=1, maximum=None):
    valeurs = []
    for valeur in request.GET.getlist(nom):
        try:
            entier = int(valeur)
        except (TypeError, ValueError):
            continue
        if entier < minimum or (maximum is not None and entier > maximum):
            continue
        valeurs.append(entier)
    return list(dict.fromkeys(valeurs))


def _ajouter_repartition(destination, lignes, cle_label):
    for ligne in lignes:
        destination[ligne[cle_label] or "Non renseignée"] += ligne["total"]


def _serialiser_repartition(repartition):
    return [
        {"label": label, "valeur": valeur}
        for label, valeur in sorted(repartition.items(), key=lambda item: (-item[1], item[0]))
    ]


def _nombre_dossiers_par_role(instructeur_id, role):
    """Compte les dossiers distincts sur lesquels un agent a effectivement tenu un rôle."""
    _, modeles = ROLES_DOSSIER[role]
    dossier_ids = set()
    for modele in modeles:
        dossier_ids.update(
            modele.objects.filter(id_instructeur_id=instructeur_id)
            .values_list("id_dossier_id", flat=True)
        )
    if role == "reception":
        dossier_ids.update(
            DossierAction.objects.filter(
                id_instructeur_id=instructeur_id,
                id_action__action__icontains="Passage en pré-instruction",
            ).values_list("id_dossier_id", flat=True)
        )
    total = len(dossier_ids)
    if role == "instructeur":
        total += DossierManifSportiveInstructeur.objects.filter(
            id_instructeur_id=instructeur_id
        ).values("id_dossier_manif_sportive_id").distinct().count()
    return total


@login_required
def tableau_de_bord(request):
    """Affiche le tableau de bord statistique réservé aux instructeurs."""
    _verifier_acces_statistiques(request.user)
    annees_dn = Dossier.objects.annotate(annee=ExtractYear("date_depot")).values_list("annee", flat=True)
    annees_dm = DossierManifSportive.objects.annotate(annee=ExtractYear("date_depot")).values_list("annee", flat=True)
    annees = sorted({annee for annee in [*annees_dn, *annees_dm] if annee}, reverse=True)

    agents_par_role = {}
    for cle_role, (_, modeles) in ROLES_DOSSIER.items():
        ids = set()
        for modele in modeles:
            ids.update(modele.objects.values_list("id_instructeur_id", flat=True))
        if cle_role == "instructeur":
            ids.update(DossierManifSportiveInstructeur.objects.values_list("id_instructeur_id", flat=True))
        if cle_role == "reception":
            ids.update(DossierAction.objects.filter(
                id_action__action__icontains="Passage en pré-instruction"
            ).values_list("id_instructeur_id", flat=True))
        agents = Instructeur.objects.filter(id__in=ids).select_related("id_agent_autorisations").order_by(
            "id_agent_autorisations__nom", "id_agent_autorisations__prenom", "email"
        )
        agents_par_role[cle_role] = [{"id": agent.id, "label": str(agent)} for agent in agents]

    instructeurs = Instructeur.objects.filter(id__in=[item["id"] for item in agents_par_role["instructeur"]]).select_related("id_agent_autorisations").order_by(
        "id_agent_autorisations__nom", "id_agent_autorisations__prenom", "email"
    )
    instructeur_connecte = None
    if request.user.email:
        instructeur_connecte = Instructeur.objects.filter(
            email__iexact=request.user.email.strip()
        ).first()

    role_par_defaut = "instructeur"
    agent_par_defaut = None
    if instructeur_connecte:
        comptes_roles = {
            role: _nombre_dossiers_par_role(instructeur_connecte.id, role)
            for role in ROLES_DOSSIER
        }
        role_dominant, total_dominant = max(
            comptes_roles.items(), key=lambda item: item[1]
        )
        if total_dominant:
            role_par_defaut = role_dominant
            agent_par_defaut = instructeur_connecte.id

    if agent_par_defaut is None:
        candidats = agents_par_role["instructeur"]
        if candidats:
            comptes_instructeurs = defaultdict(int)
            for ligne in DossierInstructeur.objects.values("id_instructeur_id").annotate(
                total=Count("id_dossier_id", distinct=True)
            ):
                comptes_instructeurs[ligne["id_instructeur_id"]] += ligne["total"]
            for ligne in DossierManifSportiveInstructeur.objects.values("id_instructeur_id").annotate(
                total=Count("id_dossier_manif_sportive_id", distinct=True)
            ):
                comptes_instructeurs[ligne["id_instructeur_id"]] += ligne["total"]
            agent_par_defaut = max(
                candidats,
                key=lambda agent: (
                    comptes_instructeurs[agent["id"]],
                    -agent["id"],
                ),
            )["id"]

    experts = Expert.objects.filter(avis__isnull=False).select_related(
        "id_instructeur__id_agent_autorisations", "id_contact_externe"
    ).distinct().order_by("id")
    experts_choices = [{"value": f"expert:{expert.id}", "label": str(expert)} for expert in experts]
    raisons_sociales = set()
    for expert in experts.filter(est_interne=False):
        contact = expert.id_contact_externe
        raison = ((contact.raison_sociale or contact.organisation or "").strip() if contact else "")
        if raison:
            raisons_sociales.add(raison)
    experts_choices.extend(
        {"value": f"organisation:{raison}", "label": raison, "est_organisation": True}
        for raison in sorted(raisons_sociales, key=str.casefold)
    )
    expert_par_defaut = next((
        choix["value"] for choix in experts_choices
        if choix.get("est_organisation") and choix["label"].casefold() == "conseil scientifique"
    ), None)

    return render(request, "instruction/statistiques.html", {
        "annees": annees,
        "demarches": Demarche.objects.filter(dossier__isnull=False).distinct().order_by("type"),
        "etapes": EtapeDossier.objects.order_by("etape"),
        "groupes_instructeurs": Groupeinstructeur.objects.order_by("nom"),
        "instructeurs": instructeurs,
        "role_par_defaut": role_par_defaut,
        "agent_par_defaut": agent_par_defaut,
        "roles_dossier": [(cle, libelle) for cle, (libelle, _) in ROLES_DOSSIER.items()],
        "agents_par_role": agents_par_role,
        "experts_choices": experts_choices,
        "expert_par_defaut": expert_par_defaut,
        "annee_courante": timezone.localdate().year,
        "mois": [
            (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
            (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
            (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
        ],
    })


@login_required
def donnees_tableau_de_bord(request):
    """Retourne les agrégats du tableau de bord en fonction des filtres multiples."""
    _verifier_acces_statistiques(request.user)
    annees = _liste_entiers(request, "annees")
    mois = _liste_entiers(request, "mois", maximum=12)
    demarche_ids = _liste_entiers(request, "demarches")
    etape_ids = _liste_entiers(request, "etapes")
    groupe_ids = _liste_entiers(request, "groupes")
    instructeur_ids = _liste_entiers(request, "instructeur")
    instructeur_id = instructeur_ids[0] if instructeur_ids else None
    role = request.GET.get("role", "instructeur")
    if role not in ROLES_DOSSIER:
        role = "instructeur"
    expert_selection = request.GET.get("expert", "")

    dossiers = Dossier.objects.select_related("id_demarche", "id_etape_dossier")
    dossiers_dm = DossierManifSportive.objects.select_related("id_etape")
    if annees:
        dossiers = dossiers.filter(date_depot__year__in=annees)
        dossiers_dm = dossiers_dm.filter(date_depot__year__in=annees)
    if demarche_ids:
        dossiers = dossiers.filter(id_demarche_id__in=demarche_ids)
    if etape_ids:
        dossiers = dossiers.filter(id_etape_dossier_id__in=etape_ids)
        dossiers_dm = dossiers_dm.filter(id_etape_id__in=etape_ids)
    if groupe_ids:
        dossiers = dossiers.filter(id_groupeinstructeur_id__in=groupe_ids)
        dossiers_dm = dossiers_dm.filter(id_groupeinstructeur_id__in=groupe_ids)

    types_selectionnes = set(
        Demarche.objects.filter(id__in=demarche_ids).values_list("type", flat=True)
    )
    inclure_dm = not demarche_ids or TYPE_MANIFESTATIONS_SPORTIVES in types_selectionnes
    if not inclure_dm:
        dossiers_dm = dossiers_dm.none()

    # Les autres graphiques respectent exactement les mois cochés. La courbe
    # cumulative utilise, elle, l'intervalle continu entre les deux bornes.
    dossiers_courbe = dossiers
    dossiers_dm_courbe = dossiers_dm
    if len(mois) >= 2:
        dossiers_courbe = dossiers_courbe.filter(date_depot__month__range=(min(mois), max(mois)))
        dossiers_dm_courbe = dossiers_dm_courbe.filter(date_depot__month__range=(min(mois), max(mois)))
    elif len(mois) == 1:
        dossiers_courbe = dossiers_courbe.filter(date_depot__month=mois[0])
        dossiers_dm_courbe = dossiers_dm_courbe.filter(date_depot__month=mois[0])

    if mois:
        dossiers = dossiers.filter(date_depot__month__in=mois)
        dossiers_dm = dossiers_dm.filter(date_depot__month__in=mois)

    ids_dn = dossiers.values_list("id", flat=True)
    ids_dm = dossiers_dm.values_list("id", flat=True)
    liaisons = DossierManifestationLiaison.objects.filter(
        id_dossier_id__in=ids_dn, id_dossier_manif_id__in=ids_dm,
    )
    ids_dn_complets = liaisons.values_list("id_dossier_id", flat=True)
    ids_dm_complets = liaisons.values_list("id_dossier_manif_id", flat=True)
    dossiers_dm_orphelins = dossiers_dm.exclude(id__in=ids_dm_complets)

    liaisons_courbe = DossierManifestationLiaison.objects.filter(
        id_dossier_id__in=dossiers_courbe.values_list("id", flat=True),
        id_dossier_manif_id__in=dossiers_dm_courbe.values_list("id", flat=True),
    )
    dossiers_dm_orphelins_courbe = dossiers_dm_courbe.exclude(
        id__in=liaisons_courbe.values_list("id_dossier_manif_id", flat=True)
    )

    total_dm_orphelins = dossiers_dm_orphelins.count()
    duree_instruction = ExpressionWrapper(
        F("date_fin_instruction") - F("date_debut_instruction"),
        output_field=fields.DurationField(),
    )
    resume_dn = dossiers.aggregate(
        reception=Count("id", filter=Q(id_etape_dossier__etape="En réception")),
        instruction=Count("id", filter=Q(date_fin_instruction__isnull=True) & ~Q(id_etape_dossier__etape="En réception")),
        termines=Count("id", filter=Q(date_fin_instruction__isnull=False)),
        delai_moyen=Avg(duree_instruction, filter=Q(date_debut_instruction__isnull=False, date_fin_instruction__isnull=False)),
    )
    reception_dm = dossiers_dm_orphelins.filter(id_etape__etape="En réception").count()
    termines_dm = dossiers_dm_orphelins.filter(archive=True).count()
    instruction_dm = total_dm_orphelins - reception_dm - termines_dm

    repartition_types = defaultdict(int)
    _ajouter_repartition(repartition_types, dossiers.values("id_demarche__type").annotate(total=Count("id")), "id_demarche__type")
    if total_dm_orphelins:
        repartition_types[TYPE_MANIFESTATIONS_SPORTIVES] += total_dm_orphelins

    repartition_etapes = defaultdict(int)
    _ajouter_repartition(repartition_etapes, dossiers.values("id_etape_dossier__etape").annotate(total=Count("id")), "id_etape_dossier__etape")
    _ajouter_repartition(repartition_etapes, dossiers_dm_orphelins.values("id_etape__etape").annotate(total=Count("id")), "id_etape__etape")

    evolution = defaultdict(int)
    for queryset in (dossiers, dossiers_dm_orphelins):
        for ligne in queryset.annotate(periode=TruncMonth("date_depot")).values("periode").annotate(total=Count("id")):
            if ligne["periode"]:
                evolution[ligne["periode"]] += ligne["total"]

    evolution_courbe = defaultdict(int)
    for queryset in (dossiers_courbe, dossiers_dm_orphelins_courbe):
        for ligne in queryset.annotate(periode=TruncMonth("date_depot")).values("periode").annotate(total=Count("id")):
            if ligne["periode"]:
                evolution_courbe[ligne["periode"]] += ligne["total"]

    dossiers_dn_ms = dossiers.filter(id_demarche__type=TYPE_MANIFESTATIONS_SPORTIVES)
    repartition_instructeur = defaultdict(int)
    if instructeur_id:
        _, modeles_role = ROLES_DOSSIER[role]
        ids_role = set()
        for modele in modeles_role:
            ids_role.update(modele.objects.filter(id_instructeur_id=instructeur_id).values_list("id_dossier_id", flat=True))
        if role == "reception":
            ids_role.update(DossierAction.objects.filter(
                id_instructeur_id=instructeur_id,
                id_action__action__icontains="Passage en pré-instruction",
            ).values_list("id_dossier_id", flat=True))
        dossiers_instructeur_ids = ids_role
        dossiers_instructeur = dossiers.filter(id__in=dossiers_instructeur_ids)
        _ajouter_repartition(
            repartition_instructeur,
            dossiers_instructeur.values("id_demarche__type").annotate(total=Count("id")),
            "id_demarche__type",
        )
        dm_instructeur_ids = DossierManifSportiveInstructeur.objects.filter(
            id_instructeur_id=instructeur_id,
            id_dossier_manif_sportive_id__in=dossiers_dm_orphelins.values_list("id", flat=True),
        ).values_list("id_dossier_manif_sportive_id", flat=True)
        nombre_dm_instructeur = dossiers_dm_orphelins.filter(id__in=dm_instructeur_ids).count() if role == "instructeur" else 0
        if nombre_dm_instructeur:
            repartition_instructeur[TYPE_MANIFESTATIONS_SPORTIVES] += nombre_dm_instructeur

    repartition_avis = defaultdict(int)
    if expert_selection:
        avis_expert = Avis.objects.none()
        if expert_selection.startswith("expert:"):
            try:
                avis_expert = Avis.objects.filter(id_expert_id=int(expert_selection.split(":", 1)[1]))
            except ValueError:
                pass
        elif expert_selection.startswith("organisation:"):
            organisation = expert_selection.split(":", 1)[1]
            avis_expert = Avis.objects.filter(id_expert__est_interne=False).filter(
                Q(id_expert__id_contact_externe__raison_sociale__iexact=organisation)
                | Q(id_expert__id_contact_externe__organisation__iexact=organisation)
            )
        avis_candidats = list(avis_expert.values(
            "id", "id_dossier_id", "id_demarche_id", "date_demande_avis"
        ))
        ids_avis_candidats = {avis["id"] for avis in avis_candidats}
        dossiers_par_avis = defaultdict(set)
        for avis_id, dossier_id in DossierAvis.objects.filter(
            id_avis_id__in=ids_avis_candidats
        ).values_list("id_avis_id", "id_dossier_id"):
            dossiers_par_avis[avis_id].add(dossier_id)
        for avis in avis_candidats:
            if avis["id_dossier_id"]:
                dossiers_par_avis[avis["id"]].add(avis["id_dossier_id"])

        dossiers_filtres_ids = set(dossiers.values_list("id", flat=True))
        avis_ids = set()
        for avis in avis_candidats:
            dossiers_lies = dossiers_par_avis[avis["id"]]
            if dossiers_lies:
                if dossiers_lies & dossiers_filtres_ids:
                    avis_ids.add(avis["id"])
                continue

            # Une demande générique ne dispose ni d'étape ni de groupe dossier.
            # Elle reste filtrable par sa démarche et sa date de demande.
            if etape_ids or groupe_ids:
                continue
            if demarche_ids and avis["id_demarche_id"] not in demarche_ids:
                continue
            date_demande = avis["date_demande_avis"]
            if annees and (not date_demande or date_demande.year not in annees):
                continue
            if mois and (not date_demande or date_demande.month not in mois):
                continue
            avis_ids.add(avis["id"])

        types_par_avis = defaultdict(set)
        for avis_id, type_demarche in DossierAvis.objects.filter(
            id_avis_id__in=avis_ids,
            id_dossier_id__in=dossiers_filtres_ids,
        ).values_list("id_avis_id", "id_dossier__id_demarche__type"):
            if type_demarche:
                types_par_avis[avis_id].add(type_demarche)
        for avis_id, type_dossier, type_demarche in Avis.objects.filter(id__in=avis_ids).values_list("id", "id_dossier__id_demarche__type", "id_demarche__type"):
            if not types_par_avis[avis_id]:
                type_final = type_dossier or type_demarche or "Sans type de dossier"
                types_par_avis[avis_id].add(type_final)
        for types in types_par_avis.values():
            for type_dossier in types:
                repartition_avis[type_dossier] += 1

    delai = resume_dn["delai_moyen"]
    repartition_groupes = defaultdict(int)
    _ajouter_repartition(
        repartition_groupes,
        dossiers.values("id_groupeinstructeur__nom").annotate(total=Count("id")),
        "id_groupeinstructeur__nom",
    )
    _ajouter_repartition(
        repartition_groupes,
        dossiers_dm_orphelins.values("id_groupeinstructeur__nom").annotate(total=Count("id")),
        "id_groupeinstructeur__nom",
    )
    return JsonResponse({
        "indicateurs": {
            "total": dossiers.count() + total_dm_orphelins,
            "reception": (resume_dn["reception"] or 0) + reception_dm,
            "instruction": (resume_dn["instruction"] or 0) + max(instruction_dm, 0),
            "termines": (resume_dn["termines"] or 0) + termines_dm,
            "delai_moyen_jours": round(delai.total_seconds() / 86400, 1) if delai else None,
        },
        "repartition_types": _serialiser_repartition(repartition_types),
        "repartition_etapes": _serialiser_repartition(repartition_etapes),
        "evolution": [
            {"label": periode.strftime("%m/%Y"), "valeur": valeur}
            for periode, valeur in sorted(evolution.items())
        ],
        "evolution_courbe": [
            {"label": periode.strftime("%m/%Y"), "valeur": valeur}
            for periode, valeur in sorted(evolution_courbe.items())
        ],
        "manifestations_sportives": {
            "visible": inclure_dm,
            "complets": dossiers_dn_ms.filter(id__in=ids_dn_complets).count(),
            "orphelins_dn": dossiers_dn_ms.exclude(id__in=ids_dn_complets).count(),
            "orphelins_dm": total_dm_orphelins,
        },
        "repartition_instructeur": _serialiser_repartition(repartition_instructeur),
        "repartition_avis": _serialiser_repartition(repartition_avis),
        "repartition_groupes": _serialiser_repartition(repartition_groupes),
    })
