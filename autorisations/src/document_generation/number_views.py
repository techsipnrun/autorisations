import logging
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from .views import _work_context
from .services.numbers import number_choices, choose_number

logger = logging.getLogger(__name__)


@login_required
@require_GET
def choices(request, num_dossier, template_id):
    dossier, template = _work_context(request, num_dossier, template_id)
    try:
        items = number_choices(dossier, template, request.user)
        nature = template.id_nature.nature if template.id_nature_id else 'Document'
        for item in items:
            item['nature'] = nature
        return JsonResponse({'choices': items})
    except DatabaseError:
        logger.exception('Liste des numéros inaccessible dossier=%s template=%s', dossier.pk, template.pk)
        return JsonResponse({'error':'Numéros indisponibles. Vérifiez le script SQL dev 0017.'}, status=503)


@login_required
@require_POST
def select(request, num_dossier, template_id):
    dossier, template = _work_context(request, num_dossier, template_id)
    try:
        action = request.POST.get('action')
        if action not in ('reserve','recover') or (action == 'recover' and not request.POST.get('choice')):
            raise ValidationError('Choisissez Générer le numéro ou Récupérer le numéro.')
        reservation, state = choose_number(request, dossier, template,
            recover=request.POST.get('choice') if action == 'recover' else None)
        return JsonResponse({'numero':reservation.numero,'selection':str(reservation.pk),'request_key':state['request_key']})
    except ValidationError as exc:
        return JsonResponse({'error':' '.join(exc.messages)}, status=400)
    except DatabaseError:
        logger.exception('Réservation impossible dossier=%s template=%s user=%s', dossier.pk, template.pk, request.user.pk)
        return JsonResponse({'error':'Réservation impossible. Vérifiez le script SQL dev 0017 et les droits.'}, status=503)
