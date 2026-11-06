"""Lecture seule : intégrité des fichiers générés numérotés avant choix d'un acte."""
from django.conf import settings
from django.utils import timezone
import ntpath

from autorisations.models.models_generation import DocumentGeneration
from .history_files import check_files


def act_file_status(dossier):
    if settings.ENVIRONMENT != 'dev':
        return {'missing': 0, 'unknown': 0, 'blocked': False}
    # Pas de limite à 50 : un ancien fichier absent doit aussi être réparé.
    # La réservation conserve la nature lors de la génération, même si le
    # template a changé depuis. Avis Instance explicitement hors périmètre.
    rows = list(DocumentGeneration.objects.filter(
        id_dossier=dossier, id_numero__isnull=False,
        id_numero__id_nature__est_acte=True,
    ).exclude(id_numero__numero='').exclude(
        id_numero__id_nature__nature__iexact='Avis Instance',
    ).select_related('id_document').only('id', 'id_document__emplacement', 'id_document__titre'))
    files = check_files(rows)
    missing = sum(item['state'] == 'missing' for item in files)
    unknown = sum(item['state'] not in ('found', 'missing') for item in files)
    return {'missing': missing, 'unknown': unknown, 'blocked': bool(missing or unknown)}


def blocked_message(status):
    if status['unknown']:
        return 'Vérification des fichiers générés impossible. Vérifiez l’accès au NAS puis réessayez.'
    return ('Des fichiers générés numérotés sont introuvables. Retrouvez-les ou supprimez-les '
            'de l’historique des générations avant de sélectionner un projet d’acte.')


def act_file_provenance(dossier):
    """Métadonnées d'actes générés du Work de ce dossier, sans accès au NAS."""
    work = ntpath.normpath(ntpath.join(dossier.emplacement, 'Work')).casefold()
    rows = DocumentGeneration.objects.filter(
        id_dossier=dossier, id_numero__isnull=False, id_numero__id_nature__est_acte=True,
    ).exclude(id_numero__numero='').exclude(
        id_numero__id_nature__nature__iexact='Avis Instance',
    ).select_related('id_document', 'id_numero__id_nature', 'user').defer(
        'context_snapshot', 'template_snapshot', 'file_corrections')
    result = []
    for row in rows:
        if ntpath.normpath(row.id_document.emplacement).casefold() != work:
            continue
        nature = row.id_numero.id_nature
        title = {'arrêté directeur': 'Projet d’arrêté', 'délibération ca': 'Projet de délibération CA',
                 'avis simple': 'Projet d’avis simple', 'avis conforme': 'Projet d’avis conforme'}.get(
                     nature.nature.casefold(), f'Projet — {nature.nature}')
        author = 'Utilisateur supprimé'
        if row.user:
            author = ' '.join(part for part in (row.user.first_name, row.user.last_name.upper()) if part).strip() or row.user.get_username()
        date = timezone.localtime(row.date).strftime('%d/%m/%Y')
        number = f'{nature.prefixe_numero}{row.id_numero.numero}'
        result.append({'filename': row.id_document.titre, 'nature_id': nature.pk,
                       'document_id': row.id_document_id, 'numero': row.id_numero.numero,
                       'active': row.id_document.id_nature_id == nature.pk,
                       'replaceable': not (row.id_document.id_statut_id or row.id_document.publie_au_raa
                                           or row.id_document.url_ds or row.id_document.url_dm),
                       'nature': nature.nature,
                       'description': f'{title} {number} généré par {author} le {date}'})
    return result
