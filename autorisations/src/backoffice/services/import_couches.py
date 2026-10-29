"""Conversion vectorielle en GeoJSON, sans écriture ni accès réseau."""
import json
import math
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException
from django.core.exceptions import ValidationError

from instruction.utils.cartographie import valider_geojson


TAILLE_MAX = 5 * 1024 * 1024
NAMESPACES = {
    "", "http://www.topografix.com/GPX/1/0", "http://www.topografix.com/GPX/1/1",
    "http://www.opengis.net/kml/2.2", "http://earth.google.com/kml/2.0",
    "http://earth.google.com/kml/2.1", "http://earth.google.com/kml/2.2",
}
ROOT_NAMESPACES = {
    ".gpx": {"", "http://www.topografix.com/GPX/1/0", "http://www.topografix.com/GPX/1/1"},
    ".kml": NAMESPACES - {"http://www.topografix.com/GPX/1/0", "http://www.topografix.com/GPX/1/1"},
}


def _nom(element):
    namespace, _, nom = element.tag.rpartition("}")
    return nom if namespace.lstrip("{") in NAMESPACES else ""


def _enfants(element, nom):
    return [enfant for enfant in element if _nom(enfant) == nom]


def _enfant(element, nom):
    return next(iter(_enfants(element, nom)), None)


def _texte(element, nom):
    enfant = _enfant(element, nom)
    return "" if enfant is None else "".join(enfant.itertext()).strip()


def _position(longitude, latitude, altitude=None):
    try:
        position = [float(longitude), float(latitude)]
        if altitude is not None:
            position.append(float(altitude))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Coordonnée manquante ou non numérique. Coordonnées WGS84 longitude/latitude attendues.") from exc
    if not all(math.isfinite(nombre) for nombre in position) or not -180 <= position[0] <= 180 or not -90 <= position[1] <= 90:
        raise ValidationError("Coordonnées invalides : utiliser le WGS84 longitude/latitude, pas des coordonnées projetées (ex. EPSG:2975).")
    return position


def _proprietes(element):
    return {cle: valeur for tag, cle in (("name", "nom"), ("desc", "description"), ("description", "description"), ("type", "type"), ("cmt", "commentaire")) if (valeur := _texte(element, tag))}


def _feature(geometrie, proprietes):
    return {"type": "Feature", "geometry": geometrie, "properties": proprietes}


def _parcours(parties):
    parties = [partie for partie in parties if partie]
    if not parties:
        raise ValidationError("Le GPX contient un parcours sans point exploitable.")
    if len(parties) == 1:
        return {"type": "Point", "coordinates": parties[0][0]} if len(parties[0]) == 1 else {"type": "LineString", "coordinates": parties[0]}
    if all(len(partie) >= 2 for partie in parties):
        return {"type": "MultiLineString", "coordinates": parties}
    # Ne pas perdre les segments isolés ni relier artificiellement deux segments.
    return {"type": "GeometryCollection", "geometries": [_parcours([partie]) for partie in parties]}


def _convertir_gpx(racine):
    if racine.get("version") not in ("1.0", "1.1"):
        raise ValidationError("Version GPX absente ou non prise en charge : GPX 1.0 ou 1.1 attendu.")

    def position(point):
        return _position(point.get("lon"), point.get("lat"), _texte(point, "ele") or None)

    features = []
    for point in _enfants(racine, "wpt"):
        proprietes = _proprietes(point)
        if date := _texte(point, "time"):
            proprietes["date"] = date
        features.append(_feature({"type": "Point", "coordinates": position(point)}, proprietes))
    for route in _enfants(racine, "rte"):
        features.append(_feature(_parcours([[position(point) for point in _enfants(route, "rtept")]]), _proprietes(route)))
    for trace in _enfants(racine, "trk"):
        parties = [[position(point) for point in _enfants(segment, "trkpt")] for segment in _enfants(trace, "trkseg")]
        features.append(_feature(_parcours(parties), _proprietes(trace)))
    return {"type": "FeatureCollection", "features": features}


def _coordonnees_kml(element):
    positions = []
    for tuple_texte in _texte(element, "coordinates").split():
        valeurs = tuple_texte.split(",")
        if len(valeurs) not in (2, 3):
            raise ValidationError("Coordonnées KML invalides : longitude,latitude[,altitude] attendues.")
        positions.append(_position(*valeurs))
    if not positions:
        raise ValidationError("Géométrie KML sans coordonnées.")
    return positions


def _geometrie_kml(element, profondeur=0):
    if profondeur > 6:
        raise ValidationError("Géométrie KML trop imbriquée.")
    nom = _nom(element)
    if nom == "MultiGeometry":
        geometries = [_geometrie_kml(enfant, profondeur + 1) for enfant in element]
        if not geometries:
            raise ValidationError("MultiGeometry KML vide.")
        return {"type": "GeometryCollection", "geometries": geometries}
    if nom == "Polygon":
        exterieurs = _enfants(element, "outerBoundaryIs")
        if len(exterieurs) != 1:
            raise ValidationError("Un polygone KML doit contenir un seul contour extérieur.")
        anneaux = []
        for bordure in exterieurs + _enfants(element, "innerBoundaryIs"):
            anneau = _enfant(bordure, "LinearRing")
            if anneau is None:
                raise ValidationError("Contour de polygone KML invalide : LinearRing manquant.")
            anneaux.append(_coordonnees_kml(anneau))
        return {"type": "Polygon", "coordinates": anneaux}
    if nom not in ("Point", "LineString"):
        raise ValidationError("Géométrie KML non prise en charge : seuls les points, lignes et polygones sont acceptés.")
    positions = _coordonnees_kml(element)
    if nom == "Point" and len(positions) != 1:
        raise ValidationError("Un point KML doit contenir une seule position.")
    return {"type": nom, "coordinates": positions[0] if nom == "Point" else positions}


def _convertir_kml(racine):
    features = []
    for element in racine.iter():
        nom = _nom(element)
        if nom in ("NetworkLink", "GroundOverlay", "ScreenOverlay", "Model") or element.tag in ("{http://www.google.com/kml/ext/2.2}Track", "{http://www.google.com/kml/ext/2.2}MultiTrack"):
            raise ValidationError("Ce KML contient des liens réseau, images, modèles 3D ou traces animées non pris en charge. Exporter uniquement ses points, lignes et polygones.")
        if nom != "Placemark":
            continue
        geometries = [enfant for enfant in element if _nom(enfant) in ("Point", "LineString", "Polygon", "MultiGeometry")]
        if len(geometries) != 1:
            raise ValidationError("Un objet KML (Placemark) doit contenir une géométrie prise en charge.")
        proprietes = _proprietes(element)
        extended = _enfant(element, "ExtendedData")
        if extended is not None:
            for attribut in extended.iter():
                cle = attribut.get("name")
                if cle and _nom(attribut) in ("Data", "SimpleData"):
                    proprietes[cle] = _texte(attribut, "value") if _nom(attribut) == "Data" else "".join(attribut.itertext()).strip()
        features.append(_feature(_geometrie_kml(geometries[0]), proprietes))
    return {"type": "FeatureCollection", "features": features}


def convertir_couche(fichier):
    """Même conversion pour l’aperçu et la sauvegarde ; seul l’appelant sauvegarde."""
    if fichier is None:
        raise ValidationError("Sélectionner un fichier GeoJSON, GPX ou KML.")
    extension = Path(fichier.name).suffix.lower()
    if extension not in (".geojson", ".json", ".gpx", ".kml"):
        raise ValidationError("Format non pris en charge. Importer un fichier .geojson, .json, .gpx ou .kml (pas de Shapefile ni de KMZ).")
    fichier.seek(0)
    contenu = fichier.read(TAILLE_MAX + 1)
    if len(contenu) > TAILLE_MAX:
        raise ValidationError("Le fichier dépasse la limite de 5 Mo.")
    try:
        if extension in (".geojson", ".json"):
            resultat = json.loads(contenu.decode("utf-8-sig"))
        else:
            racine = fromstring(contenu, forbid_dtd=True, forbid_entities=True, forbid_external=True)
            pile = [(racine, 0)]
            compteur = 0
            while pile:
                element, profondeur = pile.pop()
                compteur += 1
                if profondeur > 32 or compteur > 300000:
                    raise ValidationError("Document XML trop complexe ou trop imbriqué.")
                pile.extend((enfant, profondeur + 1) for enfant in element)
            racines_valides = {f"{{{namespace}}}{extension[1:]}" if namespace else extension[1:] for namespace in ROOT_NAMESPACES[extension]}
            if racine.tag not in racines_valides:
                raise ValidationError(f"Le contenu ne correspond pas à un fichier {extension[1:].upper()} valide.")
            resultat = _convertir_gpx(racine) if extension == ".gpx" else _convertir_kml(racine)
        valider_geojson(resultat)
        serialise = json.dumps(resultat, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(serialise) > TAILLE_MAX:
            raise ValidationError("Le GeoJSON obtenu dépasse 5 Mo. Simplifier ou découper la couche avant l’import.")
        return resultat
    except DefusedXmlException as exc:
        raise ValidationError("XML refusé : les DTD et les entités internes ou externes ne sont pas autorisées.") from exc
    except ParseError as exc:
        raise ValidationError(f"Fichier {extension[1:].upper()} XML mal formé (ligne {exc.position[0]}).") from exc
    except UnicodeError as exc:
        raise ValidationError("Encodage invalide : importer un fichier GeoJSON UTF-8 ou un GPX/KML XML correctement encodé.") from exc
    except LookupError as exc:
        raise ValidationError("Encodage XML inconnu : exporter le GPX/KML en UTF-8.") from exc
    except (ValueError, RecursionError) as exc:
        raise ValidationError("Fichier JSON invalide ou trop imbriqué ; les valeurs non finies (NaN, Infinity) sont interdites.") from exc
