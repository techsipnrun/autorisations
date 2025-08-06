import json


def formattage_geojson(geojson):
    '''
    Foramt du Geojson en entrée :
    {"parcours": [
        {
            "pois": [{},{},...],
            "pois": [{},{},...],
            ...
        }]
    }          
    '''
    features = []

    for parcours in geojson.get("parcours", []):
        # POIs (points d'intérêt)
        for poi in parcours.get("pois", []):
            if poi.get("geometry").get("coordinates"):
                features.append({
                    "type": "Feature",
                    "geometry": poi.get("geometry"),
                    "properties": poi.get("properties")
                })

        # Tracés (line_shape et line_waypoint)
        shape = parcours.get("shape", {})
        for key in ["line_shape", "line_waypoint"]:
            line = shape.get(key)
            if line and line.get("geometry").get('coordinates'):
                features.append({
                    "type": "Feature",
                    "geometry": line.get("geometry"),
                    "properties": {
                        "type": key,
                        **line.get("properties", {})
                    }
                })

    result = {
        "type": "FeatureCollection",
        "features": features
    }
    
    return (json.dumps(result))

def ecriture_geojson():
    return None