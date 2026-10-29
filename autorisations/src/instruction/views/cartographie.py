"""Diffusion des couches GeoJSON pour les cartes de l'application."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from autorisations.models.models_cartographie import CartographieSource


@login_required
@require_GET
def geojson_source(request, source_id):
    apercu = request.GET.get("apercu") == "1"
    filtres = {"pk": source_id, "format": "geojson"}
    if apercu:
        # Lecture seule du brouillon admin, sans réactiver la source en base.
        if not request.user.is_superuser:
            raise PermissionDenied("Cette fonctionnalité est réservée aux administrateurs.")
    else:
        filtres["actif"] = True
    source = get_object_or_404(CartographieSource, **filtres)
    if source.geojson is None:
        return JsonResponse({"erreur": "Cette couche n’est pas importée."}, status=404)
    reponse = JsonResponse(source.geojson)
    reponse["Cache-Control"] = "private, no-store" if apercu else "private, max-age=60"
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse
