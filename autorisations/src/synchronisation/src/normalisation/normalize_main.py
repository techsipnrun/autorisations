from .norma_demarche import demarche_normalize
from .norma_groupeinstructeur_demarche import groupeinstructeur_demarche_normalize
from .norma_champ import champ_normalize
from .norma_dossiers import dossiers_normalize_process

def normalize_process(d):
    return {
        "demarche": demarche_normalize(d),
        "groupeinstructeurs_demarches": groupeinstructeur_demarche_normalize(d),
        "champs": champ_normalize(d),
        "dossiers": dossiers_normalize_process(d),
    }
