import json
from shapely.geometry import shape
from shapely.ops import unary_union


def intersecte_coeur_de_parc(geometrie_dm, coeur_geojson):
    """
    Retourne True si la géométrie DM intersecte le coeur de parc, False sinon.
    Accepte un GeoJSON de type FeatureCollection, Feature ou Geometry.
    """

    if not geometrie_dm or not coeur_geojson:
        return False

    try:
        geom_dm = _geojson_to_shapely(geometrie_dm)
        geom_coeur = _geojson_to_shapely(coeur_geojson)

        print(geom_coeur)

        if geom_dm is None or geom_coeur is None:
            return False

        return geom_dm.intersects(geom_coeur)

    except Exception:
        return False


def _geojson_to_shapely(obj):
    """
    Convertit un GeoJSON Python (dict / list / str JSON) en géométrie shapely.
    """

    if isinstance(obj, str):
        obj = json.loads(obj)

    if not obj:
        return None

    geojson_type = obj.get("type")

    # Cas FeatureCollection
    if geojson_type == "FeatureCollection":
        geometries = []
        for feature in obj.get("features", []):
            geom = feature.get("geometry")
            if geom:
                geometries.append(shape(geom))

        if not geometries:
            return None

        return unary_union(geometries)

    # Cas Feature
    if geojson_type == "Feature":
        geom = obj.get("geometry")
        return shape(geom) if geom else None

    # Cas Geometry brute 
    return shape(obj)