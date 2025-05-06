from pathlib import Path
import requests
import json
import logging
from dotenv import load_dotenv
import os

load_dotenv()

# Spécifie le fichier de logs
logger = logging.getLogger("API_DS")

class GraphQLClient:

    def __init__(self):
        """
        Initialise le client avec les paramètres de configuration.
        """
        
        self.url = os.environ.get('API_URL')
        self.token = os.environ.get('API_TOKEN')

        

        
    def execute_query(self, query_file, variables=None):
        """
        Exécute une requête GraphQL à partir d'un fichier et renvoie le résultat.

        :param query_file: Chemin du fichier contenant la requête GraphQL.
        :param variables: Dictionnaire contenant les variables pour la requête.
        :return: Réponse JSON de l'API.
        """
        try:
            # Charger la requête
            with open(query_file, 'r') as file:
                query = file.read()

            headers = {"Authorization": f"Bearer {self.token}"}
            payload = {"query": query, "variables": variables or {}}

            # Envoyer la requête
            response = requests.post(self.url, json=payload, headers=headers)

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Erreur lors de la requête {query_file} : {response.status_code} - {response.text}")
                raise Exception(f"Erreur {response.status_code}: {response.text}")
        except Exception as e:
            logger.exception(f"Erreur lors de l'exécution de la requête {query_file} : {e}")
            raise
