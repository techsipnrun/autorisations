from .pg_functions import *


def synchro_process (dico):
    sync_demarche(dico["demarche"])
   
    pass




def sync_demarche(demarche_ds):
    """
     demarche_ds = {
        "id_ds"
        "numero"
        "titre"
        "id_etat"
        "date_creation"
        "date_derniere_modif"
        "description"
    }
    """


