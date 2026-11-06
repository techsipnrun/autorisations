from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import os
import subprocess
import time
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.http import Http404
from django.test import SimpleTestCase, RequestFactory, override_settings

from document_generation.services.pdf_preview import (
    PdfPreviewService, PdfPreviewError, PreviewBusyError, preview_directory,
    clean_previews, _lock, _stop_process_tree,
)
from document_generation import views


@override_settings(ENVIRONMENT="dev")
class PdfPreviewTests(SimpleTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "previews"
        override = override_settings(DOCUMENT_PREVIEW_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)
        self.service = PdfPreviewService()

    def converter(self, source, output):
        self.assertTrue(source.is_file())
        self.docx_path = source
        output.mkdir(parents=True)
        result = output / "preview.pdf"
        result.write_bytes(b"%PDF-1.7\nnew-preview")
        return result

    def create(self):
        with patch.object(self.service, "convert_docx_to_pdf", side_effect=self.converter):
            return self.service.create_preview(BytesIO(b"docx"), 42, 1, 5)

    def test_creation_remplacement_et_suppression_docx(self):
        path = self.create()
        path.write_bytes(b"%PDF-1.7\nold-preview")
        self.assertEqual(self.create(), path)
        self.assertEqual(path.read_bytes(), b"%PDF-1.7\nnew-preview")
        self.assertFalse(self.docx_path.exists())
        self.assertEqual([p.name for p in path.parent.iterdir()], ["preview.pdf"])

    def test_echec_conserve_ancien_pdf_et_supprime_intermediaires(self):
        path = self.create()
        original = path.read_bytes()
        with patch.object(self.service, "convert_docx_to_pdf", side_effect=PdfPreviewError("Échec")), self.assertRaises(PdfPreviewError):
            self.service.create_preview(BytesIO(b"docx"), 42, 1, 5)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual([p.name for p in path.parent.iterdir()], ["preview.pdf"])

    def test_autre_utilisateur_ne_lit_pas_le_pdf(self):
        self.create()
        with self.assertRaises(FileNotFoundError):
            self.service.read_preview(43, 1, 5)
        with self.service.read_preview(42, 1, 5) as buffer:
            self.assertTrue(buffer.read().startswith(b"%PDF-"))

    def test_identifiants_non_internes_refuses(self):
        for user in ("../42", "42", -1, 0, True):
            with self.subTest(user=user), self.assertRaises(PdfPreviewError):
                preview_directory(user, 1, 5)

    def test_verrou_empeche_conversion_et_nettoyage_concurrents(self):
        path = self.create()
        with _lock(path.parent):
            with self.assertRaises(PreviewBusyError):
                self.service.create_preview(BytesIO(b"docx"), 42, 1, 5)
            self.assertEqual(clean_previews(1), 0)

    def test_nettoyage_anciens_uniquement(self):
        old = self.create()
        age = time.time() - 10800
        os.utime(old, (age, age))
        os.utime(old.parent, (age, age))
        recent = preview_directory(43, 1, 5)
        recent.mkdir(parents=True)
        (recent / "preview.pdf").write_bytes(b"%PDF-1.7\nrecent")
        self.assertEqual(clean_previews(), 1)
        self.assertFalse(old.parent.exists())
        self.assertTrue(recent.exists())

    def test_commande_nettoyage(self):
        output = __import__('io').StringIO()
        call_command("clean_document_previews", stdout=output)
        self.assertIn("0 répertoire", output.getvalue())

    def test_libreoffice_absent(self):
        with patch("document_generation.services.pdf_preview.libreoffice_binary", side_effect=PdfPreviewError("LibreOffice absent")), self.assertRaisesRegex(PdfPreviewError, "absent"):
            self.service.convert_docx_to_pdf(self.root / "preview.docx", self.root / "converted")

    def test_timeout_interrompt_processus(self):
        process = MagicMock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("soffice", 30), (b"", b"")]
        process.poll.return_value = 0
        with patch("document_generation.services.pdf_preview.libreoffice_binary", return_value="soffice"), patch(
            "document_generation.services.pdf_preview.subprocess.Popen", return_value=process
        ), patch("document_generation.services.pdf_preview._stop_process_tree") as stop, self.assertRaisesRegex(PdfPreviewError, "délai"):
            self.service.convert_docx_to_pdf(self.root / "preview.docx", self.root / "converted")
        stop.assert_called_once_with(process)

    def test_interruption_windows_vise_arbre_processus(self):
        if os.name != "nt":
            self.skipTest("Variante Windows")
        process = MagicMock(pid=12345)
        process.poll.return_value = None
        with patch("document_generation.services.pdf_preview.subprocess.run") as run:
            _stop_process_tree(process)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "12345", "/T", "/F"])
        process.kill.assert_called_once()

    def test_processus_succes_sans_pdf_est_erreur(self):
        process = MagicMock(returncode=0)
        process.communicate.return_value = (b"", b"")
        with patch("document_generation.services.pdf_preview.libreoffice_binary", return_value="soffice"), patch(
            "document_generation.services.pdf_preview.subprocess.Popen", return_value=process
        ), self.assertRaises(PdfPreviewError):
            self.service.convert_docx_to_pdf(self.root / "preview.docx", self.root / "converted")


@override_settings(ENVIRONMENT="dev")
class PreviewHttpTests(SimpleTestCase):
    def request(self, authenticated=True, user=42):
        request = RequestFactory().get("/document-generation/preview/30769307/5/?user_id=99")
        request.user = SimpleNamespace(is_authenticated=authenticated, is_superuser=True, pk=user)
        return request

    def test_non_connecte_redirige_vers_login(self):
        self.assertEqual(views.preview_pdf(self.request(False), 30769307, 5).status_code, 302)

    def test_serve_uniquement_utilisateur_courant_et_autorise_iframe(self):
        dossier, template = SimpleNamespace(pk=1), SimpleNamespace(pk=5)
        with patch("document_generation.views._work_context", return_value=(dossier, template)), patch(
            "document_generation.views.PdfPreviewService.read_preview", return_value=BytesIO(b"%PDF-1.7\ntest")
        ) as read:
            response = views.preview_pdf(self.request(), 30769307, 5)
        try:
            read.assert_called_once_with(42, 1, 5)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
            self.assertIn("no-store", response["Cache-Control"])
        finally:
            response.close()

    def test_pdf_absent_404(self):
        with patch("document_generation.views._work_context", return_value=(SimpleNamespace(pk=1), SimpleNamespace(pk=5))), patch(
            "document_generation.views.PdfPreviewService.read_preview", side_effect=FileNotFoundError
        ), self.assertRaises(Http404):
            views.preview_pdf(self.request(user=43), 30769307, 5)
