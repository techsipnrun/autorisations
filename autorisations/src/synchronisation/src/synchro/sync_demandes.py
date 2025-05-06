from autorisations.models.models_instruction import Demande
from ..utils.model_helpers import update_fields
import logging

logger = logging.getLogger("ORM_DJANGO")

def sync_demandes(demandes, id_dossier):
    """
    Synchronisation des demandes
    [{"id_etat_demande", "id_priorite", "id_demande_type", "date_depot", "date_fin_instruction"}, ...]
    
    """
    for demande in demandes:
        defaults = {
            "date_depot": demande["date_depot"],
            "date_fin_instruction": demande["date_fin_instruction"],
            "id_etat_demande_id": demande["id_etat_demande"],
            "id_priorite_id": demande["id_priorite"],
        }

        obj, created = Demande.objects.get_or_create(
            id_dossier_id=id_dossier,
            id_demande_type_id=demande["id_demande_type"],
            defaults=defaults
        )

        if created:
            logger.info(f"[CREATE] Demande {obj.id} pour Dossier {id_dossier} créée.")
        else:
            updated_fields = update_fields(obj, defaults, date_fields=["date_depot", "date_fin_instruction"])
            if updated_fields:
                obj.save()
                champs = ", ".join(updated_fields)
                logger.info(f"[SAVE] Demande {obj.id} pour Dossier {id_dossier} mise à jour. Champs modifiés : {champs}.")
            else:
                logger.info(f"[NO CHANGE] Demande {obj.id} pour Dossier {id_dossier} inchangée.")
