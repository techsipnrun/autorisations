"""Contrôles et corrections des références ; aucune écriture ou suppression NAS."""
import hashlib
from contextlib import closing
import logging
import ntpath
import stat
from types import SimpleNamespace

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
import smbclient
from smbprotocol.exceptions import SMBException

from autorisations.models.models_documents import Document, DossierDocument
from autorisations.models.models_generation import DocumentGeneration
from .history import read_generated_document
from .output import DocumentOutputError, dev_nas_root, _relative, _assert_directory, _missing, resolve_destination

logger = logging.getLogger(__name__)


def directory_path(relative):
    root = dev_nas_root()
    try:
        _assert_directory(root)
    except (OSError, SMBException) as exc:
        raise DocumentOutputError('La racine NAS dev est inaccessible.') from exc
    parent = root
    for part in _relative(relative):
        parent = ntpath.join(parent, part)
        _assert_directory(parent)
    return parent


def list_word_files(relative):
    parent = directory_path(relative)
    # scandir réutilisé par dossier : pas une requête réseau par ligne d'historique.
    with closing(smbclient.scandir(parent)) as entries:
        return sorted((entry.name for entry in entries if entry.name.lower().endswith('.docx')
                       and entry.is_file(follow_symlinks=False)), key=str.casefold)


def check_files(rows):
    folders, result = {}, []
    for row in rows:
        folder = row.id_document.emplacement
        if folder not in folders:
            try:
                folders[folder] = ('ok', {name.casefold() for name in list_word_files(folder)})
            except (OSError, SMBException) as exc:
                folders[folder] = ('missing' if _missing(exc) else 'unknown', set())
                if not _missing(exc):
                    logger.exception('Vérification NAS impossible : %s', folder)
            except (DocumentOutputError, ValueError):
                logger.exception('Chemin de génération non vérifiable : %s', folder)
                folders[folder] = ('unknown', set())
        state, names = folders[folder]
        found = row.id_document.titre.casefold() in names
        result.append({'id': row.pk, 'state': ('found' if found else 'missing') if state == 'ok' else state})
    return result


def candidate_folders(generation, dossier):
    folders = [generation.id_document.emplacement]
    if generation.id_template_id:
        try:
            _, parts, _ = resolve_destination(generation.id_template, dossier)
            current = '/'.join(parts) + '/'
            if current not in folders:
                folders.append(current)
        except (DocumentOutputError, ValidationError, ValueError, KeyError):
            pass
    return folders


def candidates(generation, dossier):
    result = []
    for folder in candidate_folders(generation, dossier):
        try:
            result.append({'destination': folder, 'files': list_word_files(folder)})
        except (OSError, SMBException, DocumentOutputError, ValueError):
            result.append({'destination': folder, 'files': [], 'error': 'Dossier introuvable ou inaccessible.'})
    return result


def ensure_missing(generation):
    if check_files([generation])[0]['state'] != 'missing':
        raise DocumentOutputError('Le fichier existe encore ou sa présence ne peut pas être vérifiée. Actualisez la vérification.')


def other_uses(document, generation=None, dossier=None):
    for relation in document._meta.related_objects:
        query = relation.related_model._base_manager.filter(**{relation.field.name: document})
        if generation is not None and relation.related_model is DocumentGeneration:
            query = query.exclude(pk=generation.pk)
        if dossier is not None and relation.related_model is DossierDocument:
            query = query.exclude(id_dossier=dossier)
        if query.exists():
            return True
    return False


def remove_from_history(dossier, generation_id):
    with transaction.atomic():
        generation = DocumentGeneration.objects.select_for_update().get(pk=generation_id, id_dossier=dossier)
        document = Document.objects.select_for_update().get(pk=generation.id_document_id)
        generation.id_document = document
        ensure_missing(generation)
        generation.delete()
        DossierDocument.objects.filter(id_dossier=dossier, id_document=document).delete()
        retained = other_uses(document)
        if not retained:
            document.delete()
        return retained


def reassociate(dossier, generation_id, user, destination, filename):
    with transaction.atomic():
        # Le template est nullable : éviter un LEFT JOIN sous FOR UPDATE,
        # que PostgreSQL refuse de verrouiller du côté nullable.
        generation = DocumentGeneration.objects.select_for_update().get(pk=generation_id, id_dossier=dossier)
        document = Document.objects.select_for_update().get(pk=generation.id_document_id)
        generation.id_document = document
        ensure_missing(generation)
        if destination not in candidate_folders(generation, dossier) or filename not in list_word_files(destination):
            raise DocumentOutputError('Sélectionnez un fichier Word présent dans une destination proposée.')
        if other_uses(document, generation, dossier):
            raise DocumentOutputError('Ce document est utilisé ailleurs dans AGIDA. Sa réassociation nécessite l’intervention d’un administrateur.')
        if Document.objects.filter(emplacement__iexact=destination, titre__iexact=filename).exclude(pk=document.pk).exists():
            raise DocumentOutputError('Ce fichier est déjà déclaré dans AGIDA.')
        with read_generated_document(SimpleNamespace(emplacement=destination, titre=filename)) as source:
            digest = hashlib.sha256(source.getvalue()).hexdigest()
        same_content = digest == generation.template_snapshot.get('document_sha256')
        event = {'date': timezone.now().isoformat(), 'user_id': user.pk, 'user': user.get_username(),
                 'old': {'destination': document.emplacement, 'filename': document.titre},
                 'new': {'destination': destination, 'filename': filename}, 'sha256': digest,
                 'matches_original': same_content}
        document.emplacement, document.titre = destination, filename
        # update_fields évite tout changement de nature/statut/numéro.
        document.save(update_fields=['emplacement', 'titre'])
        generation.file_corrections = [*generation.file_corrections, event]
        generation.save(update_fields=['file_corrections'])
        return same_content
