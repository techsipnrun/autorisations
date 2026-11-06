from datetime import date
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from autorisations.models.models_generation import valider_destination_relative, valider_nom_fichier
from document_generation.services.filename import resolve_filename


class GenerationFilenameTests(SimpleTestCase):
    def setUp(self):
        self.dossier = SimpleNamespace(numero=30655697)

    def resolve(self, company=None, nom="du pont", prenom="Jean Paul"):
        source = SimpleNamespace(beneficiaire=SimpleNamespace(raison_sociale=company, nom=nom, prenom=prenom))
        return resolve_filename("DIR-{date.annee}-{beneficiaire.identite}-{date.jour}-{dossier.numero}.docx",
                                self.dossier, today=date(2026, 11, 4), source=source)

    def test_dates_et_raison_sociale_prioritaire_sans_espaces(self):
        self.assertEqual(self.resolve("  Société  des\tHauts\u00a0de l'île  "),
                         "DIR-2026-Société-des-Hauts-de-l'île-04-11-26-30655697.docx")

    def test_raison_sociale_vide_ou_null_utilise_nom_prenom(self):
        for company in (None, "", "  "):
            with self.subTest(company=company):
                self.assertEqual(self.resolve(company), "DIR-2026-DU-PONT-Jean-Paul-04-11-26-30655697.docx")

    def test_separateurs_interdits_du_contact_ne_creent_pas_de_chemin(self):
        self.assertNotIn("/", self.resolve("Association / Les Hauts"))

    def test_contact_ou_identite_absents_refuses(self):
        with self.assertRaises(ValueError):
            self.resolve("", "", "")
        with self.assertRaises(ValueError):
            resolve_filename("{beneficiaire.identite}.docx", self.dossier, source=SimpleNamespace(beneficiaire=None))

    def test_dates_sans_contact_et_sans_acces_bdd(self):
        self.assertEqual(resolve_filename("{date.annee}-{date.jour}.docx", self.dossier, today=date(2027, 1, 2)),
                         "2027-02-01-27.docx")

    def test_nouvelles_variables_reservees_au_nom_et_uniques(self):
        for code in ("date.annee", "date.jour", "beneficiaire.identite"):
            valider_nom_fichier("{" + code + "}.docx")
            with self.assertRaises(ValidationError):
                valider_nom_fichier("{" + code + "}-{" + code + "}.docx")
            with self.assertRaises(ValidationError):
                valider_destination_relative("{" + code + "}/Work/")
