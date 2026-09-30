import os
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from instruction.services_externes import (
    get_etat_expiration_token_dn,
    verifier_disponibilite_swagger,
)


class ServicesExternesTests(SimpleTestCase):
    @patch("instruction.services_externes.requests.get")
    def test_swagger_est_considere_disponible_sur_reponse_http(self, get):
        get.return_value = MagicMock(status_code=200)

        resultat = verifier_disponibilite_swagger("https://autorisations.test/swagger/")

        self.assertTrue(resultat["disponible"])
        self.assertEqual(resultat["status_code"], 200)
        get.assert_called_once_with(
            "https://autorisations.test/swagger/",
            timeout=(3, 8),
            allow_redirects=True,
        )

    @patch.dict(os.environ, {"DN_DATE_EXPIRATION_TOKEN": "2026-10-15"}, clear=False)
    @patch("instruction.services_externes.timezone.localdate")
    def test_duree_restante_du_jeton_dn(self, localdate):
        from datetime import date

        localdate.return_value = date(2026, 9, 30)

        resultat = get_etat_expiration_token_dn()

        self.assertTrue(resultat["configure"])
        self.assertEqual(resultat["jours_restants"], 15)
        self.assertEqual(resultat["etat"], "expire_bientot")
