from django.db import models

from synchronisation.src.utils.conversion import parse_datetime_with_tz



def get_first_id(model, **filters):
    """
    Renvoie le premier ID d’un objet correspondant aux filtres donnés.
    :param model: Le modèle Django à interroger
    :param filters: Les champs de filtrage (ex: nom="Jean", type="pdf")
    :return: L'ID (int) ou None
    """
    return model.objects.filter(**filters).values_list("id", flat=True).first()




def update_fields(obj, data: dict, date_fields: list = []):
    updated = []
    for field, new_val in data.items():
        old_val = getattr(obj, field)
        if field in date_fields:
            old_val = parse_datetime_with_tz(old_val)
            new_val = parse_datetime_with_tz(new_val)

        if old_val != new_val:
            setattr(obj, field, new_val)
            updated.append(field)
    return updated




def foreign_keys_add_suffixe_id(model_class, data):
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
