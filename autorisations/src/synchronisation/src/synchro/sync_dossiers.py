import logging

from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import Instructeur
from instruction.utils.dossier_utils import safe_enregistrer_action
from .sync_dossier import sync_doss
from .sync_contacts_externes import sync_contacts_externes
from .sync_dossier_interlocuteur import sync_dossier_interlocuteur
from .sync_dossier_beneficiaire import sync_dossier_beneficiaire
from .sync_dossier_champs import sync_dossier_champs
from .sync_dossier_document import sync_dossier_document
from .sync_messages import sync_messages
from .sync_demandes import sync_demandes
from django.db import transaction


def sync_dossiers(dossiers_list, demarche_number, un_seul_doss=False, dico_notifs={}):
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

    # On repère les dossiers supprimés sur Démarche Numérique
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
    if not un_seul_doss and numeros_a_desactiver :
        
        instructeur = Instructeur.objects.order_by("id").first()
        if not instructeur:
            logger.warning(f"[SYNCHRO] Aucun instructeur trouvé en BDD : L'action 'Dossier supprimé de Démarche Numérique' n'a pas été enregistrée.")
        

        with transaction.atomic():
            # on parcourt les dossiers pour mettre à jour present_sur_ds
            for dossier in dossiers_a_desactiver.only("id", "numero", "present_sur_ds").iterator():
                dossier.present_sur_ds = False
                dossier.save(update_fields=["present_sur_ds"])

                logger.warning(f"[DOSSIER SUPPRIMÉ] Le dossier {dossier.numero} n'est plus sur Démarche Numérique")

                # On enregistre l'action
                if instructeur:
                    safe_enregistrer_action(dossier, instructeur, "Dossier supprimé de Démarche Numérique", request=None)
               

        # nb_desactives = len(numeros_a_desactiver)

        # if nb_desactives > 0:
        #     apercu = ", ".join(map(str, numeros_a_desactiver[:50]))
        #     suffixe = " (liste tronquée)" if len(numeros_a_desactiver) > 50 else ""
        #     logger.info(
        #         f"<<< {nb_desactives} dossier(s) marqué(s) présent(s) en BDD mais absent(s) de Démarche Numérique : "
        #         f"{apercu}{suffixe} >>>"
        #     )


    for doss in dossiers_list:

        id_dossier = sync_doss(doss['dossier'], dico_notifs)
        ids_beneficiaire_intermediaire = sync_contacts_externes(doss['contacts_externes'])

        id_dossier_interlocuteur = sync_dossier_interlocuteur(
            doss['dossier_interlocuteur'], ids_beneficiaire_intermediaire, id_dossier
        )

        sync_dossier_beneficiaire(ids_beneficiaire_intermediaire, id_dossier_interlocuteur)
        sync_dossier_champs(doss['dossier_champs'], id_dossier)
        sync_dossier_document(doss['dossier_document'], id_dossier)
        sync_messages(doss['messages'], id_dossier)
        sync_demandes(doss['demandes'], id_dossier)
