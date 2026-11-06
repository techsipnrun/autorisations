"""Conversion LibreOffice réelle, uniquement sur activation explicite, sans BDD/NAS."""
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from docx import Document
from document_generation.services.pdf_preview import PdfPreviewService


@skipUnless(os.environ.get("AGIDA_TEST_LIBREOFFICE") == "1", "Test LibreOffice réel non activé.")
@override_settings(ENVIRONMENT="dev")
class LibreOfficePreviewTests(SimpleTestCase):
    def test_conversion_reelle_et_remplacement(self):
        with TemporaryDirectory() as temporary, override_settings(DOCUMENT_PREVIEW_ROOT=Path(temporary) / "previews"):
            service = PdfPreviewService()
            for texte in ("Premier aperçu AGIDA", "Nouvel aperçu AGIDA"):
                document = Document()
                document.add_paragraph(texte)
                with BytesIO() as source:
                    document.save(source)
                    path = service.create_preview(source, 42, 1, 5)
                self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
                self.assertGreater(path.stat().st_size, 100)
                self.assertEqual([p.name for p in path.parent.iterdir()], ["preview.pdf"])
