from io import BytesIO
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock

from docx import Document
from django.test import SimpleTestCase, override_settings

from autorisations.models.models_generation import Balise, DocumentTemplate
from document_generation.services.analyzer import TemplateAnalyzer


def word_bytes(text, header=None, footer=None):
    doc = Document()
    doc.add_paragraph(text)
    if header:
        doc.sections[0].header.paragraphs[0].text = header
    if footer:
        doc.sections[0].footer.paragraphs[0].text = footer
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


class TemplateAnalyzerTests(SimpleTestCase):
    def test_boucle_sur_collection_declaree_et_alias_locaux(self):
        data = word_bytes("{% for espece in projet.especes %}{{ espece.nom }}{% endfor %}")
        catalogue = [Balise(code="projet.especes", mode="CONNUE")]
        with patch.dict("document_generation.services.analyzer.KNOWN_PROVIDERS", {"projet.especes": lambda source: []}):
            report = self.analyzer.analyze_bytes(data, catalogue)
        self.assertTrue(report.valide, report.erreurs)
        self.assertEqual(report.balises, [{"code": "projet.especes", "statut": "CONNUE"}])
    def test_nouveaux_fichiers_if_for_et_syntaxe_invalide(self):
        folder = Path(__file__).resolve().parents[3] / "document_generation/test_templates"
        for name, valide in (("test_if.docx", True), ("test_for.docx", True), ("test_syntaxe_invalide.docx", False)):
            with self.subTest(name=name):
                report = self.analyzer.analyze_bytes((folder / name).read_bytes(), self.catalogue)
                self.assertEqual(report.valide, valide, report.erreurs)
                self.assertEqual(report.syntaxe_valide, valide)

    def setUp(self):
        path_exists = patch("document_generation.services.template_path.smbclient.path.isfile", return_value=True)
        path_exists.start()
        self.addCleanup(path_exists.stop)
        self.analyzer = TemplateAnalyzer()
        self.catalogue = [
            Balise(code="dossier.numero", mode="CONNUE"),
            Balise(code="beneficiaire.nom_complet", mode="CONNUE"),
            Balise(code="quantite_prelevement", mode="A_RENSEIGNER"),
        ]

    def test_unique_template_de_test_et_quatre_codes_complets(self):
        path = Path(__file__).resolve().parents[3] / "document_generation/test_templates/test_generation.docx"
        paragraphs = [p.text for p in Document(path).paragraphs]
        self.assertIn("Projet d'arrêté — test d'analyse AGIDA", paragraphs)
        self.assertIn("Bénéficiaire : {{ beneficiaire.nom_complet }}", paragraphs)
        self.assertIn("Quantité prélevée : {{ quantite_prelevement }}", paragraphs)
        with patch("docxtpl.DocxTemplate.render", side_effect=AssertionError("Rendu interdit")), patch(
            "docxtpl.DocxTemplate.save", side_effect=AssertionError("Sauvegarde interdite")
        ):
            report = self.analyzer.analyze_bytes(path.read_bytes(), self.catalogue)
        self.assertEqual(report.balises, [
            {"code": "beneficiaire.nom_complet", "statut": "CONNUE"},
            {"code": "dossier.numero", "statut": "CONNUE"},
            {"code": "quantite_prelevement", "statut": "A_RENSEIGNER"},
            {"code": "toto.foo", "statut": "INCONNUE"},
        ])
        self.assertFalse(report.valide)

    def test_entete_pied_de_page_et_balise_decoupee_en_runs(self):
        doc = Document()
        p = doc.add_paragraph()
        p.add_run("{{ dossier.")
        p.add_run("numero }}")
        doc.sections[0].header.paragraphs[0].text = "{{ beneficiaire.nom_complet }}"
        doc.sections[0].footer.paragraphs[0].text = "{{ quantite_prelevement }}"
        stream = BytesIO()
        doc.save(stream)
        report = self.analyzer.analyze_bytes(stream.getvalue(), self.catalogue)
        self.assertTrue(report.valide, report.erreurs)
        self.assertEqual(len(report.balises), 3)

    def test_syntaxe_jinja_invalide(self):
        report = self.analyzer.analyze_bytes(word_bytes("{{ dossier.numero }"), [])
        self.assertFalse(report.valide)
        self.assertIn("Jinja", report.erreurs[0])

    def test_fichier_corrompu(self):
        self.assertFalse(self.analyzer.analyze_bytes(b"pas un docx", []).valide)

    def test_condition_filtre_et_acces_statique(self):
        data = word_bytes("{% if dossier.numero %}{{ beneficiaire['nom_complet']|upper }}{% endif %}")
        report = self.analyzer.analyze_bytes(data, self.catalogue)
        self.assertTrue(report.valide, report.erreurs)
        self.assertEqual(len(report.balises), 2)

    def test_boucle_et_acces_dynamiques_explicitement_refuses(self):
        for text in ("{% for x in liste %}{{ x.nom }}{% endfor %}", "{{ dossier[champ] }}"):
            with self.subTest(text=text):
                self.assertFalse(self.analyzer.analyze_bytes(word_bytes(text), []).valide)

    def test_balise_inactive_ou_connue_sans_provider(self):
        for balise in (Balise(code="dossier.numero", mode="CONNUE", actif=False),
                       Balise(code="dossier.numero", mode="CONNUE")):
            code = "dossier.numero" if not balise.actif else "projet.inexistant"
            balise.code = code
            with self.subTest(code=code):
                report = self.analyzer.analyze_bytes(word_bytes("{{ " + code + " }}"), [balise])
                self.assertFalse(report.valide)

    def test_catalogue_sql_uniquement_en_lecture(self):
        with patch("document_generation.services.analyzer.Balise.objects.filter", return_value=MagicMock(prefetch_related=MagicMock(return_value=self.catalogue))) as lookup:
            report = self.analyzer.analyze_bytes(word_bytes("{{ dossier.numero }}"))
        self.assertTrue(report.valide)
        lookup.assert_called_once_with(code__in={"dossier.numero"})

    @override_settings(ENVIRONMENT="prod")
    def test_prod_refusee_avant_tout_acces(self):
        with self.assertRaisesRegex(ValueError, "dev"):
            self.analyzer.analyze(DocumentTemplate(chemin_relatif="test_generation.docx"))

    @override_settings(ENVIRONMENT="dev")
    def test_nas_dev_ouvert_en_lecture_seule(self):
        data = word_bytes("{{ dossier.numero }}")
        with patch("document_generation.services.template_path.dotenv_values", return_value={"NAS_ROOT": r"\\serveur\dev"}), patch(
            "document_generation.services.template_path.smbclient.open_file", mock_open(read_data=data)
        ) as opened, patch("document_generation.services.analyzer.Balise.objects.filter", return_value=MagicMock(prefetch_related=MagicMock(return_value=self.catalogue))):
            report = self.analyzer.analyze(DocumentTemplate(chemin_relatif="test_generation.docx"))
        self.assertTrue(report.valide)
        opened.assert_called_once_with(r"\\serveur\dev\Templates\test_generation.docx", mode="rb", share_access="rwd")

    @override_settings(ENVIRONMENT="dev")
    def test_antislashs_doubles_du_env_normalises(self):
        with patch("document_generation.services.template_path.dotenv_values", return_value={"NAS_ROOT": "\\\\\\\\serveur\\\\dev\\\\"}), patch(
            "document_generation.services.template_path.smbclient.open_file", mock_open(read_data=word_bytes("Texte fixe"))
        ) as opened, patch("document_generation.services.analyzer.Balise.objects.filter", return_value=MagicMock(prefetch_related=MagicMock(return_value=[]))):
            self.analyzer.analyze(DocumentTemplate(chemin_relatif="test_generation.docx"))
        opened.assert_called_once_with(r"\\serveur\dev\Templates\test_generation.docx", mode="rb", share_access="rwd")

    @override_settings(ENVIRONMENT="dev")
    def test_erreur_lecture_rapportee(self):
        with patch("document_generation.services.template_path.dotenv_values", return_value={"NAS_ROOT": r"\\serveur\dev"}), patch(
            "document_generation.services.template_path.smbclient.open_file", side_effect=PermissionError
        ):
            report = self.analyzer.analyze(DocumentTemplate(chemin_relatif="test_generation.docx"))
        self.assertFalse(report.valide)
        self.assertIn("Impossible de lire", report.erreurs[0])
