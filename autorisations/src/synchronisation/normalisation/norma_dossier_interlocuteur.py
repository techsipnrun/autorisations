def dossier_interlocuteur_normalize(doss):
    """
    Normalise les données du DossierInterlocuteur (retourne simplement l'id DS du demandeur).
    """

    return {
        "id_interlocuteur_ds": doss["usager"]["id"],
        # "id_demandeur_intermediaire": id_demandeur_intermediaire,
    }
