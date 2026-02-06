import os
from autorisations.models.models_instruction import Demarche
from .sync_declaration_manifestations import sync_declaration_manifestations
from .sync_avis_declaration_manifestations import sync_avis_declaration_manifestations
from .sync_demarche import sync_demarche
from .sync_groupeinstr import sync_groupeinstructeurs_demarches
from .sync_champ import sync_champs
from .sync_dossiers import sync_dossiers
import logging
import time

def synchro_process(dico, dico_notifs, demarche_obj):
    
    logger = logging.getLogger("SYNCHRONISATION")
    logger.info('')
    statut = True

    ####################################
    #####    DEMARCHE NUMERIQUE    #####
    ####################################
    t_ds = time.perf_counter()
    try :
        sync_demarche(dico["demarche"])
        sync_groupeinstructeurs_demarches(dico["groupeinstructeurs_demarches"])
        sync_champs(dico["champs"])
        sync_dossiers(dico["dossiers"], demarche_obj.numero, False, dico_notifs)
    except Exception as e:
        logger.error(f"Échec lors de la synchronisation Démarches Simplifiées ({demarche_obj.type}) : {e}")
        # On ne bloque pas tout le process, mais on note l'erreur
        statut = False

    t_synchro = time.perf_counter() - t_ds
    logger.info(f"-- Synchronisation DS faite en {t_synchro:.2f} sec --")



    ###########################################
    #####    DECLARATION MANIFESTATION    #####
    ###########################################
    if os.getenv("SYNCHRO_DM", "false") == "True" :
        
        t_dm = time.perf_counter()
        if demarche_obj.type.lower() == 'manifestations sportives':

            try:
                logger.info(f"------ SYNCHRONISATION Déclaration Manifestations ------")
                # Dossier
                logger.info("------- Dossiers Manif sportives -------")

                for doss in dico["manif_sportives"] :
                    sync_declaration_manifestations(doss, logger)
                
                

            except Exception as e:
                logger.error(f"Erreur lors de la synchronisation des Dossiers de Manifestation Sportives : {e}")
                statut = False

            try:
                # Avis
                logger.info("----")
                logger.info("------- Avis Manif sportives -------")
                for avis in dico["avis_manif_sportives"] :
                    sync_avis_declaration_manifestations(avis, logger)
                    
            except Exception as e:
                logger.error(f"Erreur lors de la synchronisation des Avis de Manifestation Sportives : {e}")
                statut = False


            t_API_dm = time.perf_counter() - t_dm
            logger.info(f"-- Synchronisation (DM) faite en {t_API_dm:.2f} sec --")
            logger.info("------------------------------------------------\n")


    return statut