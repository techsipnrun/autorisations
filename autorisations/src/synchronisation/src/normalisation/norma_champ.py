from autorisations.models.models_instruction import ChampType, Champ, Demarche
from synchronisation.src.functions import get_first_id


def champ_normalize(d):
    """
    Normalise les champs d'une démarche pour les préparer à l'insertion ou mise à jour dans la base.
    :param d: Données brutes de la démarche
    :return: Liste de dictionnaires normalisés représentant les champs
    """
    liste_ch = []
    for ch in d["champDescriptors"]:
        liste_ch.append({
            "id_ds": ch["id"],
            "nom": ch["label"],
            "id_champ_type": get_first_id(ChampType, type=ch["type"]),
            "description": ch["description"],
            "id_demarche": get_first_id(Demarche, id_ds=d["id"], numero=d["number"]),
            "requis": ch["required"],
        })

    return liste_ch
