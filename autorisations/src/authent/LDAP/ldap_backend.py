import os
import django
from pathlib import Path
from dotenv import load_dotenv
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
        """ Authentifie l'utilisateur et le synchronise dans Django """
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

                # 🔹 Rechercher l'utilisateur dans LDAP
                search_filter = f"(&(objectClass=user)(sAMAccountName={username}))"
                conn.search(self.LDAP_BASE_DN, search_filter, attributes=["cn", "mail", "memberOf"])

                if conn.entries:
                    entry = conn.entries[0]
                    email = entry.mail.value if hasattr(entry, 'mail') else f"{username}@pnrun.local"

                    # Il faudrait que tous les agents parcs aient leurs emails dans l'ad ou dans une table de reference postgres
                    # if not email :
                    #     email = 'louis.calu@reunion-parcnational.fr'

                    # Vérifier si l'utilisateur existe dans Django, sinon le créer
                    user, created = User.objects.get_or_create(username=username, defaults={'email': email})
                    
                    # Synchroniser les groupes LDAP avec Django
                    self.sync_user_groups(user, entry.memberOf)

                    if created:
                        logger.info(f"Utilisateur Django créé : {username}")
                    return user
                else:
                    logger.warning(f"Utilisateur {username} trouvé dans AD mais sans informations exploitables.")

            logger.warning(f"Échec de l'authentification LDAP pour : {username}")
            return None

        except Exception as e:
            logger.error(f"Erreur LDAP : {str(e)}")
            return None

    def sync_user_groups(self, user, ldap_groups):
        """ Synchronise les groupes LDAP avec Django """
        logger.info(f"🔄 Synchronisation des groupes AD-Django pour {user.username}")

        # 🔹 Effacer tous les groupes Django de l'utilisateur
        user.groups.clear()

        for ldap_group in ldap_groups:
            group_name = ldap_group.split(",")[0].replace("CN=", "")  # Extraire le nom du groupe
            group, created = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)

            if created:
                logger.info(f"Création du groupe Django : {group_name}")

        user.save()

    def get_user(self, user_id):
        """ Récupère un utilisateur Django par son ID """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
         

    def connect_admin_ldap(self):
        """ Établit une connexion LDAP avec les identifiants admin """
        admin_dn = os.environ.get('USER_LDAP_ADMIN')
        admin_password = os.environ.get('PASSWORD_LDAP_ADMIN')
        logger.info("  ")

        if not admin_dn or not admin_password:
            logger.error("Identifiants LDAP admin non définis dans les variables d'environnement.")
            return None

        server = Server(self.LDAP_SERVER, get_info=ALL)
        try:
            conn = Connection(server, user=admin_dn, password=admin_password, authentication=SIMPLE, auto_bind=True)

            if conn.bind():
                logger.info(f"Connexion admin LDAP réussie avec {admin_dn}.")
                return conn
            else:
                logger.error(f"Échec de connexion admin LDAP avec {admin_dn}.")
                return None

        except core.exceptions.LDAPBindError as e:
            logger.error(f"Erreur d'authentification LDAP pour {admin_dn} : {e}")
            return None
        
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la connexion LDAP : {e}")
            return None


    def get_user_dn(self, conn, username):
        """ Récupère le DN d'un utilisateur LDAP """
        search_filter = f"(&(objectClass=user)(sAMAccountName={username}))"
        conn.search(self.LDAP_BASE_DN, search_filter, attributes=["distinguishedName"])

        if conn.entries:
            user_dn = str(conn.entries[0].distinguishedName.value)
            return user_dn
        else:
            logger.error(f"Aucun DN trouvé pour {username}.")
            return None

    def get_group_dn(self, conn, group_name):
        """ Récupère le DN d'un groupe LDAP """
        search_filter = f"(&(objectClass=group)(cn={group_name}))"
        conn.search(self.LDAP_GROUP_BASE_DN, search_filter, attributes=["distinguishedName"])

        if conn.entries:
            group_dn = str(conn.entries[0].distinguishedName.value)
            return group_dn
        else:
            logger.error(f"Le groupe {group_name} n'existe pas dans LDAP.")
            return None

    def add_user_to_group(self, username, group_name):
        """ Ajoute un utilisateur LDAP à un groupe LDAP """
        conn = self.connect_admin_ldap()
        if not conn:
            return False

        user_dn = self.get_user_dn(conn, username)
        if not user_dn:
            return False

        group_dn = self.get_group_dn(conn, group_name)
        if not group_dn:
            return False

        print('userdn : ',user_dn, ' ---   groupdn : ', group_dn)
        modify_response = conn.modify(group_dn, {'member': [(MODIFY_ADD, [user_dn])]})
        
        if modify_response:
            logger.info(f"✅ Utilisateur {username} ajouté au groupe AD {group_name}.")
            #rappeler sync_user_groups ici
            return True
        else:
            logger.error(f"Échec de l'ajout de {username} au groupe AD {group_name}.")
            logger.error(f"Erreur LDAP : {conn.result}")
            return False

    def remove_user_from_group(self, username, group_name):
        """ Supprime un utilisateur LDAP d'un groupe LDAP """
        conn = self.connect_admin_ldap()
        if not conn:
            return False

        user_dn = self.get_user_dn(conn, username)
        if not user_dn:
            return False

        group_dn = self.get_group_dn(conn, group_name)
        if not group_dn:
            return False

        modify_response = conn.modify(group_dn, {'member': [(MODIFY_DELETE, [user_dn])]})

        if modify_response:
            logger.info(f"Utilisateur {username} retiré du groupe AD {group_name}.")
            #rappeler sync_user_groups ici
            return True
        else:
            logger.warning(f"Échec du retrait de {username} du groupe {group_name}.")
            logger.error(f"Erreur LDAP : {conn.result}")
            return False
