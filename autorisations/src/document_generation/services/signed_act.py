"""Conserver le Word source lorsque le Document du circuit devient le PDF signé."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from autorisations.models.models_documents import Document, DocumentNature, DossierDocument
from autorisations.models.models_generation import DocumentGeneration
from autorisations.models.models_instruction import Dossier


def save_signed_act(document, dossier, values, *, user=None):
    with transaction.atomic():
        # Pas de jointure ni de clause OF : tables qualifiées par schéma.
        current = Document.objects.select_for_update().get(pk=document.pk)
        generation = None
        if settings.ENVIRONMENT == 'dev':
            generation = DocumentGeneration.objects.select_for_update().filter(
                id_document=current).first()
        source = None
        if generation is not None:
            nature = DocumentNature.objects.get(nature='Fichier généré', actif=True, est_acte=False)
            source = dict(titre=current.titre, emplacement=current.emplacement,
                id_format_id=current.id_format_id, id_nature=nature, id_statut=None,
                numero=current.numero_effectif, description=current.description, date=current.date)
        for key, value in values.items():
            setattr(current, key, value)
        current.save()
        if generation is not None:
            # Libérer d'abord (emplacement, titre), unique en BDD, en déplaçant
            # la référence du circuit vers le PDF, sans toucher au Word physique.
            word = Document.objects.create(**source)
            DossierDocument.objects.create(id_dossier_id=generation.id_dossier_id, id_document=word)
            generation.id_document = word
            generation.id_document_signe = current
            generation.circuit_events = [*generation.circuit_events, {
                'type': 'transmission_acte_signe', 'date': timezone.now().isoformat(),
                'user_id': getattr(user, 'pk', None), 'source_document_id': word.pk,
                'signed_document_id': current.pk, 'numero': source['numero'],
            }]
            generation.save(update_fields=['id_document', 'id_document_signe', 'circuit_events'])
        return current


def save_signed_documents(dossier, document, values, *, report=None, report_values=None, user=None):
    """La remise à zéro et les deux conversions BDD réussissent ou sont annulées ensemble."""
    with transaction.atomic():
        Dossier.objects.select_for_update().get(pk=dossier.pk)
        links = DossierDocument.objects.filter(id_dossier=dossier).values('id_document')
        Document.objects.filter(pk__in=links, id_statut__statut__in=[
            'À envoyer', 'À signer', 'À relire', 'À valider',
        ]).update(id_statut=None)
        signed = save_signed_act(document, dossier, values, user=user)
        signed_report = save_signed_act(report, dossier, report_values, user=user) if report is not None else None
        return signed, signed_report
