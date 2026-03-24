import json
import logging

from .utils import formattage_geojson
from .get_methods import get_access_token, get_all_avis, get_dossier_by_id, get_geojson

loggerDM = logging.getLogger("API_DM")
loggerSynchro = logging.getLogger("SYNCHRONISATION")

def main():

    # Récupère le token
    token = get_access_token()

    # Récupération de tous les avis
    avis_list = get_all_avis(token)
    """
    [
        {
            "id": 877770,
            "etat": "termine",
            "reponse_avis": "favorable",
            "service": "PN La Réunion (974)",
            "date_demande": "2026-02-23T08:26:22.828663+01:00",
            "date_reponse": "2026-03-06",
            "manif_id": 106328,
            "objet_demande_str": null
        }, ...
    ]
    """
    loggerDM.info(f"{len(avis_list)} avis au total")
    loggerSynchro.info(f"{len(avis_list)} avis au total")

    # Détails pour chaque dossier
    dossiers = []
    avis_echantillon = []
    unique_numeros = []


    # avis_list = get_all_avis(token)

    avis_filtres = [
        avis for avis in avis_list
        if not (
            avis.get("reponse_avis") is not None
            or avis.get("etat") in ["caduc", "termine"]
        )
    ]

    loggerSynchro("\n avis_filtres :")
    loggerSynchro(avis_filtres)


    loggerDM.info(f"On récupère un échantillon test de dossiers")
    for avis in avis_filtres:
        #
        # EXCLURE ici les avis deja rendu (reponse_avis not null) ET (etat avis = caduc ou = termine)
        #
        manif_id = avis["manif_id"]
        date_demande = avis.get("date_demande", "")

        # Filtrer uniquement les avis 2026
        if (not date_demande.startswith("2026")) :
            continue

        # filtre sur un seul trail pour TEST
        # if manif_id != 93165 :
        #     continue

        avis_echantillon.append(avis)

      
        # if avis["date_demande"][:7] == '2025-05' :  #and avis["manif_id"] == 65866 

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
                    loggerDM.error(f"Problème lors de la récupération du Geojson sur Déclaration Manifestations {dossier['nom']} ({dossier['pk']}) : Geojson vide")
                    dossier["geometrie"] = None
                #
                # On ajoute ici que si : date du jour < date de fin de la manif  ET  etat dossier != annulée
                # Si ca respecte pas cette condition, on log en warning
                #
                dossiers.append(dossier)

            else :
                loggerDM.warning(f"Le dossier {dossier['nom']} ({dossier['pk']}) est en double sur Déclaration Manifestations")
 
    loggerDM.info(f"{len(dossiers)} dossier(s) récupéré(s) sur Déclaration manifestations")
    loggerSynchro.info(f"{len(dossiers)} dossier(s) récupéré(s) sur Déclaration manifestations")

    loggerDM.info(f"{len(avis_echantillon)} avis récupéré(s) sur Déclaration manifestations")
    loggerSynchro.info(f"{len(avis_echantillon)} avis récupéré(s) sur Déclaration manifestations")

    return dossiers, avis_echantillon


def recup_un_seul_dossier(manif_id):

    # Récupère le token
    token = get_access_token()

    dossier = get_dossier_by_id(token, manif_id)
    if dossier:
            
        loggerDM.info(f"Dossier {dossier.get('nom')} récupéré")

        if "description" in dossier and dossier["description"]:
            dossier["description"] = dossier["description"].replace("\n", " ").replace("\r", "") 
    
        # On récupère le geojson
        geojson = get_geojson(token, manif_id)

        # Formattage du geojson
        if geojson :
            geojson = formattage_geojson(geojson)
            dossier["geometrie"] = geojson
        else :
            loggerDM.error(f"Problème lors de la récupération du Geojson sur Déclaration Manifestations {dossier['nom']} ({dossier['pk']}) : Geojson vide")
            dossier["geometrie"] = None
        

    return [dossier]
