import json


def formattage_geojson(geojson):
    '''
#     Format du Geojson en entrée :
#     {"parcours": [
#         {
#             {"pois": [{},{},...], pk:int, name:str},
#             {"pois": [{},{},...], pk:int, name:str},
#             ...
#         }]
#     }    
#
#
#   Sortie:
#   FeatureCollection aplatie + properties enrichies avec parcours_id/parcours_name      
    '''


    features = []

    for parcours in geojson.get("parcours", []):
        parcours_id = parcours.get("pk")  # ex: 192914
        parcours_name = parcours.get("name")  # ex: "1 - ULTRA TERRESTRE"

        parcours_meta = {
            "parcours_id": parcours_id,
            "parcours_name": parcours_name,
        }

        # -----------------------
        # POIs (Points d'intérêt)
        # -----------------------
        for poi in parcours.get("pois", []):
            geom = (poi.get("geometry") or {})
            if geom.get("coordinates"):
                props = poi.get("properties") or {}
                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        **props,
                        **parcours_meta,  # ✅ on garde la course
                    }
                })

        # -----------------------
        # Tracés (LineString)
        # -----------------------
        shape = parcours.get("shape", {}) or {}
        for key in ["line_shape"]:
            line = shape.get(key) or {}
            geom = (line.get("geometry") or {})
            if geom.get("coordinates"):
                props = line.get("properties") or {}
                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "type": key,
                        **props,
                        **parcours_meta,  # ✅ on garde la course
                    }
                })

    return json.dumps({
        "type": "FeatureCollection",
        "features": features
    })


