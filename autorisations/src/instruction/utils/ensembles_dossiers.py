"""Regroupements informatifs de dossiers d'un même projet, indépendants de DN/DM."""
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse

from autorisations.models.models_instruction import Demarche, Dossier, EnsembleDossiers, EtapeDossier
from autorisations.models.models_utilisateurs import (
    ContactExterne, DossierBeneficiaire, DossierInterlocuteur, Instructeur,
)
from instruction.templatetags.group_tags import est_concerne_par_le_dossier
from instruction.utils.dossier_utils import get_demandeur_for_dossier


SIGNATURE_SALT = "instruction.ensembles_dossiers"


class EnsembleModifie(ValidationError):
    pass


def dossiers_avec_demandeur():
    # Même priorité que get_demandeur_for_dossier : intermédiaire, puis bénéficiaire.
    intermediaire = DossierInterlocuteur.objects.filter(
        id_dossier_id=OuterRef("pk")
    ).order_by("pk").values("id_demandeur_intermediaire_id")[:1]
    beneficiaire = DossierBeneficiaire.objects.filter(
        id_dossier_interlocuteur__id_dossier_id=OuterRef("pk")
    ).order_by("pk").values("id_beneficiaire_id")[:1]
    return Dossier.objects.select_related(
        "id_demarche", "id_etape_dossier"
    ).defer("geometrie", "geometrie_modif").annotate(
        demandeur_liaison_id=Coalesce(Subquery(intermediaire), Subquery(beneficiaire))
    )


def membres_ensemble(dossier, *, verrouiller=False):
    # Le verrou porte uniquement sur dossier, sans jointures ni FOR UPDATE OF :
    # les noms de tables qualifiés par schéma de l'application ne sont pas
    # acceptés par PostgreSQL dans la clause OF produite par Django.
    membres = Dossier.objects.all() if verrouiller else dossiers_avec_demandeur()
    if dossier.id_ensemble_dossiers_id:
        membres = membres.filter(id_ensemble_dossiers_id=dossier.id_ensemble_dossiers_id)
    else:
        membres = membres.filter(pk=dossier.pk)
    if verrouiller:
        membres = membres.select_for_update()
    return list(membres.order_by("pk"))


def empreinte(membres):
    return sorted([[d.pk, d.id_ensemble_dossiers_id] for d in membres])


def jeton_ensemble(dossier, membres, cible=None):
    return signing.dumps(
        {"source": dossier.pk, "membres": empreinte(membres),
         "cible": empreinte(cible) if cible is not None else None},
        salt=SIGNATURE_SALT, compress=True,
    )


def verifier_jeton(jeton, dossier, membres, cible=None):
    try:
        contenu = signing.loads(jeton, salt=SIGNATURE_SALT, max_age=1800)
    except signing.BadSignature:
        raise EnsembleModifie("La sélection a expiré. Actualisez la liste et réessayez.")
    attendu = {"source": dossier.pk, "membres": empreinte(membres),
               "cible": empreinte(cible) if cible is not None else None}
    if contenu != attendu:
        raise EnsembleModifie(
            "Les dossiers liés ont changé depuis l'affichage. Actualisez la liste et réessayez."
        )


def cartes_dossiers(dossiers):
    contacts = ContactExterne.objects.in_bulk(
        {d.demandeur_liaison_id for d in dossiers if d.demandeur_liaison_id}
    )
    cartes = []
    for dossier in dossiers:
        demandeur = contacts.get(dossier.demandeur_liaison_id)
        en_reception = dossier.id_etape_dossier.etape == "À affecter"
        cartes.append({
            "id": dossier.pk, "numero": dossier.numero,
            "nom": dossier.nom_dossier_plus_parlant or dossier.nom_dossier,
            "demarche": dossier.id_demarche.type,
            "etape": dossier.id_etape_dossier.etape,
            "demandeur": demandeur.get_display_name() if demandeur else "Non renseigné",
            "demandeur_id": demandeur.pk if demandeur else None,
            "url": reverse(
                "preinstruction_dossier" if en_reception else "instruction_dossier",
                kwargs={"numero" if en_reception else "num_dossier": dossier.numero},
            ),
        })
    return cartes


def contexte_dossiers_lies(request, dossier):
    peut_lier = est_concerne_par_le_dossier(request.user, dossier)
    membres = membres_ensemble(dossier) if dossier.id_ensemble_dossiers_id else []
    contexte = {
        "dossiers_lies": cartes_dossiers([d for d in membres if d.pk != dossier.pk]),
        "peut_lier_dossiers": peut_lier,
        "jeton_retrait_dossier": jeton_ensemble(dossier, membres),
    }
    if peut_lier:
        contexte.update({
            "demandeur_liaison": get_demandeur_for_dossier(dossier),
            "demarches_liaison": Demarche.objects.exclude(type="").exclude(
                type__isnull=True
            ).values_list("type", flat=True).order_by("type").distinct(),
            "etapes_liaison": EtapeDossier.objects.order_by("etape"),
        })
    return contexte


def _verrouiller_liaisons():
    # Toutes les fusions/retraits passent ici. Le verrou transactionnel dédié
    # sérialise ces opérations rares, même si elles concernent des groupes différents.
    # SQLite est utilisé uniquement pour les tests isolés.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [71423, 1])


def _acteur_autorise(user, dossier):
    if not est_concerne_par_le_dossier(user, dossier):
        raise PermissionDenied("Vous ne pouvez pas modifier les liens de ce dossier.")
    instructeur = Instructeur.objects.filter(email__iexact=user.email).first()
    if not instructeur:
        raise ValidationError("Un profil instructeur est nécessaire pour tracer cette action.")
    return instructeur


@transaction.atomic
def lier_dossiers(user, source_id, cible_id, jeton):
    _verrouiller_liaisons()
    source = Dossier.objects.get(pk=source_id)
    instructeur = _acteur_autorise(user, source)
    cible = Dossier.objects.get(pk=cible_id)
    if source.pk == cible.pk or (
        source.id_ensemble_dossiers_id
        and source.id_ensemble_dossiers_id == cible.id_ensemble_dossiers_id
    ):
        raise ValidationError("Ces dossiers sont déjà liés.")
    membres_source = membres_ensemble(source, verrouiller=True)
    membres_cible = membres_ensemble(cible, verrouiller=True)
    verifier_jeton(jeton, source, membres_source, membres_cible)
    ensemble_id = source.id_ensemble_dossiers_id or cible.id_ensemble_dossiers_id
    if ensemble_id is None:
        ensemble_id = EnsembleDossiers.objects.create(cree_par=instructeur).pk
    membres = membres_source + membres_cible
    Dossier.objects.filter(pk__in=[d.pk for d in membres]).update(
        id_ensemble_dossiers_id=ensemble_id
    )
    anciens_ids = {source.id_ensemble_dossiers_id, cible.id_ensemble_dossiers_id}
    anciens_ids.discard(None)
    anciens_ids.discard(ensemble_id)
    EnsembleDossiers.objects.filter(pk__in=anciens_ids).delete()


@transaction.atomic
def retirer_dossier_lie(user, source_id, cible_id, jeton):
    _verrouiller_liaisons()
    source = Dossier.objects.get(pk=source_id)
    instructeur = _acteur_autorise(user, source)
    if not source.id_ensemble_dossiers_id:
        raise EnsembleModifie("Ce dossier n'appartient plus à un ensemble.")
    membres = membres_ensemble(source, verrouiller=True)
    verifier_jeton(jeton, source, membres)
    cible = next((d for d in membres if d.pk == cible_id), None)
    if cible is None or cible.pk == source.pk:
        raise ValidationError("Choisissez un autre dossier de cet ensemble.")
    Dossier.objects.filter(pk=cible.pk).update(id_ensemble_dossiers=None)
    # Un membre isolé redevient indépendant.
    if len(membres) <= 2:
        Dossier.objects.filter(id_ensemble_dossiers_id=source.id_ensemble_dossiers_id).update(
            id_ensemble_dossiers=None
        )
        EnsembleDossiers.objects.filter(pk=source.id_ensemble_dossiers_id).delete()
