from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from instruction.views import changement_etape as view
from instruction import utils_instru
from autorisations.utils import nas_fonctions


class SignatureTransactionTests(SimpleTestCase):
    def test_failures_after_document_save_escape_atomic_block(self):
        for failure in ('role', 'action', 'step', None):
            with self.subTest(failure=failure), ExitStack() as stack:
                names = ('get_dossier_or_redirect', 'get_instructeur_or_redirect', 'get_type_acte',
                         'get_projets_work_manquants', 'Document', 'DocumentStatut', 'DocumentFormat',
                         'Dossier', 'DossierSignataire', 'DossierEnvoiActe', 'get_object_or_404',
                         'creer_dossier_sur_nas', 'generate_unique_filename', 'ecrire_file_sur_nas',
                         'redirect_error')
                mocks = {name: stack.enter_context(patch.object(view, name)) for name in names}
                atomic = stack.enter_context(patch.object(view.transaction, 'atomic'))
                save = stack.enter_context(patch('document_generation.services.signed_act.save_signed_documents'))
                action = stack.enter_context(patch.object(utils_instru, 'enregistrer_action'))
                step = stack.enter_context(patch.object(utils_instru, 'changer_etape_si_differente'))
                stack.enter_context(patch.dict('os.environ', {'NAS_ROOT': 'test-nas'}))
                dossier = SimpleNamespace(pk=1, numero=1, emplacement='Test/', id_etape_dossier_id=8)
                nature = Mock(pk=3, est_acte=True, rapport_ca_obligatoire=False)
                document = Mock(pk=4, id=4, id_nature_id=3, numero_effectif='2026-0123')
                mocks['get_dossier_or_redirect'].return_value = dossier, None
                mocks['get_instructeur_or_redirect'].return_value = Mock(), None
                mocks['get_type_acte'].return_value = nature
                mocks['get_projets_work_manquants'].return_value = []
                mocks['Document'].objects.filter.return_value.first.return_value = document
                mocks['Dossier'].objects.select_for_update.return_value.get.return_value = dossier
                mocks['generate_unique_filename'].return_value = 'acte', '//test/Actes/acte.pdf'
                mocks['redirect_error'].return_value = HttpResponse(status=400)
                save.return_value = document, None
                if failure == 'role':
                    mocks['DossierSignataire'].objects.create.side_effect = RuntimeError('role')
                elif failure == 'action':
                    action.side_effect = RuntimeError('action')
                elif failure == 'step':
                    step.side_effect = RuntimeError('step')
                request = RequestFactory().post('/test/', {
                    'dossierId': '1', 'nature_document': '3', 'id_doc_a_signer': '4',
                    'choix-signataire': '2', 'choix-envoi-acte-peti': '2',
                    'piece_jointe': SimpleUploadedFile('acte.pdf', b'%PDF-test'),
                })
                request.user = Mock(is_authenticated=True)
                response = view.acte_pret_a_etre_envoye(request)
                save.assert_called_once()
                self.assertEqual(response.status_code, 400 if failure else 302)
                exit_args = atomic.return_value.__exit__.call_args.args
                self.assertIs(exit_args[0], RuntimeError if failure else None)
                self.assertTrue(mocks['ecrire_file_sur_nas'].call_args.kwargs['exclusive'])
                if not failure:
                    self.assertTrue(step.call_args.kwargs['notify_after_commit'])

    def test_notification_waits_for_commit(self):
        dossier = Mock()
        dossier.id_etape_dossier = None
        with patch.object(utils_instru.EtapeDossier, 'objects') as steps, patch.object(
            utils_instru, '_notifier_changement_etape') as notify, patch(
            'django.db.transaction.on_commit') as on_commit:
            steps.filter.return_value.first.return_value = Mock(est_archivage=False)
            utils_instru.changer_etape_si_differente(dossier, 'Acte à envoyer', Mock(), Mock(),
                                                     notify_after_commit=True)
            notify.assert_not_called()
            on_commit.call_args.args[0]()
            notify.assert_called_once()

    def test_existing_nas_file_is_never_opened_for_overwrite(self):
        with patch.object(nas_fonctions.smbclient.path, 'exists', return_value=True), patch.object(
            nas_fonctions.smbclient, 'open_file', side_effect=FileExistsError) as open_file:
            self.assertFalse(nas_fonctions.ecrire_file_sur_nas(b'%PDF', '//test/file.pdf', exclusive=True))
        open_file.assert_called_once_with('//test/file.pdf', mode='xb')
