from autorisations.models.models_instruction import Demarche
from .sync_declaration_manifestations import sync_declaration_manifestations
from .sync_avis_declaration_manifestations import sync_avis_declaration_manifestations
from .sync_demarche import sync_demarche
from .sync_groupeinstr import sync_groupeinstructeurs_demarches
from .sync_champ import sync_champs
from .sync_dossiers import sync_dossiers
import logging

def synchro_process(dico, dico_notifs):
    
    logger = logging.getLogger("SYNCHRONISATION")
    logger.info('')

    # Récupération du type de la démarche à partir du titre
    try:
        demarche_obj = Demarche.objects.get(titre=dico['demarche']['titre'])
        if demarche_obj.type.lower() == 'manifestations sportives':
            logger.info(f"------ DÉMARCHE {demarche_obj.type.upper()} (Démarches Simplifiées) ------")
        else:
            logger.info(f"------ DÉMARCHE {demarche_obj.type.upper()} ------")
    except Demarche.DoesNotExist:
        logger.warning(f"Aucune démarche trouvée avec le titre : {dico['demarche']['titre']}")
    except Demarche.MultipleObjectsReturned:
        logger.warning(f"Plusieurs démarches trouvées avec le titre : {dico['demarche']['titre']}")


    sync_demarche(dico["demarche"])
    sync_groupeinstructeurs_demarches(dico["groupeinstructeurs_demarches"])
    sync_champs(dico["champs"])

    sync_dossiers(dico["dossiers"], demarche_obj.numero, False, dico_notifs)


    # Manif Sportive
    if demarche_obj.type.lower() == 'manifestations sportives':

        try:
            logger.info(f"------ DÉMARCHE {demarche_obj.type.upper()} (Déclaration Manifestations) ------")

            # Dossier
            # logger.info("")
            logger.info("------- Dossiers Manif sportives -------")
            for doss in dico["manif_sportives"] :
                sync_declaration_manifestations(doss, logger)
            logger.info("------------------------------------------------\n")

        except Exception as e:
            logger.error(f"Erreur lors de la synchronisation des Dossiers de Manifestation Sportives : {e}")

    
        try:
            # Avis
            logger.info("------- Avis Manif sportives -------")
            for avis in dico["avis_manif_sportives"] :
                sync_avis_declaration_manifestations(avis, logger)
                
        except Exception as e:
            logger.error(f"Erreur lors de la synchronisation des Avis de Manifestation Sportives : {e}")