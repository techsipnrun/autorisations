import logging
from .sync_dossier import sync_doss
from .sync_contacts_externes import sync_contacts_externes
from .sync_dossier_interlocuteur import sync_dossier_interlocuteur
from .sync_dossier_beneficiaire import sync_dossier_beneficiaire
from .sync_dossier_champs import sync_dossier_champs
from .sync_dossier_document import sync_dossier_document
from .sync_messages import sync_messages
from .sync_demandes import sync_demandes


def sync_dossiers(dossiers_list):
    """
    Synchronise les objets suivants à partir des données récupérées sur D-S.
    [
        {
            'dossier': {...},
            'contacts_externes': {...},
            'dossier_interlocuteur': {...},
            'dossier_beneficiaire': {...},
            'dossier_champs': [...],
            'dossier_document': {...},
            'messages': [...],
            'demandes': [...]
        },
        ...
    ]
    """
    logger = logging.getLogger('SYNCHRONISATION')
    
    for doss in dossiers_list:
        
        logger.info(f"Dossier {doss['dossier']['nom_dossier']}")

        id_dossier = sync_doss(doss['dossier'])
        ids_beneficiaire_intermediaire = sync_contacts_externes(doss['contacts_externes'])
        id_dossier_interlocuteur = sync_dossier_interlocuteur(doss['dossier_interlocuteur'], ids_beneficiaire_intermediaire, id_dossier)
        sync_dossier_beneficiaire(ids_beneficiaire_intermediaire, id_dossier_interlocuteur)
        sync_dossier_champs(doss['dossier_champs'], id_dossier)
        sync_dossier_document(doss['dossier_document'], id_dossier)
        sync_messages(doss['messages'], id_dossier)
        sync_demandes(doss['demandes'], id_dossier)

        logger.info("------------------------------------------------")