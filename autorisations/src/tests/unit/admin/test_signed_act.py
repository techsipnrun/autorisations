from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from document_generation.services import signed_act as service


@override_settings(ENVIRONMENT='dev')
class SignedActTests(SimpleTestCase):
    def test_statuts_acte_et_rapport_regroupes_dans_une_transaction(self):
        dossier=SimpleNamespace(pk=4)
        with patch.object(service.transaction,'atomic') as atomic, patch.object(service.Dossier,'objects'), patch.object(
            service.DossierDocument,'objects'), patch.object(service.Document,'objects') as documents, patch.object(
            service,'save_signed_act',side_effect=['acte signé','rapport signé']) as save:
            result=service.save_signed_documents(dossier,'acte',{'titre':'acte.pdf'},report='rapport',report_values={'titre':'rapport.pdf'})
        self.assertEqual(result,('acte signé','rapport signé'))
        self.assertEqual(save.call_count,2)
        documents.filter.return_value.update.assert_called_once_with(id_statut=None)
        atomic.return_value.__exit__.assert_called_once_with(None,None,None)

    def test_echec_rapport_propage_pour_annuler_aussi_statuts_et_acte(self):
        with patch.object(service.transaction,'atomic') as atomic, patch.object(service.Dossier,'objects'), patch.object(
            service.DossierDocument,'objects'), patch.object(service.Document,'objects'), patch.object(
            service,'save_signed_act',side_effect=['acte signé',RuntimeError('échec rapport')]):
            with self.assertRaisesMessage(RuntimeError,'échec rapport'):
                service.save_signed_documents(SimpleNamespace(pk=4),'acte',{},report='rapport',report_values={})
        self.assertIs(atomic.return_value.__exit__.call_args.args[0],RuntimeError)

    def test_echec_acte_ne_tente_pas_transmission_rapport(self):
        with patch.object(service.transaction,'atomic') as atomic, patch.object(service.Dossier,'objects'), patch.object(
            service.DossierDocument,'objects'), patch.object(service.Document,'objects'), patch.object(
            service,'save_signed_act',side_effect=RuntimeError('échec acte')) as save:
            with self.assertRaises(RuntimeError):
                service.save_signed_documents(SimpleNamespace(pk=4),'acte',{},report='rapport',report_values={})
        save.assert_called_once()
        self.assertIs(atomic.return_value.__exit__.call_args.args[0],RuntimeError)

    def prepare(self, stack, generated=True):
        self.document = Mock(pk=7, titre='source.docx', emplacement='Test/Work/',
            id_format_id=1, numero_effectif='2026-0123', description='Source', date='date')
        self.generation = Mock(id_dossier_id=4, circuit_events=[]) if generated else None
        stack.enter_context(patch.object(service.transaction, 'atomic', return_value=nullcontext()))
        docs = stack.enter_context(patch.object(service.Document, 'objects'))
        docs.select_for_update.return_value.get.return_value = self.document
        histories = stack.enter_context(patch.object(service.DocumentGeneration, 'objects'))
        histories.select_for_update.return_value.filter.return_value.first.return_value = self.generation
        self.links = stack.enter_context(patch.object(service.DossierDocument, 'objects'))
        self.natures = stack.enter_context(patch.object(service.DocumentNature, 'objects'))
        return docs, histories

    def test_word_conserve_numero_chemin_et_historique_pdf_garde_identite(self):
        with ExitStack() as stack:
            docs, histories = self.prepare(stack)
            # Le couple chemin/nom doit être libéré avant de créer la source.
            docs.create.side_effect = lambda **kw: (self.document.save.assert_called_once(), Mock(pk=12))[1]
            result = service.save_signed_act(self.document, SimpleNamespace(pk=4),
                {'titre': 'signe.pdf', 'emplacement': 'Test/Actes/', 'id_format_id': 2},
                user=SimpleNamespace(pk=8))
            values = docs.create.call_args.kwargs
        self.assertIs(result, self.document)
        self.assertEqual(result.pk, 7)
        self.assertEqual(result.titre, 'signe.pdf')
        self.assertEqual(values['titre'], 'source.docx')
        self.assertEqual(values['emplacement'], 'Test/Work/')
        self.assertEqual(values['numero'], '2026-0123')
        self.assertIsNone(values['id_statut'])
        self.assertEqual(self.generation.id_document.pk, 12)
        self.assertIs(self.generation.id_document_signe, result)
        self.assertEqual(self.generation.circuit_events[0]['signed_document_id'], 7)
        self.generation.save.assert_called_once()
        docs.select_for_update.assert_called_once_with()

    def test_parcours_manuel_ne_cree_pas_de_word_ou_historique(self):
        with ExitStack() as stack:
            docs, histories = self.prepare(stack, generated=False)
            service.save_signed_act(self.document, SimpleNamespace(pk=4), {'titre': 'signe.pdf'})
        self.document.save.assert_called_once()
        docs.create.assert_not_called()
        self.links.create.assert_not_called()
        self.natures.get.assert_not_called()

    def test_echec_sauvegarde_pdf_ne_detache_pas_historique(self):
        with ExitStack() as stack:
            docs, histories = self.prepare(stack)
            self.document.save.side_effect = RuntimeError('échec')
            with self.assertRaises(RuntimeError):
                service.save_signed_act(self.document, SimpleNamespace(pk=4), {'titre': 'signe.pdf'})
        docs.create.assert_not_called()
        self.generation.save.assert_not_called()

    @override_settings(ENVIRONMENT='prod')
    def test_prod_ne_consulte_pas_module_generation(self):
        with ExitStack() as stack:
            docs, histories = self.prepare(stack)
            service.save_signed_act(self.document, SimpleNamespace(pk=4), {'titre': 'signe.pdf'})
        histories.select_for_update.assert_not_called()
        docs.create.assert_not_called()
