"""Numéros système : réservation explicite, récupération contrôlée et idempotence."""
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from autorisations.models.models_documents import DossierDocument
from autorisations.models.models_instruction import Dossier
from autorisations.models.models_avis import Avis
from autorisations.models.models_generation import DocumentNumberReservation
from instruction.templatetags.group_tags import est_concerne_par_le_dossier


def number_kind(template):
    if not template.id_nature_id:
        return None
    nature = template.id_nature
    if nature.nature.strip().casefold() == 'avis instance':
        return 'avis'
    return 'acte' if nature.est_acte else None


def scope_key(dossier, template):
    return f'{dossier.pk}:{template.pk}'


def session_state(request, dossier, template):
    states = request.session.get('document_number_states', {})
    key = scope_key(dossier, template)
    state = states.get(key) or {'request_key': str(uuid4())}
    state.pop('selected', None)  # Ne jamais restaurer le numéro d'une préparation précédente.
    states[key] = state
    request.session['document_number_states'] = dict(list(states.items())[-10:])
    return state


def selected_number(token, dossier, template, user):
    if not token:
        return None
    try:
        key = UUID(str(token))
    except (ValueError, TypeError):
        raise ValidationError('Sélection de numéro invalide.') from None
    reservation = DocumentNumberReservation.objects.filter(pk=key, id_dossier=dossier,
        id_template=template, id_nature_id=template.id_nature_id, user=user).first()
    if reservation is None:
        raise ValidationError('Ce numéro ne correspond pas à ce dossier, ce template ou cet utilisateur.')
    # Recontrôler les droits sur le dossier source d'une récupération.
    if reservation.origine == 'RECUPERE' and reservation.source not in {item['key'] for item in number_choices(dossier, template, user, deduplicate=False)}:
        raise ValidationError('Le numéro récupéré n’est plus accessible depuis les dossiers liés.')
    return reservation


def accessible_dossiers(dossier, user):
    rows = [dossier]
    if dossier.id_ensemble_dossiers_id:
        rows = list(Dossier.objects.filter(id_ensemble_dossiers_id=dossier.id_ensemble_dossiers_id))
    return [row for row in rows if user.is_superuser or est_concerne_par_le_dossier(user, row)]


def number_choices(dossier, template, user, *, deduplicate=True):
    kind = number_kind(template)
    if not kind:
        return []
    dossiers = {row.pk: row for row in accessible_dossiers(dossier, user)}
    choices = []
    # Documents déjà générés : leur nature documentaire reste Fichier généré,
    # leur série provient de la réservation.
    reservations = DocumentNumberReservation.objects.filter(id_nature_id=template.id_nature_id,
        id_dossier_id__in=dossiers, generations__isnull=False).distinct().order_by('-date')[:200]
    for row in reservations:
        choices.append({'key': f'r:{row.pk}', 'numero': row.numero, 'dossier': dossiers[row.id_dossier_id].numero})
    for link in DossierDocument.objects.filter(id_dossier_id__in=dossiers,
        id_document__id_nature_id=template.id_nature_id).select_related('id_document__id_nature')[:200]:
        numero = link.id_document.numero_effectif
        if numero:
            choices.append({'key': f'd:{link.id_document_id}:{link.id_dossier_id}', 'numero': numero,
                            'dossier': dossiers[link.id_dossier_id].numero})
    if kind == 'avis':
        for avis in Avis.objects.filter(Q(id_dossier_id__in=dossiers) | Q(dossieravis__id_dossier_id__in=dossiers)).distinct()[:200]:
            sources = [avis.id_dossier_id] if avis.id_dossier_id in dossiers else list(
                avis.dossieravis_set.filter(id_dossier_id__in=dossiers).values_list('id_dossier_id', flat=True))
            for source in sources:
                choices.append({'key': f'a:{avis.pk}:{source}', 'numero': str(avis.pk), 'dossier': dossiers[source].numero})
    # Plusieurs fichiers peuvent porter le même numéro ; une seule proposition par dossier.
    if not deduplicate:
        return choices
    unique = {}
    for item in choices:
        unique.setdefault((item['numero'], item['dossier']), item)
    return list(unique.values())


def choose_number(request, dossier, template, *, recover=None):
    if settings.ENVIRONMENT != 'dev' or not number_kind(template):
        raise ValidationError('Aucune numérotation disponible pour cette nature de template.')
    state = session_state(request, dossier, template)
    try:
        key = UUID(request.POST.get('request_key', ''))
    except (ValueError, TypeError):
        raise ValidationError('Clé de réservation invalide.') from None
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', [f'docgen:{key}'])
        existing = DocumentNumberReservation.objects.filter(pk=key).first()
        if existing:
            reservation = selected_number(key, dossier, template, request.user)
        else:
            if str(key) != state['request_key']:
                raise ValidationError('Cette préparation a changé. Rechargez la page.')
            if recover:
                candidate = next((item for item in number_choices(dossier, template, request.user) if item['key'] == recover), None)
                if not candidate:
                    raise ValidationError('Ce numéro n’est pas disponible pour ce dossier et cette nature.')
                numero = candidate['numero']
            else:
                with connection.cursor() as cursor:
                    if number_kind(template) == 'avis':
                        cursor.execute("SELECT nextval(pg_get_serial_sequence('avis.avis','id'))")
                    else:
                        if template.id_nature.numerotation_manuelle:
                            raise ValidationError('Cette nature utilise une numérotation manuelle : récupérez un numéro existant.')
                        cursor.execute('SELECT generation.prochain_numero_acte(%s,%s)',
                                       [template.id_nature_id, timezone.localdate().year])
                    numero = str(cursor.fetchone()[0])
            reservation = DocumentNumberReservation.objects.create(pk=key, id_template=template,
                id_nature_id=template.id_nature_id, id_dossier=dossier, user=request.user,
                numero=numero, origine='RECUPERE' if recover else 'GENERE', source=recover or '')
    state.update(request_key=str(uuid4()))
    states = request.session['document_number_states']
    states[scope_key(dossier, template)] = state
    request.session['document_number_states'] = states
    return reservation, state
