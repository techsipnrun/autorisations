import os
from unittest import skipUnless
from unittest.mock import MagicMock, call, patch

import requests
from django.test import SimpleTestCase

from declaration_manifestations import get_methods


class DeclarationManifestationsTokenTests(SimpleTestCase):
    def setUp(self):
        logger_patcher = patch("declaration_manifestations.get_methods.loggerDM")
        logger_patcher.start()
        self.addCleanup(logger_patcher.stop)

    def test_recupere_access_token(self):
        response = MagicMock(
            status_code=200,
            headers={"Content-Type": "application/json"},
        )
        response.json.return_value = {"access_token": "token-dm"}

        with patch.object(get_methods.SESSION, "post", return_value=response) as post:
            token = get_methods.get_access_token()

        self.assertEqual(token, "token-dm")
        post.assert_called_once_with(
            get_methods.TOKEN_URL,
            json={
                "grant_type": "password",
                "username": get_methods.USERNAME,
                "password": get_methods.PASSWORD,
                "client_id": get_methods.CLIENT_ID,
                "client_secret": get_methods.CLIENT_SECRET,
            },
            headers={"Content-Type": "application/json"},
            timeout=(5, 30),
        )

    def test_identifiants_invalides_propagent_erreur_http(self):
        response = MagicMock(
            status_code=401,
            headers={"Content-Type": "application/json"},
        )
        response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Invalid credentials",
        }
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error"
        )

        with patch.object(get_methods.SESSION, "post", return_value=response):
            with self.assertRaises(requests.HTTPError):
                get_methods.get_access_token()

        response.raise_for_status.assert_called_once()

    def test_reponse_sans_access_token_est_refusee(self):
        response = MagicMock(
            status_code=200,
            headers={"Content-Type": "application/json"},
        )
        response.json.return_value = {"token_type": "Bearer"}

        with patch.object(get_methods.SESSION, "post", return_value=response):
            with self.assertRaises(KeyError):
                get_methods.get_access_token()

    def test_indisponibilite_endpoint_token_est_propagee(self):
        with patch.object(
            get_methods.SESSION,
            "post",
            side_effect=requests.ConnectionError("API indisponible"),
        ):
            with self.assertRaises(requests.ConnectionError):
                get_methods.get_access_token()


class DeclarationManifestationsLectureTests(SimpleTestCase):
    def setUp(self):
        logger_patcher = patch("declaration_manifestations.get_methods.loggerDM")
        logger_patcher.start()
        self.addCleanup(logger_patcher.stop)

    @patch("declaration_manifestations.get_methods.requests.get")
    def test_pagination_des_avis(self, get):
        page_1 = MagicMock(status_code=200)
        page_1.json.return_value = {
            "results": [{"id": 1}],
            "next": "https://dm.test/api/Avis/?page=2",
        }
        page_2 = MagicMock(status_code=200)
        page_2.json.return_value = {
            "results": [{"id": 2}],
            "next": None,
        }
        get.side_effect = [page_1, page_2]

        resultat = get_methods.get_all_avis("token-dm")

        self.assertEqual(resultat, [{"id": 1}, {"id": 2}])
        self.assertEqual(
            get.call_args_list,
            [
                call(
                    get_methods.AVIS_LIST_URL,
                    headers={"Authorization": "Bearer token-dm"},
                ),
                call(
                    "https://dm.test/api/Avis/?page=2",
                    headers={"Authorization": "Bearer token-dm"},
                ),
            ],
        )

    @patch("declaration_manifestations.get_methods.requests.get")
    def test_token_refuse_sur_lecture_propage_erreur_http(self, get):
        response = MagicMock(status_code=403, text="Forbidden")
        response.raise_for_status.side_effect = requests.HTTPError(
            "403 Client Error"
        )
        get.return_value = response

        with self.assertRaises(requests.HTTPError):
            get_methods.get_all_avis("token-invalide")

    @patch("declaration_manifestations.get_methods.requests.get")
    def test_indisponibilite_api_sur_lecture_est_propagee(self, get):
        get.side_effect = requests.Timeout("Délai dépassé")

        with self.assertRaises(requests.Timeout):
            get_methods.get_all_avis("token-dm")


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
