import json
import logging
import sys
import os
import django

from autorisations.models.models_instruction import Demarche
from DS.graphql_client import GraphQLClient


# Spécifie le fichier de logs
logger = logging.getLogger("API_DS")


def init_setup():
    '''
    Init Setup Django pour run le file dans le terminal
    '''

    CURRENT_DIR = os.path.dirname(__file__)
    SRC_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))  # src/
    
    sys.path.append(SRC_DIR)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "autorisations.settings")

    django.setup()



def get_number_demarche_Postgres():
    """
        Récupère sur Postgres le numéro 'Démarches-Simplifiées' de nos démarches
    """

    # Récupérer toutes les démarches avec leur numéro
    demarches = Demarche.objects.all().values('numero', 'titre')

    list_number_demarches = []

    # Affichage dans la console
    for d in demarches:
        list_number_demarches.append(d['numero'])

    return list_number_demarches





def recup_data_DS(number):
    '''
    Récupère les informations interessantes pour une démarche via l'API D-S

    Args:
        number : numéro de la démarche
    '''

    client = GraphQLClient()

    # Query graphQL
    query_file = "DS/queries/get_all.graphql"

    # Initialisation dictionnaire
    list_demarches_DS = []

 
    try:
        response = client.execute_query(query_file, {"number": number})
    except Exception as e:
        logger.error(f"Erreur : {e}")
    
    # list_demarches_DS.append(response["data"])
    # return list_demarches_DS

    # Ecriture Json pour check
    # output_file = "DS/response_ds.json"
    # with open(output_file, "w", encoding="utf-8") as f:
    #     json.dump(response["data"], f, ensure_ascii=False, indent=4)
    # print(f"Données enregistrées dans {output_file}")

    return response["data"]



if __name__ == "__main__":

    init_setup()
    # numero_demarche = get_number_demarche_Postgres()
    # from DS.graphql_client import GraphQLClient
    # from autorisations.models.models_instruction import Demarche

    # datas_DS = recup_data_DS(numero_demarche)

