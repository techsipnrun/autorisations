from collections import defaultdict
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, CharField, Q, Value, When
from django.db.models.functions import Cast, Concat
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import ContactExterne
from instruction.templatetags.group_tags import est_concerne_par_le_dossier
from instruction.utils.ensembles_dossiers import (
    EnsembleModifie, cartes_dossiers, dossiers_avec_demandeur, jeton_ensemble,
    lier_dossiers, membres_ensemble, retirer_dossier_lie,
)

logger = logging.getLogger("ORM_DJANGO")
TAILLE_PAGE = 20


def _entier_positif(valeur):
    try:
        nombre = int(valeur)
    except (TypeError, ValueError):
        raise ValidationError("Identifiant ou numéro de page invalide.")
    if nombre <= 0:
        raise ValidationError("Identifiant ou numéro de page invalide.")
    return nombre


@login_required
@require_GET
def autocomplete_demandeur_dossiers_lies(request, dossier_id):
    """Suggestions de demandeurs réellement présents sur des dossiers DN."""
    source = get_object_or_404(Dossier, pk=dossier_id)
    if not est_concerne_par_le_dossier(request.user, source):
        return JsonResponse({"error": "Vous ne pouvez pas gérer les liens de ce dossier."}, status=403)

    terme = request.GET.get("term", "").strip()
    demandeurs = ContactExterne.objects.filter(pk__in=(
        dossiers_avec_demandeur().exclude(demandeur_liaison_id__isnull=True)
        .values("demandeur_liaison_id")
    ))
    if terme:
        demandeurs = demandeurs.filter(
            Q(nom__icontains=terme) | Q(prenom__icontains=terme)
            | Q(raison_sociale__icontains=terme) | Q(organisation__icontains=terme)
            | Q(email__icontains=terme)
        )
    suggestions = [
        {"id": demandeur.pk, "label": demandeur.get_display_name()}
        for demandeur in demandeurs.order_by("nom", "prenom", "raison_sociale")[:15]
    ]
    return JsonResponse(suggestions, safe=False)


@login_required
@require_GET
def rechercher_dossiers_lies(request, dossier_id):
    source = get_object_or_404(Dossier, pk=dossier_id)
    if not est_concerne_par_le_dossier(request.user, source):
        return JsonResponse({"error": "Vous ne pouvez pas gérer les liens de ce dossier."}, status=403)
    try:
        page = _entier_positif(request.GET.get("page", 1))
        dossiers = dossiers_avec_demandeur().exclude(pk=source.pk)
        if source.id_ensemble_dossiers_id:
            dossiers = dossiers.exclude(id_ensemble_dossiers_id=source.id_ensemble_dossiers_id)
        recherche = request.GET.get("recherche", "").strip()
        if recherche:
            dossiers = dossiers.filter(
                Q(numero__icontains=recherche) | Q(nom_dossier__icontains=recherche)
                | Q(nom_dossier_plus_parlant__icontains=recherche)
            )
        if request.GET.get("demarche"):
            dossiers = dossiers.filter(id_demarche__type=request.GET["demarche"])
        if request.GET.get("etape"):
            dossiers = dossiers.filter(id_etape_dossier_id=_entier_positif(request.GET["etape"]))
        if request.GET.get("demandeur"):
            contact = get_object_or_404(ContactExterne, pk=_entier_positif(request.GET["demandeur"]))
            identite = Q(pk=contact.pk)
            # Des contacts de types différents peuvent représenter le même demandeur.
            if contact.email and contact.email.strip():
                identite |= Q(email__iexact=contact.email.strip())
            elif contact.siret:
                identite |= Q(siret=contact.siret)
            dossiers = dossiers.filter(demandeur_liaison_id__in=(
                ContactExterne.objects.filter(identite).values("pk")
            ))
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)

    # Pagination des ensembles, pas de leurs membres : aucune carte n'est tronquée.
    cles = list(dossiers.annotate(cle=Case(
        When(id_ensemble_dossiers__isnull=False, then=Concat(
            Value("e:"), Cast("id_ensemble_dossiers_id", CharField())
        )), default=Concat(Value("d:"), Cast("pk", CharField())), output_field=CharField(),
    )).order_by("cle").values_list("cle", flat=True).distinct()[
        (page - 1) * TAILLE_PAGE:page * TAILLE_PAGE + 1
    ])
    suite = len(cles) > TAILLE_PAGE
    cles = cles[:TAILLE_PAGE]
    ensembles = [int(cle[2:]) for cle in cles if cle.startswith("e:")]
    isoles = [int(cle[2:]) for cle in cles if cle.startswith("d:")]
    tous = list(dossiers_avec_demandeur().filter(
        Q(id_ensemble_dossiers_id__in=ensembles) | Q(pk__in=isoles)
    ).order_by("numero"))
    groupes = defaultdict(list)
    for dossier in tous:
        cle = (f"e:{dossier.id_ensemble_dossiers_id}" if dossier.id_ensemble_dossiers_id
               else f"d:{dossier.pk}")
        groupes[cle].append(dossier)
    cartes = {carte["id"]: carte for carte in cartes_dossiers(tous)}
    membres_source = membres_ensemble(source)
    resultats = [{
        "cible_id": groupes[cle][0].pk,
        "dossiers": [cartes[d.pk] for d in groupes[cle]],
        "jeton": jeton_ensemble(source, membres_source, groupes[cle]),
    } for cle in cles if groupes[cle]]
    return JsonResponse({
        "resultats": resultats, "page": page, "suite": suite,
        "source": cartes_dossiers(membres_source),
    })


def _modifier(request, dossier_id, operation):
    try:
        operation(request.user, dossier_id, _entier_positif(request.POST.get("cible_id")),
                  request.POST.get("jeton", ""))
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except Dossier.DoesNotExist:
        return JsonResponse({"error": "Un dossier a été supprimé. Actualisez la page."}, status=409)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)},
                            status=409 if isinstance(exc, EnsembleModifie) else 400)
    except Exception:
        logger.exception("Échec de modification des liens du dossier %s", dossier_id)
        return JsonResponse({"error": "Les liens n'ont pas pu être enregistrés. Réessayez."}, status=500)
    return JsonResponse({"success": True})


@login_required
@require_POST
def ajouter_lien_dossier(request, dossier_id):
    return _modifier(request, dossier_id, lier_dossiers)


@login_required
@require_POST
def retirer_lien_dossier(request, dossier_id):
    return _modifier(request, dossier_id, retirer_dossier_lie)
