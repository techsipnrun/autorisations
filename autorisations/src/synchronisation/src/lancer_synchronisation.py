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
    from autorisations.models.models_instruction import SynchronisationEtat
    from synchronisation.src.main import lancer_normalisation_et_synchronisation
    
    etat = SynchronisationEtat.objects.filter(id=1).first()
    if etat and not etat.en_cours:
        etat.en_cours = True
        etat.save()


    ok = lancer_normalisation_et_synchronisation()
    sys.exit(0 if ok else 1)

except KeyboardInterrupt:
        logger.warning("Interruption manuelle (Ctrl+C). Fin propre du script.")
        SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="erreur")
        sys.exit(130)
        
except Exception as e:
    from autorisations.models.models_instruction import SynchronisationEtat
    import traceback
    err_msg = traceback.format_exc()
    logger.error("Une erreur est survenue lors de la synchronisation :\n" + err_msg)
    SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="erreur")
    sys.exit(1)

