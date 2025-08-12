import json
import logging
import os
from django.db import transaction
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.crypto import salted_hmac
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.utils.html import strip_tags
from autorisations.models.models_utilisateurs import EmailOutbox

logger = logging.getLogger("MAIL")


# def _compute_dedupe_key(to, sujet, template, context) -> str:
#     """
#     Construit une clé de déduplication stable.
#     """
#     payload = json.dumps(
#         {"to": to, "sujet": sujet, "template": template, "context": context},
#         sort_keys=True,
#         cls=DjangoJSONEncoder,
#     )
#     return salted_hmac("email-outbox", payload).hexdigest()



def _render_message(item):
    html = render_to_string(f"emails/{item.template}.html", item.context)
    try:
        text = render_to_string(f"emails/{item.template}.txt", item.context)
    except TemplateDoesNotExist:
        text = strip_tags(html)
    return text, html

def send_outbox_now(item_id: int) -> tuple[bool, str]:
    """
    Envoie IMMÉDIATEMENT l'email outbox donné.
    - Pas de backoff ni de réessais : Envoyé si succès, Échec sinon.
    - Retourne (ok, error_message).
    """
    with transaction.atomic():
        # Verrouille pour éviter une concurrence avec le batch, au cas où
        item = (
            EmailOutbox.objects
            .select_for_update(skip_locked=True)
            .get(id=item_id)
        )

        # si déjà Envoyé, on peut court-circuiter
        if item.statut == "Envoyé":
            return True, ""

        text, html = _render_message(item)

        try:
            # Utilise la conf Django (EMAIL_*)
            with get_connection() as conn:
                msg = EmailMultiAlternatives(
                    sujet=item.subject,
                    body=text,
                    to=[item.to],
                    connection=conn,
                )
                msg.attach_alternative(html, "text/html")

                if item.id_document_id:
                    doc = item.id_document
                    chemin_fichier = os.path.join(os.getenv('ROOT_FOLDER'), doc.emplacement, doc.titre)
                    if os.path.exists(chemin_fichier):
                        msg.attach_file(chemin_fichier)
                    else :
                        return False, f"Mail non envoyé (Dossier {item.id_dossier}): La pièce jointe (Document {doc.id}) n'a pas été trouvé à l'emplacement {chemin_fichier}"


                msg.send(fail_silently=False)

        except Exception as e:
            # Échec
            EmailOutbox.objects.filter(id=item.id).update(
                statut="Échec",
                try_count=item.try_count + 1,
                derniere_tentative_envoi=timezone.now(),  # sans importance ici
                derniere_erreur=str(e)[:1000],
            )
            return False, str(e)

        # Succès
        EmailOutbox.objects.filter(id=item.id).update(
            statut="Envoyé",
            derniere_erreur="",
            derniere_tentative_envoi=timezone.now(),
        )
        return True, ""




# def queue_email(to: str, subject: str, template: str, context: dict, dedupe_key: str | None = None) -> None:
#     """
#     Mettez en file un email à envoyer par la commande batch.

#     - Si dedupe_key est vide/non fourni, on la calcule automatiquement.
#     - On insère à la fin de la transaction appelante (on_commit).
#     """
#     key = (dedupe_key or "").strip()
#     if not key:
#         key = _compute_dedupe_key(to, subject, template, context)

#     def _create():
#         # Idéal si vous avez en base :
#         # CREATE UNIQUE INDEX IF NOT EXISTS ux_email_outbox_dedupe_pending
#         # ON utilisateurs.email_outbox (dedupe_key)
#         # WHERE dedupe_key <> '' AND status = 'PENDING';
#         obj, created = EmailOutbox.objects.get_or_create(
#             dedupe_key=key,
#             defaults={
#                 "to": to,
#                 "subject": subject,
#                 "template": template,
#                 "context": context,
#                 "status": "PENDING",
#                 "next_attempt_at": timezone.now(),
#             },
#         )

#         # Si déjà présent :
#         if not created:
#             # Cas utile : la ligne existe mais n'est plus en attente (SENT/FAILED) -> on refile en PENDING
#             if obj.status != "PENDING":
#                 obj.to = to
#                 obj.subject = subject
#                 obj.template = template
#                 obj.context = context
#                 obj.status = "PENDING"
#                 obj.next_attempt_at = timezone.now()
#                 obj.save(update_fields=["to", "subject", "template", "context", "status", "next_attempt_at"])
#             # Sinon, on garde l'existant (dédup OK)
#         logger.info("EmailOutbox queued (created=%s) dedupe=%s to=%s subject=%s", created, bool(key), to, subject)

#     transaction.on_commit(_create)

