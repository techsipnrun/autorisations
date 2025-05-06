def demarche_normalize(d):
    from datetime import datetime
    from autorisations.models.models_instruction import EtatDemarche
    from synchronisation.src.utils.model_helpers import get_first_id, parse_datetime_with_tz

    return {
        "id_ds": d["id"],
        "numero": d["number"],
        "titre": d["title"],
        "id_etat": get_first_id(EtatDemarche, nom=d["state"]),
        "date_creation": parse_datetime_with_tz(d["dateCreation"]),
        "date_derniere_modif": parse_datetime_with_tz(d["dateDerniereModification"]),
    }
