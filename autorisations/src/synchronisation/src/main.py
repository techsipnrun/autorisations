import logging
from DS.call_DS import recup_data_DS
from BDD.pg_functions import get_number_demarche_Postgres
from .synchro.sync_process import synchro_process
from .normalisation.normalize_main import normalize_process

logger = logging.getLogger('SYNCHRONISATION')

def lancer_normalisation_et_synchronisation():
    logger.info("\n\n")
    logger.info("LANCEMENT SYNCHRONISATION \n")
    
    numeros_demarche = get_number_demarche_Postgres()
    for num in numeros_demarche:
        datas_DS = recup_data_DS(num)
        resultats = normalize_process(datas_DS["demarche"])
        synchro_process(resultats)
    
    logger.info("")
    logger.info("FIN SYNCHRONISATION \n")


def lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche):
    datas_DS = recup_data_DS(num_demarche)
    resultats = normalize_process(datas_DS["demarche"])
    synchro_process(resultats)