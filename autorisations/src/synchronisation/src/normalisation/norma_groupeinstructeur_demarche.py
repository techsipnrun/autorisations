from autorisations.models.models_instruction import Demarche
from autorisations.models.models_utilisateurs import Groupeinstructeur
from synchronisation.src.utils.model_helpers import get_first_id
import logging

logger = logging.getLogger('ORM_DJANGO')

def groupeinstructeur_demarche_normalize(d):
    """
    Normalise les liaisons entre GroupeInstructeurs et une Démarche.
    :param d: Données démarches brutes
    :return: Liste de dictionnaires normalisés GroupeinstructeurDemarche
    """
    liste_gi = []
    liste_i = []
    emails_vus = set()
    
    for gi in d.get("groupeInstructeurs", []):
        if gi["label"] != 'Groupe inactif':
            id_gi = get_first_id(Groupeinstructeur, nom=gi["label"])

            if not id_gi:
                logger.error(f"[ERROR] L'ID du groupe instructeur {gi['label']} n'a pas été trouvé sur Postgres.")
            else:
                liste_gi.append({
                    "id_demarche": get_first_id(Demarche, id_ds=d["id"], numero=d["number"]),
                    "id_groupeinstructeur": id_gi,
                    "id_groupeinstructeur_ds": gi["id"],
                })
            
            # On récupère les id DS des instructeurs
            for i in gi["instructeurs"]:
                email_instructeur = i["email"]
                id_DS_instructeur = i["id"]

                if email_instructeur not in emails_vus:
                    liste_i.append({
                        "email": email_instructeur,
                        "id_instructeur_ds": id_DS_instructeur
                    })
                    emails_vus.add(email_instructeur)

    return {"gi": liste_gi, 
            "i": liste_i}