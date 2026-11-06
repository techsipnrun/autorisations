from contextlib import ExitStack
from io import BytesIO
import stat
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from smbprotocol.exceptions import SMBOSError
from smbprotocol.header import NtStatus

from autorisations.models.models_generation import DocumentTemplate
from document_generation.services.output import DocumentOutputError, DocumentOutputService


@override_settings(ENVIRONMENT="dev")
class DocumentOutputTests(SimpleTestCase):
    def setUp(self):
        self.template = DocumentTemplate(nom="Test", id_nature_id=1,
                                         chemin_relatif="TEST/test.docx",
                                         destination_relative="{dossier.emplacement}Work/",
                                         nom_fichier="DIR-{dossier.numero}.docx")
        self.dossier = SimpleNamespace(numero=123, emplacement="Travaux/2026/Dossier/", pk=1)

    def environment(self, stack, prod=r"\\nas\prod"):
        stack.enter_context(patch("document_generation.services.output.dotenv_values",
                                 side_effect=lambda path: {"NAS_ROOT": r"\\nas\dev" if path.name == ".env.dev" else prod}))
        stack.enter_context(patch("document_generation.services.output.smbclient.lstat",
                                 return_value=SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)))
        opened = stack.enter_context(patch("document_generation.services.output.smbclient.open_file"))
        opened.return_value.__enter__.return_value.write.return_value = 4
        return opened

    def test_ecriture_dev_et_confirmation_chemin_reel(self):
        with ExitStack() as stack:
            opened = self.environment(stack)
            result = DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        opened.assert_called_once_with(r"\\nas\dev\Travaux\2026\Dossier\Work\DIR-123.docx", mode="xb")
        self.assertEqual(result['filename'], "DIR-123.docx")
        self.assertEqual(result['destination'], "//nas/dev/Travaux/2026/Dossier/Work/")

    def test_collisions_n_ecrasent_pas_et_suffixent(self):
        with ExitStack() as stack:
            opened = self.environment(stack)
            target = MagicMock()
            target.__enter__.return_value.write.return_value = 4
            opened.side_effect = [FileExistsError(), FileExistsError(), target]
            result = DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        self.assertEqual(result['filename'], "DIR-123_3.docx")
        self.assertTrue(all(call.kwargs['mode'] == 'xb' for call in opened.call_args_list))

    def test_collision_reelle_smb_suffixee_sans_ecrasement(self):
        with ExitStack() as stack:
            opened = self.environment(stack)
            target = MagicMock()
            target.__enter__.return_value.write.return_value = 4
            collision = SMBOSError(NtStatus.STATUS_OBJECT_NAME_COLLISION, "fichier.docx")
            self.assertNotIsInstance(collision, FileExistsError)
            opened.side_effect = [collision, collision, target]
            result = DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        self.assertEqual(result['filename'], "DIR-123_3.docx")

    def test_erreur_droits_smb_non_assimilee_a_une_collision(self):
        with ExitStack() as stack:
            opened = self.environment(stack)
            opened.side_effect = SMBOSError(NtStatus.STATUS_ACCESS_DENIED, "fichier.docx")
            with self.assertRaises(DocumentOutputError):
                DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        opened.assert_called_once()

    def test_creation_dossier_manquant_et_patron_avec_slash_historique(self):
        self.template.destination_relative = "{dossier.emplacement}/Work/"
        with ExitStack() as stack:
            self.environment(stack)
            directory = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
            stack.enter_context(patch("document_generation.services.output.smbclient.lstat",
                                      side_effect=[directory, directory, directory, directory, FileNotFoundError(), directory]))
            mkdir = stack.enter_context(patch("document_generation.services.output.smbclient.mkdir"))
            result = DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        mkdir.assert_called_once_with(r"\\nas\dev\Travaux\2026\Dossier\Work")
        self.assertEqual(result['filename'], "DIR-123.docx")

    def test_echec_ecriture_supprime_seulement_son_fichier_partiel(self):
        with ExitStack() as stack:
            opened = self.environment(stack)
            opened.return_value.__enter__.return_value.write.side_effect = OSError("disque plein")
            remove = stack.enter_context(patch("document_generation.services.output.smbclient.remove"))
            with self.assertRaises(DocumentOutputError):
                DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        remove.assert_called_once_with(r"\\nas\dev\Travaux\2026\Dossier\Work\DIR-123.docx")

    def test_aucune_suppression_si_ouverture_refusee(self):
        with ExitStack() as stack:
            opened = self.environment(stack)
            opened.side_effect = PermissionError("refusé")
            remove = stack.enter_context(patch("document_generation.services.output.smbclient.remove"))
            with self.assertRaises(DocumentOutputError):
                DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        remove.assert_not_called()

    def test_emplacement_hors_dev_et_liens_refuses(self):
        for emplacement in ("../prod/", "/prod/", r"\\nas\prod", "Travaux/../prod/"):
            with self.subTest(emplacement=emplacement), ExitStack() as stack:
                opened = self.environment(stack)
                self.dossier.emplacement = emplacement
                with self.assertRaises(DocumentOutputError):
                    DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
                opened.assert_not_called()
        self.dossier.emplacement = "Dossier/"
        with ExitStack() as stack:
            opened = self.environment(stack)
            stack.enter_context(patch("document_generation.services.output.smbclient.lstat",
                                      return_value=SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)))
            with self.assertRaises(DocumentOutputError):
                DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
            opened.assert_not_called()

    def test_racines_dev_prod_communes_refusees_avant_ecriture(self):
        for root in (r"\\nas\dev", r"\\nas\dev\production"):
            with self.subTest(root=root), ExitStack() as stack:
                opened = self.environment(stack, prod=root)
                with self.assertRaises(DocumentOutputError):
                    DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
                opened.assert_not_called()

    @override_settings(ENVIRONMENT="prod")
    def test_production_refusee_avant_tout_acces(self):
        with patch("document_generation.services.output.dotenv_values") as config:
            with self.assertRaises(DocumentOutputError):
                DocumentOutputService().save(BytesIO(b"docx"), self.template, self.dossier)
        config.assert_not_called()
