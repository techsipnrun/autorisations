import logging

from autorisations.models.models_instruction import Dossier
from .sync_dossier import sync_doss
from .sync_contacts_externes import sync_contacts_externes
from .sync_dossier_interlocuteur import sync_dossier_interlocuteur
from .sync_dossier_beneficiaire import sync_dossier_beneficiaire
from .sync_dossier_champs import sync_dossier_champs
from .sync_dossier_document import sync_dossier_document
from .sync_messages import sync_messages
from .sync_demandes import sync_demandes


def sync_dossiers(dossiers_list, demarche_number, un_seul_doss=False):
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

    # On repère les dossiers supprimés sur Démarches Simplifiées
    ids_ds_recus = set(doss['dossier']['id_ds'] for doss in dossiers_list)

    # Pour ces dossiers on passe 'present_sur_ds' à False
    dossiers_a_desactiver = Dossier.objects.filter(
        present_sur_ds=True,
        id_demarche__numero=demarche_number
    ).exclude(id_ds__in=ids_ds_recus)

    numeros_a_desactiver = list(
        dossiers_a_desactiver.values_list('numero', flat=True)
    )
    
    # Lors de la synchro générale, on vérifie d'éventuels décalages entre la BDD et DS
    if not un_seul_doss :
        nb_desactives = dossiers_a_desactiver.update(present_sur_ds=False)

        if nb_desactives > 0:
            apercu = ", ".join(map(str, numeros_a_desactiver[:50]))
            suffixe = " (liste tronquée)" if len(numeros_a_desactiver) > 50 else ""
            logger.info(
                f"<<< {nb_desactives} dossier(s) marqué(s) présent(s) en BDD mais absent(s) de Démarches Simplifiées : "
                f"{apercu}{suffixe} >>>"
            )


    for doss in dossiers_list:
        logger.info(f"Dossier {doss['dossier']['nom_dossier']}")

        id_dossier = sync_doss(doss['dossier'])
        ids_beneficiaire_intermediaire = sync_contacts_externes(doss['contacts_externes'])

        id_dossier_interlocuteur = sync_dossier_interlocuteur(
            doss['dossier_interlocuteur'], ids_beneficiaire_intermediaire, id_dossier
        )

        sync_dossier_beneficiaire(ids_beneficiaire_intermediaire, id_dossier_interlocuteur)
        sync_dossier_champs(doss['dossier_champs'], id_dossier)
        sync_dossier_document(doss['dossier_document'], id_dossier)
        sync_messages(doss['messages'], id_dossier)
        sync_demandes(doss['demandes'], id_dossier)

        logger.info("------------------------------------------------")