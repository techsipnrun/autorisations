from io import BytesIO
from docx import Document
from django.test import SimpleTestCase
from document_generation.services.test_template import enrich_test_template
from document_generation.services.docx_renderer import DocxRenderer
from document_generation.services.analyzer import TemplateAnalyzer
from autorisations.models.models_generation import Balise


class TestWordExamplesTests(SimpleTestCase):
    def test_exemples_if_for_couleurs_sans_lignes_de_controle(self):
        original = Document()
        original.add_paragraph("Base conservée : {{ dossier.numero }}")
        source = BytesIO()
        original.save(source)
        enriched = enrich_test_template(source.getvalue())
        self.assertEqual(enrich_test_template(enriched), enriched)
        report = TemplateAnalyzer().analyze_bytes(enriched, [Balise(code=code, mode="CONNUE")
                                                            for code in ("dossier.numero", "dossier.commune")])
        self.assertTrue(report.valide, report.erreurs)
        self.assertEqual({item['code'] for item in report.balises}, {"dossier.numero", "dossier.commune"})
        for commune in ("Saint-Paul", None):
            with self.subTest(commune=commune), DocxRenderer().render_to_memory(
                enriched, {"dossier": {"numero": 123, "commune": commune}}
            ) as result:
                doc = Document(result)
                texts = [p.text for p in doc.paragraphs]
                self.assertIn("Base conservée : 123", texts)
                self.assertIn("Premier exemple — Dossier 123", texts)
                self.assertIn("Troisième exemple — Dossier 123", texts)
                self.assertTrue(any(run.font.color.rgb for p in doc.paragraphs for run in p.runs))
                self.assertFalse(any("{%" in text for text in texts))
                self.assertEqual("Aucune commune renseignée." in texts, commune is None)
