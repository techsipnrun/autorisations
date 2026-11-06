from contextlib import ExitStack, nullcontext
from datetime import date
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch, MagicMock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, RequestFactory, override_settings
from django.db.models import Model
from django.db import connections

from autorisations.models.models_documents import Document, DocumentNature
from autorisations.models.models_generation import DocumentTemplate, Balise
from document_generation.services import numbers
from document_generation.services.filename import resolve_filename
from document_generation.services.filename_editor import filename_editor_context
from document_generation.forms import DynamicDocumentForm
from document_generation.services.catalogue_sources import source_errors


@override_settings(ENVIRONMENT='dev')
class DocumentNumberTests(SimpleTestCase):
    def setUp(self):
        self.nature=DocumentNature(id=3,nature='Arrêté directeur',est_acte=True,mode_numerotation='automatique')
        self.template=DocumentTemplate(id=2,nom='Test',id_nature=self.nature)
        self.dossier=SimpleNamespace(pk=1,numero=123,id_ensemble_dossiers_id=5)
        self.user=SimpleNamespace(pk=42,is_superuser=True)
        self.key=uuid4()
        self.request=RequestFactory().post('/',{'request_key':str(self.key)})
        self.request.user=self.user
        self.request.session={'document_number_states':{'1:2':{'request_key':str(self.key),'selected':''}}}

    def environment(self, stack, existing=None):
        stack.enter_context(patch.object(numbers.transaction,'atomic',return_value=nullcontext()))
        self.cursor=stack.enter_context(patch.object(connections['default'],'cursor')).return_value.__enter__.return_value
        self.cursor.fetchone.return_value=('2026-1000',)
        self.query=stack.enter_context(patch.object(numbers.DocumentNumberReservation.objects,'filter'))
        self.query.return_value.first.return_value=existing
        self.create=stack.enter_context(patch.object(numbers.DocumentNumberReservation.objects,'create',return_value=SimpleNamespace(pk=self.key,numero='2026-1000')))

    def test_get_ne_reserve_rien_et_prepare_uniquement_un_jeton_de_session(self):
        self.request.session={}
        with patch.object(numbers.DocumentNumberReservation.objects,'create') as create, patch.object(connections['default'],'cursor') as cursor:
            state=numbers.session_state(self.request,self.dossier,self.template)
            self.assertIsNone(numbers.selected_number('',self.dossier,self.template,self.user))
        self.assertTrue(state['request_key']);create.assert_not_called();cursor.assert_not_called()

    def test_reservation_acte_via_compteur_partage_et_rotation_du_jeton(self):
        with ExitStack() as stack:
            self.environment(stack)
            reservation,state=numbers.choose_number(self.request,self.dossier,self.template)
        self.assertEqual(reservation.numero,'2026-1000')
        self.assertNotEqual(state['request_key'],str(self.key))
        self.assertNotIn('selected',state)
        self.assertEqual(self.create.call_args.kwargs['id_nature_id'],3)
        self.assertEqual(self.create.call_args.kwargs['origine'],'GENERE')
        self.assertTrue(any('generation.prochain_numero_acte' in call.args[0] for call in self.cursor.execute.call_args_list))

    def test_double_envoi_reutilise_la_reservation_sans_nouveau_compteur(self):
        existing=SimpleNamespace(pk=self.key,numero='2026-1000')
        with ExitStack() as stack:
            self.environment(stack,existing)
            stack.enter_context(patch.object(numbers,'selected_number',return_value=existing))
            reservation,_=numbers.choose_number(self.request,self.dossier,self.template)
        self.assertIs(reservation,existing);self.create.assert_not_called()
        self.assertFalse(any('prochain_numero_acte' in call.args[0] or 'nextval' in call.args[0] for call in self.cursor.execute.call_args_list))

    def test_avis_instance_utilise_identifiant_sequence_et_pas_reference_externe(self):
        self.nature.nature='Avis instance';self.nature.est_acte=False
        with ExitStack() as stack:
            self.environment(stack);self.cursor.fetchone.return_value=(41,)
            numbers.choose_number(self.request,self.dossier,self.template)
        self.assertEqual(self.create.call_args.kwargs['numero'],'41')
        self.assertTrue(any("pg_get_serial_sequence('avis.avis','id')" in call.args[0] for call in self.cursor.execute.call_args_list))

    def test_recuperation_ne_consomme_aucun_numero(self):
        with ExitStack() as stack:
            self.environment(stack)
            stack.enter_context(patch.object(numbers,'number_choices',return_value=[{'key':'d:7:1','numero':'2026-011','dossier':123}]))
            numbers.choose_number(self.request,self.dossier,self.template,recover='d:7:1')
        self.assertEqual(self.create.call_args.kwargs['numero'],'2026-011')
        self.assertEqual(self.create.call_args.kwargs['origine'],'RECUPERE')
        self.assertEqual(self.cursor.execute.call_count,1) # verrou d'idempotence uniquement

    def test_recuperation_hors_liste_et_jeton_invente_refuses(self):
        with ExitStack() as stack:
            self.environment(stack)
            stack.enter_context(patch.object(numbers,'number_choices',return_value=[]))
            with self.assertRaises(ValidationError):
                numbers.choose_number(self.request,self.dossier,self.template,recover='d:999:999')
            self.create.assert_not_called()
        self.request.POST=self.request.POST.copy();self.request.POST['request_key']=str(uuid4())
        with ExitStack() as stack:
            self.environment(stack)
            with self.assertRaises(ValidationError): numbers.choose_number(self.request,self.dossier,self.template)
            self.create.assert_not_called()

    def test_selection_filtre_utilisateur_dossier_template_et_nature(self):
        with patch.object(numbers.DocumentNumberReservation.objects,'filter') as query:
            query.return_value.first.return_value=None
            with self.assertRaises(ValidationError):numbers.selected_number(self.key,self.dossier,self.template,self.user)
        query.assert_called_once_with(pk=self.key,id_dossier=self.dossier,id_template=self.template,id_nature_id=3,user=self.user)

    def test_dossiers_lies_non_autorises_exclus(self):
        other=SimpleNamespace(pk=9)
        self.user.is_superuser=False
        with patch.object(numbers.Dossier.objects,'filter',return_value=[self.dossier,other]), patch.object(numbers,'est_concerne_par_le_dossier',side_effect=lambda user,row:row.pk==1):
            self.assertEqual(numbers.accessible_dossiers(self.dossier,self.user),[self.dossier])

    def test_recuperation_filtre_bien_la_nature_et_deduplique_les_versions(self):
        linked=SimpleNamespace(pk=9,numero=999)
        row=SimpleNamespace(pk=uuid4(),numero='2026-112',id_dossier_id=9)
        duplicate=SimpleNamespace(pk=uuid4(),numero='2026-112',id_dossier_id=9)
        with patch.object(numbers,'accessible_dossiers',return_value=[self.dossier,linked]), patch.object(
            numbers.DocumentNumberReservation.objects,'filter'
        ) as reservations, patch.object(numbers.DossierDocument.objects,'filter') as links:
            reservations.return_value.distinct.return_value.order_by.return_value.__getitem__.return_value=[row,duplicate]
            links.return_value.select_related.return_value.__getitem__.return_value=[]
            choices=numbers.number_choices(self.dossier,self.template,self.user)
        self.assertEqual(choices,[{'key':f'r:{row.pk}','numero':'2026-112','dossier':999}])
        self.assertEqual(set(reservations.call_args.kwargs['id_dossier_id__in']),{1,9})
        self.assertEqual(reservations.call_args.kwargs['id_nature_id'],3)
        self.assertEqual(links.call_args.kwargs['id_document__id_nature_id'],3)

    def test_production_et_nature_non_numerotee_refusees(self):
        with override_settings(ENVIRONMENT='prod'),self.assertRaises(ValidationError):numbers.choose_number(self.request,self.dossier,self.template)
        self.nature.est_acte=False
        with self.assertRaises(ValidationError):numbers.choose_number(self.request,self.dossier,self.template)

    def test_numero_systeme_non_resolu_ne_devient_pas_un_champ_manuel(self):
        from document_generation.services.preparation import DocumentPreparationService
        from document_generation.services.analyzer import AnalysisReport
        definition=Balise(id=7,code='document.numero',libelle='Numéro',mode='CONNUE',source='AGIDA',source_propriete='document.numero',required=True)
        report=AnalysisReport(balises=[{'code':'document.numero','statut':'CONNUE'}])
        with patch('document_generation.services.preparation.TemplateAnalyzer.analyze_with_source',return_value=(b'word',report)), patch(
            'document_generation.services.preparation.Balise.objects.filter') as query:
            query.return_value.prefetch_related.return_value=[definition]
            prepared=DocumentPreparationService().prepare(self.dossier,self.template)
        self.assertEqual(prepared['form_balises'],[])
        self.assertEqual(source_errors(definition),[])
        definition.mode='A_RENSEIGNER';self.assertTrue(source_errors(definition))

    def test_nom_fichier_attend_numero_et_nettoie_ses_separateurs(self):
        with self.assertRaisesRegex(ValueError,'Générez ou récupérez'):
            resolve_filename('jeudi_{document.numero}.docx',self.dossier)
        self.assertEqual(resolve_filename('jeudi_{document.numero}.docx',self.dossier,document_number='2026-011'),'jeudi_2026-011.docx')
        values=filename_editor_context('jeudi_{document.numero}.docx',self.dossier)
        self.assertTrue(values['document.numero']['pending'])

    def test_creation_classique_acte_dev_utilise_le_meme_compteur(self):
        document=Document(id_nature=self.nature,id_format_id=1,titre='Acte.docx',emplacement='Test/')
        with patch('django.db.transaction.atomic',return_value=nullcontext()), patch.object(connections['default'],'cursor') as cursor, patch.object(Model,'save') as save:
            cursor.return_value.__enter__.return_value.fetchone.return_value=('2026-1042',)
            document.save()
        self.assertEqual(document.numero,'2026-1042');save.assert_called_once()
        cursor.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT generation.prochain_numero_acte(%s,%s)',[3,date.today().year])

    def test_creation_acte_prod_garde_le_fonctionnement_existant(self):
        document=Document(id_nature=self.nature,id_format_id=1,titre='Acte.docx',emplacement='Test/')
        with override_settings(ENVIRONMENT='prod'),patch.object(Model,'save'),patch.object(
            Document.objects,'filter'
        ) as documents,patch('django.db.transaction.atomic',return_value=nullcontext()),patch.object(connections['default'],'cursor') as cursor:
            documents.return_value.aggregate.return_value={'max_num':f'{date.today().year}-1041'}
            document.save()
        self.assertEqual(document.numero,f'{date.today().year}-1042');cursor.assert_not_called()
