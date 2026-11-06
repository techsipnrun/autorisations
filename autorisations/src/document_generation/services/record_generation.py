"""Enregistrement d'une génération définitive, avec compensation de l'écriture NAS."""
import hashlib
import json
import logging

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, transaction
import smbclient

from autorisations.models.models_documents import Document, DocumentNature, DocumentFormat, DossierDocument
from autorisations.models.models_generation import DocumentGeneration
from .output import DocumentOutputService, DocumentOutputError

logger = logging.getLogger(__name__)


class RecordGenerationService:
    def save(self, buffer, template, dossier, user, context, template_bytes, *, number_reservation=None, filename_pattern=None):
        if settings.ENVIRONMENT != 'dev':
            raise DocumentOutputError('La génération est disponible uniquement en dev.')
        # Vérifier le schéma et les référentiels avant de créer un fichier.
        try:
            DocumentGeneration.objects.values_list('file_corrections', 'id_numero', 'circuit_events').first()
            nature = DocumentNature.objects.get(nature='Fichier généré', actif=True, est_acte=False)
            docx_format = DocumentFormat.objects.get(format__iexact='docx')
        except (DatabaseError, DocumentNature.DoesNotExist, DocumentFormat.DoesNotExist,
                DocumentFormat.MultipleObjectsReturned) as exc:
            raise DocumentOutputError('Enregistrement indisponible : vérifiez les scripts jusqu’à 0019 et la nature « Fichier généré » (active, non acte).') from exc
        snapshot = json.loads(json.dumps(context, cls=DjangoJSONEncoder, ensure_ascii=False))
        template_snapshot = {
            'id': template.pk, 'nom': template.nom, 'chemin_relatif': template.chemin_relatif,
            'destination_relative': template.destination_relative, 'nom_fichier': template.nom_fichier,
            'source_sha256': hashlib.sha256(template_bytes).hexdigest(),
            'document_sha256': hashlib.sha256(buffer.getvalue()).hexdigest(),
        }
        if number_reservation is not None:
            from .numbers import selected_number
            number_reservation = selected_number(number_reservation.pk, dossier, template, user)
            if context.get('document', {}).get('numero') != number_reservation.numero:
                raise DocumentOutputError('Le contexte ne correspond pas au numéro réservé.')
        elif isinstance(getattr(template, 'id_nature_id', None), int):
            from .numbers import number_kind
            if number_kind(template):
                raise DocumentOutputError('Générez ou récupérez le numéro du document avant de créer le fichier.')
        if filename_pattern is not None:
            template_snapshot['nom_fichier_utilise'] = filename_pattern
        output_options = {}
        if number_reservation is not None:
            output_options['document_number'] = number_reservation.numero
        if filename_pattern is not None:
            output_options['filename_pattern'] = filename_pattern
        output = DocumentOutputService().save(buffer, template, dossier, **output_options)
        try:
            with transaction.atomic():
                document = Document.objects.create(
                    id_format=docx_format, id_nature=nature, titre=output['filename'],
                    emplacement=output['relative_destination'],
                    description=f'Généré depuis le modèle {template.nom} pour le dossier {dossier.numero}.',
                    numero=number_reservation.numero if number_reservation else None,
                )
                DossierDocument.objects.create(id_dossier=dossier, id_document=document)
                DocumentGeneration.objects.create(
                    id_template=template, id_dossier=dossier, id_document=document, user=user,
                    context_snapshot=snapshot, template_snapshot=template_snapshot,
                    id_numero=number_reservation,
                )
        except Exception as exc:
            # Ce chemin provient de l'écriture exclusive : aucun fichier préexistant n'est supprimé.
            logger.exception('Enregistrement génération impossible dossier=%s template=%s user=%s', dossier.pk, template.pk, user.pk)
            try:
                smbclient.remove(output['path'])
            except Exception:
                logger.exception('Nettoyage du fichier non enregistré impossible : %s', output['path'])
                raise DocumentOutputError('Enregistrement BDD impossible. Le fichier peut subsister sur le NAS ; contactez l’administrateur.') from exc
            raise DocumentOutputError('Enregistrement BDD impossible. Le fichier créé a été supprimé ; aucune génération n’a été enregistrée.') from exc
        return output
