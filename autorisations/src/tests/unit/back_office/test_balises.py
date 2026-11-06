from contextlib import nullcontext
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, RequestFactory, override_settings
from django.http import Http404
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import ProgrammingError
from backoffice.views import balises
from autorisations.models.models_generation import Balise


@override_settings(ENVIRONMENT='dev')
class BackofficeBalisesTests(SimpleTestCase):
    def request(self, post=False, admin=True, data=None):
        request = RequestFactory().post('/',data or {}) if post else RequestFactory().get('/')
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=admin)
        return request

    def test_acces_admin_dev_seulement(self):
        for view, args in [(balises.catalogue,()),(balises.champs,(14,))]:
            with self.assertRaises(PermissionDenied):
                view(self.request(admin=False),*args)
            with override_settings(ENVIRONMENT='prod'), self.assertRaises(Http404):
                view(self.request(),*args)
        with self.assertRaises(PermissionDenied):
            balises.enregistrer(self.request(post=True,admin=False))
        with override_settings(ENVIRONMENT='prod'), self.assertRaises(Http404):
            balises.enregistrer(self.request(post=True))

    def test_ecritures_refusees_en_get(self):
        self.assertEqual(balises.enregistrer(self.request()).status_code,405)

    def test_schema_absent_message_propre(self):
        with patch('backoffice.views.balises.Balise.objects.prefetch_related',side_effect=ProgrammingError):
            response = balises.catalogue(self.request())
        self.assertEqual(response.status_code,503)
        self.assertIn('0013',json.loads(response.content)['erreur'])

    def test_commune_non_proposee_comme_information_agida(self):
        with patch('backoffice.views.balises.DocumentTemplate.objects.prefetch_related') as templates, patch('backoffice.views.balises.Balise.objects.prefetch_related',return_value=[]),patch(
            'backoffice.views.balises.Demarche.objects.exclude') as demarches:
            demarches.return_value.exclude.return_value.order_by.return_value=[]
            templates.return_value.order_by.return_value=[]
            result=json.loads(balises.catalogue(self.request()).content)
        codes={item['code'] for item in result['proprietes']}
        self.assertNotIn('dossier.commune',codes)
        self.assertIn('dossier.numero',codes)

    def test_sources_choisies_par_id_demarche_et_champ(self):
        with patch('backoffice.views.balises.Champ.objects.filter') as fields:
            fields.return_value.in_bulk.return_value = {42:SimpleNamespace(id_demarche_id=14)}
            self.assertEqual(balises.valider_sources('[{"id_demarche":14,"id_champ":42}]','FORMULAIRE'),[(14,42)])
            with self.assertRaises(ValidationError):
                balises.valider_sources('[{"id_demarche":15,"id_champ":42}]','FORMULAIRE')
        for value in ('[]','{}','[{"id_demarche":14,"id_champ":true}]',
                      '[{"id_demarche":14,"id_champ":42},{"id_demarche":14,"id_champ":43}]'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                balises.valider_sources(value,'FORMULAIRE')

    def test_catalogue_expose_utilisations_des_balises_par_template(self):
        template = SimpleNamespace(pk=3, nom='Modèle Test', demarches=MagicMock(), balises_detectees=MagicMock())
        template.demarches.all.return_value = [SimpleNamespace(pk=14)]
        template.balises_detectees.all.return_value = [SimpleNamespace(code='projet.noms')]
        global_template = SimpleNamespace(pk=4, nom='Global', demarches=MagicMock(), balises_detectees=MagicMock())
        global_template.demarches.all.return_value = []
        global_template.balises_detectees.all.return_value = [SimpleNamespace(code='dossier.numero')]
        with patch('backoffice.views.balises.Balise.objects.prefetch_related', return_value=[]), patch(
            'backoffice.views.balises.DocumentTemplate.objects.prefetch_related'
        ) as templates, patch('backoffice.views.balises.Demarche.objects.exclude') as demarches:
            templates.return_value.order_by.return_value = [template, global_template]
            demarches.return_value.exclude.return_value.order_by.return_value = []
            result = json.loads(balises.catalogue(self.request()).content)
        self.assertEqual(result['templates'], [
            {'id': 3, 'nom': 'Modèle Test', 'demarche_ids': [14], 'balise_codes': ['projet.noms']},
            {'id': 4, 'nom': 'Global', 'demarche_ids': [], 'balise_codes': ['dossier.numero']},
        ])

    def test_formulaire_invalide_ne_sauvegarde_pas(self):
        with patch('backoffice.views.balises.transaction.atomic',return_value=nullcontext()),patch(
            'backoffice.views.balises.BaliseConfigurationForm') as form:
            form.return_value.is_valid.return_value=False
            form.return_value.errors.get_json_data.return_value={'code':[{'message':'Invalide'}]}
            response=balises.enregistrer(self.request(post=True))
        self.assertEqual(response.status_code,400)
        form.return_value.save.assert_not_called()

    def test_sauvegarde_invalide_et_reanalyse_les_templates_utilisant_le_code(self):
        definition=Balise(id=42,code='projet.commune')
        with patch('backoffice.views.balises.transaction.atomic',return_value=nullcontext()),patch(
            'backoffice.views.balises.BaliseConfigurationForm') as form,patch('backoffice.views.balises.valider_sources',return_value=[(14,7)]),patch(
            'backoffice.views.balises.BaliseSourceChamp.objects.filter'),patch('backoffice.views.balises.BaliseSourceChamp.objects.bulk_create') as create,patch(
            'backoffice.views.balises.TemplateBalise.objects.filter') as used,patch('backoffice.views.balises.DocumentTemplate.objects.filter') as templates,patch(
            'document_generation.services.verification.TemplateVerificationService.verify') as verify,patch('backoffice.views.balises.Balise.objects.prefetch_related'),patch(
            'backoffice.views.balises.serialiser',return_value={'id':42}):
            form.return_value.is_valid.return_value=True
            form.return_value.cleaned_data={'source':'FORMULAIRE'}
            form.return_value.save.return_value=definition
            used.return_value.values_list.return_value.distinct.return_value=[1,3]
            response=balises.enregistrer(self.request(post=True))
        self.assertEqual(response.status_code,200)
        used.assert_called_once_with(code='projet.commune')
        templates.return_value.update.assert_called_once_with(rapport_validation=None,date_verification=None)
        self.assertEqual([call.args[0] for call in verify.call_args_list],[1,3])
        self.assertEqual(create.call_args.args[0][0].id_champ_id,7)
