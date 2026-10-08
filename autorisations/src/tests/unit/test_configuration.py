import logging
import os
import socket
from unittest.mock import patch
from unittest import SkipTest

from django.conf import settings
from django.test import SimpleTestCase

from tests.support.isolation import isoler_environnement
from tests.support.database import require_postgresql_tests


class IsolationTests(SimpleTestCase):
    def test_pas_de_connexions_applicatives_configurees(self):
        if settings.TEST_POSTGRESQL_ENABLED:
            self.skipTest("Configuration PostgreSQL activée explicitement.")
        self.assertEqual(set(settings.DATABASES), {"default"})
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(settings.DATABASES["default"]["NAME"], ":memory:")

    def test_mails_en_memoire_et_notifications_reelles_desactivees(self):
        self.assertEqual(settings.EMAIL_BACKEND, "django.core.mail.backends.locmem.EmailBackend")
        self.assertFalse(settings.NOTIFS_PROD)
        self.assertEqual(settings.EMAIL_NOTIF_TEST, "notifications@example.test")

    def test_pas_de_logs_applicatifs_sur_disque(self):
        for nom in ("SYNCHRONISATION", "MAIL", "APP", "API_DS", "API_DM"):
            with self.subTest(logger=nom):
                self.assertFalse(any(isinstance(h, logging.FileHandler) for h in logging.getLogger(nom).handlers))

    def test_dotenv_ne_charge_aucun_fichier(self):
        import dotenv
        with isoler_environnement():
            self.assertFalse(dotenv.load_dotenv(".env.prod"))
            self.assertEqual(dotenv.dotenv_values(".env.prod"), {})

    def test_connexions_et_resolution_externes_bloquees(self):
        with patch.dict(os.environ, {"RUN_DB_TESTS": "0", "RUN_LIVE_API_TESTS": "0"}), isoler_environnement():
            with self.assertRaisesMessage(RuntimeError, "Accès réseau externe interdit"):
                socket.getaddrinfo("externe.example.test", 443)
            with socket.socket() as sock:
                with self.assertRaises(RuntimeError):
                    sock.connect(("192.0.2.1", 443))
                with self.assertRaises(RuntimeError):
                    sock.connect_ex(("192.0.2.1", 443))

    def test_resolution_locale_autorisee(self):
        with patch.dict(os.environ, {"RUN_DB_TESTS": "0", "RUN_LIVE_API_TESTS": "0"}), isoler_environnement():
            self.assertTrue(socket.getaddrinfo("127.0.0.1", 8000))

    def test_tests_bdd_desactives_sans_drapeau(self):
        with patch.dict(os.environ, {"RUN_DB_TESTS": "0"}):
            with self.assertRaises(SkipTest):
                require_postgresql_tests()

    def test_drapeau_bdd_seul_ne_suffit_pas_sans_configuration_dediee(self):
        with patch.dict(os.environ, {"RUN_DB_TESTS": "1"}), self.settings(TEST_POSTGRESQL_ENABLED=False):
            with self.assertRaisesMessage(RuntimeError, "base test_autorisations"):
                require_postgresql_tests()
