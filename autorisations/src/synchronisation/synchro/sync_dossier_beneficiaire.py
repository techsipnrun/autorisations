from autorisations.models.models_utilisateurs import DossierBeneficiaire
import logging

logger = logging.getLogger("SYNCHRONISATION")

def sync_dossier_beneficiaire(ids_beneficiaire_intermediaire, id_dossierInterlocuteur):
    """
    Synchronise un objet DossierBeneficiaire.
    {
        "id_dossier_interlocuteur": int,
        "id_beneficiaire": int
    }
    """
    id_beneficiaire = ids_beneficiaire_intermediaire.get("beneficiaire")
    id_doss_interlocuteur = id_dossierInterlocuteur.get("dossier_interlocuteur")

    if not id_beneficiaire or not id_doss_interlocuteur:
        # print("id_beneficiaire : ", id_beneficiaire)
        # print("id_doss_interlocuteur : ", id_doss_interlocuteur)
        logger.error(f"[ERROR] DossierBeneficiaire ne peut pas être créé (ID du bénéficiaire ({id_beneficiaire}) ou ID du DossierInterlocuteur ({id_doss_interlocuteur}) non trouvé)")
        
    else:
        obj, created = DossierBeneficiaire.objects.get_or_create(
            id_dossier_interlocuteur_id=id_doss_interlocuteur,
            id_beneficiaire_id=id_beneficiaire,
        )

        if created:
            logger.info(f"[CREATE] DossierBeneficiaire (interlocuteur: {id_doss_interlocuteur}, bénéficiaire: {id_beneficiaire}) créé.")