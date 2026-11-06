from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings, RequestFactory
from django.http import HttpResponse
from django.utils import timezone
from autorisations.models.models_documents import DocumentNature

from document_generation.services import act_file_guard as guard
from instruction.views import changement_etape


@override_settings(ENVIRONMENT='dev')
class ActFileGuardTests(SimpleTestCase):
    def test_provenance_du_work_et_nature_de_la_reservation(self):
        nature = SimpleNamespace(pk=3, nature='Arrêté directeur', prefixe_numero='DIR-I-')
        user = SimpleNamespace(first_name='Louis', last_name='Calu')
        row = SimpleNamespace(id_document_id=4, id_document=SimpleNamespace(emplacement='Autre/Test/Work/', titre='projet.docx',
            id_nature_id=2, id_statut_id=None, publie_au_raa=False, url_ds=None, url_dm=None),
            id_numero=SimpleNamespace(id_nature=nature, numero='2026-0123'), user=user, date=timezone.now())
        elsewhere = SimpleNamespace(id_document=SimpleNamespace(emplacement='Autre/AutreDossier/Work/'))
        with patch.object(guard.DocumentGeneration.objects, 'filter') as query:
            query.return_value.exclude.return_value.exclude.return_value.select_related.return_value.defer.return_value = [row, elsewhere]
            result = guard.act_file_provenance(SimpleNamespace(emplacement='Autre/Test/'))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['nature_id'], 3)
        self.assertIn('Projet d’arrêté DIR-I-2026-0123 généré par Louis CALU le ', result[0]['description'])

    def test_filtre_actes_numerotes_du_dossier_sans_limite_historique(self):
        dossier = SimpleNamespace(pk=7)
        rows = [SimpleNamespace(pk=i) for i in range(70)]
        with patch.object(guard.DocumentGeneration.objects, 'filter') as query, patch.object(
            guard, 'check_files', return_value=[{'state': 'found'}] * 69 + [{'state': 'missing'}],
        ) as check:
            query.return_value.exclude.return_value.exclude.return_value.select_related.return_value.only.return_value = rows
            result = guard.act_file_status(dossier)
        query.assert_called_once_with(id_dossier=dossier, id_numero__isnull=False, id_numero__id_nature__est_acte=True)
        query.return_value.exclude.assert_called_once_with(id_numero__numero='')
        query.return_value.exclude.return_value.exclude.assert_called_once_with(id_numero__id_nature__nature__iexact='Avis Instance')
        check.assert_called_once_with(rows)
        self.assertEqual(result, {'missing': 1, 'unknown': 0, 'blocked': True})

    def test_inaccessible_ne_compte_pas_comme_fichier_a_reparer(self):
        with patch.object(guard.DocumentGeneration.objects, 'filter'), patch.object(guard, 'check_files', return_value=[{'state': 'unknown'}]):
            result = guard.act_file_status(SimpleNamespace(pk=7))
        self.assertEqual(result, {'missing': 0, 'unknown': 1, 'blocked': True})
        self.assertIn('impossible', guard.blocked_message(result))

    @override_settings(ENVIRONMENT='prod')
    def test_prod_aucune_lecture_bdd_ni_nas(self):
        with patch.object(guard.DocumentGeneration.objects, 'filter') as query, patch.object(guard, 'check_files') as check:
            self.assertFalse(guard.act_file_status(None)['blocked'])
        query.assert_not_called()
        check.assert_not_called()

    def test_confirmation_serveur_refuse_absence_ou_indisponibilite(self):
        for status in ({'missing': 1, 'unknown': 0, 'blocked': True}, {'missing': 0, 'unknown': 1, 'blocked': True}):
            with self.subTest(status=status), patch.object(guard, 'act_file_status', return_value=status), patch.object(changement_etape, 'redirect_error', return_value='refus'):
                self.assertEqual(changement_etape._verifier_fichiers_generes_actes(None, SimpleNamespace(numero=123)), 'refus')

    def test_confirmation_serveur_refuse_bdd_inaccessible(self):
        with patch.object(guard, 'act_file_status', side_effect=OperationalError()), patch.object(changement_etape, 'redirect_error', return_value='refus'), self.assertLogs(changement_etape.logger, 'ERROR'):
            self.assertEqual(changement_etape._verifier_fichiers_generes_actes(None, SimpleNamespace(numero=123)), 'refus')

    def test_reparation_ou_suppression_debloque_controle_suivant(self):
        with patch.object(guard, 'act_file_status', return_value={'missing': 0, 'unknown': 0, 'blocked': False}):
            self.assertIsNone(changement_etape._verifier_fichiers_generes_actes(None, None))

    def test_trois_parcours_refusent_avant_mutations(self):
        dossier = SimpleNamespace(numero=123, emplacement='Test/')
        for name in ('faire_valider_une_demande_d_avis', 'faire_valider_le_projet_d_acte', 'acte_pret_a_la_signature'):
            with self.subTest(view=name), ExitStack() as stack:
                stack.enter_context(patch.object(changement_etape, 'get_dossier_or_redirect', return_value=(dossier, None)))
                stack.enter_context(patch.object(changement_etape, 'get_instructeur_or_redirect', return_value=(SimpleNamespace(id=2), None)))
                stack.enter_context(patch.object(changement_etape, 'get_type_acte', return_value=DocumentNature(nature='Arrêté directeur', est_acte=True)))
                stack.enter_context(patch.object(changement_etape, 'get_projets_work_manquants', return_value=[]))
                stack.enter_context(patch.object(changement_etape, 'Dossier'))
                stack.enter_context(patch.object(changement_etape, 'DocumentFormat'))
                stack.enter_context(patch.object(changement_etape, 'DocumentStatut'))
                stack.enter_context(patch.object(changement_etape, 'Instructeur'))
                document = stack.enter_context(patch.object(changement_etape, 'Document'))
                roles = stack.enter_context(patch.object(changement_etape, 'DossierValideur'))
                update = stack.enter_context(patch.object(changement_etape, 'safe_update_etape'))
                blocked = HttpResponse(status=409)
                check = stack.enter_context(patch.object(changement_etape, '_verifier_fichiers_generes_actes', return_value=blocked))
                request = RequestFactory().post('/test', {'dossierId': '1', 'nature_document': '3',
                    'choix-validant': '2', 'piece_jointe_work': 'projet.docx', 'avis_selectionnes': ['4']})
                request.user = SimpleNamespace(is_authenticated=True, email='agent@example.test')
                response = getattr(changement_etape, name)(request)
                self.assertIs(response, blocked)
                check.assert_called_once_with(request, dossier)
                document.objects.get_or_create.assert_not_called()
                roles.objects.filter.assert_not_called()
                update.assert_not_called()
