from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import mock_open, patch

from django.test import SimpleTestCase, override_settings
from docx import Document

from autorisations.models.models_generation import DocumentTemplate
from document_generation.services.docx_renderer import DocxRenderer, DocxRenderError, build_preview_filename
from document_generation.services.template_path import get_template_absolute_path, read_template_bytes, TemplatePathError


def template_bytes(text):
    doc = Document()
    doc.add_paragraph(text)
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


class DocxRendererTests(SimpleTestCase):
    def setUp(self):
        self.renderer = DocxRenderer()

    def test_remplacement_balises_imbriquees(self):
        source = template_bytes("Dossier {{ dossier.numero }} — {{ beneficiaire.nom }}")
        rendered = self.renderer.render_to_memory(source, {"dossier": {"numero": 30769307}, "beneficiaire": {"nom": "DUPONT"}})
        self.assertEqual(rendered.tell(), 0)
        self.assertEqual(Document(rendered).paragraphs[0].text, "Dossier 30769307 — DUPONT")
        self.assertIn("{{ dossier.numero }}", Document(BytesIO(source)).paragraphs[0].text)
        rendered.close()

    def test_condition_vrai_et_faux(self):
        source = template_bytes("{% if projet.survol_helicoptere %}Survol prévu.{% else %}Pas de survol.{% endif %}")
        for value, expected in ((True, "Survol prévu."), (False, "Pas de survol.")):
            with self.subTest(value=value):
                with self.renderer.render_to_memory(source, {"projet": {"survol_helicoptere": value}}) as stream:
                    self.assertEqual(Document(stream).paragraphs[0].text, expected)

    def test_boucle_sur_liste_de_dictionnaires(self):
        source = template_bytes("{% for espece in projet.especes %}{{ espece.nom }}\n{% endfor %}")
        with self.renderer.render_to_memory(source, {"projet": {"especes": [{"nom": "Espèce A"}, {"nom": "Espèce B"}]}}) as stream:
            text = Document(stream).paragraphs[0].text
        self.assertIn("Espèce A\nEspèce B", text)

    def test_formats_et_caracteres_xml(self):
        source = template_bytes("{{ texte }} | {{ date }} | {{ oui }} / {{ non }} | {{ nombre }} | {{ commentaire }} | {{ absent }}")
        context = {"texte": "Étude & protection <test>", "date": date(2026, 11, 3), "oui": True, "non": False,
                   "nombre": Decimal("72.5"), "commentaire": "Ligne 1\nLigne 2", "absent": None}
        with self.renderer.render_to_memory(source, context) as stream:
            text = Document(stream).paragraphs[0].text
        self.assertIn("Étude & protection <test>", text)
        self.assertIn("03/11/2026", text)
        self.assertIn("Oui / Non", text)
        self.assertIn("72.5", text)
        self.assertIn("Ligne 1\nLigne 2", text)
        self.assertNotIn("None", text)
        self.assertIsInstance(context["date"], date)
        self.assertIs(context["non"], False)

    def test_styles_tableau_entete_pied_et_balise_decoupee(self):
        doc = Document()
        p = doc.add_paragraph(style="Heading 1")
        p.add_run("Document de test").bold = True
        p = doc.add_paragraph()
        p.add_run("{{ dossier.")
        p.add_run("numero }}")
        doc.sections[0].header.paragraphs[0].text = "Entête {{ dossier.numero }}"
        doc.sections[0].footer.paragraphs[0].text = "Pied {{ dossier.numero }}"
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "{{ dossier.numero }}"
        original_width = doc.sections[0].page_width
        stream = BytesIO()
        doc.save(stream)
        with self.renderer.render_to_memory(stream.getvalue(), {"dossier": {"numero": 30769307}}) as result:
            output = Document(result)
        self.assertEqual(output.paragraphs[0].style.name, "Heading 1")
        self.assertTrue(output.paragraphs[0].runs[0].bold)
        self.assertEqual(output.paragraphs[1].text, "30769307")
        self.assertEqual(output.tables[0].cell(0, 0).text, "30769307")
        self.assertEqual(output.sections[0].header.paragraphs[0].text, "Entête 30769307")
        self.assertEqual(output.sections[0].footer.paragraphs[0].text, "Pied 30769307")
        self.assertEqual(output.sections[0].page_width, original_width)

    def test_contexte_incomplet_refuse_sans_sortie_silencieuse(self):
        with self.assertRaisesRegex(DocxRenderError, "rendu"):
            self.renderer.render_to_memory(template_bytes("{{ dossier.numero }}"), {})

    def test_syntaxe_invalide(self):
        with self.assertRaisesRegex(DocxRenderError, "rendu"):
            self.renderer.render_to_memory(template_bytes("{% if dossier.numero %}"), {"dossier": {"numero": 1}})

    def test_template_inexistant_ou_corrompu(self):
        with TemporaryDirectory() as folder:
            for source in (Path(folder) / "absent.docx", b"pas un Word"):
                with self.subTest(source=type(source)), self.assertRaisesRegex(DocxRenderError, "illisible"):
                    self.renderer.render_to_memory(source, {})

    def test_erreur_sauvegarde_memoire(self):
        with patch("docxtpl.DocxTemplate.save", side_effect=OSError("Erreur simulée")), self.assertRaisesRegex(DocxRenderError, "télécharger"):
            self.renderer.render_to_memory(template_bytes("Test"), {})

    def test_nom_de_fichier_centralise(self):
        filename = build_preview_filename(SimpleNamespace(nom="Arrêté / test"), SimpleNamespace(numero=30769307))
        self.assertEqual(filename, "Projet_arrete-test_30769307.docx")


@override_settings(ENVIRONMENT="dev")
class TemplatePathTests(SimpleTestCase):
    def setUp(self):
        config = patch("document_generation.services.template_path.dotenv_values", return_value={"NAS_ROOT": r"\\serveur\dev"})
        config.start()
        self.addCleanup(config.stop)

    def test_normalisation_et_lecture_strictement_source(self):
        source = DocumentTemplate(chemin_relatif="TEST/test.docx")
        with patch("document_generation.services.template_path.smbclient.path.isfile", return_value=True), patch(
            "document_generation.services.template_path.smbclient.open_file", mock_open(read_data=b"source")
        ) as opened:
            self.assertEqual(get_template_absolute_path(source), r"\\serveur\dev\Templates\TEST\test.docx")
            self.assertEqual(read_template_bytes(source), b"source")
        opened.assert_called_once_with(r"\\serveur\dev\Templates\TEST\test.docx", mode="rb", share_access="rwd")

    def test_chemins_interdits_avant_acces_nas(self):
        with patch("document_generation.services.template_path.smbclient.path.isfile") as exists:
            for relative in ("../ailleurs.docx", "C:/ailleurs.docx", "test.pdf", "TEST/../../ailleurs.docx"):
                with self.subTest(relative=relative), self.assertRaises(TemplatePathError):
                    get_template_absolute_path(DocumentTemplate(chemin_relatif=relative))
        exists.assert_not_called()

    def test_template_absent(self):
        with patch("document_generation.services.template_path.smbclient.path.isfile", return_value=False), self.assertRaisesRegex(TemplatePathError, "introuvable"):
            get_template_absolute_path(DocumentTemplate(chemin_relatif="TEST/absent.docx"))

    @override_settings(ENVIRONMENT="prod")
    def test_prod_interdite(self):
        with self.assertRaises(ValueError):
            get_template_absolute_path(DocumentTemplate(chemin_relatif="TEST/test.docx"))
