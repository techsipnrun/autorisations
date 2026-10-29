"""Configuration Avis : règles, validations serveur et droits, sans BDD ni NAS."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase
from django.utils.datastructures import MultiValueDict

from instruction.forms_avis import DemandeAvisForm
from instruction.utils.avis_formulaires import configuration_standard, evaluer_configuration, verifier_configuration, charger_configuration
from . import test_creation_avis as support
from instruction.views import avis as vues


class ReglesFormulairesAvisTests(SimpleTestCase):
    def setUp(self):
        self.configuration = configuration_standard("dossier")
        self.etat = dict(nature_type="instance", expert_cs="true", expert_externe="2", expert_interne="", demarche="1")
        self.variables = dict(numero_dossier=1234, numero_avis=10, type_demarche="Travaux")
        self.data = QueryDict("nature=1&thematique=1&expert_externe=2&destinataire=CS")

    def formulaire(self, brouillon=False, avis=None, fichiers=None):
        return DemandeAvisForm(self.data, fichiers or MultiValueDict(), configuration=self.configuration,
            etat=self.etat, variables=self.variables, avis=avis, brouillon=brouillon)

    def champ(self, code):
        return next(c for c in self.configuration if c["code"] == code)

    def test_standards_valides_et_independants_pour_les_trois_contextes(self):
        for contexte in ("dossier", "generique", "existant"):
            champs = configuration_standard(contexte)
            self.assertEqual(verifier_configuration(contexte, champs), champs)
        self.assertNotIn("demarche", [c["code"] for c in self.configuration])
        self.champ("note_demandeur")["libelle"] = "Autre"
        self.assertEqual(next(c for c in configuration_standard("dossier") if c["code"] == "note_demandeur")["libelle"], "Note")

    def test_import_champs_specifiques_cs_et_validation_des_valeurs_initiales(self):
        config = configuration_standard("existant")
        self.assertEqual(len(config), 13)
        self.assertFalse(any(c["requis_brouillon"] for c in config))
        effet = evaluer_configuration(config, self.etat)
        self.assertTrue(effet["publication_raa"]["visible"])
        self.assertEqual(effet["publication_raa"]["defaut"], "a_publier")
        self.assertFalse(evaluer_configuration(config, {**self.etat, "expert_cs": "false"})["numero_avis_externe"]["visible"])
        for code, valeur in (("publication_raa", "true"), ("reponse", "inconnue"),
                             ("mode_contact", "Application"), ("date_demande_avis", "pas une date"),
                             ("numero_avis_externe", "X" * 101)):
            with self.subTest(code=code):
                config = configuration_standard("existant")
                next(c for c in config if c["code"] == code)["defaut"] = valeur
                with self.assertRaises(ValidationError):
                    verifier_configuration("existant", config)

    def test_brouillon_autorise_sans_pj_ni_destinataire(self):
        self.data = QueryDict("nature=1&thematique=1&expert_externe=2")
        self.assertTrue(self.formulaire(brouillon=True).is_valid())

    def test_envoi_instance_refuse_sans_projets_et_accepte_les_docs_deja_joints(self):
        self.assertFalse(self.formulaire().is_valid())
        avis = SimpleNamespace(id_projet_avis_id=40, id_projet_acte_id=41)
        self.assertTrue(self.formulaire(avis=avis).is_valid())

    def test_regle_personnalisee_premiere_correspondance_et_conditions_et(self):
        champ = self.champ("note_demandeur")
        champ["regles"] = [
            {"conditions": [{"champ": "nature_type", "operateur": "egal", "valeur": "instance"},
                            {"champ": "expert_externe", "operateur": "egal", "valeur": "2"}],
             "visible": True, "requis_brouillon": True, "defaut": "Note pour {numero_dossier}"},
            {"conditions": [{"champ": "nature_type", "operateur": "renseigne"}], "visible": True, "defaut": "Seconde"},
        ]
        self.assertEqual(self.formulaire(brouillon=True).donnees["note_demandeur"], "Note pour 1234")
        self.etat["expert_externe"] = "3"
        self.assertEqual(self.formulaire(brouillon=True).donnees["note_demandeur"], "Seconde")

    def test_obligation_personnalisee_brouillon_et_envoi(self):
        self.champ("note_demandeur")["regles"][0]["requis_brouillon"] = True
        self.assertFalse(self.formulaire(brouillon=True).is_valid())
        self.champ("note_demandeur")["regles"][0]["requis_brouillon"] = False
        self.assertTrue(self.formulaire(brouillon=True).is_valid())

    def test_masquage_ignore_post_forge_et_conserve_valeur_du_brouillon(self):
        self.champ("note_demandeur")["regles"] = []
        self.data = QueryDict("nature=1&thematique=1&expert_externe=2&note_demandeur=Faux")
        self.assertEqual(self.formulaire(brouillon=True).donnees["note_demandeur"], "")
        self.assertEqual(self.formulaire(brouillon=True, avis=SimpleNamespace(note="Note existante")).donnees["note_demandeur"], "Note existante")

    def test_masquage_pj_et_remplacements_ignore_sans_supprimer_les_liens(self):
        self.champ("pj_lie_avis")["regles"] = []
        fichiers = MultiValueDict({"pj_lie_avis": [SimpleUploadedFile("piece.pdf", b"pdf")],
                                  "remplacer_pj_40": [SimpleUploadedFile("autre.pdf", b"pdf")]})
        form = self.formulaire(brouillon=True, fichiers=fichiers)
        self.assertFalse(form.fichiers_actifs)

    def test_format_variables_et_texte_fourni_non_remplace(self):
        self.data = QueryDict("nature=1&thematique=1&expert_externe=2&formulation_avis=Texte+manuel")
        self.assertEqual(self.formulaire(brouillon=True).donnees["formulation_avis"], "Texte manuel")

    def test_conditions_liste_vide_et_renseigne(self):
        champ = self.champ("note_demandeur")
        for operateur, valeur, attendu in (("dans", ["1", "2"], True), ("vide", "", False), ("renseigne", "", True)):
            champ["regles"] = [{"conditions": [{"champ": "expert_externe", "operateur": operateur, "valeur": valeur}], "visible": True}]
            self.assertEqual(evaluer_configuration(self.configuration, self.etat)["note_demandeur"]["visible"], attendu)

    def test_libelle_conditionnel_vide_reprend_libelle_general(self):
        champ = self.champ("note_demandeur")
        champ["libelle"] = "Ma note"
        champ["regles"][0]["libelle"] = "   "
        self.assertEqual(evaluer_configuration(self.configuration, self.etat)["note_demandeur"]["libelle"], "Ma note")
        resultat = verifier_configuration("dossier", self.configuration)
        self.assertNotIn("libelle", next(c for c in resultat if c["code"] == "note_demandeur")["regles"][0])

    def test_placeholder_conditionnel_vide_herite_du_defaut(self):
        champ = self.champ("note_demandeur")
        champ["placeholder"] = "Texte indicatif par défaut"
        for valeur in ("", "   ", "Précision pour ce cas"):
            with self.subTest(valeur=valeur):
                champ["regles"][0]["placeholder"] = valeur
                attendu = valeur if valeur.strip() else champ["placeholder"]
                self.assertEqual(evaluer_configuration(self.configuration, self.etat)["note_demandeur"]["placeholder"], attendu)
                resultat = verifier_configuration("dossier", self.configuration)
                if not valeur.strip():
                    self.assertNotIn("placeholder", next(c for c in resultat if c["code"] == "note_demandeur")["regles"][0])

    def test_anciennes_listes_personnalisees_retirees_sans_retirer_obligations(self):
        champ = self.champ("thematique")
        champ["regles"] = [{"conditions": [{"champ": "demarche", "operateur": "egal", "valeur": "1"}], "choix_autorises": ["2", "3"]}]
        normalises = verifier_configuration("dossier", self.configuration)
        self.assertIsNone(next(c for c in normalises if c["code"] == "thematique")["choix_autorises"])
        self.assertNotIn("choix_autorises", next(c for c in normalises if c["code"] == "thematique")["regles"][0])
        formulaire = DemandeAvisForm(self.data, MultiValueDict(), configuration=self.configuration,
            etat=self.etat, variables=self.variables, brouillon=True, thematiques_autorisees=["2", "3"])
        self.assertIn("thematique", formulaire.errors)
        champ["regles"][0]["requis_envoi"] = False
        with self.assertRaises(ValidationError):
            verifier_configuration("dossier", self.configuration)

    def test_placeholder_distinct_de_la_valeur_et_aide_cs_standard(self):
        champ = self.champ("note_demandeur")
        champ["placeholder"] = "Saisir un commentaire"
        self.assertTrue(verifier_configuration("dossier", self.configuration))
        self.assertFalse(self.formulaire(brouillon=True).donnees.get("note_demandeur"))
        self.assertEqual(evaluer_configuration(self.configuration, self.etat)["note_demandeur"]["placeholder"], "Saisir un commentaire")
        self.assertIn("numéro par défaut", next(c for c in configuration_standard("existant") if c["code"] == "numero_avis_externe")["aide"])

    def test_configuration_refuse_incoherences_et_code_executable(self):
        for modifier in (
            lambda c: c.update(visible=False, requis_envoi=True),
            lambda c: c.update(defaut="{__class__}"),
            lambda c: c.update(regles=[{"conditions": [{"champ": "x", "operateur": "eval"}], "visible": True}]),
            lambda c: c.update(regles=[{"conditions": []}]),
        ):
            configuration = configuration_standard("dossier")
            modifier(next(c for c in configuration if c["code"] == "note_demandeur"))
            with self.assertRaises(ValidationError):
                verifier_configuration("dossier", configuration)

    def test_structurels_proteges_et_fichier_sans_defaut(self):
        self.champ("nature")["requis_envoi"] = False
        with self.assertRaises(ValidationError):
            verifier_configuration("dossier", self.configuration)
        self.configuration = configuration_standard("dossier")
        self.champ("pj_lie_avis")["defaut"] = "fichier.pdf"
        with self.assertRaises(ValidationError):
            verifier_configuration("dossier", self.configuration)

    def test_chargement_defaults_sans_ecriture_et_personnalisation_prioritaire(self):
        with patch("instruction.utils.avis_formulaires.AvisFormulaireConfiguration") as modele:
            modele.objects.filter.return_value.prefetch_related.return_value.first.return_value = None
            self.assertEqual(charger_configuration("dossier"), self.configuration)
            modele.objects.create.assert_not_called()
            perso = SimpleNamespace(**{**self.champ("note_demandeur"), "libelle": "Note personnalisée"})
            modele.objects.filter.return_value.prefetch_related.return_value.first.return_value = SimpleNamespace(champs=Mock(all=Mock(return_value=[perso])))
            self.assertEqual(next(c for c in charger_configuration("dossier") if c["code"] == "note_demandeur")["libelle"], "Note personnalisée")


class IntegrationCreationConfigurableTests(SimpleTestCase):
    setUp = support.CreationAvisTests.setUp
    creer_avis = support.CreationAvisTests.creer_avis
    requete = support.CreationAvisTests.requete

    def test_enregistrement_reel_refuse_note_configuree_obligatoire_avant_nas(self):
        configuration = configuration_standard("dossier")
        next(c for c in configuration if c["code"] == "note_demandeur")["regles"][0]["requis_brouillon"] = True
        with patch.object(vues, "charger_configuration", return_value=configuration):
            response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(), 123456)
        self.assertEqual(response.status_code, 400)
        self.enregistrer.assert_not_called()
        self.creer_dossier.assert_not_called()
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_parametre_historique_generation_ne_contourne_pas_les_obligations(self):
        configuration = configuration_standard("dossier")
        next(c for c in configuration if c["code"] == "note_demandeur")["regles"][0]["requis_brouillon"] = True
        with patch.object(vues, "charger_configuration", return_value=configuration):
            response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(generer_numero="1"), 123456)
        self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()

    def test_condition_demarche_utilise_le_dossier_sans_champ_post_cache(self):
        self.dossier.id_demarche.pk = 7
        configuration = configuration_standard("dossier")
        next(c for c in configuration if c["code"] == "note_demandeur")["regles"] = [
            {"conditions": [{"champ": "demarche", "operateur": "egal", "valeur": "7"}], "visible": True, "requis_brouillon": True}]
        with patch.object(vues, "charger_configuration", return_value=configuration):
            response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(demarche="999"), 123456)
        self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()

    def test_envoi_reel_instance_projets_rendus_facultatifs_par_configuration(self):
        configuration = configuration_standard("dossier")
        for c in configuration:
            if c["code"] in {"pj_demande_avis", "pj_projet_acte"}:
                c["regles"][0]["requis_envoi"] = False
        with patch.object(vues, "charger_configuration", return_value=configuration):
            response = vues.instruction_dossier_confirmer_ajout_avis(self.requete(formulation_avis="Demande sans projet"), 123456)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.crees)
        self.outbox.assert_called_once()
