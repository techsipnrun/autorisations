from contextlib import ExitStack, nullcontext
from io import BytesIO
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import SimpleTestCase, RequestFactory, override_settings

from document_generation import history_views
from document_generation.services import history_files as files
from document_generation.services.output import DocumentOutputError


class HistoryFilesTests(SimpleTestCase):
    def row(self, pk=1, folder='Test/Work/', filename='Test.docx'):
        return SimpleNamespace(pk=pk, id_document=SimpleNamespace(emplacement=folder, titre=filename))

    def test_verifications_regroupees_par_destination_et_etats_distincts(self):
        with patch.object(files, 'list_word_files', side_effect=[['test.DOCX'], FileNotFoundError(), PermissionError()]) as read, self.assertLogs(files.logger, 'ERROR'):
            result = files.check_files([self.row(), self.row(2, filename='Absent.docx'), self.row(3, 'Absent/'), self.row(4, 'Denied/')])
        self.assertEqual([r['state'] for r in result], ['found', 'missing', 'missing', 'unknown'])
        self.assertEqual(read.call_count, 3)

    def test_racine_inaccessible_ne_devient_pas_fichier_manquant(self):
        with patch.object(files, 'dev_nas_root', return_value='//nas/dev/'), patch.object(files, '_assert_directory', side_effect=FileNotFoundError()), self.assertLogs(files.logger, 'ERROR'):
            self.assertEqual(files.check_files([self.row()])[0]['state'], 'unknown')

    def test_fichier_present_ou_indetermine_interdit_toute_correction(self):
        for state in ('found', 'unknown'):
            with self.subTest(state=state), patch.object(files, 'check_files', return_value=[{'state': state}]), self.assertRaises(DocumentOutputError):
                files.ensure_missing(self.row())

    def test_destinations_origine_et_actuelle_uniquement(self):
        row=self.row();row.id_template_id=3;row.id_template=SimpleNamespace()
        with patch.object(files, 'resolve_destination', return_value=('//nas/dev/', ['Nouveau', 'Work'], '//nas/dev/Nouveau/Work')):
            self.assertEqual(files.candidate_folders(row, object()), ['Test/Work/', 'Nouveau/Work/'])

    def environment(self, stack):
        self.generation=MagicMock(pk=3, id_document_id=7, template_snapshot={'document_sha256':sha256(b'original').hexdigest()}, file_corrections=[])
        self.document=MagicMock(pk=7, emplacement='Test/Work/', titre='Ancien.docx')
        stack.enter_context(patch.object(files.transaction, 'atomic', return_value=nullcontext()))
        generations=stack.enter_context(patch.object(files.DocumentGeneration.objects, 'select_for_update'))
        self.locked_generations=generations.return_value
        generations.return_value.get.return_value=self.generation
        generations.return_value.select_related.return_value.get.return_value=self.generation
        documents=stack.enter_context(patch.object(files.Document.objects, 'select_for_update'))
        documents.return_value.get.return_value=self.document
        self.missing=stack.enter_context(patch.object(files, 'ensure_missing'))
        self.uses=stack.enter_context(patch.object(files, 'other_uses', return_value=False))
        self.links=stack.enter_context(patch.object(files.DossierDocument.objects, 'filter'))
        self.existing=stack.enter_context(patch.object(files.Document.objects, 'filter'))
        self.existing.return_value.exclude.return_value.exists.return_value=False
        stack.enter_context(patch.object(files, 'candidate_folders', return_value=['Test/Work/']))
        stack.enter_context(patch.object(files, 'list_word_files', return_value=['Renommé.docx']))
        self.read=stack.enter_context(patch.object(files, 'read_generated_document', return_value=BytesIO(b'modified')))

    def test_reassociation_trace_correction_sans_modifier_snapshots(self):
        with ExitStack() as stack:
            self.environment(stack)
            original_snapshot=dict(self.generation.template_snapshot)
            user=SimpleNamespace(pk=42, get_username=lambda:'louis')
            self.assertFalse(files.reassociate(object(),3,user,'Test/Work/','Renommé.docx'))
            event=self.generation.file_corrections[-1]
            self.assertEqual(event['old']['filename'], 'Ancien.docx')
            self.assertEqual(event['new']['filename'], 'Renommé.docx')
            self.assertEqual(event['user_id'],42)
            self.assertFalse(event['matches_original'])
            self.assertEqual(self.generation.template_snapshot,original_snapshot)
            self.document.save.assert_called_once_with(update_fields=['emplacement','titre'])
            self.generation.save.assert_called_once_with(update_fields=['file_corrections'])
            self.locked_generations.select_related.assert_not_called()

    def test_reassociation_refuse_chemin_libre_et_document_partage(self):
        for folder, filename, shared in [('Autre/','Renommé.docx',False), ('Test/Work/','../Renommé.docx',False), ('Test/Work/','Renommé.docx',True)]:
            with self.subTest(folder=folder, filename=filename, shared=shared), ExitStack() as stack:
                self.environment(stack);self.uses.return_value=shared
                with self.assertRaises(DocumentOutputError):
                    files.reassociate(object(),3,object(),folder,filename)
                self.read.assert_not_called();self.document.save.assert_not_called()

    def test_suppression_bdd_conserve_document_encore_utilise(self):
        for shared in (False, True):
            with self.subTest(shared=shared), ExitStack() as stack:
                self.environment(stack);self.uses.return_value=shared
                self.assertEqual(files.remove_from_history(object(),3),shared)
                self.generation.delete.assert_called_once()
                self.links.return_value.delete.assert_called_once()
                self.assertEqual(self.document.delete.called,not shared)


@override_settings(ENVIRONMENT='dev')
class HistoryApiTests(SimpleTestCase):
    def test_acces_non_autorise_et_prod_refuses_pour_toutes_les_actions(self):
        for view, args, method in [(history_views.status,(123,),'get'),(history_views.choices,(123,3),'get'),
                                   (history_views.remove,(123,3),'post'),(history_views.relink,(123,3),'post')]:
            request=getattr(RequestFactory(),method)('/')
            request.user=SimpleNamespace(is_authenticated=True,is_superuser=False,pk=42)
            with self.subTest(view=view.__name__), patch('document_generation.views.get_object_or_404',return_value=object()), patch(
                'document_generation.views.est_concerne_par_le_dossier',return_value=False
            ), self.assertRaises(PermissionDenied):
                view(request,*args)
            with override_settings(ENVIRONMENT='prod'), self.assertRaises(Http404):
                view(request,*args)

    def test_mutations_interdites_en_get(self):
        request=RequestFactory().get('/');request.user=SimpleNamespace(is_authenticated=True)
        self.assertEqual(history_views.remove(request,123,3).status_code,405)
        self.assertEqual(history_views.relink(request,123,3).status_code,405)
