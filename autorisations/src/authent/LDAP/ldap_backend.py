import os
import django
from pathlib import Path
from dotenv import load_dotenv
from django.contrib.auth import login
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User, Group
from ldap3 import MODIFY_ADD, MODIFY_DELETE, Server, Connection, SIMPLE, ALL, core
import logging

# Spécifie le module de configuration Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "autorisations.settings")

# Charge Django
django.setup()

# Charge les variables d'environnements
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENVIRONMENT = os.getenv("DJANGO_ENV", "dev")  # dev par défaut, DJANGO_ENV=prod python manage.py runserver pour lancer en prod
dotenv_path = BASE_DIR / f".env.{ENVIRONMENT}"
load_dotenv(dotenv_path)

# Spécifie le fichier de logs
logger = logging.getLogger("LDAP_LOGS")

class LDAPBackend(BaseBackend):
    """
    Backend d'authentification LDAP personnalisé pour Django.
    Permet d'authentifier les utilisateurs AD et de synchroniser leurs groupes.
    """

    LDAP_SERVER = os.environ.get('LDAP_SERVER')
    LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN')
    LDAP_USER_DN_FORMAT = "{username}@pnrun.local"
    LDAP_GROUP_BASE_DN = os.environ.get('LDAP_GROUP_BASE_DN')  # Emplacement des groupes LDAP

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authentifie l'utilisateur et le synchronise dans Django
        """

        logger.info("  ")
        logger.info(f"Tentative de connexion LDAP pour : {username}")

        if not username or not password:
            logger.warning("Identifiants manquants pour l'authentification LDAP.")
            return None

        user_dn = self.LDAP_USER_DN_FORMAT.format(username=username)
        server = Server(self.LDAP_SERVER, get_info=ALL)

        try:
            conn = Connection(server, user=user_dn, password=password, authentication=SIMPLE, auto_bind=True)
            if conn.bind():
                logger.info(f"Connexion LDAP réussie pour : {username}")

                # Rechercher l'utilisateur dans LDAP
                search_filter = f"(&(objectClass=user)(sAMAccountName={username}))"
                conn.search(self.LDAP_BASE_DN, search_filter, attributes=["cn", "mail", "memberOf", "givenName", "sn"])

                if conn.entries:
                    entry = conn.entries[0]
                    prenom = entry.givenName.value
                    nom = entry.sn.value
                    email = entry.mail.value if entry.mail.value != None else f"{prenom.lower()}.{nom.lower()}@reunion-parcnational.fr"
                    
                    # Vérifier si l'utilisateur existe dans Django, sinon le créer
                    user, created = User.objects.get_or_create(username=username)
                    user.email = email
                    user.set_password(password)  # ← sécurise le mot de passe via hash
                    user.save()

                    if created:
                        logger.info(f"Utilisateur Django créé : {username}")
                  
                    return user
                else:
                    logger.warning(f"Utilisateur {username} trouvé dans l'AD mais sans informations exploitables.")

            logger.warning(f"Échec de l'authentification LDAP pour : {username}")
            return None

        except Exception as e:
            message = str(e)
            if "invalidCredentials" in message:
                logger.warning(f"{username} : échec de l'authentification — identifiants invalides.")
            else:
                logger.error(f"Erreur LDAP : {message}")
            return None


    # fonction à laisser sinon l'authent n'est pas transmise dans l'app
    def get_user(self, user_id):
        """ Récupère un utilisateur Django par son ID """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
