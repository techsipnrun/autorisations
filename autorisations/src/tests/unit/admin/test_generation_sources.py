from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from autorisations.models.models_generation import Balise, BaliseSourceChamp
from autorisations.models.models_instruction import Dossier, Champ
from document_generation.forms import BaliseConfigurationForm
from document_generation.services.catalogue_sources import resolve_catalogue_source, source_errors
from document_generation.services.context import DocumentContextBuilder
from document_generation.services.providers import ResolutionSource
from document_generation.services.analyzer import TemplateAnalyzer
from tests.unit.admin.test_generation_analyzer import word_bytes


class ConfiguredSourcesTests(SimpleTestCase):
    def setUp(self):
        self.dossier = Dossier(id=1, numero=123, id_demarche_id=14)

    def definition(self, type='TEXT'):
        balise = Balise(id=1, code='projet.commune', libelle='Commune', mode='CONNUE', source='FORMULAIRE', type=type)
        champ = Champ(id=42, id_demarche_id=14, nom='Commune renommée')
        mapping = BaliseSourceChamp(id=1, id_balise=balise, id_demarche_id=14, id_champ=champ)
        balise._prefetched_objects_cache = {'sources_champs': [mapping]}
        return balise

    def test_nouvelle_balise_par_champ_sans_provider_python_specifique(self):
        balise = self.definition()
        with patch('document_generation.services.catalogue_sources.DossierChamp.objects.filter') as query:
            query.return_value.order_by.return_value.values_list.return_value.first.return_value = ' Saint-Paul '
            context = DocumentContextBuilder().build(self.dossier, ['projet.commune'], balises=[balise])
        self.assertEqual(context, {'projet': {'commune': 'Saint-Paul'}})
        query.assert_called_once_with(id_dossier=self.dossier, id_champ_id=42)

    def test_conversion_des_types_connus_zero_et_non(self):
        for type, raw, expected in [('INTEGER','0',0), ('DECIMAL','1,25',Decimal('1.25')),
                                    ('BOOLEAN','non',False), ('DATE','2026-11-04',date(2026,11,4)),
                                    ('TEXTAREA','Ligne 1\nLigne 2','Ligne 1\nLigne 2')]:
            with self.subTest(type=type), patch('document_generation.services.catalogue_sources.DossierChamp.objects.filter') as query:
                query.return_value.order_by.return_value.values_list.return_value.first.return_value = raw
                self.assertEqual(resolve_catalogue_source(self.definition(type), ResolutionSource(self.dossier)), expected)

    def test_valeur_invalide_ne_devient_pas_silencieusement_vide(self):
        for type, raw in [('INTEGER','abc'),('DECIMAL','NaN'),('BOOLEAN','peut-être'),('DATE','31/02/2026')]:
            with self.subTest(type=type), patch('document_generation.services.catalogue_sources.DossierChamp.objects.filter') as query:
                query.return_value.order_by.return_value.values_list.return_value.first.return_value = raw
                with self.assertRaises(ValueError):
                    resolve_catalogue_source(self.definition(type), ResolutionSource(self.dossier))

    def test_absence_de_mapping_demarche_ne_lit_pas_une_autre_reponse(self):
        dossier = Dossier(id=2, id_demarche_id=15)
        with patch('document_generation.services.catalogue_sources.DossierChamp.objects.filter') as query:
            self.assertIsNone(resolve_catalogue_source(self.definition(), ResolutionSource(dossier)))
        query.assert_not_called()

    def test_champ_dune_autre_demarche_refuse(self):
        definition = self.definition()
        definition.sources_champs.all()[0].id_champ.id_demarche_id = 15
        self.assertTrue(source_errors(definition))
        with self.assertRaises(ValueError):
            resolve_catalogue_source(definition, ResolutionSource(self.dossier))

    def test_alias_agida_avec_code_libre_et_propriete_autorisee(self):
        definition = Balise(code='projet.numero', source='AGIDA', source_propriete='dossier.numero', mode='CONNUE')
        self.assertEqual(DocumentContextBuilder().build(self.dossier, balises=[definition]), {'projet': {'numero': 123}})
        definition.source_propriete = '__dict__'
        with self.assertRaises(ValueError):
            resolve_catalogue_source(definition, ResolutionSource(self.dossier))

    def test_analyse_accepte_une_source_formulaire_sans_registre_code(self):
        definition = self.definition()
        report = TemplateAnalyzer().analyze_bytes(word_bytes('{{ projet.commune }}'), [definition])
        self.assertTrue(report.valide, report.erreurs)
        definition._prefetched_objects_cache['sources_champs'] = []
        self.assertFalse(TemplateAnalyzer().analyze_bytes(word_bytes('{{ projet.commune }}'), [definition]).valide)

    def test_formulaire_derive_le_mode_et_bloque_les_proprietes_arbitraires(self):
        base = dict(code='projet.commentaire', libelle='Commentaire', type='TEXTAREA', source='MANUELLE', allow_blank='on', actif='on')
        with patch.object(Balise, 'validate_unique'):
            form = BaliseConfigurationForm(base)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.instance.mode, 'A_RENSEIGNER')
            form = BaliseConfigurationForm({**base, 'source':'AGIDA','source_propriete':'dossier.numero'})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.instance.mode, 'CONNUE')
            form = BaliseConfigurationForm({**base, 'source':'AGIDA','source_propriete':'request.user.password'})
            self.assertFalse(form.is_valid())
