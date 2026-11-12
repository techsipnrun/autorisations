"""Préparation anticipée d’un acte manuel, exclusivement en DEV."""
from types import SimpleNamespace
from uuid import UUID
import ntpath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from autorisations.models.models_documents import Document, DossierDocument
from autorisations.models.models_generation import ManualActPreparation, DocumentTemplate
from autorisations.models.models_instruction import Dossier
from instruction.utils.document_utils import get_types_actes_selectionnables
from instruction.templatetags.group_tags import est_concerne_par_le_dossier
from .numbers import accessible_dossiers, number_choices


def proxy(nature):
    return SimpleNamespace(id_nature_id=nature.pk, id_nature=nature)


def active_preparation(dossier):
    if settings.ENVIRONMENT != 'dev':
        return None
    return ManualActPreparation.objects.filter(id_dossier=dossier, etat='ACTIVE').first()


def choices(dossier, nature, user):
    result = number_choices(dossier, proxy(nature), user, deduplicate=False)
    allowed = {row.pk: row for row in accessible_dossiers(dossier, user)}
    for row in ManualActPreparation.objects.filter(id_dossier_id__in=allowed, id_nature=nature, etat='UTILISE').order_by('-date')[:200]:
        result.append({'key': f'm:{row.pk}', 'numero': row.numero, 'dossier': allowed[row.id_dossier_id].numero})
    # Conserver les clés de toutes les sources pour la validation des POST.
    return result


def state(dossier, user):
    natures = list(get_types_actes_selectionnables())
    templates = list(DocumentTemplate.objects.filter(actif=True, rapport_validation__valide=True).filter(
        Q(demarches=dossier.id_demarche_id) | Q(demarches__isnull=True)).distinct())
    templates = [template for template in templates if not template.erreurs_configuration()]
    options = []
    for nature in natures:
        matching = [template for template in templates if template.id_nature_id == nature.pk]
        url = reverse('document_generation:dossier_generation', args=[dossier.numero]) + f'?demarche={dossier.id_demarche_id}'
        if len(matching) == 1:
            url += f'&template={matching[0].pk}'
        options.append({'id': nature.pk, 'label': nature.nature, 'automatic': not nature.numerotation_manuelle,
                        'can_generate': bool(matching), 'url': url})
    current = active_preparation(dossier)
    preparation = None
    if current:
        nature = current.id_nature
        used = sorted({item['dossier'] for item in choices(dossier, nature, user) if item['numero'] == current.numero}) if current.origine == 'RECUPERE' else []
        preparation = {'id': str(current.pk), 'nature_id': nature.pk, 'nature': nature.nature,
                       'numero': current.numero, 'display': nature.formater_numero(current.numero),
                       'origin': current.origine, 'dossiers': used}
    return {'natures': options, 'preparation': preparation}


def require_instruction(dossier):
    if getattr(dossier.id_etape_dossier, 'etape', None) != 'En instruction':
        raise ValidationError('Le dossier n’est plus en instruction. Rechargez la page.')


def select_preparation(dossier, nature, user, key, recover=None, manual=None):
    if settings.ENVIRONMENT != 'dev':
        raise ValidationError('Fonctionnalité disponible uniquement en développement.')
    if not nature.est_acte or not nature.actif:
        raise ValidationError('Sélectionnez une nature d’acte active.')
    if manual is not None:
        manual = manual.strip()
        if (not nature.numerotation_manuelle or not manual or len(manual)>150
                or any(ord(char)<32 or char in '\\:*?"<>|' for char in manual)):
            raise ValidationError('Saisissez une référence valide de 150 caractères maximum. Les / et le texte sont autorisés.')
    try:
        key = UUID(str(key))
    except (ValueError, TypeError):
        raise ValidationError('Clé de préparation invalide.') from None
    with transaction.atomic():
        locked = Dossier.objects.select_for_update().get(pk=dossier.pk)
        require_instruction(locked)
        existing = ManualActPreparation.objects.filter(pk=key).first()
        if existing:
            if (existing.id_dossier_id != dossier.pk or existing.id_nature_id != nature.pk
                    or existing.user_id != user.pk or existing.etat != 'ACTIVE'):
                raise ValidationError('Cette préparation a changé. Rechargez la page.')
            return existing
        if active_preparation(dossier):
            raise ValidationError('Un numéro est déjà préparé pour ce dossier. Rechargez la page.')
        if manual is not None:
            numero = manual
        elif recover:
            candidate = next((item for item in choices(dossier, nature, user) if item['key'] == recover), None)
            if not candidate:
                raise ValidationError('Ce numéro n’est pas accessible pour ce dossier et cette nature.')
            numero = candidate['numero']
        else:
            if nature.numerotation_manuelle:
                raise ValidationError('Cette nature utilise une référence libre : récupérez un numéro existant ou utilisez le circuit manuel habituel.')
            with connection.cursor() as cursor:
                cursor.execute('SELECT generation.prochain_numero_acte(%s,%s)', [nature.pk, timezone.localdate().year])
                numero = str(cursor.fetchone()[0])
        return ManualActPreparation.objects.create(pk=key, id_dossier=dossier, id_nature=nature,
            user=user, numero=numero, origine='SAISI' if manual is not None else 'RECUPERE' if recover else 'GENERE', source=recover or '')


def cancel_preparation(dossier, token):
    if settings.ENVIRONMENT != 'dev':
        raise ValidationError('Fonctionnalité disponible uniquement en développement.')
    with transaction.atomic():
        locked = Dossier.objects.select_for_update().get(pk=dossier.pk)
        require_instruction(locked)
        current = active_preparation(dossier)
        if current is None:
            return
        if str(current.pk) != str(token):
            raise ValidationError('La préparation a changé. Rechargez la page.')
        current.etat, current.date_fin = 'ABANDONNE', timezone.now()
        current.save(update_fields=['etat', 'date_fin'])


def validate_transition(request, dossier):
    current = active_preparation(dossier)
    token = request.POST.get('manual_preparation', '')
    if current is None:
        if token:
            raise ValidationError('Cette préparation n’est plus active. Rechargez la page.')
        return None
    if request.POST.get('nature_document') not in (str(current.id_nature_id), current.id_nature.nature):
        return None  # La réservation ne concerne pas la nature sélectionnée.
    if not (request.user.is_superuser or est_concerne_par_le_dossier(request.user, dossier)):
        raise ValidationError('Vous n’êtes pas autorisé à utiliser le numéro préparé pour ce dossier.')
    require_instruction(dossier)
    if str(current.pk) != token:
        raise ValidationError('Un numéro est préparé pour ce dossier. Rechargez la page pour l’utiliser.')
    if request.POST.get('projet_acte_identique') == 'on':
        raise ValidationError('Le numéro préparé remplace le choix de partage avec un autre dossier.')
    filename = request.POST.get('piece_jointe_work', '')
    if filename and ntpath.basename(filename) != filename:
        raise ValidationError('Sélectionnez un fichier du dossier Work.')
    generated = getattr(request, '_generated_act', None)
    if generated is not None and generated.id_numero.numero != current.numero:
        raise ValidationError('Le fichier généré ne porte pas le numéro préparé. Annulez la préparation ou choisissez le bon fichier.')
    if current.origine == 'RECUPERE' and not any(item['key'] == current.source and item['numero'] == current.numero for item in choices(dossier, current.id_nature, request.user)):
        raise ValidationError('Le numéro récupéré n’est plus accessible. Annulez la préparation puis récupérez à nouveau le numéro.')
    return current


def integrate_preparation(request, dossier, filename, nature, statut, file_format, generated=None):
    current = validate_transition(request, dossier)
    if current is None:
        return generated
    with transaction.atomic():
        locked = Dossier.objects.select_for_update().get(pk=dossier.pk)
        require_instruction(locked)
        current = ManualActPreparation.objects.select_for_update().get(pk=current.pk, etat='ACTIVE')
        if current.id_nature_id != nature.pk:
            raise ValidationError('Nature incompatible avec le numéro préparé.')
        work = Document.normaliser_emplacement(f'{dossier.emplacement}/Work/')
        document = generated or Document.objects.filter(emplacement=work, titre=filename).first()
        if document:
            if (document.id_nature_id != nature.pk or document.numero_effectif != current.numero
                    or document.url_ds or document.url_dm or document.publie_au_raa):
                raise ValidationError('Ce fichier est déjà déclaré pour un autre acte ou a été diffusé. Choisissez le bon projet.')
            if document.id_statut and document.id_statut.statut in ('Envoyé', 'À envoyer'):
                raise ValidationError('Ce fichier est déjà dans le circuit de diffusion.')
        else:
            number_field = 'numero_reference' if nature.numerotation_manuelle else 'numero'
            if Document.objects.filter(emplacement=work, id_nature=nature, **{number_field: current.numero}).exists():
                raise ValidationError('Un autre projet porte déjà ce numéro dans Work. Sélectionnez ce projet ou préparez un nouveau numéro.')
            document = Document(emplacement=work, titre=filename, id_nature=nature,
                                **{number_field: current.numero})
            if nature.numerotation_manuelle and current.source.startswith('d:'):
                source = Document.objects.select_for_update().get(pk=int(current.source.split(':')[1]))
                if source.id_nature_id != nature.pk or source.numero_effectif != current.numero:
                    raise ValidationError('La référence de l’acte source a changé. Récupérez à nouveau le numéro.')
                document.id_document_reference_id = source.id_document_reference_id or source.pk
        document.id_statut, document.id_format = statut, file_format
        document.description = f'{nature.nature} du dossier {dossier.numero}'
        # Numéro déjà fourni, même nature : Document.save ne sollicite pas le compteur.
        document.save()
        DossierDocument.objects.get_or_create(id_dossier=dossier, id_document=document)
        current.id_document = document
        current.save(update_fields=['id_document'])
        return document


def finish_instruction(dossier):
    """Appelé dans la transaction du changement d’étape, sans recycler le numéro."""
    if settings.ENVIRONMENT != 'dev':
        return
    ManualActPreparation.objects.filter(id_dossier=dossier, etat='ACTIVE', id_document__isnull=False).update(
        etat='UTILISE', date_fin=timezone.now())
    ManualActPreparation.objects.filter(id_dossier=dossier, etat='ACTIVE').update(etat='ABANDONNE', date_fin=timezone.now())
