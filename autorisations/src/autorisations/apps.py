import warnings
from django.apps import AppConfig
from django.db import OperationalError
from .utils.nas_config import configurer_smb
from django.utils import timezone
import logging


class AutorisationsConfig(AppConfig):
    name = "autorisations"

    def ready(self):
        # Configuration de la connexion au NAS
        configurer_smb()


        loggerSynchro = logging.getLogger("SYNCHRONISATION")

        # Attention ici ca fait planter car ca re rend cliquable les boutons synchro meme si elle deja en cours
        
        # Reset Flag de synchro 
        # from autorisations.models.models_instruction import SynchronisationEtat

        # try:
        #     with warnings.catch_warnings():
        #         warnings.filterwarnings("ignore", category=RuntimeWarning)
        #         SynchronisationEtat.objects.filter(en_cours=True).update(en_cours=False)
        # except OperationalError:
        #     loggerSynchro.warning("⚠️ Base non disponible au démarrage — flag synchro non réinitialisé.")
        # except Exception as e:
            # loggerSynchro.error(f"⚠️ Impossible de réinitialiser le flag : {e}")
