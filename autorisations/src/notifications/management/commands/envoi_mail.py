"""
Commande batch d'envoi des mails de la table EmailOutbox.

Points clés :
- Concurrence sûre : select_for_update(skip_locked) + réservation courte.
- Une seule connexion SMTP pour tout le lot.
- Corps texte + alternative HTML (fallback strip_tags si .txt absent).
- Backoff exponentiel borné et statut FAILED au-delà des tentatives.
"""

import logging
from smtplib import SMTPAuthenticationError, SMTPException
import ssl
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.utils.html import strip_tags
from django.utils import timezone
from django.db import transaction

from autorisations.models.models_utilisateurs import EmailOutbox

logger = logging.getLogger("MAIL")

# Paramètres batch
BATCH_SIZE = 50
MAX_TRIES = 3

# Réserve les lignes X minutes pour éviter qu’un autre worker ne les prenne.
RESERVATION_MINUTES = 3

# Backoff exponentiel borné (en minutes)
MIN_BACKOFF_MINUTES = 1
MAX_BACKOFF_MINUTES = 60


def _reserve_batch():
    """
    Sélectionne et RÉSERVE un lot d'emails prêts à être envoyés.
    La réservation est concrétisée en décalant next_attempt_at.
    On évalue la queryset DANS la transaction pour maintenir les verrous.
    """
    now = timezone.now()
    with transaction.atomic():
        qs = (
            EmailOutbox.objects
            .select_for_update(skip_locked=True)
            .filter(status="PENDING", next_attempt_at__lte=now)
            .order_by("next_attempt_at", "id")[:BATCH_SIZE]
        )
        items = list(qs)  # matérialise -> verrous pris

        if not items:
            return []

        reserve_until = now + timezone.timedelta(minutes=RESERVATION_MINUTES)
        EmailOutbox.objects.filter(pk__in=[i.pk for i in items]).update(next_attempt_at=reserve_until)
        return items


class Command(BaseCommand):
    help = "Envoie les emails en file d’attente (EmailOutbox)."

    def handle(self, *args, **opts):
        # 1) Ouvrir la connexion SMTP (utilise settings EMAIL_*)
        try:
            with get_connection(
                host="smtp-reunion.pnrun.local",
                port=587,
                username="",
                password="",
                use_tls=True,              # STARTTLS
                ssl_context=ssl._create_unverified_context(),
                timeout=20,
            ) as conn:
                # 2) Réserver le lot APRÈS la connexion
                items = _reserve_batch()
                if not items:
                    logger.info("Aucun email à envoyer pour le moment.")
                    self.stdout.write("Aucun email à envoyer pour le moment.")
                    return
                logger.info("")
                logger.info("%s emails à envoyer", len(items))
                self.stdout.write(self.style.SUCCESS(f"{len(items)} emails à envoyer"))

                # 3) Envoyer les mails un par un
                for item in items:
                    self._send_one(conn, item)

        except SMTPAuthenticationError as e:
            logger.error("SMTP auth failed: %s", e)
            self.stderr.write(self.style.ERROR(f"SMTP auth failed: {e}"))

        except SMTPException as e:
            logger.exception("SMTP error during connection: %s", e)
            self.stderr.write(self.style.ERROR(f"SMTP error: {e}"))

        except ImproperlyConfigured as e:
            logger.exception("Configuration email invalide: %s", e)
            self.stderr.write(self.style.ERROR(f"Configuration email invalide: {e}"))

        except Exception as e:
            logger.exception("Unexpected error while opening SMTP: %s", e)
            self.stderr.write(self.style.ERROR(f"Unexpected SMTP error: {e}"))

    def _send_one(self, conn, item):
        """
        Envoie un email puis met à jour la ligne correspondante.
        """
        try:
            # Corps HTML
            html = render_to_string(f"emails/{item.template}.html", item.context)

            # Corps texte (.txt optionnel) sinon fallback strip_tags
            try:
                text = render_to_string(f"emails/{item.template}.txt", item.context)
            except TemplateDoesNotExist:
                text = strip_tags(html)

            msg = EmailMultiAlternatives(
                subject=item.subject,
                body=text,
                to=[item.to],
                connection=conn,
            )
            msg.attach_alternative(html, "text/html")
            msg.send(fail_silently=False)

            # Succès
            EmailOutbox.objects.filter(pk=item.pk).update(
                status="SENT",
                last_error="",
                try_count=item.try_count  # on ne touche pas au compteur en cas de succès
            )
            logger.info("EmailOutbox id=%s envoyé à %s", item.pk, item.to)

        except Exception as e:
            # Échec : incrément + backoff exponentiel borné
            try_count = item.try_count + 1
            delay = max(MIN_BACKOFF_MINUTES, min(MAX_BACKOFF_MINUTES, 2 ** try_count))
            next_at = timezone.now() + timezone.timedelta(minutes=delay)

            EmailOutbox.objects.filter(pk=item.pk).update(
                status="FAILED" if try_count >= MAX_TRIES else "PENDING",
                try_count=try_count,
                next_attempt_at=next_at,
                last_error=str(e)[:1000],
            )
            logger.exception("Échec envoi EmailOutbox id=%s (tentative %s) : %s", item.pk, try_count, e)
