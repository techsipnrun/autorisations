def format_etat_dossier(etat_technique):
    mapping = {
        "sans_suite": "Sans suite",
        "refuse": "Refusé",
        "en_instruction": "En instruction",
        "en_construction": "En pré-instruction",
        "accepte": "Accepté"
    }
    return mapping.get(etat_technique, etat_technique.replace("_", " ").capitalize())
