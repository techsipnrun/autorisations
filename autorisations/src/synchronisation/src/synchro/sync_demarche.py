import logging
from autorisations.models.models_instruction import Demarche
from functions import update_fields, clean_date

logger = logging.getLogger("ORM_DJANGO")

def sync_demarche(demarche_ds):
    demarche_obj, created = Demarche.objects.get_or_create(
        id_ds=demarche_ds["id_ds"],
        numero=demarche_ds["numero"],
        defaults={
            "titre": demarche_ds["titre"],
            "id_etat_id": demarche_ds["id_etat"],
            "date_creation": demarche_ds["date_creation"],
            "date_derniere_modif": demarche_ds["date_derniere_modif"],
            "description": demarche_ds.get("description", "")
        }
    )

    if created:
        logger.info(f"[CREATE] Demarche {demarche_obj.numero} - {demarche_obj.titre} créée.")
    else:
        updated_fields = update_fields(demarche_obj, {
            "titre": demarche_ds["titre"],
            "id_etat_id": demarche_ds["id_etat"],
            "date_creation": clean_date(demarche_ds["date_creation"]),
            "date_derniere_modif": clean_date(demarche_ds["date_derniere_modif"]),
        }, date_fields=["date_creation", "date_derniere_modif"])

        if updated_fields:
            demarche_obj.save()
            logger.info(f"[SAVE] Demarche {demarche_obj.numero} mise à jour. Champs modifiés : {', '.join(updated_fields)}.")
        else:
            logger.info(f"[NO CHANGE] Demarche {demarche_obj.numero} inchangée.")