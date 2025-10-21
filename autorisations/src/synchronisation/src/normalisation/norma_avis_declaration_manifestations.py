def avis_declaration_manifestations_normalize(list_avis):
    """
    Normalise la liste des avis manif_sportive à partir des données brutes récupérées via l'API de déclaration-manifestations.

    :return: Liste de dictionnaires, chacun représentant un avis_manif_sportive et ses composants associés
    """
    avis_manifs_sportives = []
    for a in list_avis :

            avis_manifs_sportives.append(
                {
                    "id_avis_manif_sportive": a.get("id"),
                    "id_dossier_manif_sportive": a.get("manif_id"),
                    "etat": a.get("etat"),
                    "service": a.get("service"),
                    "date_demande": a.get("date_demande"),
                    "date_reponse": a.get("date_reponse"),
                    "reponse_avis": a.get("reponse_avis"),
                    "prescriptions": "",    #laisse vide par défaut car GET /Avis/ ne renvoi pas cet attribut (alors que GET /Avis/{{ID_AVIS}}/ oui)
                    "objet_demande": a.get("objet_demande_str"),

                }
            )
    return avis_manifs_sportives





