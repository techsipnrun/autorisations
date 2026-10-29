"""Configuration des dates d'activité et des tableaux par démarche."""
import re

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from autorisations.models.models_instruction import (
    Champ, Demarche, DemarcheColonneVueEnsemble, DemarcheDateActiviteChamp,
    DemarcheDateActiviteConfiguration, DossierManifSportive,
)
from instruction.utils.colonnes_vue_ensemble import (
    TABLEAU_ARCHIVES, TABLEAU_EN_COURS, TABLEAU_MES_DOSSIERS,
    TABLEAU_RECEPTION_DM, TABLEAU_RECEPTION_DN, TABLEAU_RECEPTION_COMPLET,
    colonnes_vue_ensemble,
)


@login_required
@require_POST
def back_office_enregistrer_date_activite(request, demarche_id):
    """Enregistre les champs sources, dans leur ordre de priorité."""
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    demarche = get_object_or_404(Demarche, pk=demarche_id)
    sources = list(dict.fromkeys(request.POST.getlist("champs[]")))
    try:
        delai_alerte_jours = int(request.POST.get("delai_alerte_jours", 30))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de champs ou le délai est invalide."}, status=400)
    if not 0 <= delai_alerte_jours <= 3650:
        return JsonResponse({"error": "Le délai doit être compris entre 0 et 3 650 jours."}, status=400)

    couleurs = {
        "couleur_alerte": (request.POST.get("couleur_alerte") or "").strip(),
        "couleur_passee": (request.POST.get("couleur_passee") or "").strip(),
    }
    if any(not re.fullmatch(r"#[0-9a-fA-F]{6}", couleur) for couleur in couleurs.values()):
        return JsonResponse({"error": "Les couleurs doivent être au format hexadécimal #RRGGBB."}, status=400)

    ids_champs = [int(source.removeprefix("dn:")) for source in sources if source.startswith("dn:")]
    champs_dm = [source.removeprefix("dm:") for source in sources if source.startswith("dm:")]
    if len(ids_champs) + len(champs_dm) != len(sources):
        return JsonResponse({"error": "Une source de date est invalide."}, status=400)
    champs = list(Champ.objects.filter(id_demarche=demarche, pk__in=ids_champs).select_related("id_champ_type"))
    champs_par_id = {champ.pk: champ for champ in champs}
    champs_dm_autorises = {champ.name for champ in DossierManifSportive._meta.fields}
    if len(champs_par_id) != len(ids_champs) or not set(champs_dm).issubset(champs_dm_autorises):
        return JsonResponse({"error": "Un des champs ne correspond pas à cette démarche."}, status=400)

    with transaction.atomic():
        DemarcheDateActiviteChamp.objects.filter(id_demarche=demarche).delete()
        DemarcheDateActiviteChamp.objects.bulk_create([
            DemarcheDateActiviteChamp(
                id_demarche=demarche, ordre=ordre,
                source="dm" if source.startswith("dm:") else "dn",
                champ_dm=source.removeprefix("dm:") or None,
                id_champ=champs_par_id.get(int(source.removeprefix("dn:"))) if source.startswith("dn:") else None,
            ) for ordre, source in enumerate(sources, start=1)
        ])
        DemarcheDateActiviteConfiguration.objects.update_or_create(
            id_demarche=demarche,
            defaults={"delai_alerte_jours": delai_alerte_jours, **couleurs},
        )
    return JsonResponse({
        "success": True,
        "sources": [
            {"id": champ_id, "nom": champs_par_id[champ_id].nom, "ordre": ordre}
            for ordre, champ_id in enumerate(ids_champs, start=1)
        ],
    })


@login_required
@require_POST
def back_office_enregistrer_personnalisation_tableau(request, demarche_id):
    """Enregistre les colonnes visibles d'un tableau de la vue d'ensemble."""
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    demarche = get_object_or_404(Demarche, pk=demarche_id)
    tableau = request.POST.get("tableau")
    if tableau not in {TABLEAU_EN_COURS, TABLEAU_ARCHIVES, TABLEAU_MES_DOSSIERS, TABLEAU_RECEPTION_DM, TABLEAU_RECEPTION_DN, TABLEAU_RECEPTION_COMPLET}:
        return JsonResponse({"error": "Le tableau demandé est invalide."}, status=400)

    definitions_colonnes = dict(colonnes_vue_ensemble(demarche.type)[tableau])
    colonnes_autorisees = set(definitions_colonnes)
    colonnes_visibles = set(request.POST.getlist("colonnes[]"))
    ordre_colonnes = request.POST.getlist("ordre[]")
    if not colonnes_visibles.issubset(colonnes_autorisees):
        return JsonResponse({"error": "Une des colonnes ne correspond pas à cette démarche."}, status=400)
    if len(ordre_colonnes) != len(colonnes_autorisees) or set(ordre_colonnes) != colonnes_autorisees:
        return JsonResponse({"error": "L’ordre des colonnes est invalide."}, status=400)

    libelles_personnalises = {}
    for colonne in colonnes_autorisees:
        libelle = request.POST.get(f"libelles[{colonne}]", "").strip()
        if len(libelle) > 150:
            return JsonResponse({"error": "Un libellé ne peut pas dépasser 150 caractères."}, status=400)
        if libelle and libelle != definitions_colonnes[colonne]:
            libelles_personnalises[colonne] = libelle

    with transaction.atomic():
        DemarcheColonneVueEnsemble.objects.filter(
            id_demarche=demarche,
            tableau=tableau,
        ).delete()
        DemarcheColonneVueEnsemble.objects.bulk_create([
            DemarcheColonneVueEnsemble(
                id_demarche=demarche,
                tableau=tableau,
                colonne=colonne,
                affiche=colonne in colonnes_visibles,
                libelle_personnalise=libelles_personnalises.get(colonne),
                ordre=ordre,
            )
            for ordre, colonne in enumerate(ordre_colonnes, start=1)
        ])
    return JsonResponse({
        "success": True,
        "tableau": tableau,
        "colonnes_visibles": sorted(colonnes_visibles),
        "libelles_personnalises": libelles_personnalises,
    })
