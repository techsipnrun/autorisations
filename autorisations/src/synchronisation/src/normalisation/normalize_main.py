import logging
from .norma_avis_declaration_manifestations import avis_declaration_manifestations_normalize
from .norma_declaration_manifestations import dossiers_declaration_manifestations_normalize
from .norma_demarche import demarche_normalize
from .norma_groupeinstructeur_demarche import groupeinstructeur_demarche_normalize
from .norma_champ import champ_normalize
from .norma_dossiers import dossiers_normalize_process
from declaration_manifestations import call_api_dm
import time

logger = logging.getLogger('SYNCHRONISATION')

def normalize_process(d, demarche_obj):
    """
    Normalise toutes les structures de données d'une démarche.
    """
    statut = True

    
    manif_sportives = None
    avis_manif_sportives = None
    
    try :
        """
        ##### MANIF SPORTIVE #####
        if "Manifestations sportives" in d["title"] :
            logger.info("Récupération des données sur Déclaration Manifestations...")
            
            try:
                t_api_start = time.perf_counter()
                dic_dm, list_avis = call_api_dm.main()
                t_api_dm = time.perf_counter() - t_api_start
                logger.info(f"Récupération des données Déclaration Manifestations faite en {t_api_dm:.2f} secondes\n")

            except Exception as e:
                logger.error(f"Échec lors de la récupération des données via l'API Déclaration Manifestations : {e}")
                # On ne bloque pas tout le process, mais on note l'erreur
                dic_dm, list_avis = [], []
                statut = False


            # Normalisation des données DM
            try:
                if dic_dm :
                    manif_sportives = dossiers_declaration_manifestations_normalize(dic_dm)
                if list_avis :
                    avis_manif_sportives = avis_declaration_manifestations_normalize(list_avis)

            except Exception as e:
                logger.error(f"Erreur pendant la normalisation des données Déclaration Manifestations : {e}")
                manif_sportives = None
                avis_manif_sportives = None
                statut = False
        """

        try:
            demarche_norm = demarche_normalize(d)
            groupeinstr_norm = groupeinstructeur_demarche_normalize(d)
            champs_norm = champ_normalize(d)
            dossiers_norm = dossiers_normalize_process(d)
        except Exception as e:
            logger.exception(f"Erreur lors de la normalisation DS ({demarche_obj.type}): {e}")
            statut = False
        

        return {
                "statut": statut,
                "demarche": demarche_norm,
                "groupeinstructeurs_demarches": groupeinstr_norm,
                "champs": champs_norm,
                "dossiers": dossiers_norm,
                "manif_sportives": manif_sportives,
                "avis_manif_sportives": avis_manif_sportives,
            }

    except Exception as e:
        logger.exception(f"Erreur lors du processus de Normalisation ({demarche_obj.type}) : {e}")
        raise
        
    
