import json
import uuid

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, ProgrammingError, transaction
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from autorisations.models.models_cartographie import (
    CartographieConfiguration, CartographieConfigurationSource, CartographieSource,
)
from instruction.utils.cartographie import (
    CACHE_KEY, CONTROLES, PROFILS, charger_configurations, serialiser_source, sources_sans_geometries,
    valider_options_carte, valider_options_source, valider_url,
)
from instruction.utils.import_couches import convertir_couche


def verifier_admin(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette fonctionnalité est réservée aux administrateurs.")


def erreur_validation(exc):
    return JsonResponse({"erreur": " ".join(exc.messages) if isinstance(exc, ValidationError) else "Données JSON invalides."}, status=400)


@login_required
@require_GET
def catalogue(request):
    verifier_admin(request)
    try:
        sources = [serialiser_source(source) for source in sources_sans_geometries()]
        if not CartographieConfiguration.objects.exists():
            return JsonResponse({"erreur": "Exécutez le script SQL 0039_cartographie_dev.sql pour initialiser les cartes."}, status=503)
    except (ProgrammingError, OperationalError):
        return JsonResponse({"erreur": "Les tables cartographiques sont inaccessibles. Vérifiez le script SQL 0039 et les droits du compte applicatif."}, status=503)
    return JsonResponse({"sources": sources, "configurations": charger_configurations(), "controles": CONTROLES})


@login_required
@require_POST
def convertir_source(request):
    verifier_admin(request)
    try:
        geojson = convertir_couche(request.FILES.get("fichier"))
    except ValidationError as exc:
        return erreur_validation(exc)
    reponse = JsonResponse({"success": True, "geojson": geojson})
    reponse["Cache-Control"] = "private, no-store"
    return reponse


@login_required
@require_POST
def enregistrer_source(request, source_id=0):
    verifier_admin(request)
    source = get_object_or_404(CartographieSource, pk=source_id) if source_id else CartographieSource(code=f"source-{uuid.uuid4().hex[:16]}")
    try:
        donnees = json.loads(request.POST.get("configuration", "{}"))
        nom = donnees.get("nom", "").strip()
        format_source = donnees.get("format")
        if not nom or len(nom) > 150 or format_source not in ("tuiles", "geojson"):
            raise ValidationError("Le nom et un format valide sont obligatoires (nom : 150 caractères maximum).")
        if source_id and source.format != format_source:
            raise ValidationError("Le format d’une source existante ne peut pas être changé.")
        if type(donnees.get("actif", True)) is not bool:
            raise ValidationError("Statut actif invalide.")
        options = valider_options_source(format_source, donnees.get("options", {}))
        options["version"] = uuid.uuid4().hex[:12]
        fichier = request.FILES.get("fichier")
        geojson = source.geojson if source_id else None
        if fichier:
            if format_source != "geojson":
                raise ValidationError("Un fond de carte attend une URL de tuiles, pas un fichier vectoriel.")
            geojson = convertir_couche(fichier)
        url = donnees.get("url", "").strip()
        if fichier:
            url = ""
        if url:
            url = valider_url(url, fond=format_source == "tuiles")
            if not fichier:
                geojson = None
        elif geojson is None:
            raise ValidationError("Renseigner une URL ou importer une couche GeoJSON.")
        if format_source == "tuiles" and not donnees.get("attribution", "").strip():
            raise ValidationError("L’attribution du fournisseur du fond est obligatoire.")
        source.nom, source.format, source.url = nom, format_source, url
        source.geojson, source.options = geojson, options
        source.attribution = str(donnees.get("attribution", ""))[:250]
        source.actif = donnees.get("actif", True)
        if not source.actif and CartographieConfigurationSource.objects.filter(source=source, visible=True).exists():
            raise ValidationError("Cette source est visible par défaut sur une carte. Retirez-la de ces cartes avant de la désactiver.")
        source.save()
        cache.delete(CACHE_KEY)
        return JsonResponse({"success": True, "source": serialiser_source(source)})
    except (ValidationError, ValueError, UnicodeError, TypeError, AttributeError) as exc:
        return erreur_validation(exc)


@login_required
@require_POST
def enregistrer_configuration(request, code):
    verifier_admin(request)
    if code not in PROFILS:
        return JsonResponse({"erreur": "Carte inconnue."}, status=404)
    try:
        donnees = json.loads(request.body)
        options = valider_options_carte(code, donnees.get("options", {}))
        membres = donnees.get("sources", [])
        if not isinstance(membres, list) or len(membres) > 100:
            raise ValidationError("Liste de couches invalide (100 maximum).")
        ids = [membre["id"] for membre in membres]
        if any(type(identifiant) is not int for identifiant in ids) or len(ids) != len(set(ids)):
            raise ValidationError("Sources invalides ou dupliquées.")
        sources = CartographieSource.objects.filter(pk__in=ids, actif=True).in_bulk()
        if len(sources) != len(ids):
            raise ValidationError("Une source sélectionnée est absente ou désactivée.")
        for membre in membres:
            if type(membre.get("visible")) is not bool:
                raise ValidationError("Visibilité invalide.")
        if sum(membre["visible"] and sources[membre["id"]].format == "tuiles" for membre in membres) != 1:
            raise ValidationError("Sélectionner exactement un fond visible par défaut.")
        with transaction.atomic():
            configuration = get_object_or_404(CartographieConfiguration.objects.select_for_update(), code=code)
            configuration.options = options
            configuration.save(update_fields=["options"])
            configuration.sources.all().delete()
            CartographieConfigurationSource.objects.bulk_create([
                CartographieConfigurationSource(configuration=configuration, source_id=membre["id"], ordre=ordre, visible=membre["visible"])
                for ordre, membre in enumerate(membres)
            ])
        cache.delete(CACHE_KEY)
        return JsonResponse({"success": True})
    except IntegrityError:
        return JsonResponse({"erreur": "Une source a changé pendant l’enregistrement. Actualisez le catalogue puis réessayez."}, status=409)
    except (ValidationError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return erreur_validation(exc)


@login_required
@require_GET
def geojson_source(request, source_id):
    apercu = request.GET.get("apercu") == "1"
    filtres = {"pk": source_id, "format": "geojson"}
    if apercu:
        # Lecture seule du brouillon admin, sans réactiver la source en base.
        verifier_admin(request)
    else:
        filtres["actif"] = True
    source = get_object_or_404(CartographieSource, **filtres)
    if source.geojson is None:
        return JsonResponse({"erreur": "Cette couche n’est pas importée."}, status=404)
    reponse = JsonResponse(source.geojson)
    reponse["Cache-Control"] = "private, no-store" if apercu else "private, max-age=60"
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse


@login_required
@require_POST
def supprimer_source(request, source_id):
    verifier_admin(request)
    try:
        with transaction.atomic():
            source = get_object_or_404(CartographieSource.objects.select_for_update(), pk=source_id)
            cartes = list(source.configurations.values_list("configuration__nom", flat=True))
            if cartes:
                return JsonResponse({"erreur": "Cette source est encore utilisée. Retirez-la d’abord des cartes suivantes : " + ", ".join(cartes) + "."}, status=409)
            source.delete()
    except (ProtectedError, IntegrityError):
        # Une carte a pu référencer la source pendant le contrôle.
        return JsonResponse({"erreur": "Cette source est encore utilisée par une carte et ne peut pas être supprimée."}, status=409)
    cache.delete(CACHE_KEY)
    return JsonResponse({"success": True})
