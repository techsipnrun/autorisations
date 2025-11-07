# utils/nas_config.py
import logging
import os
from pathlib import Path
import smbclient
from dotenv import load_dotenv

logger = logging.getLogger("ORM_DJANGO")

#BASE_DIR = autorisations\autorisations\src
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Chemin du fichier .env en fonction de l'environnement
ENVIRONMENT = os.getenv("DJANGO_ENV", "dev")  # dev par défaut, DJANGO_ENV=prod python manage.py runserver pour lancer en prod
dotenv_path = BASE_DIR / f".env.{ENVIRONMENT}"
load_dotenv(dotenv_path)


def configurer_smb():
    """
        Configure la connexion SMB pour accéder au NAS selon le système d'exploitation.
        - Windows : utilise le compte local (ex: admin_auto)
        - Linux   : utilise le compte domaine (ex: admin_auto@pnrun.local)
    """

    # --- Chargement des variables d'environnement ---
    nas_user = os.getenv("NAS_USER", "admin_auto")
    nas_pass = os.getenv("NAS_PASSWORD", "")
    nas_domain = os.getenv("NAS_DOMAIN", "pnrun.local")

    # --- Choix du format du username ---
    if os.system == "Windows":
        username = nas_user
    else:
        # Sur Linux / Debian, on utilise le compte domaine complet
        username = f"{nas_user}@{nas_domain}"

    try :
        smbclient.ClientConfig(username=username, password=nas_pass)
    except Exception as e:
        logger.error(f"[NAS] ⚠️ Erreur lors de la configuration de la connexion de {username} au NAS : {e}")
    
