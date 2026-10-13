"""Politique de relance automatique et maintien du lancement manuel, sans BDD."""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from instruction.views import synchro


class ActualisationGlobaleTests(SimpleTestCase):
    def requete(self, methode="get"):
        request = getattr(RequestFactory(), methode)("/")
        request.user = SimpleNamespace(is_authenticated=True)
        return request

    def test_etat_transmet_la_politique_avec_ou_sans_historique(self):
        etat = SimpleNamespace(
            en_cours=False, dernier_statut="ok",
            date_maj=timezone.now(), date_derniere_tentative=timezone.now(),
        )
        for environnement, automatique in (("dev", False), ("prod", True)):
            for historique in (None, etat):
                with self.subTest(automatique=automatique, historique=bool(historique)):
                    with patch.dict(os.environ, {"DJANGO_ENV": environnement}), patch.object(
                        synchro.SynchronisationEtat.objects, "filter",
                    ) as filtrer, patch.object(synchro, "get_statut_demarche_numerique", return_value=None):
                        filtrer.return_value.first.return_value = historique
                        reponse = synchro.etat_actualisation(self.requete())
                    self.assertEqual(reponse.status_code, 200)
                    self.assertIs(json.loads(reponse.content)["synchro_globale_auto"], automatique)

    @patch.dict(os.environ, {"DJANGO_ENV": "dev"})
    def test_lancement_manuel_reste_possible_sans_relance_automatique(self):
        with patch.object(synchro, "_api_dn_est_disponible", return_value=True), patch.object(
            synchro, "lancer_en_arriere_plan2", return_value=True,
        ) as lancer:
            reponse = synchro.actualiser_donnees(self.requete("post"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(json.loads(reponse.content)["status"], "ok")
        lancer.assert_called_once_with()
