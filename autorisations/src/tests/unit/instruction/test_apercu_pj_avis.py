from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from instruction.templatetags.custom_filters import type_apercu_document


class ApercuPjAvisTests(SimpleTestCase):
    def test_loupe_docx_dans_formulaire_et_projet_avis(self):
        for template,context in (
            ('instruction/refacto/file_hover_preview.html',{'fichier_emplacement':'Work/','fichier_titre':'projet.DOCX'}),
            ('instruction/refacto/avis_document_apercu_pdf.html',{'emplacement':'Work/','titre':'projet.docx'}),
            ('instruction/refacto/message_avis_piece_jointe.html',{'msg':SimpleNamespace(pj_emplacement='Avis/',pj_title='message.DOCX')}),
        ):
            with self.subTest(template=template):
                html=render_to_string(template,context)
                self.assertIn('data-preview-type="docx"',html)
                self.assertIn('document-apercu-popover',html)

    def test_formats_supportes_et_detection_de_lextension_finale(self):
        for titre, attendu in (("acte.PDF", "pdf"), ("photo.PNG", "image"), ("photo.jpg", "image"),
            ("photo.jpeg", "image"), ("image.webp", "image"), ("projet.docx", "docx"), ("projet.DOCX", "docx"), ("ancien.doc", ""),
            ("annexe.pdf.docx", "docx"), (None, "")):
            with self.subTest(titre=titre):
                self.assertEqual(type_apercu_document(titre), attendu)

    def test_loupe_avant_telechargement_uniquement_pour_les_formats_compatibles(self):
        for titre, attendu in (("acte.pdf", True), ("photo.png", True), ("projet.docx", True)):
            with self.subTest(titre=titre):
                html = render_to_string("instruction/refacto/avis_piece_jointe_form.html", {
                    "avis": SimpleNamespace(id=1), "document": SimpleNamespace(id=2, titre=titre, emplacement="Avis/Annexes/"),
                    "input_id": "pj_projet_acte", "input_name": "pj_projet_acte", "source_pj": "id_projet_acte",
                })
                self.assertEqual('class="avis-pj-action document-apercu-trigger"' in html, attendu)
                if attendu:
                    self.assertLess(html.index('class="avis-pj-action document-apercu-trigger"'), html.index('?download=1'))
                    self.assertIn('role="tooltip"', html)
