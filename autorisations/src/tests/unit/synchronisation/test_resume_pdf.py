from contextlib import ExitStack
import os
from unittest.mock import call, patch

import requests
from django.test import SimpleTestCase

from synchronisation.utils.fichiers import write_resume_pdf
from tests.support.constants import FICHIERS, URL_SIGNEE

from tests.support.fichiers import ReponseHTTP


class ResumePdfTests(SimpleTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"NAS_ROOT": r"\\nas\share"}))
        self.stack.enter_context(patch(f"{FICHIERS}.ensure_dossier_root", return_value=r"\\nas\share\Dossier"))
        self.http = self.stack.enter_context(patch(f"{FICHIERS}.requests.get"))
        self.ecrire = self.stack.enter_context(patch(f"{FICHIERS}.ecrire_file_sur_nas", return_value=True))
        self.sleep = self.stack.enter_context(patch(f"{FICHIERS}.time.sleep"))
        self.logger = self.stack.enter_context(patch(f"{FICHIERS}.loggerORM"))

    def test_pdf_resume_lit_en_flux_avec_un_delai_adapte(self):
        self.http.return_value = ReponseHTTP(headers={"Content-Length": "3"}, chunks=[b"pdf"])

        chemin = write_resume_pdf("Dossier", "dossier-123.pdf", URL_SIGNEE)

        self.assertEqual(chemin, r"\\nas\share\Dossier\dossier-123.pdf")
        self.assertEqual(self.http.call_args.kwargs["timeout"], (10, 120))
        self.assertTrue(self.http.call_args.kwargs["stream"])
        self.assertEqual(self.ecrire.call_args.args[0].read(), b"pdf")

    def test_pdf_resume_reessaie_sans_exposer_url_signee(self):
        self.http.side_effect = [
            requests.exceptions.ReadTimeout(f"délai dépassé {URL_SIGNEE}"),
            ReponseHTTP(headers={"Content-Length": "3"}, chunks=[b"pdf"]),
        ]

        self.assertIsNotNone(write_resume_pdf("Dossier", "dossier-123.pdf", URL_SIGNEE))

        self.assertEqual(self.sleep.call_args_list, [call(2)])
        self.assertIn("RESUME PDF HTTP RETRY", str(self.logger.warning.call_args))
        self.assertNotIn("SECRET_A_NE_PAS_LOGGER", str(self.logger.mock_calls))
