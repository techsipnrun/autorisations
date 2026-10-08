"""Intégration PostgreSQL volontaire, sur une base de test dédiée et préparée."""
import os

from .settings import *  # noqa: F403

if os.getenv("RUN_DB_TESTS") != "1":
    raise RuntimeError("Définir RUN_DB_TESTS=1 pour autoriser les tests PostgreSQL.")

# Ne jamais reprendre BDD_* ni les fichiers .env.dev/.env.prod.
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "test_autorisations",
    "HOST": os.environ["TEST_PG_HOST"],
    "PORT": os.getenv("TEST_PG_PORT", "5432"),
    "USER": os.environ["TEST_PG_USER"],
    "PASSWORD": os.environ["TEST_PG_PASSWORD"],
    "OPTIONS": {"options": "-c search_path=public,avis,documents,instruction,utilisateurs"},
    "TEST": {"NAME": "test_autorisations"},
}}
TEST_POSTGRESQL_ENABLED = True
SILENCED_SYSTEM_CHECKS = []
