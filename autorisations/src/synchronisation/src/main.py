from django.utils import timezone
import logging
from DS.call_DS import recup_data_DS
from BDD.pg_functions import get_number_demarche_Postgres
from autorisations.models.models_instruction import Demarche, SynchronisationEtat
from notifications.service import envoi_notif_mails_nouveaux_dossiers
from .synchro.sync_process import synchro_process
from .normalisation.normalize_main import normalize_process

logger = logging.getLogger('SYNCHRONISATION')

# def lancer_normalisation_et_synchronisation():
#     logger.info("\n\n")
#     logger.info("LANCEMENT SYNCHRONISATION \n")
    
#     numeros_demarche = get_number_demarche_Postgres()
#     dico_notifs = {}
#     for num in numeros_demarche:
#         datas_DS = recup_data_DS(num)
#         if datas_DS :
#             resultats = normalize_process(datas_DS["demarche"])
#             synchro_process(resultats, dico_notifs)
#         else :
#             SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="erreur")

    
#     if dico_notifs :
#         envoi_notif_mails_nouveaux_dossiers(dico_notifs)
    
#     logger.info("")
#     logger.info("FIN SYNCHRONISATION \n")


def lancer_normalisation_et_synchronisation():
    logger.info("\n\n")
    logger.info("LANCEMENT SYNCHRONISATION \n")
    
    numeros_demarche = get_number_demarche_Postgres()
    dico_notifs = {}
    success = True  # <-- suivi du statut global

    for num in numeros_demarche:
        try:
            datas_DS = recup_data_DS(num)
            if datas_DS == False:
                logger.error("Retour False de recup_data_DS")
                success = False
                continue  # ne pas lever d'erreur globale, on continue les autres démarches

            resultats = normalize_process(datas_DS["demarche"])
            synchro_process(resultats, dico_notifs)

        except Exception as e:
            logger.exception(f"Erreur lors de la synchronisation de la démarche {num}: {e}")
            success = False

    if dico_notifs:
        envoi_notif_mails_nouveaux_dossiers(dico_notifs)

    # --- Mise à jour du statut global ---
    if success:
        SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="ok", date_maj=timezone.now())
    else:
        logger.error("ON MET dernier_statut=erreur")
        SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="erreur")

    logger.info("FIN SYNCHRONISATION\n")
    return success





#  A ADAPTER
def lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche):
    demarche = Demarche.objects.get(numero=num_demarche)
    
    logger.info("\n\n")
    logger.info(f"SYNCHRONISATION {demarche.type.upper()} \n")
    dico_notifs = {}

    datas_DS = recup_data_DS(num_demarche)
    if datas_DS :
        resultats = normalize_process(datas_DS["demarche"])
        synchro_process(resultats, dico_notifs)

    else :
        SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="erreur")

    if dico_notifs :
        envoi_notif_mails_nouveaux_dossiers(dico_notifs)

    logger.info("")
    logger.info(f"FIN SYNCHRONISATION {demarche.type.upper()} \n")