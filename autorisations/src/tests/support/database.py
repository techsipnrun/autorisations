"""Garde-fou des anciens tests ORM nécessitant les schémas PostgreSQL."""
import os
from unittest import SkipTest

from django.conf import settings


def require_postgresql_tests():
    if os.getenv("RUN_DB_TESTS") != "1":
        raise SkipTest("Tests BDD désactivés : utiliser RUN_DB_TESTS=1 et tests.settings_postgresql.")
    config = settings.DATABASES["default"]
    if (not getattr(settings, "TEST_POSTGRESQL_ENABLED", False)
            or config["ENGINE"] != "django.db.backends.postgresql"
            or config["NAME"] != "test_autorisations"
            or config.get("TEST", {}).get("NAME") != "test_autorisations"):
        raise RuntimeError("Les tests BDD exigent tests.settings_postgresql et la base test_autorisations.")
