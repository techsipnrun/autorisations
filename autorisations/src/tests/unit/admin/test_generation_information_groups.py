from django.test import SimpleTestCase
from autorisations.models.models_generation import Balise
from document_generation.forms import DynamicDocumentForm
from document_generation.templatetags.generation_fields import information_groups, manual_information_fields


class InformationGroupsTests(SimpleTestCase):
    def test_sources_and_missing_known_values_stay_in_their_group(self):
        agida = Balise(id=1, code='numero', source='AGIDA', mode='CONNUE', type='TEXT')
        formulaire = Balise(id=2, code='commune', source='FORMULAIRE', mode='CONNUE', type='TEXT')
        missing = Balise(id=3, code='date', source='FORMULAIRE', mode='CONNUE', type='DATE', required=True)
        manual = Balise(id=4, code='texte', source='MANUELLE', mode='A_RENSEIGNER', type='TEXT')
        known_form = DynamicDocumentForm(balises=[agida, formulaire], prefix='known')
        form = DynamicDocumentForm(balises=[missing, manual])
        groups = information_groups(form, known_form, [{'code': 'numero'}, {'code': 'commune'}])
        self.assertEqual([field.name for field in groups[0]['known_fields']], ['balise_1'])
        self.assertEqual([field.name for field in groups[1]['known_fields']], ['balise_2'])
        self.assertEqual([field.name for field in groups[1]['fields']], ['balise_3'])
        self.assertEqual([row['code'] for row in groups[1]['rows']], ['commune'])
        self.assertEqual([field.name for field in manual_information_fields(form)], ['balise_4'])
