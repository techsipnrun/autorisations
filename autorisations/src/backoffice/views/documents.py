"""Catalogue et vérification des templates, réservés au back-office dev."""

from io import BytesIO
from pathlib import Path, PurePosixPath

from dotenv import dotenv_values

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, OperationalError, ProgrammingError, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from autorisations.models.models_generation import DocumentTemplate
from autorisations.models.models_documents import DocumentNature
from autorisations.models.models_instruction import Demarche


def verifier_acces(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette fonctionnalité est réservée aux administrateurs.")
    if settings.ENVIRONMENT != "dev":
        raise Http404


def serialiser(template):
    configuration_errors = template.erreurs_configuration()
    return {
        "id": template.pk, "nom": template.nom,
        "nature": template.id_nature.nature if template.id_nature_id else "", "chemin_relatif": template.chemin_relatif,
        "actif": template.actif,
        "destination_relative": template.destination_relative,
        "nom_fichier": template.nom_fichier,
        "id_nature": template.id_nature_id,
        "demarche_ids": [demarche.pk for demarche in template.demarches.all()],
        "demarches": [demarche.type for demarche in template.demarches.all()],
        "configuration_complete": not configuration_errors,
        "configuration_errors": configuration_errors,
        "rapport": template.rapport_validation,
        "date_verification": template.date_verification.isoformat() if template.date_verification else None,
        "verification_url": reverse("back_office_template_verifier", args=[template.pk]),
        "edition_url": reverse("back_office_template_enregistrer", args=[template.pk]),
        "telechargement_url": reverse("back_office_template_telecharger", args=[template.pk]),
    }


def erreur_schema():
    return JsonResponse({"erreur": "Tables de génération inaccessibles. Vérifiez les scripts dev jusqu’à 0013_balise_liste_repetable.sql et les droits."}, status=503)


@login_required
@require_GET
def telecharger(request, template_id):
    verifier_acces(request)
    from document_generation.services.template_path import read_template_bytes, TemplatePathError
    template = get_object_or_404(DocumentTemplate, pk=template_id)
    try:
        content = read_template_bytes(template)
    except TemplatePathError as exc:
        raise Http404(str(exc)) from exc
    response = FileResponse(BytesIO(content), as_attachment=True,
                            filename=PurePosixPath(template.chemin_relatif).name,
                            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_GET
def catalogue(request):
    verifier_acces(request)
    try:
        templates = DocumentTemplate.objects.select_related("id_nature").prefetch_related("demarches")
        return JsonResponse({"templates": [serialiser(template) for template in templates]})
    except (ProgrammingError, OperationalError):
        return erreur_schema()


@login_required
@require_POST
def verifier_tous(request):
    verifier_acces(request)
    from document_generation.services.verification import TemplateVerificationService
    try:
        # Inclut aussi les modèles inactifs. Chaque modèle a sa transaction :
        # un rapport invalide ne bloque pas les modèles suivants.
        ids = list(DocumentTemplate.objects.order_by("pk").values_list("pk", flat=True))
        service = TemplateVerificationService()
        for template_id in ids:
            try:
                service.verify(template_id)
            except DocumentTemplate.DoesNotExist:
                continue  # Fiche supprimée pendant la vérification du catalogue.
        templates = DocumentTemplate.objects.select_related("id_nature").prefetch_related("demarches")
        return JsonResponse({"templates": [serialiser(template) for template in templates]})
    except (ProgrammingError, OperationalError):
        return erreur_schema()


@login_required
@require_POST
def verifier(request, template_id):
    verifier_acces(request)
    from document_generation.services.verification import TemplateVerificationService
    try:
        get_object_or_404(DocumentTemplate, pk=template_id)
        TemplateVerificationService().verify(template_id)
        template = DocumentTemplate.objects.select_related("id_nature").prefetch_related("demarches").get(pk=template_id)
        return JsonResponse({"template": serialiser(template)})
    except (ProgrammingError, OperationalError):
        return erreur_schema()


@login_required
@require_GET
def options_edition(request):
    verifier_acces(request)
    nas_root = getattr(settings, "NAS_ROOT", None) or dotenv_values(
        Path(settings.BASE_DIR) / f".env.{settings.ENVIRONMENT}"
    ).get("NAS_ROOT", "")
    if nas_root:
        nas_root = nas_root.strip().replace("\\", "/")
        prefix = "//" if nas_root.startswith("//") else "/" if nas_root.startswith("/") else ""
        nas_root = prefix + "/".join(part for part in nas_root.split("/") if part) + "/"
    today = timezone.localdate()
    return JsonResponse({
        "nas_root": nas_root,
        "filename_date": {"year": str(today.year), "day": today.strftime("%d-%m-%y")},
        "natures": [{"id": nature.pk, "nom": nature.nature} for nature in DocumentNature.objects.order_by("nature")],
        "demarches": [{"id": demarche.pk, "nom": demarche.type} for demarche in Demarche.objects.order_by("type", "numero")],
    })


@login_required
@require_POST
def enregistrer(request, template_id=None):
    verifier_acces(request)
    from document_generation.forms import DocumentTemplateForm

    try:
        with transaction.atomic():
            creation = template_id is None
            template = DocumentTemplate() if creation else get_object_or_404(DocumentTemplate.objects.select_for_update(), pk=template_id)
            form = DocumentTemplateForm(request.POST, instance=template)
            if not form.is_valid():
                return JsonResponse({"erreur": "Vérifiez les champs du modèle.", "fields": form.errors.get_json_data()}, status=400)
            if creation or form.has_changed():
                template = form.save(commit=False)
                template.rapport_validation = None
                template.date_verification = None
                template.save()
                form.save_m2m()
            from document_generation.services.verification import TemplateVerificationService
            TemplateVerificationService().verify(template.pk)
        template = DocumentTemplate.objects.select_related("id_nature").prefetch_related("demarches").get(pk=template.pk)
        return JsonResponse({"template": serialiser(template)}, status=201 if creation else 200)
    except IntegrityError:
        return JsonResponse({"erreur": "L’enregistrement entre en conflit avec une donnée existante ou une association est invalide."}, status=400)
    except (ProgrammingError, OperationalError):
        return erreur_schema()
