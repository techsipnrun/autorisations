from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from autorisations.models.models_generation import Balise, BaliseSourceChamp, DocumentTemplate
from autorisations.models.models_instruction import Champ
from document_generation.services.analyzer import TemplateAnalyzer
from tests.unit.admin.test_generation_analyzer import word_bytes


def matches(row, key, value):
    if key == 'id_template__isnull':
        return (row.id_template_id is None) == value
    if key.endswith('__in'):
        return getattr(row, key[:-4]) in value
    return getattr(row, key) == value


def evaluate(row, condition):
    children = [evaluate(row, part) if hasattr(part, 'children') else matches(row, *part) for part in condition.children]
    result = any(children) if condition.connector == 'OR' else all(children)
    return not result if condition.negated else result


class Rows(list):
    def filter(self, *conditions, **values):
        return Rows(row for row in self if all(evaluate(row, condition) for condition in conditions)
                    and all(matches(row, key, value) for key, value in values.items()))

    def exclude(self, **values):
        return Rows(row for row in self if not all(matches(row, key, value) for key, value in values.items()))

    def exists(self):
        return bool(self)

    def prefetch_related(self, *args):
        return self


class ScopedBaliseTests(SimpleTestCase):
    def test_meme_code_manuel_et_formulaire_independants_et_agida_partagee(self):
        global_tag = Balise(id=1, code='dossier.numero', libelle='Numéro', source='AGIDA', source_propriete='dossier.numero', mode='CONNUE')
        manual = Balise(id=2, code='toto', libelle='Texte local A', source='MANUELLE', mode='A_RENSEIGNER', id_template_id=10)
        form = Balise(id=3, code='toto', libelle='Champ local B', source='FORMULAIRE', mode='CONNUE', id_template_id=20)
        form._prefetched_objects_cache = {'sources_champs': [BaliseSourceChamp(id_balise=form,
            id_demarche_id=14, id_champ=Champ(id=7, id_demarche_id=14))]}
        rows = Rows([global_tag, manual, form])
        with patch.object(Balise.objects, 'filter', side_effect=rows.filter):
            a = TemplateAnalyzer().analyze_bytes(word_bytes('{{ dossier.numero }} {{ toto }}'), template=DocumentTemplate(id=10))
            b = TemplateAnalyzer().analyze_bytes(word_bytes('{{ dossier.numero }} {{ toto }}'), template=DocumentTemplate(id=20))
            c = TemplateAnalyzer().analyze_bytes(word_bytes('{{ dossier.numero }} {{ toto }}'), template=DocumentTemplate(id=30))
        self.assertTrue(a.valide, a.erreurs)
        self.assertTrue(b.valide, b.erreurs)
        self.assertEqual(a.balises[-1]['statut'], 'A_RENSEIGNER')
        self.assertEqual(b.balises[-1]['statut'], 'CONNUE')
        self.assertEqual(c.balises[-1]['statut'], 'INCONNUE')
        self.assertEqual(c.balises[0]['statut'], 'CONNUE')

    def test_perimetre_local_obligatoire_et_agida_sans_template(self):
        for source in ('MANUELLE', 'FORMULAIRE'):
            with self.subTest(source=source), self.assertRaisesMessage(ValidationError, 'Choisissez le template'):
                Balise(code='toto', source=source).clean()
        with self.assertRaisesMessage(ValidationError, 'globale'):
            Balise(code='toto', source='AGIDA', id_template_id=1).clean()

    def test_collision_agida_locale_refusee_et_meme_code_autres_templates_autorise(self):
        local = Balise(code='toto', source='MANUELLE', mode='A_RENSEIGNER', id_template_id=10)
        other = Balise(id=5, code='toto', source='MANUELLE', id_template_id=20)
        with patch.object(Balise.objects, 'filter', side_effect=Rows([other]).filter):
            local.clean()
        global_tag = Balise(id=6, code='toto', source='AGIDA', source_propriete='dossier.numero')
        with patch.object(Balise.objects, 'filter', side_effect=Rows([global_tag]).filter), self.assertRaisesMessage(ValidationError, 'conflit'):
            local.clean()
        with patch.object(Balise.objects, 'filter', side_effect=Rows([other]).filter), self.assertRaisesMessage(ValidationError, 'conflit'):
            Balise(code='toto', source='AGIDA', source_propriete='dossier.numero').clean()
