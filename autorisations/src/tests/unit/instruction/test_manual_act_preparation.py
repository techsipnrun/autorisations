from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, OperationalError
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings

from autorisations.models.models_documents import Document, DocumentNature, DocumentStatut, DocumentFormat
from autorisations.models.models_instruction import Dossier, EtapeDossier
from document_generation.services import manual_act as service
from instruction.views.manual_act import prepare_act
from instruction import utils_instru


@override_settings(ENVIRONMENT='dev')
class ManualActPreparationTests(SimpleTestCase):
    def setUp(self):
        self.dossier = Dossier(id=4, numero=123, emplacement='Test/', id_demarche_id=7)
        self.dossier.id_etape_dossier = EtapeDossier(id=8, etape='En instruction')
        self.nature = DocumentNature(id=3, nature='Arrêté directeur', est_acte=True, actif=True,
                                     mode_numerotation='automatique', prefixe_numero='DIR-I-')
        self.user = SimpleNamespace(pk=9, is_authenticated=True, is_superuser=True)
        self.key = uuid4()
        self.row = Mock(pk=self.key, id_dossier_id=4, id_nature_id=3, user_id=9, numero='2026-0012',
                        origine='GENERE', etat='ACTIVE', id_nature=self.nature)

    def db(self, stack):
        stack.enter_context(patch.object(service.transaction, 'atomic'))
        dossiers = stack.enter_context(patch.object(service.Dossier, 'objects'))
        dossiers.select_for_update.return_value.get.return_value = self.dossier
        rows = stack.enter_context(patch.object(service.ManualActPreparation, 'objects'))
        rows.filter.return_value.first.return_value = None
        rows.create.return_value = self.row
        return rows

    def test_reserve_utilise_le_compteur_commun_et_une_seule_creation(self):
        with ExitStack() as stack:
            rows = self.db(stack)
            cursor = stack.enter_context(patch.object(service, 'connection')).cursor
            sql = cursor.return_value.__enter__.return_value
            sql.fetchone.return_value = ('2026-0012',)
            service.select_preparation(self.dossier, self.nature, self.user, self.key)
        self.assertIn('generation.prochain_numero_acte', sql.execute.call_args.args[0])
        self.assertEqual(sql.execute.call_args.args[1][0], 3)
        self.assertEqual(rows.create.call_args.kwargs['numero'], '2026-0012')
        self.assertNotIn('id_template', rows.create.call_args.kwargs)

    def test_rejeu_meme_cle_ne_consomme_pas_un_autre_numero(self):
        with ExitStack() as stack:
            rows = self.db(stack)
            rows.filter.return_value.first.return_value = self.row
            cursor = stack.enter_context(patch.object(service, 'connection')).cursor
            result = service.select_preparation(self.dossier, self.nature, self.user, self.key)
        self.assertIs(result, self.row)
        cursor.assert_not_called()
        rows.create.assert_not_called()

    def test_autre_reservation_active_refusee(self):
        with ExitStack() as stack:
            self.db(stack)
            stack.enter_context(patch.object(service, 'active_preparation', return_value=self.row))
            cursor = stack.enter_context(patch.object(service, 'connection')).cursor
            with self.assertRaises(ValidationError):
                service.select_preparation(self.dossier, self.nature, self.user, uuid4())
        cursor.assert_not_called()

    def test_recuperation_sans_compteur_et_source_recontrolee(self):
        for source in ('d:1:4', 'd:2:999'):
            with self.subTest(source=source), ExitStack() as stack:
                rows = self.db(stack)
                stack.enter_context(patch.object(service, 'choices', return_value=[{'key':'d:1:4','numero':'2026-0012','dossier':123}]))
                cursor = stack.enter_context(patch.object(service, 'connection')).cursor
                if source == 'd:1:4':
                    service.select_preparation(self.dossier, self.nature, self.user, self.key, recover=source)
                    self.assertEqual(rows.create.call_args.kwargs['origine'], 'RECUPERE')
                else:
                    with self.assertRaises(ValidationError):
                        service.select_preparation(self.dossier, self.nature, self.user, self.key, recover=source)
                cursor.assert_not_called()

    def test_annulation_conserve_historique_et_ne_touche_pas_compteur(self):
        with ExitStack() as stack:
            self.db(stack)
            stack.enter_context(patch.object(service, 'active_preparation', return_value=self.row))
            cursor = stack.enter_context(patch.object(service, 'connection')).cursor
            service.cancel_preparation(self.dossier, self.key)
        self.assertEqual(self.row.etat, 'ABANDONNE')
        self.row.save.assert_called_once_with(update_fields=['etat','date_fin'])
        cursor.assert_not_called()

    def test_nature_et_token_du_changement_etape_verifies(self):
        for nature, token, allowed in [('3', str(self.key), True), ('4', str(self.key), False), ('3', '', False)]:
            request = RequestFactory().post('/', {'nature_document':nature,'manual_preparation':token})
            request.user = self.user
            with self.subTest(nature=nature, token=token), patch.object(service, 'active_preparation', return_value=self.row):
                if allowed:
                    self.assertIs(service.validate_transition(request,self.dossier), self.row)
                elif nature != '3':
                    self.assertIsNone(service.validate_transition(request,self.dossier))
                else:
                    with self.assertRaises(ValidationError):
                        service.validate_transition(request,self.dossier)

    def test_integration_document_reprend_numero_sans_appel_compteur(self):
        with ExitStack() as stack:
            rows = self.db(stack)
            rows.select_for_update.return_value.get.return_value = self.row
            stack.enter_context(patch.object(service, 'validate_transition', return_value=self.row))
            documents = stack.enter_context(patch.object(Document, 'objects'))
            documents.filter.return_value.first.return_value = None
            documents.filter.return_value.exists.return_value = False
            stack.enter_context(patch.object(service.DossierDocument, 'objects'))
            stack.enter_context(patch.object(models.Model, 'save', autospec=True, side_effect=lambda doc,*a,**kw:setattr(doc,'pk',100)))
            cursor = stack.enter_context(patch.object(service, 'connection')).cursor
            document = service.integrate_preparation(Mock(),self.dossier,'projet.docx',self.nature,
                DocumentStatut(id=1,statut='À valider'),DocumentFormat(id=1,format='docx'))
        self.assertEqual(document.numero, '2026-0012')
        self.assertEqual(document.id_nature_id,3)
        self.assertEqual(document.emplacement,'Test/Work/')
        self.assertIs(self.row.id_document,document)
        cursor.assert_not_called()

    def test_retour_instruction_ne_voit_que_la_preparation_active(self):
        with patch.object(service.ManualActPreparation,'objects') as rows:
            service.active_preparation(self.dossier)
        rows.filter.assert_called_once_with(id_dossier=self.dossier,etat='ACTIVE')

    def test_fichiers_generes_avec_autre_numero_et_partage_concurrent_refuses(self):
        for extra in ({'projet_acte_identique':'on'}, {}):
            request=RequestFactory().post('/', {'nature_document':'3','manual_preparation':str(self.key),**extra})
            request.user=self.user
            request._generated_act=SimpleNamespace(id_numero=SimpleNamespace(numero='2026-9999'))
            with self.subTest(extra=extra),patch.object(service,'active_preparation',return_value=self.row),self.assertRaises(ValidationError):
                service.validate_transition(request,self.dossier)

    def test_collecteur_orm_ne_consulte_pas_la_table_dev_en_production(self):
        for name in ('id_dossier','id_nature','id_document','user'):
            self.assertIs(service.ManualActPreparation._meta.get_field(name).remote_field.on_delete,models.DO_NOTHING)

    @override_settings(ENVIRONMENT='prod')
    def test_aucune_attribution_ni_lecture_en_prod(self):
        with patch.object(service.ManualActPreparation,'objects') as rows:
            with self.assertRaises(ValidationError):
                service.select_preparation(self.dossier,self.nature,self.user,self.key)
            self.assertIsNone(service.active_preparation(self.dossier))
            service.finish_instruction(self.dossier)
        rows.filter.assert_not_called()

    def test_templates_eligibles_seuls_et_preselection_si_unique(self):
        for count in (0,1,2):
            templates = [Mock(pk=index+10,id_nature_id=3) for index in range(count)]
            for item in templates:item.erreurs_configuration.return_value=[]
            with self.subTest(count=count), patch.object(service,'get_types_actes_selectionnables',return_value=[self.nature]), patch.object(
                service.DocumentTemplate,'objects') as objects, patch.object(service,'active_preparation',return_value=None), patch.object(
                service,'reverse',return_value='/document-generation/dossier/123/'):
                objects.filter.return_value.filter.return_value.distinct.return_value=templates
                result=service.state(self.dossier,self.user)['natures'][0]
            self.assertEqual(result['can_generate'],count>0)
            self.assertEqual('&template=' in result['url'],count==1)
            self.assertIn('demarche=7',result['url'])

    def test_nature_manuelle_incluse_et_saisie_sans_compteur(self):
        self.nature.mode_numerotation='manuelle'
        with patch.object(service,'get_types_actes_selectionnables',return_value=[self.nature]), patch.object(
                service.DocumentTemplate,'objects'), patch.object(service,'active_preparation',return_value=None), patch.object(
                service,'reverse',return_value='/generation/'):
            result=service.state(self.dossier,self.user)['natures']
            self.assertEqual(len(result),1)
            self.assertFalse(result[0]['automatic'])
        with ExitStack() as stack:
            self.db(stack)
            cursor=stack.enter_context(patch.object(service,'connection')).cursor
            service.select_preparation(self.dossier,self.nature,self.user,self.key,manual='COURRIER/42/Test')
            self.assertEqual(service.ManualActPreparation.objects.create.call_args.kwargs['numero'],'COURRIER/42/Test')
            self.assertEqual(service.ManualActPreparation.objects.create.call_args.kwargs['origine'],'SAISI')
            cursor.assert_not_called()

    def test_reference_saisie_invalide_ou_nature_automatique_refusee(self):
        with self.assertRaises(ValidationError):
            service.select_preparation(self.dossier,self.nature,self.user,self.key,manual='2026-42')
        self.nature.mode_numerotation='manuelle'
        for value in ('', 'A\\B', 'a'*151):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                service.select_preparation(self.dossier,self.nature,self.user,self.key,manual=value)

    def test_integration_reference_manuelle_saisie_sans_compteur(self):
        self.nature.mode_numerotation='manuelle'
        self.row.numero='COURRIER/42/Test';self.row.source='';self.row.origine='SAISI'
        with ExitStack() as stack:
            rows=self.db(stack);rows.select_for_update.return_value.get.return_value=self.row
            stack.enter_context(patch.object(service,'validate_transition',return_value=self.row))
            documents=stack.enter_context(patch.object(Document,'objects'))
            documents.filter.return_value.first.return_value=None
            documents.filter.return_value.exists.return_value=False
            stack.enter_context(patch.object(service.DossierDocument,'objects'))
            stack.enter_context(patch.object(models.Model,'save',autospec=True,side_effect=lambda doc,*a,**kw:setattr(doc,'pk',100)))
            cursor=stack.enter_context(patch.object(service,'connection')).cursor
            document=service.integrate_preparation(Mock(),self.dossier,'courrier.docx',self.nature,
                DocumentStatut(id=1,statut='À valider'),DocumentFormat(id=1,format='docx'))
        self.assertEqual(document.numero_reference,'COURRIER/42/Test')
        self.assertIsNone(document.numero)
        cursor.assert_not_called()



@override_settings(ENVIRONMENT='dev')
class ManualActHttpTests(SimpleTestCase):
    def request(self, data=None):
        request=RequestFactory().get('/') if data is None else RequestFactory().post('/',data)
        request.user=SimpleNamespace(pk=1,is_authenticated=True,is_superuser=True)
        return request

    def test_api_et_erreur_schema(self):
        dossier=Mock()
        for error, status in ((None,200),(OperationalError('schema'),503)):
            with self.subTest(status=status),patch('instruction.views.manual_act.get_object_or_404',return_value=dossier),patch.object(
                service,'require_instruction'),patch.object(service,'state',return_value={'natures':[],'preparation':None},side_effect=error):
                response=prepare_act(self.request(),123)
                self.assertEqual(response.status_code,status)
                self.assertIn('no-store',response['Cache-Control'])

    def test_post_sans_confirmation_ne_reserve_rien(self):
        with patch('instruction.views.manual_act.get_object_or_404'),patch.object(service,'require_instruction'),patch.object(service,'select_preparation') as reserve:
            response=prepare_act(self.request({'action':'reserve'}),123)
        self.assertEqual(response.status_code,409)
        reserve.assert_not_called()

    @override_settings(ENVIRONMENT='prod')
    def test_route_inaccessible_en_prod(self):
        with patch('instruction.views.manual_act.get_object_or_404') as lookup,self.assertRaises(Http404):
            prepare_act(self.request(),123)
        lookup.assert_not_called()

    def test_dossier_autre_instructeur_interdit(self):
        request=self.request();request.user.is_superuser=False
        with patch('instruction.views.manual_act.get_object_or_404'),patch(
            'instruction.views.manual_act.est_concerne_par_le_dossier',return_value=False),self.assertRaises(PermissionDenied):
            prepare_act(request,123)


@override_settings(ENVIRONMENT='dev')
class ManualActLifecycleTests(SimpleTestCase):
    def test_cloture_et_etape_sont_dans_la_meme_transaction(self):
        dossier=Mock(pk=4,id_etape_dossier=SimpleNamespace(pk=8,etape='En instruction'))
        target=SimpleNamespace(pk=9,etape='À valider avant signature',est_archivage=False)
        with patch.object(utils_instru.EtapeDossier,'objects') as steps,patch.object(utils_instru.Dossier,'objects') as dossiers,patch(
            'django.db.transaction.atomic') as atomic,patch.object(service,'finish_instruction',side_effect=RuntimeError('failure')) as finish:
            steps.filter.return_value.first.return_value=target
            dossiers.select_for_update.return_value.get.return_value.id_etape_dossier_id=8
            with self.assertRaises(Exception):
                utils_instru.changer_etape_si_differente(dossier,target.etape,Mock(),Mock())
        finish.assert_called_once_with(dossier)
        self.assertIs(atomic.return_value.__exit__.call_args.args[0],RuntimeError)
