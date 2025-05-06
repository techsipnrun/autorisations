from autorisations.models.models_instruction import Champ
from ..utils.model_helpers import update_fields
import logging

logger = logging.getLogger("ORM_DJANGO")

def sync_champs(champs_list):
    """
    Synchronise les objets Champs à partir des données récupérées sur D-S.
    [{ "id_ds", "nom", "id_champ_type", "description", "id_demarche", "requis" }]
    """

    for ch in champs_list:

        obj, created = Champ.objects.get_or_create(
            id_ds=ch["id_ds"], id_demarche_id=ch["id_demarche"],
            defaults={
                "nom": ch["nom"],
                "id_champ_type_id": ch["id_champ_type"],
                "description": ch["description"],
                # "id_demarche_id": ch.get("id_demarche"),
                "requis": ch["requis"],
            }
        )

        nom_champ_sans_apostrophe = obj.nom.replace("'", " ").replace("’", " ")

        if created:
            logger.info(f"[CREATE] Champ '{nom_champ_sans_apostrophe}' (id: {obj.id}) créé.")
        else:
            updated_fields = update_fields(obj, {
                "nom": ch["nom"],
                "id_champ_type_id": ch["id_champ_type"],
                "description": ch["description"],
                # "id_demarche_id": ch.get("id_demarche"),
                "requis": ch["requis"],
            })

            if updated_fields:
                obj.save()
                champs = ", ".join(updated_fields).replace("'", " ").replace("’", " ")
                logger.info(f"[SAVE] Champ '{nom_champ_sans_apostrophe}' mis à jour. Champs modifiés : {champs}.")
