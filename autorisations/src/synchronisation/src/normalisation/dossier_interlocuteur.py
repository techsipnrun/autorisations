from synchronisation.src.functions import get_first_id, clean_email
from autorisations.models.models_utilisateurs import ContactExterne, TypeContactExterne


def dossier_interlocuteur_normalize(doss, id_dossier):
    """
    Normalise les données du DossierInterlocuteur à partir d’un dossier DS.
    """

    if doss.get("prenomMandataire") is None and doss.get("nomMandataire") is None:
        id_demandeur_intermediaire = None
    else:
        id_type_inter = get_first_id(TypeContactExterne, type="demandeur_intermediaire")
        id_demandeur_intermediaire = get_first_id(
            ContactExterne,
            email=clean_email(doss["usager"]["email"]),
            id_type=id_type_inter
        )

    return {
        "id_interlocuteur_ds": doss["usager"]["id"],
        "id_demandeur_intermediaire": id_demandeur_intermediaire,
        "id_dossier": id_dossier,
    }
