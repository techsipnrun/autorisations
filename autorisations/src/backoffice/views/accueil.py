"""Accueil du Back Office."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import render

from autorisations.models.models_instruction import (
    Champ, Demarche, DemarcheColonneVueEnsemble, DemarcheDateActiviteChamp,
    DemarcheDateActiviteConfiguration, DemarcheNomDossierRegle, DemarcheNomDossierElement,
)
from instruction.utils.colonnes_vue_ensemble import configurations_colonnes_vue_ensemble
from synchronisation.utils.nom_dossier import (
    ATTRIBUTS_NOM_DOSSIER, TRANSFORMATIONS_NOM_DOSSIER, champs_dm_nommage_autorises,
    compiler_regles_nommage,
)
from backoffice.views.nom_dossier import champ_nommage_autorise


@login_required
def back_office(request):
    """Page d'accueil reservee aux superutilisateurs pour l'administration interne."""
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    demarches = list(Demarche.objects.exclude(type__isnull=True).exclude(type="").order_by("type").prefetch_related(
        Prefetch(
            "champ_set",
            queryset=Champ.objects.select_related("id_champ_type").order_by("nom", "id"),
            to_attr="champs_back_office",
        ),
        Prefetch(
            "date_activite_champs",
            queryset=DemarcheDateActiviteChamp.objects.select_related(
                "id_champ", "id_champ__id_champ_type"
            ).order_by("ordre", "id"),
            to_attr="date_activite_sources",
        ),
        Prefetch(
            "regles_nom_dossier",
            queryset=DemarcheNomDossierRegle.objects.prefetch_related(
                Prefetch("elements", queryset=DemarcheNomDossierElement.objects.select_related("id_champ")),
            ),
            to_attr="regles_nommage_back_office",
        ),
    ))
    configurations_par_demarche = {}
    for configuration in DemarcheColonneVueEnsemble.objects.filter(
            id_demarche_id__in=[demarche.id for demarche in demarches]
        ):
        configurations_par_demarche.setdefault(configuration.id_demarche_id, []).append(configuration)
    for demarche in demarches:
        demarche.configurations_tableaux_vue_ensemble = configurations_colonnes_vue_ensemble(
            demarche.type,
            configurations_par_demarche.get(demarche.id, []),
        )
    configurations_date_activite = {
        configuration.id_demarche_id: configuration
        for configuration in DemarcheDateActiviteConfiguration.objects.filter(
            id_demarche_id__in=[demarche.id for demarche in demarches]
        )
    }
    champs_dm = champs_dm_nommage_autorises()
    for demarche in demarches:
        demarche.configuration_date_activite_back_office = configurations_date_activite.get(demarche.id)
        demarche.champs_dm_back_office = champs_dm if (demarche.type or "").lower() == "manifestations sportives" else []
        demarche.nommage_donnees = {
            "regles": compiler_regles_nommage(demarche.regles_nommage_back_office),
            "champs": [{"id": champ.pk, "nom": champ.nom, "type": champ.id_champ_type.type}
                       for champ in demarche.champs_back_office if champ_nommage_autorise(champ)],
            "champs_dm": [{"name": champ.name, "nom": str(champ.verbose_name).capitalize(),
                            "type": champ.get_internal_type()}
                           for champ in demarche.champs_dm_back_office],
            "attributs": ATTRIBUTS_NOM_DOSSIER,
            "transformations": TRANSFORMATIONS_NOM_DOSSIER,
        }
        demarche.nommage_script_id = f"nommage-demarche-{demarche.id}"
    from backoffice.views.types_actes import contexte_types_actes
    return render(request, "backoffice/back_office.html", {"demarches_back_office": demarches, **contexte_types_actes()})
