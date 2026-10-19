"""Catalogue unique des thématiques : droits, rattachements et validation, sans BDD."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from instruction.utils.avis_utils import categories_thematiques_avis, repartition_thematiques_avis
from instruction.utils.avis_formulaires import charger_configuration, configuration_standard
from instruction.views import avis_configuration, avis as vues
from . import test_creation_avis as support


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


class RepartitionThematiquesTests(SimpleTestCase):
    def test_categories_existantes_nouvelles_et_communes(self):
        demarches = [SimpleNamespace(pk=7, type="Activités commerciales"), SimpleNamespace(pk=8, type="Nouvelle démarche")]
        themes = [SimpleNamespace(pk=1, demarche="Activités commerciales"), SimpleNamespace(pk=2, demarche="Autre"),
                  SimpleNamespace(pk=3, demarche="Nouvelle démarche"), SimpleNamespace(pk=4, demarche=None)]
        self.assertEqual(repartition_thematiques_avis(themes, demarches), {"7": ["1", "2"], "8": ["2", "3"]})
        self.assertEqual(categories_thematiques_avis(SimpleNamespace(type="Survol hélicoptère")), ["Autre", "Survol hélicoptère"])

    def test_ancienne_liste_de_formulaire_ignoree_sans_perdre_les_autres_reglages(self):
        champ = next(c for c in configuration_standard("dossier") if c["code"] == "thematique")
        champ.update(choix_autorises=["999"], libelle="Mon thème", regles=[{
            "conditions": [{"champ": "demarche", "operateur": "egal", "valeur": "7"}],
            "choix_autorises": ["999"], "libelle": "Thème commercial"}])
        with patch("instruction.utils.avis_formulaires.AvisFormulaireConfiguration") as modele:
            modele.objects.filter.return_value.prefetch_related.return_value.first.return_value = SimpleNamespace(champs=Mock(all=Mock(return_value=[SimpleNamespace(**champ)])))
            charge = next(c for c in charger_configuration("dossier") if c["code"] == "thematique")
        self.assertIsNone(charge["choix_autorises"])
        self.assertNotIn("choix_autorises", charge["regles"][0])
        self.assertEqual(charge["libelle"], "Mon thème")
        self.assertEqual(charge["regles"][0]["libelle"], "Thème commercial")


class ValidationCatalogueTests(SimpleTestCase):
    setUp = support.CreationAvisTests.setUp
    creer_avis = support.CreationAvisTests.creer_avis
    requete = support.CreationAvisTests.requete

    def test_thematique_hors_demarche_refusee_avant_nas_et_avis(self):
        with patch.object(vues, "thematiques_avis_liees_a_demarche", return_value=[SimpleNamespace(pk=2)]):
            response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(), 123456)
        self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()
        self.enregistrer.assert_not_called()
        self.outbox.assert_not_called()
