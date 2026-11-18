"""Gestion du catalogue de balises, administrateurs et environnement dev seulement."""

import json
import logging
import re
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, ProgrammingError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from autorisations.models.models_generation import Balise, BaliseSourceChamp, DocumentTemplate, TemplateBalise
from autorisations.models.models_instruction import Champ, Demarche
from document_generation.forms import BaliseConfigurationForm
from document_generation.services.catalogue_sources import PROPERTY_LABELS, PROPERTY_DESCRIPTIONS, AVAILABLE_PROPERTIES, source_errors
from document_generation.services.catalogue_sources import PROPERTY_CATEGORIES, formulaire_type_error
from .documents import verifier_acces

logger = logging.getLogger(__name__)


def codes_utilises(template):
    """Inclure les codes identifiés par une analyse partielle non synchronisée."""
    detected = [row.code for row in template.balises_detectees.all()]
    report = getattr(template, 'rapport_validation', None) or {}
    return sorted(set(detected) | {row['code'] for row in report.get('balises', []) if row.get('code')})


def serialiser(balise):
    return {**{name: getattr(balise, name) for name in BaliseConfigurationForm.Meta.fields if name != 'id_template'},
            'id_template': balise.id_template_id,
            'template_nom': balise.id_template.nom if balise.id_template_id else '',
            'id': balise.pk, 'mode': balise.mode,
            'source': balise.source or (Balise.Source.MANUELLE if balise.mode == Balise.Mode.A_RENSEIGNER else Balise.Source.AGIDA),
            'source_propriete': balise.source_propriete or (balise.code if not balise.source and balise.mode == Balise.Mode.CONNUE else ''),
            'sources': [{'id_demarche': row.id_demarche_id, 'id_champ': row.id_champ_id,
                         'demarche': row.id_demarche.type, 'champ': row.id_champ.nom} for row in balise.sources_champs.all()],
            'erreurs': source_errors(balise)}


def erreur_schema():
    return JsonResponse({'erreur': 'Catalogue inaccessible. Exécutez manuellement les scripts jusqu’à 0021_perimetre_balises.sql et vérifiez les droits.'}, status=503)


@login_required
@require_GET
def catalogue(request):
    verifier_acces(request)
    try:
        rows = Balise.objects.prefetch_related('id_template', 'sources_champs__id_champ', 'sources_champs__id_demarche')
        templates = DocumentTemplate.objects.prefetch_related('demarches', 'balises_detectees').order_by('nom')
        return JsonResponse({'balises': [serialiser(row) for row in rows],
            'templates': [{'id': template.pk, 'nom': template.nom,
                           'demarche_ids': [row.pk for row in template.demarches.all()],
                           'balise_codes': codes_utilises(template)}
                          for template in templates],
            'proprietes': [{'code': code, 'nom': PROPERTY_LABELS.get(code, code), 'description': PROPERTY_DESCRIPTIONS.get(code, ''), 'categorie': PROPERTY_CATEGORIES[code]} for code in AVAILABLE_PROPERTIES],
            'types': [{'code': code, 'nom': label} for code, label in Balise.Type.choices if code not in ('SELECT', 'MULTISELECT')],
            'demarches': [{'id': row.pk, 'nom': row.type} for row in Demarche.objects.exclude(type__isnull=True).exclude(type='').order_by('type', 'numero')]})
    except (ProgrammingError, OperationalError):
        return erreur_schema()


@login_required
@require_GET
def champs(request, demarche_id):
    verifier_acces(request)
    get_object_or_404(Demarche, pk=demarche_id)
    rows = Champ.objects.filter(id_demarche_id=demarche_id).select_related('id_champ_type').order_by('nom', 'pk')
    return JsonResponse({'champs': [{'id': row.pk, 'nom': row.nom, 'type': row.id_champ_type.type,
        'erreurs_types': {kind: error for kind in Balise.Type.values
                          if (error := formulaire_type_error(row.id_champ_type.type, kind))}} for row in rows]})


@login_required
@require_POST
def supprimer(request, balise_id):
    verifier_acces(request)
    try:
        with transaction.atomic():
            balise = get_object_or_404(Balise.objects.select_for_update(), pk=balise_id)
            usages = TemplateBalise.objects.filter(code=balise.code)
            if balise.id_template_id:
                usages = usages.filter(id_template_id=balise.id_template_id)
            ids = list(usages.values_list('id_template_id', flat=True).distinct())
            partial = DocumentTemplate.objects.filter(rapport_validation__balises__contains=[{'code': balise.code}])
            if balise.id_template_id:
                partial = partial.filter(pk=balise.id_template_id)
            ids = sorted(set(ids) | set(partial.values_list('pk', flat=True)))
            # Conserver les balises détectées dans les Word : elles deviennent inconnues.
            TemplateBalise.objects.filter(id_balise=balise).update(id_balise=None)
            DocumentTemplate.objects.filter(pk__in=ids).update(rapport_validation=None, date_verification=None)
            balise.delete()
        return JsonResponse({'supprime': True, 'templates_concernes': len(ids)})
    except (ProgrammingError, OperationalError):
        return erreur_schema()


def valider_sources(raw, source, value_type=None):
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError
        def identifier(value):
            if not re.fullmatch(r'[1-9][0-9]*', str(value)):
                raise ValueError
            return int(value)
        pairs = [(identifier(row['id_demarche']), identifier(row['id_champ'])) for row in rows]
    except (ValueError, TypeError, KeyError):
        raise ValidationError('Les sources de formulaire sont invalides.') from None
    if source != Balise.Source.FORMULAIRE:
        if pairs:
            raise ValidationError('Cette origine ne peut pas contenir de sources de formulaire.')
        return []
    if not pairs:
        raise ValidationError('Ajoutez au moins une démarche et son champ de formulaire.')
    if len({demarche for demarche, _ in pairs}) != len(pairs):
        raise ValidationError('Une seule source est autorisée par démarche.')
    fields = Champ.objects.filter(pk__in=[champ for _, champ in pairs]).in_bulk()
    for demarche, champ in pairs:
        if champ not in fields or fields[champ].id_demarche_id != demarche:
            raise ValidationError('Un champ ne correspond pas à la démarche sélectionnée.')
        if value_type and fields[champ].id_champ_type_id:
            error = formulaire_type_error(fields[champ].id_champ_type.type, value_type)
            if error:
                raise ValidationError(f'« {fields[champ].nom} » : {error}')
    return pairs


@login_required
@require_POST
def enregistrer(request, balise_id=None):
    verifier_acces(request)
    try:
        with transaction.atomic():
            instance = get_object_or_404(Balise.objects.select_for_update(), pk=balise_id) if balise_id else Balise()
            form = BaliseConfigurationForm(request.POST, instance=instance)
            if not form.is_valid():
                return JsonResponse({'erreur': 'Vérifiez les champs de la balise.', 'fields': form.errors.get_json_data()}, status=400)
            pairs = valider_sources(request.POST.get('sources', '[]'), form.cleaned_data['source'], form.cleaned_data['type'])
            template = form.cleaned_data.get('id_template')
            if form.cleaned_data['source'] == Balise.Source.FORMULAIRE and template:
                allowed = set(template.demarches.values_list('pk', flat=True))
                if allowed and any(demarche not in allowed for demarche, _ in pairs):
                    raise ValidationError('Choisissez uniquement les démarches associées au template sélectionné.')
            balise = form.save()
            BaliseSourceChamp.objects.filter(id_balise=balise).delete()
            BaliseSourceChamp.objects.bulk_create([BaliseSourceChamp(id_balise=balise, id_demarche_id=d, id_champ_id=c) for d, c in pairs])
            impacted = TemplateBalise.objects.filter(code=balise.code)
            if balise.source != Balise.Source.AGIDA:
                impacted = impacted.filter(id_template_id=balise.id_template_id)
            template_ids = list(impacted.values_list('id_template_id', flat=True).distinct())
            if balise.id_template_id and balise.id_template_id not in template_ids:
                template_ids.append(balise.id_template_id)
            DocumentTemplate.objects.filter(pk__in=template_ids).update(rapport_validation=None, date_verification=None)
        # Le catalogue est enregistré avant les lectures NAS, qui peuvent échouer.
        from document_generation.services.verification import TemplateVerificationService
        warnings = []
        for template_id in template_ids:
            try:
                TemplateVerificationService().verify(template_id)
            except DocumentTemplate.DoesNotExist:
                continue
            except (OSError, ValueError, ValidationError, ProgrammingError, OperationalError):
                logger.exception('Réanalyse du template %s après édition de la balise %s', template_id, balise.pk)
                warnings.append(f'Balise enregistrée ; le template {template_id} devra être réanalysé.')
        balise = Balise.objects.prefetch_related('sources_champs__id_champ', 'sources_champs__id_demarche').get(pk=balise.pk)
        return JsonResponse({'balise': serialiser(balise), 'warnings': warnings})
    except ValidationError as exc:
        return JsonResponse({'erreur': ' '.join(exc.messages)}, status=400)
    except IntegrityError:
        return JsonResponse({'erreur': 'Ce code existe déjà dans ce périmètre, entre en conflit avec une balise AGIDA globale, ou une source est invalide.'}, status=400)
    except (ProgrammingError, OperationalError):
        return erreur_schema()
