import json
import logging

from .utils import formattage_geojson
from .get_methods import get_access_token, get_all_avis, get_dossier_by_id, get_geojson

loggerDM = logging.getLogger("API_DM")

def main():

    # Récupère le token
    token = get_access_token()

    # Récupération de tous les avis
    avis_list = get_all_avis(token)
    loggerDM.info(f"{len(avis_list)} avis récupérés")

    # Détails pour chaque dossier
    dossiers = []
    loggerDM.info(f"On récupère un échantillon test de dossiers")
    unique_numeros = []

    for avis in avis_list:
        manif_id = avis["manif_id"]

        # Pour le test on prend que les dossiers déposés en mai 2025 ici
        if avis["date_demande"][:7] == '2025-05' :  #and avis["manif_id"] == 65866 

            dossier = get_dossier_by_id(token, manif_id)
            if dossier:
                if "description" in dossier and dossier["description"]:
                    dossier["description"] = dossier["description"].replace("\n", " ").replace("\r", "") 
                
                if dossier["pk"] not in unique_numeros:

                    unique_numeros.append(dossier["pk"])
                    # On récupère le geojson
                    geojson = get_geojson(token, manif_id)

                    # Formattage du geojson
                    if geojson :
                        geojson = formattage_geojson(geojson)
                        dossier["geometrie"] = geojson
                    else :
                        loggerDM.error(f"Problème lors de la récupération du Geojson sur Déclaration Manifestations {dossier["nom"]} ({dossier["pk"]}) : Geojson vide")
                        dossier["geometrie"] = None
                    
                    dossiers.append(dossier)

                else :
                    loggerDM.warning(f"Le dossier {dossier["nom"]} ({dossier["pk"]}) est en double sur Déclaration Manifestations")


           
            

            geojson_str = json.dumps(geojson)
            # Afficher au plus 200 caractères (tronqués proprement)
            print(geojson_str[:200] + ("..." if len(geojson_str) > 200 else ""))

            

    loggerDM.info(f"{len(dossiers)} dossier(s) récupéré(s) sur Déclaration manifestations")

    return dossiers
