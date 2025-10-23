from datetime import timedelta
import json
import logging
import os
import smtplib
from django.db import DatabaseError, IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.crypto import salted_hmac
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.utils.html import strip_tags
from autorisations.models.models_utilisateurs import EmailOutbox, Instructeur
from psycopg2.errors import UniqueViolation

logger = logging.getLogger("MAIL")


def compute_dedupe_key(to, sujet, template, context) -> str:
    """
    Construit une clé de déduplication stable.
    """
    payload = json.dumps(
        {"to": to, "sujet": sujet, "template": template, "context": context},
        sort_keys=True,
        cls=DjangoJSONEncoder,
    )
    return salted_hmac("email-outbox", payload).hexdigest()



def _render_message(item):
    html = render_to_string(f"emails/{item.template}.html", item.context)
    try:
        text = render_to_string(f"emails/{item.template}.txt", item.context)
    except TemplateDoesNotExist:
        text = strip_tags(html)
    return text, html


# Envoi_mail
def envoi_mail(item_id: int) -> tuple[bool, str]:  #item_id = EmailOutbox_id
    """
    Envoie IMMÉDIATEMENT l'email outbox donné.
    - Pas de backoff ni de réessais : Envoyé si succès, Échec sinon.
    - Retourne (ok, error_message).
    """

    with transaction.atomic():
        # Verrouille pour éviter une concurrence avec le batch, au cas où
        item = (EmailOutbox.objects.select_for_update(skip_locked=True).get(id=item_id))

        # si déjà Envoyé, on peut court-circuiter
        if item.statut == "Envoyé":
            return True, ""

        text, html = _render_message(item)

        try:
            # Utilise la conf Django (EMAIL_*)
            with get_connection() as conn:
                msg = EmailMultiAlternatives(
                    subject=item.sujet,
                    body=text,
                    to=item.to,
                    connection=conn,
                )
                msg.attach_alternative(html, "text/html")

                if item.id_document:
                    doc = item.id_document
                    chemin_fichier = os.path.join(os.getenv('ROOT_FOLDER'), doc.emplacement, doc.titre)
                    if os.path.exists(chemin_fichier):
                        msg.attach_file(chemin_fichier)
                    else :
                        # Échec
                        EmailOutbox.objects.filter(id=item.id).update(
                            statut="Échec",
                            try_count=item.try_count + 1,
                            derniere_tentative_envoi=timezone.now(),
                            derniere_erreur=str(e)[:1000],
                        )
                        return False, f"Mail non envoyé (Dossier {item.id_dossier}): La pièce jointe (Document {doc.id}) n'a pas été trouvé à l'emplacement {chemin_fichier}"


                msg.send(fail_silently=False)

        except Exception as e:
            # Échec
            EmailOutbox.objects.filter(id=item.id).update(
                statut="Échec",
                try_count=item.try_count + 1,
                derniere_tentative_envoi=timezone.now(),
                derniere_erreur=str(e)[:1000],
            )

            logger.error(f"[MAIL {item_id}] Echec de l'envoi du mail à {item.to} : {e}")

            return False, str(e)

        # Succès
        EmailOutbox.objects.filter(id=item.id).update(
            statut="Envoyé",
            # derniere_erreur="",
            derniere_tentative_envoi=timezone.now(),
        )
        return True, ""



''' 
- 


A METTRE DANS UNE VIEW HTML (QD ON VA CLIQUER SUR REESAYER L'ENVOI DU MAIL MANUELLEMENT)

'''
# Envoi_mail_en_copie
def envoi_notification_par_mail(item_id: int) -> tuple[bool, str]:  #item_id = EmailOutbox_id
    """
    Envoie l'email outbox donné.
    - Si succès : 'Envoyé', 
      Si erreur : try_count += 3, statut reste à Échec'
    - Retourne (ok, error_message).
    """

    # verifie try count ect .. comme dans envoyer_mail_en_copie

    # email = get_object_or_404(EmailOutbox, pk=item_id)
    # dossier = email.id_dossier

    # LOGGER ok, err   (les eventuelles erreurs = logger.error + messages.error)


    return True, ""


def create_EmailOutbox (emails_norm, sujet, template_name, dedupe, context, dossier, type_mail) :

    try:
        outbox = EmailOutbox.objects.create(
            to=emails_norm,
            email_from=os.getenv("DEFAULT_FROM_EMAIL"),
            sujet=sujet,
            type_mail=type_mail,
            # statut = "À envoyer" par défaut
            template = template_name,
            dedupe_key=dedupe,
            context=context,
            id_dossier=dossier,
        )
        
        return outbox


    # Si Email identique existant en attente d'envoi --> on le récupère
    except IntegrityError as e:
        is_unique_violation = (
            (UniqueViolation and isinstance(getattr(e, "__cause__", None), UniqueViolation))
            or "ux_outbox_dedupe_pending" in str(e)
            or "unique" in str(e).lower()
        )
        if is_unique_violation:
            # On récupère l'élément déjà en attente (cas « doublon »)
            outbox = (EmailOutbox.objects.filter(dedupe_key=dedupe, statut__in=["À envoyer", "Échec"]).order_by("-date_creation").first())
            logger.warning(f"[DOSSIER {dossier.numero}] Doublon détecté et récupéré : Email ({type_mail}) déjà existant ({outbox.sujet} -> {', '.join(outbox.to)})")
            return outbox
        
        else:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur IntegrityError non liée à l’unicité lors de la création de l'EmailOutbox ({type_mail}) : {e}")
            return None

    except DatabaseError as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur en base de données lors de la création de l'EmailOutbox ({type_mail}) : {e}")
        return None
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur inattendue lors de la création de l'EmailOutbox ({type_mail}) : {e}")
        return None