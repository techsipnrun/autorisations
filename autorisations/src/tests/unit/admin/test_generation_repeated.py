from io import BytesIO
from unittest.mock import patch
from docx import Document
from django.http import QueryDict
from django.test import SimpleTestCase
from autorisations.models.models_generation import Balise
from document_generation.forms import DynamicDocumentForm, BaliseConfigurationForm
from document_generation.services.docx_renderer import DocxRenderer
from document_generation.services.test_template import add_repeated_names_example
from document_generation.services.analyzer import TemplateAnalyzer
from document_generation.services.validation import GenerationContextValidator


class RepeatedNamesTests(SimpleTestCase):
    def definition(self, required=True):
        return Balise(id=42, code='projet.noms', libelle='Noms', type='LIST', source='MANUELLE',
                      mode='A_RENSEIGNER', required=required, libelle_element='Nom')

    def form(self, values, required=True):
        data=QueryDict(mutable=True);data.setlist('balise_42',values)
        return DynamicDocumentForm(data,balises=[self.definition(required)])

    def test_liste_nettoyee_et_contexte_reellement_iterable(self):
        form=self.form([' DUPONT ','  ','MARTIN'])
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.to_context(),{'projet':{'noms':['DUPONT','MARTIN']}})
        result=GenerationContextValidator().validate([self.definition()],{},form.to_manual_values())
        self.assertEqual(result['missing'],[])
        self.assertEqual(result['resolved']['projet']['noms'],['DUPONT','MARTIN'])

    def test_obligatoire_au_moins_un_element_facultative_accepte_le_vide(self):
        for values in ([],[''],['  ','']):
            with self.subTest(values=values):
                self.assertFalse(self.form(values).is_valid())
                optional=self.form(values,required=False)
                self.assertTrue(optional.is_valid(),optional.errors)
                self.assertEqual(optional.cleaned_data['balise_42'],[])
                self.assertEqual(optional.to_context(),{'projet':{'noms':[]}})
                result=GenerationContextValidator().validate([self.definition(False)],{},optional.to_manual_values())
                self.assertEqual(result['resolved'],{'projet':{'noms':[]}})

    def test_valeurs_reaffichees_et_echappees(self):
        form=self.form(['<script>','MARTIN'])
        self.assertTrue(form.is_valid())
        html=str(form['balise_42'])
        self.assertIn('&lt;script&gt;',html)
        self.assertIn('id="id_balise_42_2"',html)
        self.assertIn('Ajouter : Nom',html)
        self.assertNotIn('required',html)

    def test_limites_de_taille(self):
        self.assertFalse(self.form(['Nom']*101).is_valid())
        self.assertFalse(self.form(['a'*501]).is_valid())

    def test_configuration_liste_reservee_a_la_saisie_instructeur(self):
        data={'code':'projet.noms','libelle':'Noms','type':'LIST','source':'MANUELLE','libelle_element':'Nom','actif':'on'}
        with patch.object(Balise,'validate_unique'):
            form=BaliseConfigurationForm(data)
            self.assertTrue(form.is_valid(),form.errors)
            self.assertEqual(form.cleaned_data['libelle_element'], 'Nom')
            form=BaliseConfigurationForm({**data,'source':'AGIDA','source_propriete':'dossier.numero'})
            self.assertFalse(form.is_valid())
            form=BaliseConfigurationForm({**data,'libelle_element':''})
            self.assertFalse(form.is_valid())
            self.assertIn('libelle_element', form.errors)
            without_item_label = {key: value for key, value in data.items() if key != 'libelle_element'}
            form=BaliseConfigurationForm(without_item_label)
            self.assertFalse(form.is_valid())
            self.assertIn('libelle_element', form.errors)
            form=BaliseConfigurationForm({**without_item_label, 'type': 'TEXT'})
            self.assertTrue(form.is_valid(),form.errors)

    def test_boucle_word_analysee_et_rendue_sans_balise_locale_catalogue(self):
        doc=Document();doc.add_paragraph('Original conservé')
        buffer=BytesIO();doc.save(buffer)
        source=add_repeated_names_example(buffer.getvalue())
        self.assertEqual(add_repeated_names_example(source),source)
        report=TemplateAnalyzer().analyze_bytes(source,[self.definition()])
        self.assertTrue(report.valide,report.erreurs)
        self.assertEqual(report.balises,[{'code':'projet.noms','statut':'A_RENSEIGNER'}])
        with DocxRenderer().render_to_memory(source,{'projet':{'noms':['DUPONT','MARTIN']}}) as rendered:
            texts=[p.text for p in Document(rendered).paragraphs]
        self.assertIn('Original conservé',texts)
        self.assertIn('Nom : DUPONT',texts)
        self.assertIn('Nom : MARTIN',texts)
        self.assertFalse(any('{%' in value for value in texts))
