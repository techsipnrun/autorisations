from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from document_generation.services.providers import ResolutionSource
from document_generation.services.catalogue_sources import (
    AVAILABLE_PROPERTIES, PROPERTY_LABELS, PROPERTY_DESCRIPTIONS,
    PROPERTY_CATEGORIES, grouped_property_choices,
)


class PropertyCategoryTests(SimpleTestCase):
    def test_demande_complements_zero_une_ou_plusieurs(self):
        from document_generation.services.docx_renderer import format_word_value
        source=self.source()
        for actions, expected in [([],False),([('Passage en instruction',None)],False),
                                  ([('Demande de compléments',None)],True),
                                  ([('Demande de compléments',None),('Repassage en instruction',None),('Demande de compléments',None)],True)]:
            source.historique_dates=actions
            value=AVAILABLE_PROPERTIES['dossier.demande_complements'](source)
            self.assertIs(value,expected)
            self.assertEqual(format_word_value(value),'Oui' if expected else 'Non')

    def source(self):
        return ResolutionSource(SimpleNamespace(pk=1, date_debut_instruction=None, date_depot=None))

    def test_catalogue_complet_et_categories(self):
        self.assertEqual(set(AVAILABLE_PROPERTIES), set(PROPERTY_LABELS))
        self.assertEqual(set(AVAILABLE_PROPERTIES), set(PROPERTY_DESCRIPTIONS))
        self.assertEqual(set(AVAILABLE_PROPERTIES), set(PROPERTY_CATEGORIES))
        self.assertEqual([group for group, _ in grouped_property_choices()], ['Année', 'Date', 'Dossier', 'Document', 'Pétitionnaire'])

    def test_annees_jusqua_cinq_et_pas_de_cache_global(self):
        source=self.source()
        source.annee_courante=2026
        for n in range(6):
            self.assertEqual(AVAILABLE_PROPERTIES[f'annee.n_plus_{n}'](source), 2026+n)
        self.assertNotIn('annee.n_plus_6', AVAILABLE_PROPERTIES)
        with patch('document_generation.services.providers.timezone.localdate') as today:
            today.return_value.year=2027
            self.assertEqual(AVAILABLE_PROPERTIES['annee.n_plus_0'](self.source()),2027)

    def test_dates_historique_et_absences(self):
        source=self.source()
        dates=[datetime(2026,1,day,12,tzinfo=dt_timezone.utc) for day in (2,3,4,5)]
        source.historique_dates=[('Passage en instruction',dates[0]),('Demande de compléments',dates[1]),('Passage en instruction',dates[2]),('Repassage en instruction',dates[3])]
        source.dossier.date_depot=dates[0]
        for code, expected in [('premier_passage_instruction','02/01/2026'),('dernier_passage_instruction','05/01/2026'),('instruction_apres_complements','05/01/2026'),('derniere_demande_complements','03/01/2026'),('reception_dossier','02/01/2026')]:
            self.assertEqual(AVAILABLE_PROPERTIES[f'date.{code}'](source),expected)
        source.historique_dates.append(('Demande de compléments',datetime(2026,2,1,tzinfo=dt_timezone.utc)))
        self.assertIsNone(AVAILABLE_PROPERTIES['date.instruction_apres_complements'](source))
        source.historique_dates=[]
        source.dossier.date_debut_instruction=dates[0]
        self.assertEqual(AVAILABLE_PROPERTIES['date.premier_passage_instruction'](source),'02/01/2026')
        self.assertIsNone(AVAILABLE_PROPERTIES['date.derniere_demande_complements'](source))

    def test_intermediaire_absent_et_identite(self):
        source=self.source()
        source.demandeur_intermediaire=None
        self.assertIsNone(AVAILABLE_PROPERTIES['demandeur_intermediaire.prenom_nom'](source))
        source.demandeur_intermediaire=SimpleNamespace(prenom=' Louis ',nom=' Calu ',raison_sociale=' ',organisation=' Association ')
        self.assertEqual(AVAILABLE_PROPERTIES['demandeur_intermediaire.prenom_nom'](source),'Louis CALU')
        self.assertEqual(AVAILABLE_PROPERTIES['demandeur_intermediaire.raison_sociale'](source),'Association')
