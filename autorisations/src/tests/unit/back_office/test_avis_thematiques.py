"""Gestion du catalogue des thématiques dans le Back Office."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from backoffice.views import avis as avis_configuration


class CatalogueThematiquesTests(SimpleTestCase):
    def setUp(self):
        self.modele = self.enterContext(patch.object(avis_configuration, "AvisThematique"))
        self.demarches = self.enterContext(patch.object(avis_configuration, "Demarche"))
        self.enterContext(patch.object(avis_configuration.transaction, "atomic"))
        self.theme = SimpleNamespace(pk=1, thematique="Artisanat", demarche="Activités commerciales", save=Mock())
        self.modele.objects.all.return_value.order_by.return_value = [self.theme]
        self.modele.objects.exclude.return_value.exclude.return_value.values_list.return_value.distinct.return_value = ["Activités commerciales", "Autre"]
        self.modele.objects.select_for_update.return_value.filter.return_value.first.return_value = self.theme
        self.modele.objects.filter.return_value.exclude.return_value.exists.return_value = False
        self.demarches.objects.all.return_value.order_by.return_value = [SimpleNamespace(pk=7, type="Activités commerciales")]

    def requete(self, donnees=None, admin=True):
        factory = RequestFactory()
        request = factory.get("/back-office/avis/thematiques/") if donnees is None else factory.post(
            "/back-office/avis/thematiques/", json.dumps(donnees), content_type="application/json")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=admin)
        return request

    def test_lecture_et_ecriture_reservees_admin(self):
        for donnees in (None, {"id": 1, "thematique": "Artisanat", "demarche": "Autre"}):
            with self.assertRaises(PermissionDenied):
                avis_configuration.configurer_thematiques(self.requete(donnees, admin=False))
        self.theme.save.assert_not_called()

    def test_catalogue_charge_champ_existant_et_categories(self):
        response = avis_configuration.configurer_thematiques(self.requete())
        self.assertEqual(response.status_code, 200)
        resultat = json.loads(response.content)
        self.assertEqual(resultat["thematiques"][0]["demarche"], "Activités commerciales")
        self.assertIn({"valeur": "Autre", "libelle": "Toutes les démarches"}, resultat["categories"])
        self.theme.save.assert_not_called()

    def test_changement_de_rattachement_conserve_identifiant(self):
        response = avis_configuration.configurer_thematiques(self.requete({"id": 1, "thematique": " Artisanat ", "demarche": "Autre"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.theme.pk, 1)
        self.assertEqual(self.theme.thematique, "Artisanat")
        self.assertEqual(self.theme.demarche, "Autre")
        self.theme.save.assert_called_once()

    def test_non_rattachee_et_creation(self):
        self.modele.return_value = self.theme
        response = avis_configuration.configurer_thematiques(self.requete({"thematique": "Nouveau thème", "demarche": ""}))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.theme.demarche)
        self.modele.assert_called_once_with()
        self.theme.save.assert_called_once()

    def test_erreurs_de_saisie_et_doublon_sans_ecriture(self):
        for donnees in ({"thematique": "", "demarche": "Autre"}, {"thematique": "T", "demarche": "Inconnue"},
                        {"id": True, "thematique": "T", "demarche": "Autre"}):
            self.assertEqual(avis_configuration.configurer_thematiques(self.requete(donnees)).status_code, 400)
        self.modele.objects.filter.return_value.exclude.return_value.exists.return_value = True
        self.assertEqual(avis_configuration.configurer_thematiques(self.requete({"thematique": "Artisanat", "demarche": "Autre"})).status_code, 400)
        self.theme.save.assert_not_called()
