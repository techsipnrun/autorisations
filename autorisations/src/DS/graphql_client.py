from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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
        self.token = os.environ.get('API_TOKEN_BOITE_AUTO')

        if not self.url:
            raise ValueError("API_URL manquant dans les variables d'environnement")

        if not self.token:
            raise ValueError("API_TOKEN_BOITE_AUTO manquant dans les variables d'environnement")

        
        retry_strategy = Retry(
            total=5,
            connect=5,
            read=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10,
        )

        self.session = requests.Session()
        self.session.trust_env = True
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)


        
    # def execute_query(self, query_file, variables=None):
    #     """
    #     Exécute une requête GraphQL à partir d'un fichier et renvoie le résultat.

    #     :param query_file: Chemin du fichier contenant la requête GraphQL.
    #     :param variables: Dictionnaire contenant les variables pour la requête.
    #     :return: Réponse JSON de l'API.
    #     """
    #     try:
    #         # Charger la requête
    #         with open(query_file, 'r') as file:
    #             query = file.read()

    #         headers = {"Authorization": f"Bearer {self.token}"}
    #         payload = {"query": query, "variables": variables or {}}

    #         # Envoyer la requête
    #         response = requests.post(self.url, json=payload, headers=headers)

    #         if response.status_code == 200:
    #             return response.json()
    #         else:
    #             logger.error(f"Erreur lors de la requête {query_file} : {response.status_code} - {response.text}")
    #             raise Exception(f"Erreur {response.status_code}: {response.text}")
    #     except Exception as e:
    #         logger.error(f"Erreur lors de l'exécution de la requête {query_file} : {e}")
    #         raise

    def execute_query(self, query_file, variables=None):
        try:

            with open(query_file, "r", encoding="utf-8") as file:
                query = file.read()

            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            payload = {
                "query": query,
                "variables": variables or {},
            }

            response = self.session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=(5, 60),
            )

            if response.status_code != 200:
                logger.error(
                    f"Erreur GraphQL {query_file} : "
                    f"{response.status_code} - {response.text[:500]}"
                )
                response.raise_for_status()

            data = response.json()

            if data.get("errors"):
                logger.error(f"Erreurs GraphQL {query_file} : {data['errors']}")
                raise Exception(f"Erreurs GraphQL : {data['errors']}")

            return data

        except requests.exceptions.RequestException as e:
            logger.exception(
                f"Erreur réseau/API lors de l'exécution de {query_file} "
                f"vers {self.url} : {e}"
            )
            raise

        except Exception as e:
            logger.exception(
                f"Erreur lors de l'exécution de la requête {query_file} : {e}"
            )
            raise