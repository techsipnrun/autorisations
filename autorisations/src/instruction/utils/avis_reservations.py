"""Un seul compteur PostgreSQL pour les avis envoyés, brouillons et réservations."""
from contextlib import contextmanager
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from autorisations.models.models_avis import Avis, AvisReservation
from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import Instructeur


def cle_reservation(valeur):
    try:
        return UUID(str(valeur))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("La réservation du numéro est absente ou invalide. Rechargez le formulaire.")


def verifier_reservation(reservation, instructeur, dossier=None):
    contexte = "dossier" if dossier is not None else "generique"
    if reservation.id_instructeur_id != instructeur.pk or reservation.contexte != contexte or reservation.id_dossier_id != (dossier.pk if dossier is not None else None):
        raise PermissionDenied("Cette réservation n'appartient pas à ce formulaire ou à cet instructeur.")
    if reservation.date_utilisation and not reservation.id_avis_id:
        raise ValidationError("Ce numéro a déjà été utilisé pour un avis supprimé. Ouvrez une nouvelle demande.")


def reserver_numero(instructeur, dossier=None, cle=None):
    cle = cle_reservation(cle)
    with transaction.atomic():
        reservation = AvisReservation.objects.filter(pk=cle).first()
        if not reservation:
            # Ne jamais utiliser MAX(id) + 1 ni remettre la séquence en arrière.
            with connection.cursor() as cursor:
                cursor.execute("SELECT nextval(pg_get_serial_sequence('avis.avis', 'id'))")
                numero = cursor.fetchone()[0]
            if numero is None:
                raise ValidationError("Le compteur des avis est introuvable. Contactez le support.")
            reservation, _ = AvisReservation.objects.get_or_create(pk=cle, defaults={
                "numero": numero, "id_instructeur": instructeur,
                "contexte": "dossier" if dossier is not None else "generique", "id_dossier": dossier,
            })
        verifier_reservation(reservation, instructeur, dossier)
        return reservation


def lire_reservation(cle, instructeur, dossier=None):
    reservation = AvisReservation.objects.filter(pk=cle_reservation(cle)).first()
    if not reservation:
        raise ValidationError("La réservation est introuvable. Ouvrez une nouvelle demande.")
    verifier_reservation(reservation, instructeur, dossier)
    return reservation


@contextmanager
def creation_avis_reservee(request, num_dossier=None):
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        raise PermissionDenied("Vous devez disposer d'un profil instructeur.")
    dossier = None
    if num_dossier is not None:
        dossier = Dossier.objects.filter(numero=num_dossier).first()
        if not dossier:
            raise ValidationError("Le dossier est introuvable.")
    with transaction.atomic():
        reservation = AvisReservation.objects.select_for_update().filter(
            pk=cle_reservation(request.POST.get("reservation")),
        ).first()
        if not reservation:
            raise ValidationError("La réservation est introuvable. Rechargez le formulaire.")
        verifier_reservation(reservation, instructeur, dossier)
        request.instructeur_reservation = instructeur
        request.dossier_reservation = dossier
        deja_utilisee = bool(reservation.date_utilisation)
        yield reservation
        if not deja_utilisee and not getattr(request, "creation_avis_validee", False):
            # Les vues historiques retournent aussi des redirections en cas d'erreur.
            transaction.set_rollback(True)


def utiliser_reservation(request, avis):
    reservation = request.reservation_avis
    if avis.pk != reservation.numero or reservation.date_utilisation:
        raise ValidationError("Ce numéro d'avis ne peut pas être utilisé une seconde fois.")
    reservation.id_avis = avis
    reservation.date_utilisation = timezone.now()
    reservation.save(update_fields=["id_avis", "date_utilisation"])


@contextmanager
def modification_brouillon_verrouillee(request, num_dossier, avis_id):
    with transaction.atomic():
        avis = Avis.objects.select_for_update().filter(id=avis_id, id_dossier__numero=num_dossier).first()
        yield avis
        if not getattr(request, "creation_avis_validee", False):
            transaction.set_rollback(True)
