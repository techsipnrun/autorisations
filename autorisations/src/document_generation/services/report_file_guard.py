"""Reconnaissance des fichiers générés sélectionnés comme projets de Rapport CA."""
import ntpath
from django.core.exceptions import ValidationError
from autorisations.models.models_generation import DocumentGeneration


def generated_report_files(dossier):
    work = ntpath.normpath(ntpath.join(dossier.emplacement, 'Work')).casefold()
    rows = DocumentGeneration.objects.filter(id_dossier=dossier).select_related(
        'id_document', 'id_numero__id_nature', 'id_template__id_nature').defer(
        'context_snapshot', 'file_corrections', 'circuit_events')
    result = []
    for row in rows:
        if ntpath.normpath(row.id_document.emplacement).casefold() != work:
            continue
        if row.id_numero_id:
            nature = row.id_numero.id_nature.nature
        elif 'nature_cible' in row.template_snapshot:
            nature = row.template_snapshot['nature_cible']
        else:
            nature = row.id_template.id_nature.nature if row.id_template and row.id_template.id_nature else None
        # Sans nature cible connue, conserver le parcours manuel.
        if nature:
            result.append({'filename': row.id_document.titre, 'nature': nature,
                           'is_report': nature.casefold() == 'rapport ca'})
    return result


def validate_generated_report(dossier, filename):
    matches = [item for item in generated_report_files(dossier)
               if item['filename'].casefold() == filename.casefold()]
    if any(not item['is_report'] for item in matches):
        raise ValidationError('Ce fichier a été généré pour une autre nature. Le projet de Rapport du CA doit provenir d’un modèle de nature Rapport CA, ou être un fichier rédigé manuellement.')
