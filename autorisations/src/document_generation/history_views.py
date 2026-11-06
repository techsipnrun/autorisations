"""API de l'historique : mêmes droits dossier et restriction dev que la génération."""
import logging

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from autorisations.models.models_generation import DocumentGeneration
from .views import _dossier_context
from .services.output import DocumentOutputError
from .services.history_files import check_files, candidates, remove_from_history, reassociate
from .services.act_file_guard import act_file_status, act_file_provenance
from .services.history import history_queryset

logger = logging.getLogger(__name__)


@login_required
@require_GET
def act_status(request, num_dossier):
    dossier = _dossier_context(request, num_dossier)
    def operation():
        return {**act_file_status(dossier), 'recognized_files': act_file_provenance(dossier)}
    response = api_result(operation)
    response['Cache-Control'] = 'private, no-store'
    return response


def api_result(operation):
    try:
        return JsonResponse(operation())
    except DocumentGeneration.DoesNotExist:
        raise Http404 from None
    except DocumentOutputError as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    except DatabaseError:
        logger.exception('Erreur BDD historique de génération')
        return JsonResponse({'error': 'Historique inaccessible. Vérifiez les scripts SQL dev jusqu’à 0019 et les droits BDD.'}, status=503)


@login_required
@require_GET
def status(request, num_dossier):
    dossier = _dossier_context(request, num_dossier)
    def operation():
        rows = list(history_queryset(dossier).select_related('id_document').only(
            'id', 'id_document__emplacement', 'id_document__titre'))
        return {'files': check_files(rows)}
    return api_result(operation)


@login_required
@require_GET
def choices(request, num_dossier, generation_id):
    dossier = _dossier_context(request, num_dossier)
    def operation():
        generation = get_object_or_404(DocumentGeneration.objects.select_related('id_document', 'id_template'),
                                       pk=generation_id, id_dossier=dossier)
        return {'folders': candidates(generation, dossier)}
    return api_result(operation)


@login_required
@require_POST
def remove(request, num_dossier, generation_id):
    dossier = _dossier_context(request, num_dossier)
    def operation():
        retained = remove_from_history(dossier, generation_id)
        return {'message': 'Génération supprimée de l’historique. Aucun fichier NAS n’a été supprimé.'
                + (' Le document est conservé car il est utilisé ailleurs dans AGIDA.' if retained else '')}
    return api_result(operation)


@login_required
@require_POST
def relink(request, num_dossier, generation_id):
    dossier = _dossier_context(request, num_dossier)
    def operation():
        destination = request.POST.get('destination', '')
        filename = request.POST.get('filename', '')
        same = reassociate(dossier, generation_id, request.user, destination, filename)
        return {'filename': filename, 'destination': destination,
                'message': 'Fichier associé.' if same else 'Fichier associé. Son contenu diffère du document généré à l’origine.'}
    return api_result(operation)
