"""Géométries statistiques calculées sans altérer les données des dossiers."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from instruction.views import statistiques


class GeometriesStatistiquesTests(SimpleTestCase):
    def trace_mixte(self):
        return {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"nom": "Départ"},
                 "geometry": {"type": "Point", "coordinates": [55.423221, -20.909081, 100]}},
                {"type": "Feature", "properties": {"nom": "Arrivée"},
                 "geometry": {"type": "Point", "coordinates": [55.412142, -20.949328, 200]}},
                {"type": "Feature", "properties": {},
                 "geometry": {"type": "LineString", "coordinates": [
                     [55.423221, -20.909081, 100], [55.42, -20.92, 110],
                     [55.418, -20.93], [55.415, -20.94, 190], [55.412142, -20.949328, 200],
                 ]}},
                {"type": "Feature", "properties": {},
                 "geometry": {"type": "LineString", "coordinates": [
                     [55.423221, -20.909081], [55.42, -20.92, 110], [55.412142, -20.949328, 200],
                 ]}},
            ],
        }

    def test_traces_mixtes_xy_xyz_exploitables_sans_modifier_la_source(self):
        source = self.trace_mixte()
        avant = deepcopy(source)
        resultat = statistiques._preparer_geometrie_carte(source, statistiques.TOLERANCE_CARTE)
        self.assertFalse(resultat.is_empty)
        self.assertTrue(resultat.is_valid)
        self.assertFalse(resultat.has_z)
        self.assertEqual(source, avant)

    def test_json_texte_et_json_objet_donnent_le_meme_calcul(self):
        source = self.trace_mixte()
        objet = statistiques._preparer_geometrie_carte(source, statistiques.TOLERANCE_CARTE)
        texte = statistiques._preparer_geometrie_carte(json.dumps(source), statistiques.TOLERANCE_CARTE)
        self.assertTrue(objet.equals(texte))

    def test_geometries_imbriquees_et_polygones_mixtes(self):
        anneau = [[55.5, -21.1, 100], [55.6, -21.1], [55.6, -21.2, 120], [55.5, -21.1]]
        for geometrie in (
            {"type": "Polygon", "coordinates": [anneau]},
            {"type": "MultiPolygon", "coordinates": [[anneau]]},
            {"type": "MultiLineString", "coordinates": [anneau]},
            {"type": "MultiPoint", "coordinates": [[55.5, -21.1, 100], [55.6, -21.2]]},
            {"type": "GeometryCollection", "geometries": [
                {"type": "Polygon", "coordinates": [anneau]},
                {"type": "LineString", "coordinates": [[55.5, -21.1, 100], [55.6, -21.2]]},
            ]},
        ):
            with self.subTest(type=geometrie["type"]):
                source = {"type": "Feature", "properties": {"coordinates": "Information conservée"},
                          "geometry": geometrie}
                avant = deepcopy(source)
                resultat = statistiques._preparer_geometrie_carte(source, statistiques.TOLERANCE_CARTE)
                self.assertFalse(resultat.is_empty)
                self.assertTrue(resultat.is_valid)
                self.assertFalse(resultat.has_z)
                self.assertEqual(source, avant)

    def test_geometrie_2d_donne_le_meme_resultat_que_sa_version_3d(self):
        xy = {"type": "LineString", "coordinates": [[55.5, -21.1], [55.6, -21.2]]}
        xyz = {"type": "LineString", "coordinates": [[55.5, -21.1, 100], [55.6, -21.2, 200]]}
        self.assertTrue(
            statistiques._preparer_geometrie_carte(xy, statistiques.TOLERANCE_CARTE).equals(
                statistiques._preparer_geometrie_carte(xyz, statistiques.TOLERANCE_CARTE)
            )
        )

    def test_geometries_absentes_ou_vides_restent_non_representees(self):
        for source in (None, {}, {"type": "FeatureCollection", "features": []},
                       {"type": "Feature", "geometry": None}):
            with self.subTest(source=source):
                self.assertIsNone(statistiques._preparer_geometrie_carte(source, statistiques.TOLERANCE_CARTE))

    def test_donnees_reellement_invalides_restent_refusees(self):
        for source in ('{invalide', {"type": "Point", "coordinates": [340000, 7650000, 100]},
                       {"type": "LineString", "coordinates": [[55.5], [55.6]]}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                statistiques._preparer_geometrie_carte(source, statistiques.TOLERANCE_CARTE)

    def test_endpoint_represente_la_geometrie_modifiee_mixte(self):
        requete = RequestFactory().get("/statistiques/donnees-carte/", {"type_carte": "7"})
        requete.user = SimpleNamespace(is_authenticated=True, is_superuser=True, email="")
        source = self.trace_mixte()
        avant = deepcopy(source)
        dossiers = Mock()
        dossiers.count.return_value = 1
        dossiers.values_list.return_value.iterator.return_value = iter([
            (42, None, source, 34074317, "Nom initial", None, "En instruction", "Nom généré"),
        ])
        with (
            patch.object(statistiques.Demarche, "objects") as demarches,
            patch.object(statistiques, "_filtrer_dossiers_carte", return_value=(dossiers, False)),
        ):
            demarches.filter.return_value.first.return_value = SimpleNamespace(id=7, type="Survol hélicoptère")
            reponse = statistiques.donnees_carte(requete)
        self.assertEqual(reponse.status_code, 200)
        donnees = json.loads(reponse.content)
        self.assertEqual(donnees["dossiers_representes"], 1)
        self.assertEqual(donnees["geometries_invalides"], 0)
        self.assertEqual(donnees["details_compteurs"]["representes"], ["dn:42"])
        self.assertTrue(donnees["cellules"]["features"])
        self.assertEqual(source, avant)
