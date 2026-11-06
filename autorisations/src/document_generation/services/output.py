"""Écriture exclusive d'un DOCX sur le NAS dev, sans création en BDD."""

import logging
import ntpath
from pathlib import Path
import re
import stat
import errno

from django.conf import settings
from django.core.exceptions import ValidationError
from dotenv import dotenv_values
import smbclient
from smbprotocol.exceptions import SMBException
from smbprotocol.header import NtStatus

from autorisations.models.models_generation import valider_destination_relative
from .filename import resolve_filename

logger = logging.getLogger(__name__)


class DocumentOutputError(Exception):
    pass


def _collision(exc):
    return (isinstance(exc, FileExistsError) or getattr(exc, 'errno', None) == errno.EEXIST
            or getattr(exc, 'ntstatus', getattr(exc, 'status', None)) == NtStatus.STATUS_OBJECT_NAME_COLLISION)


def _missing(exc):
    return (isinstance(exc, FileNotFoundError) or getattr(exc, 'errno', None) == errno.ENOENT
            or getattr(exc, 'ntstatus', getattr(exc, 'status', None)) in (
                NtStatus.STATUS_OBJECT_NAME_NOT_FOUND, NtStatus.STATUS_OBJECT_PATH_NOT_FOUND, NtStatus.STATUS_NOT_FOUND))


def _unc(value):
    value = (value or '').strip().replace('/', '\\')
    if not value.startswith('\\\\'):
        raise DocumentOutputError("La racine NAS dev est invalide.")
    return '\\\\' + '\\'.join(part for part in value.split('\\') if part) + '\\'


def _relative(value):
    if not value or value.startswith(('/', '\\')) or ntpath.splitdrive(value)[0]:
        raise DocumentOutputError("La destination doit rester relative au NAS dev.")
    parts = value.removesuffix('/').split('/')
    if any(part in ('', '.', '..') or part.endswith((' ', '.')) for part in parts) or re.search(r'[\\<>:"|?*\x00-\x1f{}]', value):
        raise DocumentOutputError("La destination du fichier généré est invalide.")
    return parts


def _assert_directory(path):
    info = smbclient.lstat(path)
    if getattr(info, 'st_file_attributes', 0) & 0x400:
        raise DocumentOutputError("La destination ne peut pas traverser un lien ou une redirection NAS.")
    if not stat.S_ISDIR(info.st_mode):
        raise DocumentOutputError("La destination configurée n'est pas un dossier.")


def dev_nas_root():
    if settings.ENVIRONMENT != 'dev':
        raise DocumentOutputError('Accès NAS réservé au développement.')
    root = _unc(dotenv_values(Path(settings.BASE_DIR) / '.env.dev').get('NAS_ROOT'))
    prod_root = dotenv_values(Path(settings.BASE_DIR) / '.env.prod').get('NAS_ROOT')
    if prod_root:
        prod_root = _unc(prod_root)
        try:
            common = ntpath.commonpath([root, prod_root]).rstrip('\\').casefold()
        except ValueError:
            common = None  # Partages distincts.
        if common in (root.rstrip('\\').casefold(), prod_root.rstrip('\\').casefold()):
            raise DocumentOutputError("Les racines NAS dev et production doivent être distinctes et séparées.")
    return root


def resolve_destination(template, dossier):
    valider_destination_relative(template.destination_relative)
    root = dev_nas_root()
    values = {'dossier.numero': str(dossier.numero), 'num_doss': str(dossier.numero)}
    pattern = template.destination_relative
    if '{dossier.emplacement}' in pattern:
        emplacement = dossier.emplacement or ''
        _relative(emplacement)
        values['dossier.emplacement'] = emplacement.rstrip('/') + '/'
        pattern = pattern.replace('{dossier.emplacement}/', '{dossier.emplacement}')
    relative = re.sub(r'\{([^{}]+)\}', lambda match: values[match.group(1)], pattern)
    parts = _relative(relative)
    folder = ntpath.join(root, *parts)
    if ntpath.commonpath([root, folder]).rstrip('\\').casefold() != root.rstrip('\\').casefold():
        raise DocumentOutputError("La destination doit rester sous la racine NAS dev.")
    return root, parts, folder


class DocumentOutputService:
    def save(self, buffer, template, dossier, *, filename_pattern=None, document_number=None):
        if settings.ENVIRONMENT != 'dev':
            raise DocumentOutputError("La génération de fichier est autorisée uniquement en dev.")
        folder = filename = name = None
        try:
            if template.erreurs_configuration():
                raise DocumentOutputError("La configuration du template est incomplète.")
            root, parts, folder = resolve_destination(template, dossier)
            filename = resolve_filename(filename_pattern if filename_pattern is not None else template.nom_fichier,
                                        dossier, document_number=document_number)
            _assert_directory(root)
            parent = root
            for part in parts:
                parent = ntpath.join(parent, part)
                try:
                    _assert_directory(parent)
                except (OSError, SMBException) as exc:
                    if not _missing(exc):
                        raise
                    try:
                        smbclient.mkdir(parent)
                    except (OSError, SMBException) as exc:
                        if not _collision(exc):
                            raise
                    _assert_directory(parent)
            stem, extension = ntpath.splitext(filename)
            data = buffer.getvalue()
            for number in range(1, 10001):
                name = filename if number == 1 else f'{stem}_{number}{extension}'
                if len(name) > 200:
                    raise DocumentOutputError("Le nom du fichier avec suffixe dépasse 200 caractères.")
                path = ntpath.join(folder, name)
                created = False
                completed = False
                try:
                    # Mode exclusif : aucune course entre un test d'existence et l'écriture.
                    with smbclient.open_file(path, mode='xb') as target:
                        created = True
                        written = target.write(data)
                        if written != len(data):
                            raise OSError("Écriture DOCX incomplète")
                    completed = True
                    return {'filename': name, 'destination': folder.replace('\\', '/') + '/',
                            'path': path, 'relative_destination': '/'.join(parts) + '/'}
                except (OSError, SMBException) as exc:
                    if not created and _collision(exc):
                        continue
                    raise
                finally:
                    if created and not completed:
                        try:
                            smbclient.remove(path)
                        except (OSError, SMBException):
                            logger.exception("Suppression du DOCX incomplet impossible : %s", path)
            raise DocumentOutputError("Trop de fichiers portent déjà ce nom dans la destination.")
        except DocumentOutputError as exc:
            if folder and filename:
                raise DocumentOutputError(f"Impossible de générer le fichier {name or filename} ici : {folder}. {exc}") from exc
            raise
        except (OSError, SMBException, ValueError, ValidationError) as exc:
            destination = f" {name or filename} ici : {folder}." if folder and filename else " sur le NAS dev."
            raise DocumentOutputError(f"Impossible de générer le fichier{destination} Vérifiez la destination et les droits d'accès.") from exc
