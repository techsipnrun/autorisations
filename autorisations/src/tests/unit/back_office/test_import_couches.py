import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_cartographie import CartographieSource
from instruction.utils.import_couches import TAILLE_MAX, convertir_couche
from instruction.views import cartographie


def fichier(nom, contenu):
    return SimpleUploadedFile(nom, contenu.encode("utf-8") if isinstance(contenu, str) else contenu)


def gpx(contenu):
    return '<gpx version="1.1" creator="AGIDA" xmlns="http://www.topografix.com/GPX/1/1">' + contenu + '</gpx>'


def kml(contenu):
    return '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + contenu + '</Document></kml>'


POINT_KML = '<Placemark><name>Mafate</name><Point><coordinates>55.5,-21.1,42</coordinates></Point></Placemark>'
POINT_GPX = '<wpt lat="-21.1" lon="55.5"><name>Îlet</name><ele>42</ele><time>2026-10-13T08:00:00Z</time></wpt>'


class ImportCouchesTests(SimpleTestCase):
    def test_geojson_existant_utf8_bom(self):
        contenu = b'\xef\xbb\xbf' + json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [55, -21]}, "properties": {"nom": "Îlet"}}, ensure_ascii=False).encode()
        resultat = convertir_couche(fichier("couche.GEOJSON", contenu))
        self.assertEqual(resultat["properties"]["nom"], "Îlet")

    def test_gpx_points_altitude_date_et_accents(self):
        feature = convertir_couche(fichier("points.GPX", gpx(POINT_GPX)))["features"][0]
        self.assertEqual(feature["geometry"], {"type": "Point", "coordinates": [55.5, -21.1, 42]})
        self.assertEqual(feature["properties"], {"nom": "Îlet", "date": "2026-10-13T08:00:00Z"})

    def test_gpx_route_et_segments_de_trace_non_relies(self):
        points = '<rtept lat="-21" lon="55"/><rtept lat="-21.1" lon="55.1"/>'
        segment = '<trkseg>' + points.replace('rtept', 'trkpt') + '</trkseg>'
        resultat = convertir_couche(fichier("parcours.gpx", gpx('<rte><name>Route</name>' + points + '</rte><trk><name>Trace</name>' + segment * 2 + '</trk>')))
        route, trace = resultat["features"]
        self.assertEqual(route["geometry"]["type"], "LineString")
        self.assertEqual(trace["geometry"]["type"], "MultiLineString")
        self.assertEqual(len(trace["geometry"]["coordinates"]), 2)
        self.assertEqual(trace["properties"]["nom"], "Trace")

    def test_gpx_point_isole_dans_un_segment_conserve(self):
        xml = gpx('<trk><trkseg><trkpt lat="-21" lon="55"/></trkseg><trkseg><trkpt lat="-21.1" lon="55.1"/><trkpt lat="-21.2" lon="55.2"/></trkseg></trk>')
        geometrie = convertir_couche(fichier("trace.gpx", xml))["features"][0]["geometry"]
        self.assertEqual([g["type"] for g in geometrie["geometries"]], ["Point", "LineString"])

    def test_gpx_10_et_sans_namespace(self):
        for xml in (gpx(POINT_GPX).replace('/GPX/1/1', '/GPX/1/0').replace('version="1.1"', 'version="1.0"'), gpx(POINT_GPX).replace(' xmlns="http://www.topografix.com/GPX/1/1"', '')):
            with self.subTest(xml=xml):
                self.assertEqual(len(convertir_couche(fichier("point.gpx", xml))["features"]), 1)

    def test_kml_point_et_attributs_etendus(self):
        xml = POINT_KML.replace('<Point>', '<ExtendedData><Data name="secteur"><value>nord</value></Data><SchemaData><SimpleData name="code">42</SimpleData></SchemaData></ExtendedData><Point>')
        feature = convertir_couche(fichier("point.kml", kml(xml)))["features"][0]
        self.assertEqual(feature["geometry"]["coordinates"], [55.5, -21.1, 42])
        self.assertEqual(feature["properties"], {"nom": "Mafate", "secteur": "nord", "code": "42"})

    def test_kml_polygone_avec_trou_et_multigeometrie(self):
        anneau = '<LinearRing><coordinates>55,-21 56,-21 56,-20 55,-21</coordinates></LinearRing>'
        polygone = '<Polygon><outerBoundaryIs>' + anneau + '</outerBoundaryIs><innerBoundaryIs>' + anneau + '</innerBoundaryIs></Polygon>'
        ligne = '<LineString><coordinates>55,-21 55.5,-21.5</coordinates></LineString>'
        xml = kml('<Placemark><MultiGeometry>' + polygone + ligne + '</MultiGeometry></Placemark>')
        geometries = convertir_couche(fichier("couche.kml", xml))["features"][0]["geometry"]["geometries"]
        self.assertEqual([g["type"] for g in geometries], ["Polygon", "LineString"])
        self.assertEqual(len(geometries[0]["coordinates"]), 2)

    def test_xml_utf16_et_description_reste_du_texte(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?>' + kml(POINT_KML.replace('<Point>', '<description>&lt;script&gt;test&lt;/script&gt;</description><Point>'))
        resultat = convertir_couche(fichier("couche.kml", xml.encode("utf-16")))
        self.assertEqual(resultat["features"][0]["properties"]["description"], '<script>test</script>')

    def test_fichiers_non_pris_en_charge_ou_vides(self):
        for nom, contenu in (("couche.zip", b"PK"), ("couche.kmz", b"PK"), ("couche.shp", b"shp"), ("couche.gpx", gpx('')), ("couche.kml", kml('')), ("couche.geojson", '{"type":"FeatureCollection","features":[]}')):
            with self.subTest(nom=nom), self.assertRaises(ValidationError):
                convertir_couche(fichier(nom, contenu))

    def test_contenu_xml_invalide_et_mauvaise_extension(self):
        for contenu, extension in (('<gpx', 'gpx'), (kml(POINT_KML), 'gpx'), (gpx(POINT_GPX), 'kml'), (gpx(POINT_GPX).replace('/GPX/1/1', '/inconnu'), 'gpx'), (gpx(POINT_GPX).replace('version="1.1"', 'version="2.0"'), 'gpx')):
            with self.subTest(contenu=contenu), self.assertRaises(ValidationError):
                convertir_couche(fichier('couche.' + extension, contenu))

    def test_dtd_entites_et_references_externes_refusees(self):
        for dtd in ('<!DOCTYPE gpx>', '<!DOCTYPE gpx [<!ENTITY x "texte">]>', '<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///secret">]>', '<!DOCTYPE gpx SYSTEM "https://example.test/dtd">'):
            with self.subTest(dtd=dtd), self.assertRaisesMessage(ValidationError, "XML refusé"):
                convertir_couche(fichier("couche.gpx", dtd + gpx(POINT_GPX)))

    def test_kml_ressources_externes_et_modeles_non_acceptes(self):
        for element in ('<NetworkLink/>', '<GroundOverlay/>', '<ScreenOverlay/>', '<Model/>', '<gx:Track xmlns:gx="http://www.google.com/kml/ext/2.2"/>'):
            with self.subTest(element=element), self.assertRaisesMessage(ValidationError, "non pris en charge"):
                convertir_couche(fichier("couche.kml", kml(POINT_KML + element)))

    def test_coordonnees_absentes_projetees_ou_non_finies(self):
        for point in ('<wpt lat="-21"/>', '<wpt lat="7650000" lon="340000"/>', '<wpt lat="NaN" lon="55"/>', '<wpt lat="-21" lon="abc"/>'):
            with self.subTest(point=point), self.assertRaisesMessage(ValidationError, "Coordonn"):
                convertir_couche(fichier("couche.gpx", gpx(point)))

    def test_geometries_kml_incompletes_refusees(self):
        for geometrie in ('<Point/>', '<Point><coordinates>55,-21 56,-22</coordinates></Point>', '<LineString><coordinates>55,-21</coordinates></LineString>', '<Polygon/>', '<MultiGeometry/>', '<Polygon><outerBoundaryIs><LinearRing><coordinates>55,-21 56,-21 56,-20 55,-20</coordinates></LinearRing></outerBoundaryIs></Polygon>'):
            with self.subTest(geometrie=geometrie), self.assertRaises(ValidationError):
                convertir_couche(fichier("couche.kml", kml('<Placemark>' + geometrie + '</Placemark>')))

    def test_fichier_et_geojson_converti_bornes(self):
        with self.assertRaisesMessage(ValidationError, "5 Mo"):
            convertir_couche(fichier("gros.gpx", b'x' * (TAILLE_MAX + 1)))
        contenu = gpx('<wpt lat="-21" lon="55"/>' * 100)
        with patch("instruction.utils.import_couches.TAILLE_MAX", len(contenu.encode()) + 1):
            with self.assertRaisesMessage(ValidationError, "GeoJSON obtenu"):
                convertir_couche(fichier("converti.gpx", contenu))

    def test_complexite_et_json_non_fini_refuses(self):
        xml = kml('<Folder>' * 40 + POINT_KML + '</Folder>' * 40)
        for nom, contenu in (("couche.kml", xml), ("couche.json", '{"type":"Point","coordinates":[55,-21],"autre":NaN}')):
            with self.subTest(nom=nom), self.assertRaises(ValidationError):
                convertir_couche(fichier(nom, contenu))

    def test_encodages_invalides_et_absence_fichier(self):
        for nom, contenu in (("couche.json", b'\xff'), ("couche.gpx", b'<?xml version="1.0" encoding="inconnu"?><gpx/>')):
            with self.subTest(nom=nom), self.assertRaisesMessage(ValidationError, "ncodage"):
                convertir_couche(fichier(nom, contenu))
        with self.assertRaisesMessage(ValidationError, "Sélectionner"):
            convertir_couche(None)


class ConversionCouchesVuesTests(SimpleTestCase):
    def requete(self, upload=None, admin=True):
        request = RequestFactory().post('/back-office/cartographie/convertir/', {"fichier": upload} if upload else {})
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=admin)
        return request

    def test_conversion_sans_lecture_ni_ecriture_bdd(self):
        # SimpleTestCase interdit toute requête SQL, même en lecture.
        reponse = cartographie.convertir_source(self.requete(fichier("couche.gpx", gpx(POINT_GPX))))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(json.loads(reponse.content)["geojson"]["features"][0]["properties"]["nom"], "Îlet")
        self.assertEqual(reponse["Cache-Control"], "private, no-store")

    def test_conversion_reservee_aux_admins_et_post(self):
        with self.assertRaises(PermissionDenied):
            cartographie.convertir_source(self.requete(fichier("couche.gpx", gpx(POINT_GPX)), admin=False))
        request = RequestFactory().get('/back-office/cartographie/convertir/')
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        self.assertEqual(cartographie.convertir_source(request).status_code, 405)

    def test_conversion_erreur_claire_sans_bdd(self):
        for upload, message in ((None, "Sélectionner"), (fichier("mauvais.kml", '<kml'), "XML mal formé")):
            with self.subTest(message=message):
                reponse = cartographie.convertir_source(self.requete(upload))
                self.assertEqual(reponse.status_code, 400)
                self.assertIn(message, json.loads(reponse.content)["erreur"])

    def test_enregistrement_reconvertit_original_et_persiste_geojson(self):
        for nom, contenu in (("couche.gpx", gpx(POINT_GPX)), ("couche.kml", kml(POINT_KML))):
            with self.subTest(nom=nom):
                request = self.requete(fichier(nom, contenu))
                request.POST = request.POST.copy()
                request.POST['configuration'] = json.dumps({"nom": "Import", "format": "geojson", "options": {}})
                with patch.object(CartographieSource, "save", autospec=True, side_effect=lambda source: setattr(source, "pk", 10)) as save:
                    reponse = cartographie.enregistrer_source(request)
                self.assertEqual(reponse.status_code, 200)
                source = save.call_args.args[0]
                self.assertEqual(source.geojson["type"], "FeatureCollection")
                self.assertEqual(source.format, "geojson")
                self.assertEqual(source.url, "")

    def test_echec_import_ne_remplace_pas_source_existante(self):
        source = CartographieSource(id=10, nom="Ancienne", format="geojson", geojson={"type": "Point", "coordinates": [55, -21]})
        request = self.requete(fichier("invalide.kml", '<kml'))
        request.POST = request.POST.copy()
        request.POST['configuration'] = json.dumps({"nom": "Nouveau", "format": "geojson", "options": {}})
        with patch('instruction.views.cartographie.get_object_or_404', return_value=source), patch.object(CartographieSource, "save") as save:
            reponse = cartographie.enregistrer_source(request, 10)
        self.assertEqual(reponse.status_code, 400)
        save.assert_not_called()
        self.assertEqual(source.nom, "Ancienne")
        self.assertEqual(source.geojson["type"], "Point")
