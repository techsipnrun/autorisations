import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from autorisations.models.models_instruction import Dossier
from instruction.templatetags.group_tags import est_concerne_par_le_dossier
from instruction.utils.document_utils import get_type_acte
from document_generation.services import manual_act as service

logger = logging.getLogger('ORM_DJANGO')


@login_required
@require_http_methods(['GET', 'POST'])
def prepare_act(request, num_dossier):
    if settings.ENVIRONMENT != 'dev':
        raise Http404
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    if not (request.user.is_superuser or est_concerne_par_le_dossier(request.user, dossier)):
        raise PermissionDenied
    try:
        service.require_instruction(dossier)
        if request.method == 'POST':
            if request.POST.get('confirmed') != '1':
                raise ValidationError('Confirmez cette action avant de poursuivre.')
            action = request.POST.get('action')
            if action == 'cancel':
                service.cancel_preparation(dossier, request.POST.get('preparation'))
            elif action in ('reserve', 'recover', 'manual'):
                nature = get_type_acte(request.POST.get('nature'), nouveau=True)
                if nature is None:
                    raise ValidationError('Sélectionnez une nature d’acte active.')
                source = request.POST.get('source') if action == 'recover' else None
                if action == 'recover' and not source:
                    raise ValidationError('Sélectionnez un numéro à récupérer.')
                service.select_preparation(dossier, nature, request.user, request.POST.get('request_key'), recover=source,
                    manual=request.POST.get('numero','') if action=='manual' else None)
            else:
                raise ValidationError('Action inconnue.')
            logger.info('[DOSSIER %s] Préparation acte manuel action=%s user=%s nature=%s réservation=%s',
                        dossier.numero, action, request.user.pk, request.POST.get('nature'),
                        request.POST.get('preparation') or request.POST.get('request_key'))
        if request.method == 'GET' and request.GET.get('nature'):
            nature = get_type_acte(request.GET['nature'], nouveau=True)
            if nature is None:
                raise ValidationError('Nature d’acte indisponible.')
            unique = {}
            for item in service.choices(dossier, nature, request.user):
                unique.setdefault((item['numero'], item['dossier']), {**item, 'display': nature.formater_numero(item['numero'])})
            response = JsonResponse({'choices': list(unique.values())})
        else:
            response = JsonResponse(service.state(dossier, request.user))
    except ValidationError as error:
        response = JsonResponse({'error': ' '.join(error.messages)}, status=409)
    except DatabaseError:
        logger.exception('Préparation manuelle indisponible dossier=%s user=%s', dossier.pk, request.user.pk)
        response = JsonResponse({'error': 'Préparation indisponible. Vérifiez les scripts DEV 0026 et 0028 et les droits BDD (0099).'}, status=503)
    response['Cache-Control'] = 'private, no-store'
    return response
