import logging
from django.db import models

from autorisations.models.models_instruction import DossierChamp
from synchronisation.utils.conversion import parse_datetime_with_tz



def get_first_id(model, **filters):
    """
    Renvoie le premier ID d’un objet correspondant aux filtres donnés.
    :param model: Le modèle Django à interroger
    :param filters: Les champs de filtrage (ex: nom="Jean", type="pdf")
    :return: L'ID (int) ou None
    """
    return model.objects.filter(**filters).values_list("id", flat=True).first()




def update_fields(obj, data: dict, date_fields: list = []):
    logger = logging.getLogger("SYNCHRONISATION")
    updated = []
    for field, new_val in data.items():
        old_val = getattr(obj, field)
        if field in date_fields:
            old_val = parse_datetime_with_tz(old_val)
            new_val = parse_datetime_with_tz(new_val)

        if old_val != new_val and str(old_val) != str(new_val):
            
            # logger.warning('-------------')
            # logger.warning(f"{field}")
            # logger.warning(f"old val : {old_val}")
            # logger.warning(f"new val : {new_val}")
            # logger.warning('-------------')

            setattr(obj, field, new_val)
            updated.append(field)
    return updated


def update_fields_dossier_champs(obj, data: dict, date_fields: list = []):
    logger = logging.getLogger("SYNCHRONISATION")
    updated = []
    num_doss_dm = {}
    for field, new_val in data.items():
        old_val = getattr(obj, field)
        if field in date_fields:
            old_val = parse_datetime_with_tz(old_val)
            new_val = parse_datetime_with_tz(new_val)

        if old_val != new_val and str(old_val) != str(new_val):
            setattr(obj, field, new_val)
            updated.append(field)

            # Recupérer l'ancien numéro de dossier DM (Manif Sportives)
            if isinstance(obj, DossierChamp):
                if obj.id_champ.nom == "Numéro du dossier sur la plateforme déclaration-manifestations" and field == 'valeur':
                    num_doss_dm = {'old_num_dossDM': old_val, 'new_num_dossDM': new_val}

                if obj.id_champ.nom.startswith("Choix de la méthode pour localiser") and field == 'valeur':
                    if "Fournir une pièce justificative" in obj.valeur :
                        # Changement du Choix de la méthode pour localiser le projet (module carto --> PJ)
                        logger.info("switch carto --> pj")
                        setattr(obj, 'geometrie_a_saisir', False)
                        updated.append('geometrie_a_saisir')
                        
                    
    return updated, num_doss_dm




def foreign_keys_add_suffixe_id(model_class, data):
    logger = logging.getLogger('SYNCHRONISATION')
    corrected = {}
    for field, value in data.items():
        if hasattr(model_class, field):
            model_field = getattr(model_class, field)
            if hasattr(model_field, 'field') and isinstance(model_field.field, models.ForeignKey):
                corrected[f"{field}_id"] = value
            else:
                corrected[field] = value
        else:
            corrected[field] = value
    return corrected
