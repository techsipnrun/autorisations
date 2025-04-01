from .sync_demarche import sync_demarche
from .sync_groupeinstr import sync_groupeinstructeurs_demarches
from .sync_champ import sync_champs
from .sync_dossiers import sync_dossiers

def synchro_process(dico):
    import logging
    logger = logging.getLogger("ORM_DJANGO")
    logger.info("\n ----------------- \n")

    sync_demarche(dico["demarche"])
    sync_groupeinstructeurs_demarches(dico["groupeinstructeurs_demarches"])
    sync_champs(dico["champs"])
    sync_dossiers(dico["dossiers"])
