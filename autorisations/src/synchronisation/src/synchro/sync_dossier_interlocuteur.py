from autorisations.models.models_utilisateurs import DossierInterlocuteur
from ..utils.model_helpers import update_fields
import logging

logger = logging.getLogger("ORM_DJANGO")

def sync_dossier_interlocuteur(dossier_interlocuteur, ids_beneficiaire_intermediaire, id_dossier):
    """
    Synchronise les Dossier_Interlocuteur
    {
        "id_interlocuteur_ds": str,
        "id_demandeur_intermediaire": int | None,
    }
    """

    result_ids = {
        "dossier_interlocuteur": None
    }

    obj, created = DossierInterlocuteur.objects.get_or_create(
        id_interlocuteur_ds=dossier_interlocuteur["id_interlocuteur_ds"],
        id_dossier_id=id_dossier,
        defaults={
            "id_demandeur_intermediaire_id": ids_beneficiaire_intermediaire["demandeur_intermediaire"]
        }
    )

    if created:
        logger.info(f"[CREATE] DossierInterlocuteur (id_dossier: {obj.id_dossier_id}) créé.")

    else:
        updated_fields = update_fields(obj, {
            "id_demandeur_intermediaire_id": ids_beneficiaire_intermediaire["demandeur_intermediaire"],
        })

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] DossierInterlocuteur {obj.id} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")

    result_ids["dossier_interlocuteur"] = obj.id
    return result_ids
