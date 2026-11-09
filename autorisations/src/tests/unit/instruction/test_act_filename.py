from datetime import date
from types import SimpleNamespace
from unittest.mock import patch, PropertyMock
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from autorisations.models.models_documents import DocumentNature
from autorisations.utils.act_filename import render_act_filename, validate_act_filename


class ActFilenameTests(SimpleTestCase):
    def setUp(self):
        self.nature = DocumentNature(prefixe_nom_fichier='DIR-I-')
        self.dossier = SimpleNamespace(pk=1, numero=31770683)

    def render(self, number='2026-012', **options):
        return render_act_filename(self.nature, number, dossier=self.dossier,
            today=date(2026, 11, 9), **options)

    def test_regle_initiale_et_numero_conserve(self):
        self.assertEqual(self.render(), 'DIR-I-2026-012_09-11.pdf')

    def test_ordre_separateurs_dates_et_texte_libres(self):
        self.nature.nom_fichier_signe = 'Signe_{date.jour}_{dossier.numero}_{document.numero}_{date.annee}.pdf'
        self.assertEqual(self.render(), 'Signe_09-11-26_31770683_2026-012_2026.pdf')

    def test_reference_manuelle_et_prefixe_facultatif(self):
        self.nature.prefixe_nom_fichier = ''
        self.assertEqual(self.render('2025-018/PF'), '2025-018-PF_09-11.pdf')

    def test_raison_sociale_puis_nom_prenom_sans_espaces(self):
        from document_generation.services.providers import ResolutionSource
        self.nature.nom_fichier_signe = '{beneficiaire.identite}_{document.numero}.pdf'
        contact = SimpleNamespace(raison_sociale='Société Exemple', nom='Dupont', prenom='Jean Paul')
        with patch.object(ResolutionSource, 'beneficiaire', new_callable=PropertyMock, return_value=contact):
            self.assertEqual(self.render(), 'Société-Exemple_2026-012.pdf')
            contact.raison_sociale = ''
            self.assertEqual(self.render(), 'DUPONT-Jean-Paul_2026-012.pdf')

    def test_configuration_invalide_refusee_sans_regle_cachee_de_secours(self):
        for value in ('', '.pdf', '../acte.pdf', '/acte.pdf', 'A\\acte.pdf', '{toto}.pdf',
                      '{document.numero}_{document.numero}.pdf', '{document.numero.pdf', 'acte.docx', 'a\n.pdf', 'CON.pdf', 'LPT1.pdf'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_act_filename(value)
        self.nature.nom_fichier_signe = ''
        with self.assertRaises(ValidationError): self.render()

    def test_valeurs_manquantes_et_longueur_refusees(self):
        with self.assertRaises(ValidationError): self.render('')
        with self.assertRaises(ValidationError): self.render('a'*200)
        self.nature.nom_fichier_signe = '{dossier.numero}.pdf'
        with self.assertRaises(ValidationError): render_act_filename(self.nature, '2026-012')

    def test_pas_de_double_prefixe_affichage(self):
        self.nature.prefixe_numero='DIR-I-'
        self.assertEqual(self.render(), 'DIR-I-2026-012_09-11.pdf')
