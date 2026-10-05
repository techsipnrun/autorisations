"""Définition centralisée des colonnes configurables de la vue d'ensemble."""


TABLEAU_EN_COURS = "en_cours"
TABLEAU_ARCHIVES = "archives"
TABLEAU_MES_DOSSIERS = "mes_dossiers"
TABLEAU_RECEPTION_DM = "reception_dm"
TABLEAU_RECEPTION_DN = "reception_dn"
TABLEAU_RECEPTION_COMPLET = "reception_complet"


def colonnes_vue_ensemble(type_demarche):
    """Retourne les colonnes disponibles, dans l'ordre d'affichage."""
    est_manifestation = (type_demarche or "").lower() == "manifestations sportives"
    colonnes_communes = [
        ("dossier", "Dossier"),
        ("numero", "Numéro"),
        ("demandeur", "Demandeur"),
    ]
    libelle_date_activite = "Début activité"

    tableaux = {
        TABLEAU_EN_COURS: [
            *colonnes_communes,
            ("date_reception", "Reçu le"),
            ("groupe_instructeur", "Groupe instructeur"),
            ("date_activite", libelle_date_activite),
            ("etape", "Étape"),
        ],
        TABLEAU_ARCHIVES: [
            *colonnes_communes,
            ("date_reception", "Déposé le"),
            ("groupe_instructeur", "Groupe instructeur"),
            ("date_activite", libelle_date_activite),
            ("etape", "Étape"),
        ],
        TABLEAU_MES_DOSSIERS: [
            *colonnes_communes,
            ("date_reception", "Reçu le"),
            ("date_activite", libelle_date_activite),
            ("mon_role", "Mon rôle"),
            ("etape", "Étape"),
        ],
    }
    if est_manifestation:
        tableaux.update({
            TABLEAU_RECEPTION_DM: [
                ("nom_manifestation", "Nom de la manifestation"),
                ("organisateur", "Organisateur"),
                ("numero_dm", "N° DM"),
                ("date_debut_evenement", "Début activité"),
                ("coeur_de_parc", "Cœur de parc"),
                ("date_reception", "Reçu le"),
                ("mails_relance", "Mails de relance"),
            ],
            TABLEAU_RECEPTION_DN: [
                ("nom_manifestation", "Nom de la manifestation"),
                ("organisateur", "Organisateur"),
                ("numero_dn", "N° DN"),
                ("date_debut_manifestation", "Début activité"),
                ("date_reception", "Reçu le"),
                ("numero_dm_renseigne", "N° DM renseigné"),
            ],
            TABLEAU_RECEPTION_COMPLET: [
                ("nom_manifestation", "Nom de la manifestation"),
                ("organisateur", "Organisateur"),
                ("date_debut_manifestation", "Début activité"),
                ("coeur_de_parc", "Cœur de parc"),
                ("numero_dn", "N° DN"),
                ("numero_dm", "N° DM"),
                ("date_reception", "Dossier complet reçu le"),
            ],
        })
    return tableaux


def configurations_colonnes_vue_ensemble(type_demarche, configurations=()):
    """Applique les réglages sauvegardés aux colonnes par défaut."""
    configurations_par_colonne = {
        (configuration.tableau, configuration.colonne): configuration
        for configuration in configurations
    }

    def libelle_personnalise(configuration):
        return (getattr(configuration, "libelle_personnalise", "") or "").strip()

    resultat = {}
    for tableau, colonnes in colonnes_vue_ensemble(type_demarche).items():
        colonnes_configurees = []
        for ordre_defaut, (identifiant, libelle) in enumerate(colonnes):
            configuration = configurations_par_colonne.get((tableau, identifiant))
            ordre = getattr(configuration, "ordre", None)
            colonnes_configurees.append({
                "id": identifiant,
                "libelle": libelle_personnalise(
                    configurations_par_colonne.get((tableau, identifiant))
                ) or libelle,
                "libelle_standard": libelle,
                "libelle_personnalise": libelle_personnalise(
                    configurations_par_colonne.get((tableau, identifiant))
                ),
                "affiche": getattr(configuration, "affiche", True),
                "ordre": ordre,
                "ordre_defaut": ordre_defaut,
            }
            )
        resultat[tableau] = sorted(
            colonnes_configurees,
            key=lambda colonne: (
                colonne["ordre"] is None,
                colonne["ordre"] if colonne["ordre"] is not None else colonne["ordre_defaut"],
            ),
        )
    return resultat


def colonnes_visibles(type_demarche, configurations=()):
    """Retourne un dictionnaire ``colonne -> bool`` par tableau."""
    return {
        tableau: {colonne["id"]: colonne["affiche"] for colonne in colonnes}
        for tableau, colonnes in configurations_colonnes_vue_ensemble(
            type_demarche, configurations
        ).items()
    }


def libelles_colonnes(type_demarche, configurations=()):
    """Retourne les libellés effectivement affichés, par tableau."""
    return {
        tableau: {colonne["id"]: colonne["libelle"] for colonne in colonnes}
        for tableau, colonnes in configurations_colonnes_vue_ensemble(
            type_demarche, configurations
        ).items()
    }
