def demarche_normalize(d):
    from datetime import datetime
    from autorisations.models.models_instruction import EtatDemarche
    from synchronisation.src.functions import get_first_id

    return {
        "id_ds": d["id"],
        "numero": d["number"],
        "titre": d["title"],
        "id_etat": get_first_id(EtatDemarche, nom=d["state"]),
        "date_creation": datetime.fromisoformat(d["dateCreation"]),
        "date_derniere_modif": datetime.fromisoformat(d["dateDerniereModification"]),
    }
