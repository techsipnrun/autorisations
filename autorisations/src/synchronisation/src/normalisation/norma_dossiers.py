from .norma_dossier import dossier_normalize
from .norma_contacts_externes import contact_externe_normalize
from .norma_dossier_interlocuteur import dossier_interlocuteur_normalize
from .norma_dossier_champs import dossiers_champs_normalize
from .norma_dossier_document import dossier_document_normalize
from .norma_messages import message_normalize
from .norma_demandes import demande_normalize
from synchronisation.src.utils.model_helpers import get_first_id
from synchronisation.src.utils.fichiers import construire_emplacement_dossier
from autorisations.models.models_instruction import Demarche


def dossiers_normalize_process(d):
    """
    Normalise la liste des dossiers d'une démarche à partir des données brutes.
    :param d: Données brutes d'une démarche
    :return: Liste de dictionnaires, chacun représentant un dossier et ses composants associés
    """

    id_demarche = get_first_id(Demarche, id_ds=d["id"], numero=d["number"])
    dossiers = []

    for doss in d["dossiers"]["nodes"]:

        contact_beneficiaire = doss["demandeur"]
        titre_demarche = d["title"]

        #Construction du chemin du dossier (sans le créer physiquement)
        emplacement_dossier = construire_emplacement_dossier(doss, contact_beneficiaire, titre_demarche)

        dico_dossier = {
            "dossier": dossier_normalize(id_demarche, doss, emplacement_dossier),
            "contacts_externes": contact_externe_normalize(doss),
            "dossier_interlocuteur": dossier_interlocuteur_normalize(doss),
            "dossier_champs": dossiers_champs_normalize(doss, emplacement_dossier),
            "dossier_document": dossier_document_normalize(doss, emplacement_dossier),
            "messages": message_normalize(doss, emplacement_dossier),
            "demandes": demande_normalize(id_demarche, titre_demarche, doss)
        }

        dossiers.append(dico_dossier)

    return dossiers
