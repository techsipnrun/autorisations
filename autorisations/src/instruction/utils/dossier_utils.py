import logging
from autorisations.models.models_instruction import Message

logger = logging.getLogger("ORM_DJANGO")


EXCLUDED_EMAILS = ["contact@demarches-simplifiees.fr",]
EXCLUDED_SUFFIXES = ["reunion-parcnational.fr"]


def count_unread_messages_for_dossier(dossier, num_dossier: int | None = None) -> int:
    """
    Retourne le nombre de messages non lus pour un dossier.
    Exclut les messages DS et les messages internes selon les règles métier.

    Ne lève jamais d’exception :
    en cas d'erreur → log + renvoie 0.
    """
    try:
        qs = Message.objects.filter(id_dossier=dossier, lu=False)

        # Exclure les messages DS
        for email in EXCLUDED_EMAILS:
            qs = qs.exclude(email_emetteur=email)

        # Exclure les messages internes "finissant par"
        for suffix in EXCLUDED_SUFFIXES:
            qs = qs.exclude(email_emetteur__endswith=suffix)

        return qs.count()

    except Exception as e:
        dossier_id = num_dossier or (getattr(dossier, "numero", None) or dossier.id)
        logger.error(f"[DOSSIER {dossier_id}] Erreur lors du calcul des messages non lus : {e}")
        return 0
