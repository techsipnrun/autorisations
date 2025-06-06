from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import Instructeur
from instruction.utils import enregistrer_action
from ..utils.model_helpers import update_fields, foreign_keys_add_suffixe_id
from ..utils.fichiers import create_emplacement, write_geojson
from django.db import models
from datetime import date, datetime
import logging

logger = logging.getLogger('SYNCHRONISATION')

def sync_doss(dossier):
    """
    Synchronise un objet Dossier à partir des données D-S.

    { "id_ds", "id_etat_dossier", "id_demarche", "numero", "id_groupeinstructeur", 
    "date_depot", "date_fin_instruction", "id_dossier_type", 
    "note", "nom_dossier", "emplacement", "date_limite_traitement", "geometrie" }

    """
    defaults = foreign_keys_add_suffixe_id(Dossier, dossier)

    obj, created = Dossier.objects.get_or_create(
        id_ds=dossier["id_ds"],
        numero=dossier["numero"],
        defaults=defaults
    )

    if created:
        logger.info(f"[CREATE] Dossier {obj.numero} (id_ds: {obj.id_ds}) créé.")

        # Création des folders
        create_emplacement(defaults["emplacement"])

        # Write geojson
        write_geojson(f"{obj.emplacement}/Carto", f"{obj.numero}.geojson",obj.geometrie)

        instructeur = Instructeur.objects.first()
        # Dossier Action 'Dossier reçu'
        enregistrer_action(obj, instructeur, "Dossier reçu", date=dossier['date_depot'])

    else:
        update_data = {}

        for field, new_value in dossier.items():
            model_field = getattr(obj.__class__, field, None)
            field_name = f"{field}_id" if isinstance(getattr(model_field, 'field', None), models.ForeignKey) else field
            update_data[field_name] = new_value if isinstance(new_value, (date, datetime)) else new_value

        updated_fields = update_fields(
            obj,
            update_data,
            date_fields=[k for k, v in dossier.items() if isinstance(v, (date, datetime))]
        )

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] Dossier {obj.numero} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
            if "geometrie" in updated_fields :
                # Write geojson
                write_geojson(f"{obj.emplacement}/Carto", f"{obj.numero}.geojson",obj.geometrie)
        # else:
        #     logger.info(f"[NO CHANGE] Dossier {obj.numero} inchangé.")

    return obj.id
