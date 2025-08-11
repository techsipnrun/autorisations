"""
Service de mise en file d'attente des emails.

- Utilise transaction.on_commit pour n'insérer qu'après succès de la transaction appelante.
- Déduplication optionnelle :
    * Si dedupe_key donnée : on l'utilise telle quelle.
    * Sinon, on calcule une empreinte stable à partir de (to, subject, template, context).
- get_or_create() sur dedupe_key pour éviter les doublons PENDING (idéalement avec
  une contrainte UNIQUE partielle en base sur (dedupe_key) WHERE dedupe_key<>'' AND status='PENDING').
"""

import json
import logging
from django.db import transaction
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.crypto import salted_hmac

from autorisations.models.models_utilisateurs import EmailOutbox

logger = logging.getLogger("APP")


def _compute_dedupe_key(to, subject, template, context) -> str:
    """
    Construit une clé de déduplication stable à partir de la charge utile.
    """
    payload = json.dumps(
        {"to": to, "subject": subject, "template": template, "context": context},
        sort_keys=True,
        cls=DjangoJSONEncoder,
    )
    # On utilise salted_hmac pour une empreinte stable et sûre
    return salted_hmac("email-outbox", payload).hexdigest()


def queue_email(to: str, subject: str, template: str, context: dict, dedupe_key: str | None = None) -> None:
    """
    Mettez en file un email à envoyer par la commande batch.

    - Si dedupe_key est vide/non fourni, on la calcule automatiquement.
    - On insère à la fin de la transaction appelante (on_commit).
    """
    key = (dedupe_key or "").strip()
    if not key:
        key = _compute_dedupe_key(to, subject, template, context)

    def _create():
        # Idéal si vous avez en base :
        # CREATE UNIQUE INDEX IF NOT EXISTS ux_email_outbox_dedupe_pending
        # ON utilisateurs.email_outbox (dedupe_key)
        # WHERE dedupe_key <> '' AND status = 'PENDING';
        obj, created = EmailOutbox.objects.get_or_create(
            dedupe_key=key,
            defaults={
                "to": to,
                "subject": subject,
                "template": template,
                "context": context,
                "status": "PENDING",
                "next_attempt_at": timezone.now(),
            },
        )

        # Si déjà présent :
        if not created:
            # Cas utile : la ligne existe mais n'est plus en attente (SENT/FAILED) -> on refile en PENDING
            if obj.status != "PENDING":
                obj.to = to
                obj.subject = subject
                obj.template = template
                obj.context = context
                obj.status = "PENDING"
                obj.next_attempt_at = timezone.now()
                obj.save(update_fields=["to", "subject", "template", "context", "status", "next_attempt_at"])
            # Sinon, on garde l'existant (dédup OK)
        logger.info("EmailOutbox queued (created=%s) dedupe=%s to=%s subject=%s", created, bool(key), to, subject)

    transaction.on_commit(_create)
