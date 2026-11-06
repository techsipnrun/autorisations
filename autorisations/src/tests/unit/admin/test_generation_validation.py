from copy import deepcopy

from django.test import SimpleTestCase

from autorisations.models.models_generation import Balise
from document_generation.services.validation import GenerationContextValidator, valeur_vide


class GenerationContextValidatorTests(SimpleTestCase):
    def setUp(self):
        self.validator = GenerationContextValidator()

    def balise(self, mode="CONNUE", required=True, allow_blank=False, **kwargs):
        return Balise(code="projet.quantite", libelle="Quantité", type="INTEGER", mode=mode,
                      required=required, allow_blank=allow_blank, **kwargs)

    def test_connue_presente_pour_toutes_les_combinaisons(self):
        for value in (42, 0, False, "texte"):
            for required in (True, False):
                for blank in (True, False):
                    with self.subTest(value=value, required=required, blank=blank):
                        context = {"projet": {"quantite": value}}
                        report = self.validator.validate([self.balise(required=required, allow_blank=blank)], context)
                        self.assertEqual(report, {"resolved": context, "missing": [], "errors": []})

    def test_connue_vide_acceptee_si_facultative(self):
        for value in (None, "", "  ", [], {}):
            with self.subTest(value=value):
                report = self.validator.validate([self.balise(required=False, allow_blank=False)], {"projet": {"quantite": value}})
                self.assertEqual(report["missing"], [])
                self.assertEqual(report["errors"], [])

    def test_connue_requise_vide_a_demander(self):
        for context in ({}, {"projet": {}}, {"projet": {"quantite": None}}, {"projet": {"quantite": " "}}):
            with self.subTest(context=context):
                report = self.validator.validate([self.balise()], context)
                self.assertEqual(report["missing"][0]["code"], "projet.quantite")
                self.assertEqual(report["missing"][0]["reason"], "connue_vide")
                self.assertEqual(report["errors"], [])
        report = self.validator.validate([self.balise(required=True, allow_blank=True)], {})
        self.assertEqual(report['missing'][0]['reason'], 'connue_vide')

    def test_manuelle_requise_a_demander_meme_si_allow_blank(self):
        for allow_blank in (True, False):
            report = self.validator.validate([self.balise(mode="A_RENSEIGNER", allow_blank=allow_blank)], {})
            self.assertEqual(report["missing"][0]["reason"], "saisie_requise")

    def test_facultative_absente_acceptee_meme_si_vide_interdit(self):
        for mode in ("CONNUE", "A_RENSEIGNER"):
            report = self.validator.validate([self.balise(mode=mode, required=False)], {})
            self.assertEqual(report, {"resolved": {"projet": {"quantite": None}}, "missing": [], "errors": []})

    def test_saisie_vide_explicitement_refusee(self):
        report = self.validator.validate([self.balise(mode="A_RENSEIGNER", required=True)], {}, {"projet.quantite": " "})
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["missing"][0]['reason'], 'valeur_vide_interdite')

    def test_completion_connue_vide_et_saisie_manuelle(self):
        for mode in ("CONNUE", "A_RENSEIGNER"):
            report = self.validator.validate([self.balise(mode=mode)], {}, {"projet.quantite": 0})
            self.assertEqual(report, {"resolved": {"projet": {"quantite": 0}}, "missing": [], "errors": []})

    def test_saisie_vide_autorisee_explicitement(self):
        report = self.validator.validate([self.balise(mode="A_RENSEIGNER", required=False, allow_blank=False)], {}, {"projet.quantite": ""})
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["missing"], [])

    def test_pas_de_remplacement_de_valeur_connue(self):
        report = self.validator.validate([self.balise()], {"projet": {"quantite": 1}}, {"projet.quantite": 2})
        self.assertEqual(len(report["errors"]), 1)

    def test_erreurs_configuration_et_saisie_hors_selection(self):
        for balise in (self.balise(actif=False), self.balise(mode="INCONNUE")):
            report = self.validator.validate([balise], {}, {"autre": "x"})
            self.assertEqual(len(report["errors"]), 2)

    def test_contexte_mal_forme_et_doublon(self):
        report = self.validator.validate([self.balise(), self.balise()], {"projet": "texte"})
        self.assertEqual(len(report["errors"]), 2)

    def test_entrees_non_modifiees_et_contextes_independants(self):
        context = {"projet": {"quantite": " texte "}, "autre": 42}
        original = deepcopy(context)
        report = self.validator.validate([self.balise()], context)
        self.assertEqual(report["resolved"], {"projet": {"quantite": "texte"}})
        self.assertEqual(context, original)

    def test_zero_et_false_ne_sont_pas_vides(self):
        self.assertFalse(valeur_vide(0))
        self.assertFalse(valeur_vide(False))

    def test_saisie_obligatoire_vide_reste_a_demander_et_signale_erreur(self):
        report = self.validator.validate([self.balise(mode="A_RENSEIGNER")], {}, {"projet.quantite": None})
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["missing"][0]["reason"], "valeur_vide_interdite")

    def test_pipeline_builder_puis_validation(self):
        from autorisations.models.models_instruction import Dossier
        from document_generation.services.context import DocumentContextBuilder

        dossier = Dossier(id=1, numero=30769307, nom_dossier="Test")
        context = DocumentContextBuilder().build(dossier, ["dossier.numero"])
        known = Balise(code="dossier.numero", mode="CONNUE", required=True, allow_blank=False)
        report = self.validator.validate([known, self.balise(mode="A_RENSEIGNER")], context)
        self.assertEqual(report["resolved"], {"dossier": {"numero": 30769307}})
        self.assertEqual(report["missing"][0]["code"], "projet.quantite")
        self.assertEqual(report["errors"], [])
