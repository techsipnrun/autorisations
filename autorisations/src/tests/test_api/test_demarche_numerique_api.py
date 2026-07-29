import os
import tempfile
from unittest import skipUnless
from unittest.mock import MagicMock, mock_open, patch

import requests
from django.test import SimpleTestCase

from DS.graphql_client import GraphQLClient


class GraphQLClientConfigurationTests(SimpleTestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_url_obligatoire(self):
        with self.assertRaisesMessage(ValueError, "API_URL manquant"):
            GraphQLClient()

    @patch.dict(os.environ, {"API_URL": "https://dn.test/graphql"}, clear=True)
    def test_token_obligatoire(self):
        with self.assertRaisesMessage(ValueError, "API_TOKEN_BOITE_AUTO manquant"):
            GraphQLClient()

    @patch("DS.graphql_client.requests.Session")
    @patch.dict(
        os.environ,
        {
            "API_URL": "https://dn.test/graphql",
            "API_TOKEN_BOITE_AUTO": "token-secret",
        },
        clear=True,
    )
    def test_configure_la_session_http(self, session_cls):
        session = session_cls.return_value

        client = GraphQLClient()

        self.assertEqual(client.url, "https://dn.test/graphql")
        self.assertEqual(client.token, "token-secret")
        self.assertTrue(session.trust_env)
        self.assertEqual(session.mount.call_count, 2)


class GraphQLClientExecuteQueryTests(SimpleTestCase):
    def setUp(self):
        logger_patcher = patch("DS.graphql_client.logger")
        logger_patcher.start()
        self.addCleanup(logger_patcher.stop)

        self.client = GraphQLClient.__new__(GraphQLClient)
        self.client.url = "https://dn.test/graphql"
        self.client.token = "token-secret"
        self.client.session = MagicMock()

    @patch("builtins.open", new_callable=mock_open, read_data="query Test { __typename }")
    def test_requete_valide(self, fichier):
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"__typename": "Query"}}
        self.client.session.post.return_value = response

        resultat = self.client.execute_query("requete.graphql", {"numero": 123})

        self.assertEqual(resultat, {"data": {"__typename": "Query"}})
        self.client.session.post.assert_called_once_with(
            "https://dn.test/graphql",
            json={
                "query": "query Test { __typename }",
                "variables": {"numero": 123},
            },
            headers={
                "Authorization": "Bearer token-secret",
                "Content-Type": "application/json",
            },
            timeout=(5, 60),
        )
        fichier.assert_called_once_with("requete.graphql", "r", encoding="utf-8")

    @patch("builtins.open", new_callable=mock_open, read_data="query { __typename }")
    def test_token_refuse_propage_erreur_http(self, _):
        response = MagicMock(status_code=401, text="Unauthorized")
        erreur = requests.HTTPError("401 Client Error")
        response.raise_for_status.side_effect = erreur
        self.client.session.post.return_value = response

        with self.assertRaises(requests.HTTPError):
            self.client.execute_query("requete.graphql")

    @patch("builtins.open", new_callable=mock_open, read_data="query { __typename }")
    def test_erreurs_graphql_sont_refusees(self, _):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "errors": [{"message": "Le jeton ne permet pas cette opération"}]
        }
        self.client.session.post.return_value = response

        with self.assertRaisesRegex(Exception, "Erreurs GraphQL"):
            self.client.execute_query("requete.graphql")

    @patch("builtins.open", new_callable=mock_open, read_data="query { __typename }")
    def test_indisponibilite_api_est_propagee(self, _):
        self.client.session.post.side_effect = requests.ConnectionError(
            "API indisponible"
        )

        with self.assertRaises(requests.ConnectionError):
            self.client.execute_query("requete.graphql")


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
