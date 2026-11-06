from contextlib import nullcontext, ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from autorisations.models.models_documents import Document, DocumentNature
from document_generation.services import act_integration as service


@override_settings(ENVIRONMENT='dev')
class ActIntegrationTests(SimpleTestCase):
    def setUp(self):
        self.dossier = SimpleNamespace(pk=1, emplacement='Test/')
        self.nature = DocumentNature(id=3, nature='Arrêté directeur', est_acte=True)
        self.document = Document(id=7, emplacement='Test/Work/', titre='projet.docx',
            id_nature=DocumentNature(id=2, nature='Fichier généré'), numero='2026-0123')
        self.reservation = SimpleNamespace(pk='uuid', numero='2026-0123', id_nature_id=3, id_dossier_id=1,
            id_nature=self.nature, origine='GENERE')
        self.row = SimpleNamespace(pk=11, id_document=self.document, id_document_id=7, id_numero=self.reservation, id_numero_id='uuid')

    def setup_integration(self, stack):
        stack.enter_context(patch.object(service, 'find_generated_act', return_value=self.row))
        stack.enter_context(patch.object(service.transaction, 'atomic', return_value=nullcontext()))
        stack.enter_context(patch.object(service.Dossier, 'objects'))
        objects = stack.enter_context(patch.object(service.Document, 'objects'))
        objects.select_for_update.return_value.select_related.return_value.get.return_value = self.document
        objects.filter.return_value.exclude.return_value.values_list.return_value = []
        reservations = stack.enter_context(patch.object(service.DocumentNumberReservation, 'objects'))
        reservations.select_for_update.return_value.get.return_value = self.reservation
        stack.enter_context(patch.object(service.DossierDocument, 'objects'))
        return objects

    def test_promotion_sans_save_sans_compteur_et_meme_document(self):
        with ExitStack() as stack:
            objects = self.setup_integration(stack)
            save = stack.enter_context(patch.object(self.document, 'save'))
            result = service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None)
        self.assertIs(result, self.document)
        self.assertEqual(result.id_nature_id, 3)
        self.assertEqual(result.numero, '2026-0123')
        self.assertEqual(objects.filter.return_value.update.call_args.kwargs['numero'], '2026-0123')
        save.assert_not_called()

    def test_nature_differente_ou_plusieurs_generations_refusees(self):
        with patch.object(service.DocumentGeneration, 'objects') as objects:
            query = objects.filter.return_value.exclude.return_value.exclude.return_value.select_related.return_value.defer
            query.return_value = [self.row]
            with self.assertRaisesMessage(ValidationError, 'même nature'):
                service.find_generated_act(self.dossier, 'projet.docx', 9)
            query.return_value = [self.row, self.row]
            with self.assertRaisesMessage(ValidationError, 'plusieurs générations'):
                service.find_generated_act(self.dossier, 'projet.docx', 3)
            query.return_value = []
            self.assertIsNone(service.find_generated_act(self.dossier, 'manuel.docx', 3))

    def test_numero_modifie_et_conflit_existant_refuses(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict), ExitStack() as stack:
                objects = self.setup_integration(stack)
                self.document.numero = '2026-0123' if conflict else 'FAUX'
                objects.filter.return_value.exclude.return_value.values_list.return_value = ['Test/Work/'] if conflict else []
                with self.assertRaises(ValidationError):
                    service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None)
                objects.filter.return_value.update.assert_not_called()

    def test_partage_volontaire_autre_emplacement_conserve_numero_sans_compteur(self):
        self.reservation.origine = 'RECUPERE'
        with ExitStack() as stack:
            objects = self.setup_integration(stack)
            objects.filter.return_value.exclude.return_value.values_list.return_value = ['AutreDossier/Work/']
            save = stack.enter_context(patch.object(self.document, 'save'))
            result = service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None)
        self.assertEqual(result.numero, '2026-0123')
        objects.filter.return_value.update.assert_called_once()
        save.assert_not_called()

    def test_document_source_peut_integrer_apres_le_dossier_qui_a_recupere_son_numero(self):
        with ExitStack() as stack:
            objects = self.setup_integration(stack)
            objects.filter.return_value.exclude.return_value.values_list.return_value = ['AutreDossier/Work/']
            result = service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None)
            self.assertEqual(result.numero, self.reservation.numero)
            objects.filter.return_value.update.assert_called_once()

    def test_meme_emplacement_normalise_refuse_meme_avec_recuperation(self):
        self.reservation.origine = 'RECUPERE'
        with ExitStack() as stack:
            objects = self.setup_integration(stack)
            objects.filter.return_value.exclude.return_value.values_list.return_value = ['TEST\\Work']
            with self.assertRaisesMessage(ValidationError, 'Confirmez explicitement'):
                service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None)
            objects.filter.return_value.update.assert_not_called()

    def test_document_envoye_refuse(self):
        from autorisations.models.models_documents import DocumentStatut
        self.document.id_statut = DocumentStatut(statut='Envoyé')
        with ExitStack() as stack:
            objects = self.setup_integration(stack)
            with self.assertRaisesMessage(ValidationError, 'diffusion'):
                service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None)
            objects.filter.return_value.update.assert_not_called()

    def test_remplacement_explicite_archive_ancienne_version_et_historise_sans_compteur(self):
        old = Document(id=9, titre='ancien.docx', emplacement='Test/Work/', id_nature=self.nature, numero=self.reservation.numero)
        old_history = SimpleNamespace(circuit_events=[], save=lambda **kwargs: None)
        new_history = SimpleNamespace(circuit_events=[], save=lambda **kwargs: None)
        with ExitStack() as stack:
            objects = self.setup_integration(stack)
            objects.filter.return_value.exclude.return_value.values_list.return_value = ['Test/Work/']
            stack.enter_context(patch.object(service, 'replacement_candidate', return_value=old))
            histories = stack.enter_context(patch.object(service.DocumentGeneration, 'objects'))
            histories.select_for_update.return_value.get.side_effect = [old_history, new_history]
            natures = stack.enter_context(patch.object(service.DocumentNature, 'objects'))
            natures.get.return_value = DocumentNature(id=2, nature='Fichier généré')
            save = stack.enter_context(patch.object(self.document, 'save'))
            result = service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None,
                replace_document_id='9', user=SimpleNamespace(pk=42))
        self.assertEqual(result.numero, '2026-0123')
        self.assertEqual(objects.filter.return_value.update.call_count, 2)
        self.assertEqual(objects.filter.return_value.update.call_args_list[0].kwargs['id_nature'].nature, 'Fichier généré')
        self.assertEqual(old_history.circuit_events, new_history.circuit_events)
        self.assertEqual(new_history.circuit_events[0]['old_document_id'], 9)
        self.assertEqual(new_history.circuit_events[0]['new_document_id'], 7)
        self.assertEqual(new_history.circuit_events[0]['user_id'], 42)
        save.assert_not_called()

    def test_identifiant_remplacement_falsifie_refuse_sans_modifier_document(self):
        with ExitStack() as stack:
            objects = self.setup_integration(stack)
            objects.filter.return_value.exclude.return_value.values_list.return_value = ['Test/Work/']
            stack.enter_context(patch.object(service, 'replacement_candidate', return_value=SimpleNamespace(pk=9)))
            with self.assertRaisesMessage(ValidationError, 'Confirmez explicitement'):
                service.integrate_generated_act(self.dossier, 'projet.docx', self.nature, None, None, replace_document_id='999')
            objects.filter.return_value.update.assert_not_called()

    def test_projet_encore_en_circuit_ou_diffuse_non_remplacable(self):
        for attribute, value in [('id_statut_id', 4), ('publie_au_raa', True), ('url_ds', 'https://example.test')]:
            with self.subTest(attribute=attribute), patch.object(service.Document, 'objects') as objects:
                old = Document(id=9, titre='ancien.docx', emplacement='Test/Work/', id_nature=self.nature, numero=self.reservation.numero)
                setattr(old, attribute, value)
                objects.filter.return_value.exclude.return_value.select_related.return_value = [old]
                with self.assertRaisesMessage(ValidationError, 'encore dans le circuit'):
                    service.replacement_candidate(self.row, self.dossier)

    @override_settings(ENVIRONMENT='prod')
    def test_prod_aucune_recherche_generation(self):
        with patch.object(service.DocumentGeneration, 'objects') as objects:
            self.assertIsNone(service.find_generated_act(self.dossier, 'projet.docx', 3))
            objects.filter.assert_not_called()
