from io import BytesIO

from django.test import SimpleTestCase
from docx import Document

from document_generation.services.docx_renderer import DocxRenderer


class PreviewMarkerTests(SimpleTestCase):
    def test_liste_manquante_utilise_libelle_du_formulaire(self):
        from autorisations.models.models_generation import Balise
        from document_generation.forms import DynamicDocumentForm
        from document_generation.services.partial_preview import partial_preview_context
        balise=Balise(id=1,code='projet.nom',libelle='Nom technique',type='TEXT',required=True)
        form=DynamicDocumentForm(data={},balises=[balise])
        form.fields['balise_1'].label='Nom du bénéficiaire'
        _,missing=partial_preview_context({'balises':[balise],'known_context':{}},form,None,numbering_kind='acte')
        self.assertEqual([item['label'] for item in missing],['Nom du bénéficiaire','Numéro du document'])

    def render(self, word, context, missing=None):
        source = BytesIO()
        word.save(source)
        return DocxRenderer().render_to_memory(source.getvalue(), context, missing_markers=missing)

    def test_repere_rouge_seul_et_texte_voisin_conserve(self):
        word = Document()
        word.add_paragraph('Commune : {{ dossier.commune }} — fin').runs[0].bold = True
        missing = [{'code': 'dossier.commune', 'label': 'Commune'}]
        with self.render(word, {'dossier': {'commune': None}}, missing) as buffer:
            result = Document(buffer)
        self.assertEqual(result.paragraphs[0].text, 'Commune : [Commune] — fin')
        runs = result.paragraphs[0].runs
        marker = next(run for run in runs if run.text == 'Commune')
        self.assertEqual(str(marker.font.color.rgb), 'B42318')
        self.assertTrue(marker.bold)
        self.assertNotIn('à renseigner', result.paragraphs[0].text)
        self.assertTrue(all(run.font.color.rgb is None for run in runs if 'Commune :' in run.text or 'fin' in run.text))

    def test_variable_scindee_sur_plusieurs_runs_et_entete_tableau(self):
        word = Document()
        paragraph = word.add_paragraph()
        paragraph.add_run('{{ dossier.')
        paragraph.add_run('commune }}')
        word.sections[0].header.paragraphs[0].text = '{{ dossier.commune }}'
        word.add_table(rows=1, cols=1).cell(0, 0).text = '{{ dossier.commune }}'
        with self.render(word, {'dossier': {'commune': None}}, [{'code': 'dossier.commune', 'label': 'Commune & lieu'}]) as buffer:
            result = Document(buffer)
        for text in (result.paragraphs[0].text, result.sections[0].header.paragraphs[0].text, result.tables[0].cell(0, 0).text):
            self.assertEqual(text, '[Commune & lieu]')

    def test_conditions_et_boucles_manquantes_affichent_un_repere_sans_contenu_fictif(self):
        word = Document()
        word.add_paragraph('{% if dossier.commune %}VISIBLE {{ dossier.commune }}{% endif %}')
        word.add_paragraph('{% for nom in projet.noms %}{{ nom }}{% endfor %}')
        with self.render(word, {'dossier': {'commune': None}, 'projet': {'noms': []}},
                         [{'code': 'dossier.commune', 'label': 'Commune'}, {'code': 'projet.noms', 'label': 'Noms'}]) as buffer:
            paragraphs = Document(buffer).paragraphs
            self.assertEqual([p.text for p in paragraphs],
                             ['[Commune à renseigner pour afficher du contenu]', '[Noms à renseigner]'])
            for paragraph, label in zip(paragraphs, ('Commune', 'Noms')):
                self.assertTrue(next(run for run in paragraph.runs if run.text == label).bold)
                self.assertFalse(next(run for run in paragraph.runs if 'à renseigner' in run.text).bold)

    def test_if_else_comparaison_et_bloc_imbrique_ne_sont_pas_evalues(self):
        word = Document()
        word.add_paragraph('Avant {% if projet.nombre > 2 %}VRAI {% if dossier.commune %}INTERIEUR{% endif %}{% else %}FAUX{% endif %} après')
        with self.render(word, {'projet': {'nombre': None}, 'dossier': {'commune': None}},
                         [{'code': 'projet.nombre', 'label': 'Nombre'}, {'code': 'dossier.commune', 'label': 'Commune'}]) as buffer:
            self.assertEqual(Document(buffer).paragraphs[0].text, 'Avant [Nombre à renseigner pour afficher du contenu] après')

    def test_blocs_structurels_paragraphe_et_boucle_tableau(self):
        word = Document()
        word.add_paragraph('{%p if dossier.commune %}')
        word.add_paragraph('CONTENU CONDITIONNEL')
        word.add_paragraph('{%p else %}')
        word.add_paragraph('CONTENU ALTERNATIF')
        word.add_paragraph('{%p endif %}')
        table = word.add_table(rows=3, cols=1)
        table.cell(0, 0).text = '{%tr for nom in projet.noms %}'
        table.cell(1, 0).text = '{{ nom }}'
        table.cell(2, 0).text = '{%tr endfor %}'
        with self.render(word, {'dossier': {'commune': None}, 'projet': {'noms': []}},
                         [{'code': 'dossier.commune', 'label': 'Commune'}, {'code': 'projet.noms', 'label': 'Liste des bénéficiaires'}]) as buffer:
            result = Document(buffer)
        self.assertEqual([p.text for p in result.paragraphs], ['[Commune à renseigner pour afficher du contenu]'])
        self.assertEqual(result.tables[0].cell(0, 0).text, '[Liste des bénéficiaires à renseigner]')

    def test_donnees_connues_et_variables_locales_gardent_la_logique_normale(self):
        word = Document()
        word.add_paragraph('{% if accord %}OUI{% else %}NON{% endif %}')
        word.add_paragraph('{% for nom in noms %}{% if nom %}{{ nom }}{% endif %}{% endfor %}')
        with self.render(word, {'accord': False, 'nom': None, 'noms': ['Alice', 'Bob']},
                         [{'code': 'nom', 'label': 'Nom global'}]) as buffer:
            self.assertEqual([p.text for p in Document(buffer).paragraphs], ['NON', 'AliceBob'])

    def test_variable_locale_et_expressions_non_modifiees(self):
        word = Document()
        word.add_paragraph('{% for nom in noms %}{{ nom }}{% endfor %}')
        word.add_paragraph('{{ dossier.commune | default("Absente", true) }}')
        with self.render(word, {'nom': None, 'noms': ['Alice'], 'dossier': {'commune': None}},
                         [{'code': 'nom', 'label': 'Nom'}, {'code': 'dossier.commune', 'label': 'Commune'}]) as buffer:
            self.assertEqual([p.text for p in Document(buffer).paragraphs], ['Alice', 'Absente'])

    def test_generation_normale_ne_contient_aucun_repere(self):
        word = Document()
        word.add_paragraph('Commune : {{ dossier.commune }}')
        with self.render(word, {'dossier': {'commune': None}}) as buffer:
            self.assertEqual(Document(buffer).paragraphs[0].text, 'Commune : ')
