from django.test import SimpleTestCase
from jinja2 import Environment
from autorisations.models.models_generation import Balise
from document_generation.forms import DynamicDocumentForm
from document_generation.services.conditions import collect_conditions, evaluate
from document_generation.services.validation import GenerationContextValidator
from document_generation.services.analyzer import TemplateAnalyzer
from tests.unit.admin.test_generation_analyzer import word_bytes


class ConditionalFieldsTests(SimpleTestCase):
    def test_word_paragraph_conditions_drive_nested_fields(self):
        from io import BytesIO
        from docx import Document
        document = Document()
        for text in ['{%p if a %}', '{%p if b %}', '{{ x }}', '{%p endif %}', '{%p endif %}']:
            document.add_paragraph(text)
        buffer = BytesIO(); document.save(buffer)
        definitions = [Balise(id=i, code=code, type='BOOLEAN' if code != 'x' else 'TEXT', mode='A_RENSEIGNER')
                       for i, code in enumerate(['a', 'b', 'x'], 1)]
        report = TemplateAnalyzer().analyze_bytes(buffer.getvalue(), definitions)
        self.assertTrue(report.valide, report.erreurs)
        self.assertFalse(evaluate(report.conditions['b'], {'a': False}))
        self.assertFalse(evaluate(report.conditions['x'], {'a': True, 'b': False}))
        self.assertTrue(evaluate(report.conditions['x'], {'a': True, 'b': True}))

    def rules(self, source):
        return collect_conditions([Environment().parse(source)], {'a', 'b', 'x', 'y'})[0]

    def test_or_nested_else_and_unconditional_occurrence(self):
        rules = self.rules('{% if a or b %}{{ x }}{% if b %}{{ y }}{% endif %}{% else %}{{ y }}{% endif %}{{ x }}')
        self.assertTrue(evaluate(rules['x'], {'a': False, 'b': False}))
        self.assertFalse(evaluate(rules['y'], {'a': True, 'b': False}))
        self.assertTrue(evaluate(rules['y'], {'a': False, 'b': False}))
        self.assertTrue(evaluate(rules['y'], {'a': False, 'b': True}))
        self.assertTrue(evaluate(rules['a'], {}))
        self.assertTrue(evaluate(rules['b'], {}))

    def test_nested_controller_only_shown_under_parent(self):
        rules = self.rules('{% if a %}{% if b %}{{ x }}{% endif %}{% endif %}')
        self.assertFalse(evaluate(rules['b'], {'a': False, 'b': True}))
        self.assertFalse(evaluate(rules['x'], {'a': False, 'b': True}))
        self.assertTrue(evaluate(rules['b'], {'a': True}))

    def test_elif_not_and_comparison(self):
        rules = self.rules('{% if a == "oui" and not b %}{{ x }}{% elif b %}{{ y }}{% endif %}')
        self.assertTrue(evaluate(rules['x'], {'a': 'oui', 'b': False}))
        self.assertFalse(evaluate(rules['y'], {'a': 'oui', 'b': False}))
        self.assertTrue(evaluate(rules['y'], {'a': 'non', 'b': True}))

    def test_complex_condition_keeps_fields_visible_with_warning(self):
        rules, warnings = collect_conditions([Environment().parse('{% if a|length %}{{ x }}{% endif %}')], {'a', 'x'})
        self.assertTrue(evaluate(rules['x'], {}))
        self.assertTrue(warnings)

    def test_word_analysis_includes_rules(self):
        definitions = [Balise(id=i, code=code, mode='A_RENSEIGNER', type='BOOLEAN' if code=='a' else 'TEXT')
                       for i, code in enumerate(['a', 'x'], 1)]
        report = TemplateAnalyzer().analyze_bytes(word_bytes('{% if a %}{{ x }}{% endif %}'), definitions)
        self.assertTrue(report.valide, report.erreurs)
        self.assertFalse(evaluate(report.conditions['x'], {'a': False}))

    def test_hidden_required_and_invalid_values_do_not_block_server(self):
        a = Balise(id=1, code='a', type='BOOLEAN', mode='A_RENSEIGNER', required=True)
        x = Balise(id=2, code='x', type='INTEGER', mode='A_RENSEIGNER', required=True)
        x.visibility_rule = ['value', 'a']
        for raw in ('', 'invalid'):
            form = DynamicDocumentForm({'balise_1': 'false', 'balise_2': raw}, balises=[a, x])
            self.assertTrue(form.is_valid(), form.errors)
            self.assertNotIn('x', form.to_manual_values())
            validation = GenerationContextValidator().validate([a, x], {}, form.to_manual_values())
            self.assertEqual(validation['missing'], [])
            self.assertEqual(validation['errors'], [])
        form = DynamicDocumentForm({'balise_1': 'true'}, balises=[a, x])
        self.assertFalse(form.is_valid())
        self.assertIn('balise_2', form.errors)

    def test_known_controller_can_hide_manual_required(self):
        x = Balise(id=2, code='x', type='TEXT', mode='A_RENSEIGNER', required=True)
        x.visibility_rule = ['value', 'a']
        self.assertTrue(DynamicDocumentForm({}, balises=[x], condition_context={'a': False}).is_valid())
        self.assertFalse(DynamicDocumentForm({}, balises=[x], condition_context={'a': True}).is_valid())

    def test_hidden_required_not_reported_missing_in_preview(self):
        from document_generation.services.partial_preview import partial_preview_context
        a = Balise(id=1, code='a', type='BOOLEAN', mode='A_RENSEIGNER', required=True)
        x = Balise(id=2, code='x', type='TEXT', mode='A_RENSEIGNER', required=True)
        x.visibility_rule = ['value', 'a']
        prepared = {'balises': [a, x], 'known_context': {}}
        form = DynamicDocumentForm({'balise_1': 'false'}, balises=[a, x])
        context, missing = partial_preview_context(prepared, form, None)
        self.assertEqual(missing, [])
        self.assertIsNone(context['x'])
        self.assertIs(context['a'], False)
