import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError
from django.http import Http404
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_cartographie import CartographieConfiguration, CartographieSource
from instruction.utils.cartographie import (
    CACHE_KEY, PROFILS, charger_configurations, configurations_par_defaut,
    options_par_defaut, serialiser_source, valider_geojson, valider_options_carte,
    valider_options_source, valider_style, valider_url,
)
from instruction.views import cartographie


class ValidationCartographieTests(SimpleTestCase):
    def test_sept_profils_initialises_avec_un_seul_fond_visible(self):
        configurations = configurations_par_defaut()
        self.assertEqual(set(configurations), set(PROFILS))
        for code, configuration in configurations.items():
            with self.subTest(code=code):
                fonds = [s for s in configuration["sources"] if s["format"] == "tuiles"]
                self.assertEqual(sum(s["visible"] for s in fonds), 1)
                self.assertEqual(valider_options_carte(code, configuration["options"]), configuration["options"])
        self.assertEqual(next(s["code"] for s in configurations["statistiques"]["sources"] if s["visible"]), "osm")
        self.assertNotIn("mafate", [s["code"] for s in configurations["instruction_dm"]["sources"]])

    def test_styles_couleurs_et_opacites_sont_valides(self):
        self.assertEqual(valider_style({"color": "#123ABC", "fillOpacity": .4, "onclick": "interdit"}), {"color": "#123ABC", "fillOpacity": .4})
        for style in ({"color": "red"}, {"opacity": 2}, {"weight": -1}, {"radius": float("nan")}, {"opacity": True}):
            with self.subTest(style=style), self.assertRaises(ValidationError):
                valider_style(style)

    def test_outils_de_dessin_non_activables_sur_une_carte_en_lecture(self):
        options = options_par_defaut("instruction_dn")
        options["controles"]["editMode"] = True
        self.assertFalse(valider_options_carte("instruction_dn", options)["controles"]["editMode"])

    def test_centre_zoom_et_booleens_controles(self):
        for options in (
            {"centre": [91, 55]}, {"zoom": 1.5}, {"recentrage": "oui"},
            {"controles": {"zoom": "non"}}, {"zoom": 15, "zoom_cadrage": 12},
        ):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                valider_options_carte("edition", options)

    def test_urls_autorisees_et_attributs_sources(self):
        url = "https://tiles.example.test/{z}/{x}/{y}.png"
        self.assertEqual(valider_url(url, fond=True), url)
        for url in ("javascript:alert(1)", "file:///secret", "//host/geojson", "https://user:secret@host/geojson", "/instruction/123/"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                valider_url(url)
        with self.assertRaises(ValidationError):
            valider_url("https://example.test/sans-tuiles", fond=True)
        options = {"style": {"color": "#123456"}, "categories": {"propriete": "secteur", "couleurs": {"nord": "#654321"}}, "popup": {"mode": "clic", "texte": "Information", "propriete": "nom"}}
        self.assertEqual(valider_options_source("geojson", options), options)

    def test_import_wgs84_et_refus_2975(self):
        point = {"type": "Point", "coordinates": [55.5, -21.1]}
        couche = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": point, "properties": {"nom": "Cœur de parc"}}]}
        self.assertEqual(valider_geojson(couche), couche)
        couche["crs"] = {"properties": {"name": "EPSG:2975"}}
        with self.assertRaises(ValidationError):
            valider_geojson(couche)
        for mauvais in ({"type": "Point", "coordinates": [340000, 7650000]}, {"type": "Point", "coordinates": [55, float("inf")]}, {"type": "FeatureCollection", "features": []}):
            with self.subTest(mauvais=mauvais), self.assertRaises(ValidationError):
                valider_geojson(mauvais)

    def test_configuration_absente_fallback_court_et_mise_en_cache(self):
        cache.delete(CACHE_KEY)
        with patch("instruction.utils.cartographie.CartographieConfiguration.objects.prefetch_related", side_effect=OperationalError("table absente")) as requete:
            self.assertEqual(set(charger_configurations()), set(PROFILS))
            charger_configurations()
            requete.assert_called_once()
        cache.delete(CACHE_KEY)

    def test_geometries_mal_structurees_refusees(self):
        for mauvais in (
            {"type": "Point", "coordinates": [[55, -21]]},
            {"type": "Polygon", "coordinates": [55, -21]},
            {"type": "LineString", "coordinates": [[55, -21]]},
            {"type": "Polygon", "coordinates": [[[55, -21], [56, -21], [56, -20], [55, -20]]]},
        ):
            with self.subTest(mauvais=mauvais), self.assertRaises(ValidationError):
                valider_geojson(mauvais)
    def test_serialisation_import_sans_charger_le_geojson(self):
        source = SimpleNamespace(pk=1, code="test", nom="Couche", format="geojson", url="", importe=True, attribution="", actif=True, options={"version": "abc"})
        resultat = serialiser_source(source)
        self.assertTrue(resultat["importe"])
        self.assertEqual(resultat["url"], "/cartographie/couche/1/?v=abc")
        self.assertNotIn("geojson", resultat)

    def test_templates_compilables(self):
        for nom in ("instruction/back_office.html", "instruction/refacto/back_office_cartographie.html", "instruction/refacto/cartographie_assets.html"):
            with self.subTest(nom=nom):
                get_template(nom)


class VuesCartographieTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = SimpleNamespace(is_authenticated=True, is_superuser=True)

    def requete(self, chemin="/", donnees=None, *, admin=True, multipart=False):
        if donnees is None:
            request = self.factory.get(chemin)
        elif multipart:
            request = self.factory.post(chemin, donnees)
        else:
            request = self.factory.post(chemin, json.dumps(donnees), content_type="application/json")
        request.user = self.admin if admin else SimpleNamespace(is_authenticated=True, is_superuser=False)
        return request

    def test_catalogue_reserve_aux_superutilisateurs(self):
        with self.assertRaises(PermissionDenied):
            cartographie.catalogue(self.requete(admin=False))

    def test_ecritures_reservees_aux_superutilisateurs(self):
        with self.assertRaises(PermissionDenied):
            cartographie.enregistrer_source(self.requete(donnees={}, admin=False))
        with self.assertRaises(PermissionDenied):
            cartographie.enregistrer_configuration(self.requete(donnees={}, admin=False), "edition")
        with self.assertRaises(PermissionDenied):
            cartographie.supprimer_source(self.requete(donnees={}, admin=False), 1)

    def test_geojson_inactif_consultable_uniquement_en_apercu_admin(self):
        source = CartographieSource(id=9, format="geojson", actif=False, geojson={"type": "Point", "coordinates": [55, -21]})
        with patch("instruction.views.cartographie.get_object_or_404", return_value=source) as obtenir:
            reponse = cartographie.geojson_source(self.requete("/?apercu=1"), 9)
        obtenir.assert_called_once_with(CartographieSource, pk=9, format="geojson")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(json.loads(reponse.content), source.geojson)
        self.assertEqual(reponse["Cache-Control"], "private, no-store")
        self.assertFalse(source.actif)

    def test_geojson_apercu_refuse_aux_non_administrateurs(self):
        with patch("instruction.views.cartographie.get_object_or_404") as obtenir:
            with self.assertRaises(PermissionDenied):
                cartographie.geojson_source(self.requete("/?apercu=1", admin=False), 9)
        obtenir.assert_not_called()

    def test_geojson_inactif_reste_inaccessible_sur_url_normale(self):
        with patch("instruction.views.cartographie.get_object_or_404", side_effect=Http404) as obtenir:
            with self.assertRaises(Http404):
                cartographie.geojson_source(self.requete(admin=False), 9)
        obtenir.assert_called_once_with(CartographieSource, pk=9, format="geojson", actif=True)

    def test_geojson_actif_conserve_acces_et_cache_habituels(self):
        source = CartographieSource(id=5, format="geojson", actif=True, geojson={"type": "Point", "coordinates": [55, -21]})
        with patch("instruction.views.cartographie.get_object_or_404", return_value=source) as obtenir:
            reponse = cartographie.geojson_source(self.requete(admin=False), 5)
        obtenir.assert_called_once_with(CartographieSource, pk=5, format="geojson", actif=True)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Cache-Control"], "private, max-age=60")

    def test_suppression_source_utilisee_refusee(self):
        source = MagicMock()
        source.configurations.values_list.return_value = ["Instruction · DN"]
        with patch("instruction.views.cartographie.transaction.atomic"), patch("instruction.views.cartographie.CartographieSource.objects.select_for_update"), patch("instruction.views.cartographie.get_object_or_404", return_value=source), patch("instruction.views.cartographie.cache.delete") as invalider:
            reponse = cartographie.supprimer_source(self.requete(donnees={}), 3)
        self.assertEqual(reponse.status_code, 409)
        self.assertIn("Instruction", json.loads(reponse.content)["erreur"])
        source.delete.assert_not_called()
        invalider.assert_not_called()

    def test_suppression_source_libre_invalide_cache(self):
        source = MagicMock()
        source.configurations.values_list.return_value = []
        with patch("instruction.views.cartographie.transaction.atomic"), patch("instruction.views.cartographie.CartographieSource.objects.select_for_update"), patch("instruction.views.cartographie.get_object_or_404", return_value=source), patch("instruction.views.cartographie.cache.delete") as invalider:
            reponse = cartographie.supprimer_source(self.requete(donnees={}), 3)
        self.assertEqual(reponse.status_code, 200)
        source.delete.assert_called_once()
        invalider.assert_called_once_with(CACHE_KEY)

    def test_suppression_concurrente_protegee(self):
        source = MagicMock()
        source.configurations.values_list.return_value = []
        source.delete.side_effect = IntegrityError("source désormais utilisée")
        with patch("instruction.views.cartographie.transaction.atomic"), patch("instruction.views.cartographie.CartographieSource.objects.select_for_update"), patch("instruction.views.cartographie.get_object_or_404", return_value=source):
            reponse = cartographie.supprimer_source(self.requete(donnees={}), 3)
        self.assertEqual(reponse.status_code, 409)

    def test_absence_tables_message_sql_explicite(self):
        with patch("instruction.views.cartographie.sources_sans_geometries", side_effect=OperationalError("table absente")):
            reponse = cartographie.catalogue(self.requete())
        self.assertEqual(reponse.status_code, 503)
        self.assertIn("0039", json.loads(reponse.content)["erreur"])

    def test_config_refuse_sources_dupliquees_avant_toute_ecriture(self):
        reponse = cartographie.enregistrer_configuration(self.requete(donnees={"sources": [{"id": 1, "visible": True}, {"id": 1, "visible": False}]}), "edition")
        self.assertEqual(reponse.status_code, 400)

    def test_config_refuse_deux_fonds_visibles(self):
        requete = self.requete(donnees={"sources": [{"id": 1, "visible": True}, {"id": 2, "visible": True}]})
        with patch("instruction.views.cartographie.CartographieSource.objects.filter") as filtrer:
            filtrer.return_value.in_bulk.return_value = {i: SimpleNamespace(format="tuiles") for i in (1, 2)}
            reponse = cartographie.enregistrer_configuration(requete, "edition")
        self.assertEqual(reponse.status_code, 400)

    def test_config_ordre_et_visibilite_enregistres_en_bloc(self):
        configuration = CartographieConfiguration(id=3, code="edition", nom="Édition")
        requete = self.requete(donnees={"options": {"geometrie": {"color": "#123456"}}, "sources": [{"id": 2, "visible": True}, {"id": 1, "visible": False}]})
        with patch("instruction.views.cartographie.CartographieSource.objects.filter") as filtrer, patch("instruction.views.cartographie.transaction.atomic"), patch("instruction.views.cartographie.get_object_or_404", return_value=configuration), patch("instruction.views.cartographie.CartographieConfiguration.objects.select_for_update"), patch.object(configuration, "save") as sauvegarder, patch.object(CartographieConfiguration, "sources", new_callable=PropertyMock) as liens, patch("instruction.views.cartographie.CartographieConfigurationSource.objects.bulk_create") as creer, patch("instruction.views.cartographie.cache.delete") as invalider:
            filtrer.return_value.in_bulk.return_value = {2: SimpleNamespace(format="tuiles"), 1: SimpleNamespace(format="geojson")}
            reponse = cartographie.enregistrer_configuration(requete, "edition")
            self.assertEqual(reponse.status_code, 200)
            self.assertEqual(configuration.options["geometrie"]["color"], "#123456")
            self.assertEqual([(l.source_id, l.ordre, l.visible) for l in creer.call_args.args[0]], [(2, 0, True), (1, 1, False)])
            sauvegarder.assert_called_once_with(update_fields=["options"])
            liens.return_value.all.return_value.delete.assert_called_once()
            invalider.assert_called_once_with(CACHE_KEY)

    def test_import_geojson_prioritaire_sur_ancienne_url(self):
        fichier = SimpleUploadedFile("couche.geojson", b'{"type":"Point","coordinates":[55,-21]}')
        configuration = {"nom": "Couche importée", "format": "geojson", "url": "/static/instruction/carto/fond_coeur_de_parc.geojson", "options": {}}
        requete = self.requete(donnees={"configuration": json.dumps(configuration), "fichier": fichier}, multipart=True)
        with patch.object(CartographieSource, "save", autospec=True, side_effect=lambda source: setattr(source, "pk", 9)) as sauvegarder:
            reponse = cartographie.enregistrer_source(requete)
        self.assertEqual(reponse.status_code, 200)
        resultat = json.loads(reponse.content)["source"]
        self.assertTrue(resultat["importe"])
        self.assertEqual(resultat["url_source"], "")
        sauvegarder.assert_called_once()

    def test_import_invalide_necrit_pas_en_bdd(self):
        fichier = SimpleUploadedFile("couche.geojson", b'{"type":"Point","coordinates":[340000,7650000]}')
        requete = self.requete(donnees={"configuration": json.dumps({"nom": "Couche", "format": "geojson"}), "fichier": fichier}, multipart=True)
        with patch.object(CartographieSource, "save") as sauvegarder:
            reponse = cartographie.enregistrer_source(requete)
        self.assertEqual(reponse.status_code, 400)
        sauvegarder.assert_not_called()
