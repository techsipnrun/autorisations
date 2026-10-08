"""Paramètres isolés : aucun chargement des fichiers .env de l'application."""
import os
from unittest.mock import patch

# Réutiliser les applications/templates, sans importer les connexions réelles.
with patch("dotenv.load_dotenv"), patch("dotenv.dotenv_values", return_value={}), patch.dict(
    os.environ, {"NOTIF_PROD": "false", "EMAIL_NOTIF_TEST": "notifications@example.test"},
):
    from autorisations.settings import *  # noqa: F403

SECRET_KEY = "tests-only-not-for-deployment"
ENVIRONMENT = "test"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
TEST_POSTGRESQL_ENABLED = False
TEST_RUNNER = "tests.runner.IsolatedTestRunner"
# Les modèles PostgreSQL autorisent varchar sans longueur ; SQLite ne sert
# ici qu'à isoler les tests sans SQL, et ne doit pas bloquer leur découverte.
SILENCED_SYSTEM_CHECKS = ["fields.E120"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "agida@example.test"
DEFAULT_FROM_EMAIL_DEMANDEUR = DEFAULT_FROM_EMAIL
NOTIFS_PROD = False
EMAIL_NOTIF_TEST = "notifications@example.test"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
# Les tests ne doivent pas écrire de faux événements dans les logs applicatifs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"]},
    "loggers": {
        name: {"handlers": ["null"], "propagate": False}
        for name in ("LDAP_LOGS", "API_DS", "API_PG", "API_DM", "ORM_DJANGO", "SYNCHRONISATION", "APP", "MAIL")
    },
}
