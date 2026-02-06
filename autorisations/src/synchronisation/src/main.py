from django.utils import timezone
import logging
from DS.call_DS import recup_data_DS
from BDD.pg_functions import get_number_demarche_Postgres
from autorisations.models.models_instruction import Demarche, SynchronisationEtat
from notifications.service import envoi_notif_mails_nouveaux_dossiers
from .synchro.sync_process import synchro_process
from .normalisation.normalize_main import normalize_process
import time

logger = logging.getLogger('SYNCHRONISATION')


def lancer_normalisation_et_synchronisation():
    logger.info("\n\n")
    logger.info("LANCEMENT SYNCHRONISATION \n")
    
    numeros_demarche = get_number_demarche_Postgres()
    dico_notifs = {}
    success = True  # <-- suivi du statut global

    for num in numeros_demarche:
        try:

            try :
                demarche_obj = Demarche.objects.get(numero=num)
                logger.info('')
                logger.info('')
                if demarche_obj.type.lower() == 'manifestations sportives':
                    # POUR LE MOMENT ON EXCLU MANIFESTATIONS SPORTIVES
                    continue
                    logger.info(f"###### DÉMARCHE {demarche_obj.type.upper()} (Démarches Simplifiées) ######")
                else:
                    logger.info(f"###### DÉMARCHE {demarche_obj.type.upper()} ######")
            except :
                demarche_obj = None
                success = False
                logger.error(f"Échec de la récupération de la Démarche n° {num} en BDD")
                continue

            t0 = time.perf_counter()
            datas_DS = recup_data_DS(num)
            t_API_ds = time.perf_counter() - t0
            logger.info(f"-- Récupération des données (API DS) faite en {t_API_ds:.2f} sec --")

            if datas_DS == False:
                logger.error("ERREUR LORS DE LA RÉCUPÉRATION DES DONNÉES SUR Démarches Simplifiées")
                success = False
                continue  # ne pas lever d'erreur globale, on continue les autres démarches
            
            resultats = normalize_process(datas_DS["demarche"], demarche_obj)
            if not resultats or not resultats.get("statut") :
                success = False
                logger.error("Erreur lors de la normalisation des données Démarches Simplifiées - Déclaration Manifestations")
                
            else :
                s = synchro_process(resultats, dico_notifs, demarche_obj)
                if not s :
                    success = False

                logger.info("------------------------------------------------")

        except Exception as e:
            logger.exception(f"Erreur lors de la synchronisation de la démarche {num}: {e}")
            success = False

    if dico_notifs:
        envoi_notif_mails_nouveaux_dossiers(dico_notifs)

    # --- Mise à jour du statut global ---
    if success:
        # logger.info(" ############## STATUT OK lancer_normalisation_et_synchronisation --> DATE_MAJ mise à jour ################ ")
        SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="ok", date_maj=timezone.now())
    else:
        logger.error("-- Plantage lors de la synchronisation --")
        SynchronisationEtat.objects.filter(id=1).update(en_cours=False, dernier_statut="erreur")
    logger.info('')
    logger.info('')
    logger.info("FIN SYNCHRONISATION\n")
    return success



#  A TESTER
def lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche):
    """
    Lance la synchronisation complète pour une seule démarche.
    Même logique de gestion d'erreurs et de logs que lancer_normalisation_et_synchronisation().
    Retourne True si tout s’est bien passé, False sinon.
    """
    success = True
    dico_notifs = {}
    logger.info("\n\n")

    try:
        # --- Récupération de la démarche ---
        try:
            demarche = Demarche.objects.get(numero=num_demarche)
        except Demarche.DoesNotExist:
            logger.error(f"Échec de synchronisation : la Démarche {demarche.type} est introuvable en base.")
            return False
        except Exception as e:
            logger.exception(f"Erreur lors de la récupération de la démarche {demarche.type} en base : {e}")
            return False



        logger.info(f"###### SYNCHRONISATION DÉMARCHE {demarche.type} ######")

        # --- Récupération des données DS ---
        try:
            t0 = time.perf_counter()
            datas_DS = recup_data_DS(num_demarche)
            t_API_ds = time.perf_counter() - t0
            logger.info(f"-- Récupération des données (API DS) faite en {t_API_ds:.2f} sec --")

            if datas_DS == False:
                logger.error(f"Erreur lors de la récupération des données sur Démarches Simplifiées ({demarche.type})")
                
        except Exception as e:
            logger.error(f"-- Erreur lors de la récupération des données sur Démarches Simplifiées ({demarche.type}) : {e} --")
            return False



        # --- Normalisation ---
        if datas_DS :
            resultats = normalize_process(datas_DS["demarche"], demarche)

            if not resultats or not resultats.get("statut") :
                logger.error(f"Erreur lors de la normalisation ({demarche.type}) Démarches Simplifiées - Déclaration Manifestations")
                return False

            else :
                s = synchro_process(resultats, dico_notifs, demarche)
                if not s :
                    return False


        if dico_notifs :
            envoi_notif_mails_nouveaux_dossiers(dico_notifs)

        logger.info("")
        logger.info(f"FIN SYNCHRONISATION {demarche.type.upper()} \n")

    except KeyboardInterrupt:
        logger.warning("Interruption manuelle (Ctrl+C). Fin propre du script.")
        return False

    except Exception as e:
        logger.error(f"Erreur critique dans lancer_normalisation_et_synchronisation_pour_une_demarche({num_demarche}) : {e}")
        return False