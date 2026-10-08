import os
from unittest import skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase

from declaration_manifestations import get_methods


@skipUnless(
    os.getenv("RUN_LIVE_API_TESTS") == "1",
    "Test réel désactivé ; définir RUN_LIVE_API_TESTS=1 pour l'activer.",
)
class DeclarationManifestationsLiveTests(SimpleTestCase):
    def setUp(self):
        logger_patcher = patch("declaration_manifestations.get_methods.loggerDM")
        logger_patcher.start()
        self.addCleanup(logger_patcher.stop)

    def test_api_disponible_et_identifiants_valides(self):
        token = get_methods.get_access_token()

        self.assertIsInstance(token, str)
        self.assertTrue(token.strip())
