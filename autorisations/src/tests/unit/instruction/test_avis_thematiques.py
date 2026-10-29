"""Catalogue unique des thématiques : droits, rattachements et validation, sans BDD."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from instruction.utils.avis_utils import categories_thematiques_avis, repartition_thematiques_avis
from instruction.utils.avis_formulaires import charger_configuration, configuration_standard
from instruction.views import avis as vues
from . import test_creation_avis as support


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
