from .dossier import dossier_normalize
from .contacts_externes import contact_externe_normalize
from .dossier_interlocuteur import dossier_interlocuteur_normalize
from .dossier_champs import dossiers_champs_normalize
from .dossier_document import dossier_document_normalize
from .messages import message_normalize
from .demandes import demande_normalize
from synchronisation.src.functions import get_first_id
from autorisations.models.models_instruction import Demarche, Dossier


def dossiers_normalize_process(d):
    """
    Normalise la liste des dossiers d'une démarche à partir des données brutes.
    :param d: Données brutes d'une démarche
    :return: Liste de dictionnaires, chacun représentant un dossier et ses composants associés
    """

    id_demarche = get_first_id(Demarche, id_ds=d["id"], numero=d["number"])
    dossiers = []

    for doss in d["dossiers"]["nodes"]:
        id_dossier = get_first_id(Dossier, id_ds=doss["id"], numero=doss["number"])

        dico_dossier = {
            "dossier": dossier_normalize(id_demarche, doss),
            "contacts_externes": contact_externe_normalize(doss),
            "dossier_interlocuteur": dossier_interlocuteur_normalize(doss, id_dossier),
            "dossier_champs": dossiers_champs_normalize(doss, id_dossier),
            "dossier_document": dossier_document_normalize(doss),
            "messages": message_normalize(doss, id_dossier),
            "demandes": demande_normalize(id_demarche, d["title"], doss, id_dossier)
        }

        dossiers.append(dico_dossier)

    return dossiers
