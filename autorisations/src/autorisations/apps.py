import os
import warnings
from django.apps import AppConfig
from django.db import OperationalError
from .utils.nas_config import configurer_smb
from django.utils import timezone
import logging
import threading


class AutorisationsConfig(AppConfig):
    name = "autorisations"
    _init_done = False

    def ready(self):
        
        # Protection contre reload multiples
        # if self._init_done or os.environ.get("RUN_MAIN") != "true":
        #     return
        # self._init_done = True

        # Configuration de la connexion au NAS
        configurer_smb()

        # loggerSynchro = logging.getLogger("SYNCHRONISATION")

        # # Attention ici ca fait planter car ca re rend cliquable les boutons synchro meme si elle deja en cours
        # # le ready() de AppConfig s’exécute à chaque fois qu’un processus Django démarre, pas seulement au lancement du serveur.

        # active_threads = [t.name for t in threading.enumerate()]
        # if any("SYNCHRO" in name.upper() for name in active_threads):
        #     loggerSynchro.warning("⏳ Thread de synchronisation actif — reset flag annulé.")
        #     return
        

        # # --- Reset du flag uniquement si aucun thread actif ---
        # from autorisations.models.models_instruction import SynchronisationEtat

        # try:
        #     with warnings.catch_warnings():
        #         warnings.filterwarnings("ignore", category=RuntimeWarning)
        #         SynchronisationEtat.objects.filter(en_cours=True).update(en_cours=False)
        # except OperationalError:
        #     loggerSynchro.warning("⚠️ Base non disponible au démarrage — flag synchro non réinitialisé.")
        # except Exception as e:
        #     loggerSynchro.error(f"⚠️ Impossible de réinitialiser le flag : {e}")
