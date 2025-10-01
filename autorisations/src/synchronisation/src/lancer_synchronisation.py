import os
import sys
import django
import logging
from django.conf import settings



# Ajouter le chemin vers la racine du projet
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
sys.path.insert(0, BASE_DIR)

# Initialisation Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "autorisations.settings")
django.setup()

# Configuration manuelle du logger "SYNCHRONISATION"
logging.config.dictConfig(settings.LOGGING)
logger = logging.getLogger("SYNCHRONISATION")


# Lancement du traitement
try:
    from synchronisation.src.main import lancer_normalisation_et_synchronisation
    lancer_normalisation_et_synchronisation()
except Exception as e:
    from autorisations.models.models_instruction import SynchronisationEtat
    import traceback
    err_msg = traceback.format_exc()
    logger.error("Une erreur est survenue lors de la synchronisation :\n" + err_msg)
    SynchronisationEtat.objects.get(id=1).update(en_cours=False)
