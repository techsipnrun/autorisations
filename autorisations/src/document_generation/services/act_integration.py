"""Entrée explicite d'un Word généré dans le circuit des actes, sans compteur."""
import ntpath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from autorisations.models.models_documents import Document, DossierDocument, DocumentNature
from autorisations.models.models_instruction import Dossier
from autorisations.models.models_generation import DocumentGeneration, DocumentNumberReservation


def find_generated_act(dossier, filename, nature_id):
    if settings.ENVIRONMENT != 'dev' or not filename or not nature_id:
        return None
    work = ntpath.normpath(ntpath.join(dossier.emplacement, 'Work')).casefold()
    candidates = DocumentGeneration.objects.filter(
        id_dossier=dossier, id_document__titre__iexact=filename,
        id_numero__isnull=False, id_numero__id_nature__est_acte=True,
    ).exclude(id_numero__numero='').exclude(id_numero__id_nature__nature__iexact='Avis Instance').select_related(
        'id_document__id_nature', 'id_document__id_statut', 'id_numero__id_nature').defer(
            'context_snapshot', 'template_snapshot', 'file_corrections')
    matches = [row for row in candidates if ntpath.normpath(row.id_document.emplacement).casefold() == work]
    if not matches:
        return None  # Document manuel, ou génération sans numéro : parcours historique.
    if len(matches) != 1:
        raise ValidationError('Ce fichier correspond à plusieurs générations. Réparez son historique avant de poursuivre.')
    row = matches[0]
    if str(row.id_numero.id_nature_id) != str(nature_id):
        raise ValidationError(f'Ce fichier a été généré pour la nature « {row.id_numero.id_nature.nature} ». '
                              'Choisissez la même nature ou un autre fichier.')
    return row


def replacement_candidate(row, dossier):
    """Projet généré remplaçable : même dossier/Work/nature/numéro, hors circuit actif."""
    nature = row.id_numero.id_nature
    field = 'numero_reference' if nature.numerotation_manuelle else 'numero'
    work = ntpath.normpath(ntpath.join(dossier.emplacement, 'Work')).casefold()
    candidates = list(Document.objects.filter(id_nature=nature, **{field: row.id_numero.numero}).exclude(
        pk=row.id_document_id).select_related('id_statut'))
    local = [doc for doc in candidates if ntpath.normpath(doc.emplacement).casefold() == work]
    if not local:
        return None
    if len(local) != 1:
        raise ValidationError('Plusieurs projets portent ce numéro au même emplacement. Contactez l’administrateur.')
    old = local[0]
    if old.id_statut_id or old.publie_au_raa or old.url_ds or old.url_dm:
        raise ValidationError('Le projet précédent est encore dans le circuit ou a été diffusé. '
                              'Le remplacement exige un retour en instruction et ne concerne pas les actes diffusés.')
    old_generation = DocumentGeneration.objects.filter(id_document=old, id_dossier=dossier,
        id_numero__id_nature_id=nature.pk, id_numero__numero=row.id_numero.numero).first()
    if old_generation is None or DossierDocument.objects.filter(id_document=old).exclude(id_dossier=dossier).exists():
        raise ValidationError('Le projet précédent est manuel ou partagé. Son remplacement nécessite une intervention explicite hors de ce formulaire.')
    if Document.objects.filter(id_document_reference=old).exists():
        raise ValidationError('Le projet précédent sert de référence à un autre acte. Son remplacement nécessite une intervention explicite.')
    return old


def integrate_generated_act(dossier, filename, nature, statut, file_format, *, replace_document_id=None, user=None):
    row = find_generated_act(dossier, filename, nature.pk)
    if row is None:
        return None
    with transaction.atomic():
        # Sérialise les intégrations de versions dans un même dossier.
        Dossier.objects.select_for_update().get(pk=dossier.pk)
        reservation = DocumentNumberReservation.objects.select_for_update().get(pk=row.id_numero_id)
        document = Document.objects.select_for_update().select_related('id_nature', 'id_statut').get(pk=row.id_document_id)
        work = ntpath.normpath(ntpath.join(dossier.emplacement, 'Work')).casefold()
        if (reservation.id_nature_id != nature.pk or reservation.id_dossier_id != dossier.pk
                or ntpath.normpath(document.emplacement).casefold() != work
                or document.titre.casefold() != filename.casefold()):
            raise ValidationError('La génération a changé. Actualisez la page avant de poursuivre.')
        if document.id_statut and document.id_statut.statut.casefold() in ('envoyé', 'à envoyer'):
            raise ValidationError('Ce document est déjà dans le circuit de diffusion et ne peut pas redevenir un projet.')
        if document.id_nature_id not in (nature.pk, row.id_document.id_nature_id):
            raise ValidationError('La nature du document a changé. Actualisez la page.')
        if document.id_nature.nature != 'Fichier généré' and document.id_nature_id != nature.pk:
            raise ValidationError('La nature du document ne correspond plus à sa génération.')
        current = document.numero_effectif
        if current != reservation.numero:
            raise ValidationError('Le numéro du document ne correspond plus à sa réservation. Contactez l’administrateur.')
        # L'unicité des actes porte sur nature + numéro + emplacement.
        # La réservation apporte le numéro : une récupération permet le partage
        # entre dossiers sans empêcher ensuite l'intégration du document source.
        number_field = 'numero_reference' if nature.numerotation_manuelle else 'numero'
        existing_locations = list(Document.objects.filter(
            id_nature=nature, **{number_field: reservation.numero},
        ).exclude(pk=document.pk).values_list('emplacement', flat=True))
        if any(ntpath.normpath(location).casefold() == work for location in existing_locations):
            old = replacement_candidate(row, dossier)
            if old is None or str(old.pk) != str(replace_document_id or ''):
                raise ValidationError('Confirmez explicitement le remplacement du projet précédent avant de poursuivre.')
            # Verrouiller les versions et leurs journaux dans la transaction.
            Document.objects.select_for_update().get(pk=old.pk)
            old = replacement_candidate(row, dossier)
            if old is None or str(old.pk) != str(replace_document_id):
                raise ValidationError('Le projet précédent a changé. Actualisez la page.')
            old_generation = DocumentGeneration.objects.select_for_update().get(id_document=old, id_dossier=dossier)
            new_generation = DocumentGeneration.objects.select_for_update().get(pk=row.pk, id_document=document, id_dossier=dossier)
            generated_nature = DocumentNature.objects.get(nature='Fichier généré', actif=True, est_acte=False)
            Document.objects.filter(pk=old.pk).update(id_nature=generated_nature, id_statut=None,
                numero=reservation.numero, numero_reference=None, id_document_reference=None)
            event = {'date': timezone.now().isoformat(), 'user_id': getattr(user, 'pk', None),
                     'old_document_id': old.pk, 'new_document_id': document.pk,
                     'old_filename': old.titre, 'new_filename': document.titre,
                     'numero': reservation.numero, 'id_nature': nature.pk}
            for generation in (old_generation, new_generation):
                generation.circuit_events = [*generation.circuit_events, event]
                generation.save(update_fields=['circuit_events'])
        elif replace_document_id:
            raise ValidationError('Le projet à remplacer n’est plus celui attendu. Actualisez la page.')
        values = dict(id_nature=nature, id_statut=statut, id_format=file_format,
                      numero=None if nature.numerotation_manuelle else reservation.numero,
                      numero_reference=reservation.numero if nature.numerotation_manuelle else None,
                      id_document_reference=None)
        # Mise à jour contrôlée : save() renuméroterait lors du changement de nature.
        # Le numéro vient exclusivement de la réservation relue et verrouillée.
        Document.objects.filter(pk=document.pk).update(**values)
        for key, value in values.items():
            setattr(document, key, value)
        DossierDocument.objects.get_or_create(id_dossier=dossier, id_document=document)
        return document
