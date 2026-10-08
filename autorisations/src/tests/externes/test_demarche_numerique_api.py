import os
import tempfile
from unittest import skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase

from DS.graphql_client import GraphQLClient
from DS.service_status import (
    get_statut_demarche_numerique,
    signaler_disponibilite_demarche_numerique,
    signaler_indisponibilite_demarche_numerique,
)


@skipUnless(
    os.getenv("RUN_LIVE_API_TESTS") == "1",
    "Test réel désactivé ; définir RUN_LIVE_API_TESTS=1 pour l'activer.",
)
class DemarcheNumeriqueLiveTests(SimpleTestCase):
    def setUp(self):
        logger_patcher = patch("DS.graphql_client.logger")
        logger_patcher.start()
        self.addCleanup(logger_patcher.stop)

    def test_api_disponible_et_token_valide(self):
        client = GraphQLClient()

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".graphql",
            encoding="utf-8",
            delete=False,
        ) as fichier:
            fichier.write("query Healthcheck { __typename }")
            chemin = fichier.name

        try:
            resultat = client.execute_query(chemin)
        finally:
            os.unlink(chemin)

        self.assertEqual(resultat.get("data", {}).get("__typename"), "Query")
