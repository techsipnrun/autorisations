from contextlib import ExitStack, nullcontext
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
import stat
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, ProgrammingError
from django.http import Http404
from django.test import SimpleTestCase, RequestFactory, override_settings

from document_generation.services.record_generation import RecordGenerationService
from document_generation.services.output import DocumentOutputError
from document_generation.services.history import dossier_history, read_generated_document
from document_generation import views


@override_settings(ENVIRONMENT='dev')
class RecordGenerationTests(SimpleTestCase):
    def setUp(self):
        self.dossier = SimpleNamespace(pk=1, numero=31770683)
        self.user = SimpleNamespace(pk=42)
        self.template = SimpleNamespace(pk=3, code='test', nom='Test', chemin_relatif='TEST/test.docx',
                                        destination_relative='{dossier.emplacement}Work/', nom_fichier='Test.docx')
        self.output = {'filename': 'Test_2.docx', 'destination': '//nas/dev/Test/Work/',
                       'relative_destination': 'Test/Work/', 'path': r'\\nas\dev\Test\Work\Test_2.docx'}

    def environment(self, stack):
        stack.enter_context(patch('document_generation.services.record_generation.DocumentGeneration.objects.values_list'))
        self.nature_get = stack.enter_context(patch('document_generation.services.record_generation.DocumentNature.objects.get'))
        self.format_get = stack.enter_context(patch('document_generation.services.record_generation.DocumentFormat.objects.get'))
        self.write = stack.enter_context(patch('document_generation.services.record_generation.DocumentOutputService.save', return_value=self.output))
        self.document = stack.enter_context(patch('document_generation.services.record_generation.Document.objects.create'))
        self.link = stack.enter_context(patch('document_generation.services.record_generation.DossierDocument.objects.create'))
        self.record = stack.enter_context(patch('document_generation.services.record_generation.DocumentGeneration.objects.create'))
        self.atomic = stack.enter_context(patch('document_generation.services.record_generation.transaction.atomic', return_value=nullcontext()))
        self.remove = stack.enter_context(patch('document_generation.services.record_generation.smbclient.remove'))

    def save(self):
        return RecordGenerationService().save(BytesIO(b'rendered'), self.template, self.dossier, self.user,
            {'projet': {'quantite': Decimal('12.50'), 'noms': ['Élodie'], 'survol': False}}, b'source')

    def test_document_liaison_et_historique_dans_une_transaction(self):
        with ExitStack() as stack:
            self.environment(stack)
            self.assertEqual(self.save(), self.output)
        self.nature_get.assert_called_once_with(nature='Fichier généré', actif=True, est_acte=False)
        self.format_get.assert_called_once_with(format__iexact='docx')
        self.atomic.assert_called_once()
        self.assertEqual(self.document.call_args.kwargs['titre'], 'Test_2.docx')
        self.assertEqual(self.document.call_args.kwargs['emplacement'], 'Test/Work/')
        self.assertIs(self.document.call_args.kwargs['id_nature'], self.nature_get.return_value)
        self.link.assert_called_once_with(id_dossier=self.dossier, id_document=self.document.return_value)
        record = self.record.call_args.kwargs
        self.assertEqual(record['context_snapshot']['projet'], {'quantite': '12.50', 'noms': ['Élodie'], 'survol': False})
        self.assertEqual(record['template_snapshot']['source_sha256'], sha256(b'source').hexdigest())
        self.assertEqual(record['template_snapshot']['document_sha256'], sha256(b'rendered').hexdigest())
        self.assertIs(record['user'], self.user)
        json.dumps(record['context_snapshot'])
        self.remove.assert_not_called()

    def test_echec_de_chacune_des_trois_insertions_supprime_uniquement_le_nouveau_word(self):
        for stage in ('document', 'link', 'record'):
            with self.subTest(stage=stage), ExitStack() as stack:
                self.environment(stack)
                getattr(self, stage).side_effect = IntegrityError('test')
                with self.assertLogs('document_generation.services.record_generation', 'ERROR'), self.assertRaisesRegex(DocumentOutputError, 'a été supprimé'):
                    self.save()
                self.atomic.assert_called_once()
                self.remove.assert_called_once_with(self.output['path'])

    def test_echec_nettoyage_signale_fichier_potentiellement_present(self):
        with ExitStack() as stack:
            self.environment(stack)
            self.record.side_effect = IntegrityError('test')
            self.remove.side_effect = OSError('locked')
            with self.assertLogs('document_generation.services.record_generation', 'ERROR'), self.assertRaisesRegex(DocumentOutputError, 'peut subsister'):
                self.save()

    def test_schema_absent_bloque_avant_ecriture_nas(self):
        with ExitStack() as stack:
            self.environment(stack)
            stack.enter_context(patch('document_generation.services.record_generation.DocumentGeneration.objects.values_list', side_effect=ProgrammingError('missing')))
            with self.assertRaisesRegex(DocumentOutputError, '0019'):
                self.save()
            self.write.assert_not_called()

    def test_echec_nas_ne_cree_aucune_ligne(self):
        with ExitStack() as stack:
            self.environment(stack)
            self.write.side_effect = DocumentOutputError('NAS indisponible')
            with self.assertRaises(DocumentOutputError):
                self.save()
            self.document.assert_not_called()
            self.record.assert_not_called()
            self.remove.assert_not_called()

    def test_production_refusee_avant_bdd_ou_nas(self):
        with override_settings(ENVIRONMENT='prod'), self.assertRaises(DocumentOutputError):
            self.save()

    def test_numero_reserve_sans_changer_la_nature_fichier_genere(self):
        reservation=SimpleNamespace(pk='token',numero='2026-112')
        with ExitStack() as stack:
            self.environment(stack)
            stack.enter_context(patch('document_generation.services.numbers.selected_number',return_value=reservation))
            RecordGenerationService().save(BytesIO(b'rendered'),self.template,self.dossier,self.user,
                {'document':{'numero':'2026-112'}},b'source',number_reservation=reservation,
                filename_pattern='jeudi_{document.numero}.docx')
        self.assertEqual(self.document.call_args.kwargs['numero'],'2026-112')
        self.assertIs(self.document.call_args.kwargs['id_nature'],self.nature_get.return_value)
        self.assertIs(self.record.call_args.kwargs['id_numero'],reservation)
        self.assertEqual(self.write.call_args.kwargs['document_number'],'2026-112')

    def test_numero_falsifie_bloque_avant_nas(self):
        reservation=SimpleNamespace(pk='token',numero='2026-112')
        with ExitStack() as stack:
            self.environment(stack)
            stack.enter_context(patch('document_generation.services.numbers.selected_number',return_value=reservation))
            with self.assertRaises(DocumentOutputError):
                RecordGenerationService().save(BytesIO(b'rendered'),self.template,self.dossier,self.user,
                    {'document':{'numero':'2026-999'}},b'source',number_reservation=reservation)
            self.write.assert_not_called()


@override_settings(ENVIRONMENT='dev')
class GenerationHistoryTests(SimpleTestCase):
    def test_historique_limite_au_dossier_sans_charger_le_contexte(self):
        dossier = SimpleNamespace(pk=1)
        with patch('document_generation.services.history.DocumentGeneration.objects.filter') as query:
            query.return_value.filter.return_value.select_related.return_value.defer.return_value = []
            self.assertEqual(dossier_history(dossier), {'generation_history': []})
        query.assert_called_once_with(id_dossier=dossier)
        query.return_value.filter.return_value.select_related.return_value.defer.assert_called_once_with('context_snapshot', 'file_corrections')
        query.return_value.values.assert_called_once_with('pk')

    def test_schema_absent_affiche_message_sans_bloquer_la_page(self):
        with patch('document_generation.services.history.DocumentGeneration.objects.filter', side_effect=ProgrammingError), self.assertLogs('document_generation.services.history', 'ERROR'):
            result = dossier_history(SimpleNamespace(pk=1))
        self.assertIn('0019', result['generation_history_error'])

    def test_telechargement_controle_dossier_et_generation(self):
        request = RequestFactory().get('/')
        request.user = SimpleNamespace(is_authenticated=True, pk=42)
        dossier = SimpleNamespace(pk=1)
        generation = SimpleNamespace(id_document=SimpleNamespace(titre='Test_2.docx'))
        with patch('document_generation.views._dossier_context', return_value=dossier), patch(
            'document_generation.views.DocumentGeneration.objects.select_related'
        ) as query, patch('document_generation.views.get_object_or_404', return_value=generation) as get, patch(
            'document_generation.views.read_generated_document', return_value=BytesIO(b'docx')
        ):
            response = views.download_generated(request, 123, 5)
        get.assert_called_once_with(query.return_value, pk=5, id_dossier=dossier)
        self.assertIn('Test_2.docx', response['Content-Disposition'])
        self.assertEqual(b''.join(response.streaming_content), b'docx')
        response.close()

    def test_utilisateur_non_autorise_ne_lit_pas_le_nas(self):
        request = RequestFactory().get('/')
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, pk=42)
        with patch('document_generation.views.get_object_or_404', return_value=SimpleNamespace()), patch(
            'document_generation.views.est_concerne_par_le_dossier', return_value=False
        ), patch('document_generation.views.read_generated_document') as read:
            with self.assertRaises(PermissionDenied):
                views.download_generated(request, 123, 5)
        read.assert_not_called()

    def test_generation_d_un_autre_dossier_refusee(self):
        request = RequestFactory().get('/')
        request.user = SimpleNamespace(is_authenticated=True, pk=42)
        dossier = SimpleNamespace(pk=1)
        with patch('document_generation.views._dossier_context', return_value=dossier), patch(
            'document_generation.views.DocumentGeneration.objects.select_related'
        ), patch('document_generation.views.get_object_or_404', side_effect=Http404), patch(
            'document_generation.views.read_generated_document'
        ) as read, self.assertRaises(Http404):
            views.download_generated(request, 123, 5)
        read.assert_not_called()

    def test_telechargement_non_connecte_refuse(self):
        request = RequestFactory().get('/document-generation/dossier/123/generation/5/telecharger/')
        request.user = SimpleNamespace(is_authenticated=False)
        with patch('document_generation.views.read_generated_document') as read:
            response = views.download_generated(request, 123, 5)
        self.assertEqual(response.status_code, 302)
        read.assert_not_called()

    def test_chemin_historique_ne_peut_pas_sortir_du_nas(self):
        for path in ('../prod/', '/absolu/', '//nas/prod/'):
            with self.subTest(path=path), patch('document_generation.services.history.dev_nas_root', return_value='//nas/dev/'), patch(
                'document_generation.services.history.smbclient.open_file'
            ) as opened:
                with self.assertRaises(DocumentOutputError):
                    read_generated_document(SimpleNamespace(emplacement=path, titre='Test.docx'))
                opened.assert_not_called()

    def test_lien_fichier_refuse(self):
        with patch('document_generation.services.history.dev_nas_root', return_value='//nas/dev/'), patch(
            'document_generation.services.history._assert_directory'
        ), patch('document_generation.services.history.smbclient.lstat', return_value=SimpleNamespace(st_file_attributes=0x400, st_mode=stat.S_IFREG)), patch(
            'document_generation.services.history.smbclient.open_file'
        ) as opened, self.assertRaises(DocumentOutputError):
            read_generated_document(SimpleNamespace(emplacement='Test/', titre='Test.docx'))
        opened.assert_not_called()
