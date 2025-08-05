from .norma_declaration_manifestations import dossiers_declaration_manifestations_normalize
from .norma_demarche import demarche_normalize
from .norma_groupeinstructeur_demarche import groupeinstructeur_demarche_normalize
from .norma_champ import champ_normalize
from .norma_dossiers import dossiers_normalize_process
from declaration_manifestations import call_api_dm

def normalize_process(d):

    manif_sportives = None
    if "Manifestations sportives" in d["title"] :
        dic_dm = call_api_dm.main()
        manif_sportives = dossiers_declaration_manifestations_normalize(dic_dm)

    return {
        "demarche": demarche_normalize(d),
        "groupeinstructeurs_demarches": groupeinstructeur_demarche_normalize(d),
        "champs": champ_normalize(d),
        "dossiers": dossiers_normalize_process(d),
        "manif_sportives": manif_sportives,
    }
