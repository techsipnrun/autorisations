from autorisations.models.models_instruction import Demarche
from .sync_demarche import sync_demarche
from .sync_groupeinstr import sync_groupeinstructeurs_demarches
from .sync_champ import sync_champs
from .sync_dossiers import sync_dossiers
import logging

def synchro_process(dico):
    
    logger = logging.getLogger("SYNCHRONISATION")
    logger.info('')

     # Récupération du type de la démarche à partir du titre
    try:
        demarche_obj = Demarche.objects.get(titre=dico['demarche']['titre'])
        logger.info(f"------ Démarche {demarche_obj.type} ------")
    except Demarche.DoesNotExist:
        logger.warning(f"Aucune démarche trouvée avec le titre : {dico['demarche']['titre']}")
    except Demarche.MultipleObjectsReturned:
        logger.warning(f"Plusieurs démarches trouvées avec le titre : {dico['demarche']['titre']}")


    sync_demarche(dico["demarche"])
    sync_groupeinstructeurs_demarches(dico["groupeinstructeurs_demarches"])
    sync_champs(dico["champs"])
    sync_dossiers(dico["dossiers"])
