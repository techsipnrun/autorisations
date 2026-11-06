"""Historique du dossier et lecture des Word enregistrés sur le NAS dev."""
from io import BytesIO
import logging
import ntpath
import stat

from django.db import DatabaseError
from django.db.models import Q
import smbclient
from smbprotocol.exceptions import SMBException

from autorisations.models.models_generation import DocumentGeneration
from .output import DocumentOutputError, dev_nas_root, _relative, _assert_directory

logger = logging.getLogger(__name__)


def history_queryset(dossier):
    rows = DocumentGeneration.objects.filter(id_dossier=dossier)
    recent = rows.values('pk')[:50]
    # Les actes numérotés restent accessibles à la réparation même au-delà
    # des 50 générations récentes affichées habituellement.
    acts = (Q(id_numero__isnull=False, id_numero__id_nature__est_acte=True)
            & ~Q(id_numero__numero='') & ~Q(id_numero__id_nature__nature__iexact='Avis Instance'))
    return rows.filter(Q(pk__in=recent) | acts)


def dossier_history(dossier):
    try:
        rows = list(history_queryset(dossier).select_related(
            'id_document', 'user', 'id_numero__id_nature').defer('context_snapshot', 'file_corrections'))
        return {'generation_history': rows}
    except DatabaseError:
        logger.exception('Historique inaccessible dossier=%s', dossier.pk)
        return {'generation_history': [], 'generation_history_error':
                'Historique indisponible. Vérifiez les scripts SQL dev jusqu’à 0019.'}


def read_generated_document(document):
    try:
        root = dev_nas_root()
        parts = _relative(document.emplacement)
        filename = document.titre
        if not filename.lower().endswith('.docx') or _relative(filename) != [filename]:
            raise DocumentOutputError('Nom du document invalide.')
        parent = root
        _assert_directory(parent)
        for part in parts:
            parent = ntpath.join(parent, part)
            _assert_directory(parent)
        path = ntpath.join(parent, filename)
        info = smbclient.lstat(path)
        if getattr(info, 'st_file_attributes', 0) & 0x400 or not stat.S_ISREG(info.st_mode):
            raise DocumentOutputError('Le fichier ne peut pas être ouvert.')
        with smbclient.open_file(path, mode='rb', share_access='rwd') as source:
            return BytesIO(source.read())
    except (OSError, SMBException, ValueError) as exc:
        raise DocumentOutputError('Le fichier est introuvable ou inaccessible sur le NAS dev.') from exc
