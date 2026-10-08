import logging

from autorisations.models.models_instruction import (
    DemarcheDateActiviteChamp,
    DemarcheNomDossierRegle,
    DemarcheNomDossierElement,
    Dossier,
    DossierManifestationLiaison,
)
from autorisations.models.models_utilisateurs import Instructeur
from instruction.utils.dossier_utils import check_si_on_casse_liaison_dm, safe_enregistrer_action
from .sync_dossier import sync_doss
from .sync_contacts_externes import sync_contacts_externes
from .sync_dossier_interlocuteur import sync_dossier_interlocuteur
from .sync_dossier_beneficiaire import sync_dossier_beneficiaire
from .sync_dossier_champs import sync_dossier_champs
from .sync_dossier_document import sync_dossier_document
from .sync_messages import sync_messages
from .sync_demandes import sync_demandes
from django.db import transaction
from django.db.models import Prefetch
from synchronisation.utils.nom_dossier import (
    compiler_regles_nommage, construire_contexte_nommage, generer_nom_dossier,
)


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

    # Une seule requête, quel que soit le nombre de dossiers traités. La liste
    # est ensuite passée à chaque synchronisation de champs de la démarche.
    date_activite_champs = list(
        DemarcheDateActiviteChamp.objects.filter(
            id_demarche__numero=demarche_number,
        )
        .order_by("ordre", "id")
        .select_related("id_champ")
    )
    regles_nommage = compiler_regles_nommage(
        DemarcheNomDossierRegle.objects.filter(id_demarche__numero=demarche_number)
        .prefetch_related(Prefetch(
            "elements", queryset=DemarcheNomDossierElement.objects.select_related("id_champ"),
        ))
    )
    champs_dm_nommage = {
        element["champ_dm"] for regle in regles_nommage for element in regle["elements"]
        if element["type"] == "champ_dm"
    }
    valeurs_dm_par_numero_dn = {}
    if champs_dm_nommage and dossiers_list:
        champs_values = [f"id_dossier_manif__{champ}" for champ in champs_dm_nommage]
        for liaison in DossierManifestationLiaison.objects.filter(
            id_dossier__numero__in=[doss["dossier"]["numero"] for doss in dossiers_list],
        ).values("id_dossier__numero", *champs_values):
            valeurs_dm_par_numero_dn[liaison["id_dossier__numero"]] = {
                champ: liaison.get(f"id_dossier_manif__{champ}")
                for champ in champs_dm_nommage
            }

    # On repère les dossiers supprimés sur Démarche Numérique
    ids_ds_recus = set(doss['dossier']['id_ds'] for doss in dossiers_list)

    # Pour ces dossiers on passe 'present_sur_ds' à False
    dossiers_a_desactiver = Dossier.objects.filter(
        present_sur_ds=True,
        id_demarche__numero=demarche_number
    ).exclude(id_ds__in=ids_ds_recus)

    numeros_a_desactiver = list(dossiers_a_desactiver.values_list('numero', flat=True))
    
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

      
                # -----------------------------------------------------------------------
                # DOSSIER DN SUPPRIMÉ : ON REGARDE SI ON CASSE LA LIAISON (MANIF SPORTIVE)
                # -----------------------------------------------------------------------

                liaison_dossDN = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()
                if liaison_dossDN :
                    dossier_dm = liaison_dossDN.id_dossier_manif
                    try :
                        check_si_on_casse_liaison_dm(dossier, dossier_dm, liaison_dossDN, logger)
                    except Exception as e :
                        logger.warning(f"[DOSSIER {dossier.numero} SUPPRIMÉ DE DN] Erreur lors de la tentative de suppression de la DossierManifestationLiaison. On continue la synchro.")
               


    for doss in dossiers_list:
        contexte_nom = construire_contexte_nommage(
            doss["dossier"], doss["contacts_externes"], doss["dossier_champs"],
            dossier_dm=valeurs_dm_par_numero_dn.get(doss["dossier"]["numero"]),
        )
        doss["dossier"]["nom_dossier_genere"] = generer_nom_dossier(
            regles_nommage, contexte_nom,
        )["nom_genere"]
        id_dossier = sync_doss(doss['dossier'], dico_notifs, doss['dossier_champs'])
        ids_beneficiaire_intermediaire = sync_contacts_externes(doss['contacts_externes'])

        id_dossier_interlocuteur = sync_dossier_interlocuteur(doss['dossier_interlocuteur'], ids_beneficiaire_intermediaire, id_dossier)

        sync_dossier_beneficiaire(ids_beneficiaire_intermediaire, id_dossier_interlocuteur)

        try :
            resultat_champs = sync_dossier_champs(doss['dossier_champs'], id_dossier, date_activite_champs=date_activite_champs,)
            if resultat_champs and not resultat_champs["success"]:
                logger.warning(
                    "[DOSSIER %s PARTIELLEMENT SYNCHRONISÉ] %s PJ non récupérée(s) : %s. "
                    "Poursuite de la synchronisation des documents, messages et demandes.",
                    doss['dossier']['numero'], len(resultat_champs["pj_en_erreur"]),
                    "; ".join(f"{pj['champ']} : {pj['titre']}" for pj in resultat_champs["pj_en_erreur"]),
                )
        except Exception as e:
            logger.error(f"ERROR dans sync_dossier_champs : {e}")

        sync_dossier_document(doss['dossier_document'], id_dossier)

        sync_messages(doss['messages'], id_dossier)
        sync_demandes(doss['demandes'], id_dossier)
