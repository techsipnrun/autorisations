from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from autorisations.models.models_documents import Document, DocumentNature
from backoffice.forms.types_actes import TypeActeForm


def contexte_types_actes():
    types = list(DocumentNature.objects.filter(est_acte=True).order_by("ordre_affichage", "nature", "id"))
    annee = date.today().year
    # Une seule agrégation pour tous les types, sans réserver de numéro.
    derniers_numeros = {
        ligne["id_nature_id"]: ligne["dernier_numero"]
        for ligne in Document.objects.filter(
            id_nature_id__in=[nature.pk for nature in types], numero__startswith=str(annee),
        ).values("id_nature_id").annotate(dernier_numero=Max("numero"))
    }
    return {
        "formulaire_nouveau_type_acte": TypeActeForm(instance=DocumentNature(est_acte=True), auto_id="nouveau-acte-%s"),
        "premier_numero_acte": Document.prochain_numero(None, annee),
        "formulaires_types_actes": [
            {"type": nature, "form": TypeActeForm(instance=nature, auto_id=f"acte-{nature.pk}-%s"),
             "position": position,
             "prochain_numero": Document.prochain_numero(derniers_numeros.get(nature.pk), annee)}
            for position, nature in enumerate(types, 1)
        ],
    }


def _types_actes_verrouilles():
    return list(DocumentNature.objects.select_for_update().filter(est_acte=True).order_by("ordre_affichage", "nature", "id"))


def _enregistrer_classement(types):
    modifies = []
    for position, nature in enumerate(types, 1):
        if nature.ordre_affichage != position:
            nature.ordre_affichage = position
            modifies.append(nature)
    if modifies:
        DocumentNature.objects.bulk_update(modifies, ["ordre_affichage"])


@login_required
@require_POST
def deplacer_type_acte(request, type_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    direction = request.POST.get("direction")
    if direction not in ("monter", "descendre"):
        return JsonResponse({"success": False, "error": "Déplacement invalide."}, status=400)
    with transaction.atomic():
        types = _types_actes_verrouilles()
        index = next((index for index, nature in enumerate(types) if nature.pk == type_id), None)
        if index is None:
            raise Http404("Type d’acte introuvable.")
        destination = index + (-1 if direction == "monter" else 1)
        if 0 <= destination < len(types):
            types[index], types[destination] = types[destination], types[index]
        _enregistrer_classement(types)
    return JsonResponse({"success": True, "ordre": [nature.pk for nature in types]})


@login_required
@require_POST
def enregistrer_type_acte(request, type_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    instance = get_object_or_404(DocumentNature, pk=type_id, est_acte=True) if type_id else DocumentNature(est_acte=True)
    formulaire = TypeActeForm(request.POST, instance=instance)
    if not formulaire.is_valid():
        return JsonResponse({"success": False, "errors": formulaire.errors}, status=400)
    try:
        with transaction.atomic():
            if not type_id:
                types = _types_actes_verrouilles()
                _enregistrer_classement(types)
                formulaire.instance.ordre_affichage = len(types) + 1
            formulaire.save()
    except IntegrityError:
        return JsonResponse({"success": False, "error": "Un type portant ce nom existe déjà."}, status=400)
    return JsonResponse({"success": True})

