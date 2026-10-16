from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from instruction.templatetags.custom_filters import type_apercu_document


class ApercuPjAvisTests(SimpleTestCase):
    def test_formats_supportes_et_detection_de_lextension_finale(self):
        for titre, attendu in (("acte.PDF", "pdf"), ("photo.PNG", "image"), ("photo.jpg", "image"),
            ("photo.jpeg", "image"), ("image.webp", "image"), ("projet.docx", ""),
            ("annexe.pdf.docx", ""), (None, "")):
            with self.subTest(titre=titre):
                self.assertEqual(type_apercu_document(titre), attendu)

    def test_loupe_avant_telechargement_uniquement_pour_les_formats_compatibles(self):
        for titre, attendu in (("acte.pdf", True), ("photo.png", True), ("projet.docx", False)):
            with self.subTest(titre=titre):
                html = render_to_string("instruction/refacto/avis_piece_jointe_form.html", {
                    "avis": SimpleNamespace(id=1), "document": SimpleNamespace(id=2, titre=titre, emplacement="Avis/Annexes/"),
                    "input_id": "pj_projet_acte", "input_name": "pj_projet_acte", "source_pj": "id_projet_acte",
                })
                self.assertEqual('class="avis-pj-action document-apercu-trigger"' in html, attendu)
                if attendu:
                    self.assertLess(html.index('class="avis-pj-action document-apercu-trigger"'), html.index('?download=1'))
                    self.assertIn('role="tooltip"', html)
