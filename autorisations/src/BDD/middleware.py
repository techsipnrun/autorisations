from datetime import datetime
import json
import logging
import os
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.authtoken.models import Token
from rest_framework.request import Request
from rest_framework.parsers import JSONParser

logger = logging.getLogger('API_PG')


"""
Pour appeler depuis l'invite de commande :

curl -X POST http://127.0.0.1:8000/api_autorisations/v1/avis_thematique/ ^
  -H "Authorization: monToken" ^
  -H "Content-Type: application/json" ^
  -d "{\"thematique\": \"testdepuisCurl\"}"

"""


class API_PG_LogMiddleware:
    """
    Middleware pour tracer tous les appels à l'API.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.token_auth = TokenAuthentication()
        self.session_auth = SessionAuthentication()

    def __call__(self, request):
        # Log de la requête

        if request.path.startswith(f"/{os.environ.get('API_PG_URL')}"):  # Cible uniquement les endpoints API
            user = self.get_authenticated_user(request)  # Récupérer l'utilisateur
            logger.info(f"[Requete] {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} {request.method} {request.path} | Utilisateur: {user}")

        # Forcer Django REST Framework à utiliser l'utilisateur authentifié
        request._force_auth_user = request.user 

        # Processus de la réponse
        response = self.get_response(request)

        # Log de la réponse
        if request.path.startswith(f"/{os.environ.get('API_PG_URL')}"):
            logger.info(f"[Réponse] {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} {response.status_code} | {response.content.decode()[:100]}...")
            logger.info("------------------------------------------------")
        return response
    
    def get_authenticated_user(self, request):
        """
        Récupère l'utilisateur authentifié en gérant `TokenAuthentication`.
        """
        # Vérifier si `request.user` est déjà défini par Django
        if request.user.is_authenticated:
            return request.user.username

        # Vérifier si un Token est présent dans l'en-tête `Authorization`
        auth_token = request.headers.get("Authorization", "")
        if auth_token :
            try:
                token = Token.objects.get(key=auth_token)  # Vérifier si le token existe
                request.user = token.user
                return token.user.username  # Retourne le nom de l'utilisateur
            except Token.DoesNotExist:
                return "Token Invalide"
        if not auth_token and not request.user.is_authenticated :
            return "Utilisateur non connecté"
        return "Anonyme"  # Si aucun utilisateur n'est trouvé
    
