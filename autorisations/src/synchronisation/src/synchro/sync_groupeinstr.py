import logging
from autorisations.models.models_utilisateurs import GroupeinstructeurDemarche, Instructeur
from ..utils.model_helpers import update_fields

logger = logging.getLogger("SYNCHRONISATION")

def sync_groupeinstructeurs_demarches(gi_demarche_list):
    for gi in gi_demarche_list["gi"]:
        obj, created = GroupeinstructeurDemarche.objects.get_or_create(
            id_demarche_id=gi["id_demarche"],
            id_groupeinstructeur_id=gi["id_groupeinstructeur"],
            defaults={"id_groupeinstructeur_ds": gi.get("id_groupeinstructeur_ds")}
        )
        if created:
            logger.info(f"[CREATE] GroupeinstructeurDemarche (Groupe {gi['id_groupeinstructeur']} - Demarche {gi['id_demarche']}) créé.")
        else:
            updated_fields = update_fields(obj, {"id_groupeinstructeur_ds": gi.get("id_groupeinstructeur_ds")})
            if updated_fields:
                obj.save()
                logger.info(f"[SAVE] GroupeinstructeurDemarche {obj.id} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
    
    for i in gi_demarche_list["i"]:
        
        obj, created = Instructeur.objects.get_or_create(
            email=i["email"],
            defaults={"id_ds": i["id_instructeur_ds"]}
        )
        if created:
            logger.info(f"[CREATE] Instructeur {obj} créé.")
        else:
            updated_fields = update_fields(obj, {"id_ds": i["id_instructeur_ds"]})
            if updated_fields:
                obj.save()
                logger.info(f"[SAVE] Instructeur {obj.id} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
