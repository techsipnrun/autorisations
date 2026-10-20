"""Configuration visuelle uniquement : les référentiels des calculs restent inchangés."""
import copy
import logging
import math
import re
from urllib.parse import urlsplit

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError
from django.db.models import BooleanField, Case, Prefetch, Value, When
from django.urls import reverse
from django.templatetags.static import static

from autorisations.models.models_cartographie import CartographieConfiguration, CartographieConfigurationSource, CartographieSource


logger = logging.getLogger("APP")
CACHE_KEY = "cartographie:configurations:v1"
PROFILS = {
    "preinstruction_dn": "Pré-instruction · DN",
    "instruction_dn": "Instruction · DN",
    "preinstruction_dm": "Pré-instruction · DM",
    "instruction_dm": "Instruction · DM",
    "requetes": "Requête",
    "statistiques": "Statistiques",
    "edition": "Édition de géométrie",
}
CONTROLES = {
    "zoom": "Boutons de zoom", "molette": "Zoom à la molette",
    "fonds": "Menu des fonds", "couches": "Menu des couches",
    "legende": "Légende", "impression": "Impression PDF",
    "drawMarker": "Dessiner des points", "drawPolyline": "Dessiner des lignes",
    "drawPolygon": "Dessiner des polygones", "drawRectangle": "Dessiner des rectangles",
    "editMode": "Modifier les dessins", "removalMode": "Supprimer les dessins",
}
COULEURS_SECTEURS = {"sud": "#e63946", "ouest": "#f59e0b", "est": "#2563eb", "nord": "#7c3aed"}
STYLE_DN = {"color": "#B84A4A", "fillColor": "#D97878", "weight": 2.5, "opacity": .9, "fillOpacity": .28, "radius": 5}
STYLE_DM = {"color": "#3388ff", "fillColor": "#3388ff", "weight": 3, "opacity": 1, "fillOpacity": .5, "radius": 5}


def options_par_defaut(code):
    dessin = code in ("requetes", "edition")
    geometrie = copy.deepcopy(STYLE_DM if code.endswith("_dm") else STYLE_DN)
    if code == "requetes":
        geometrie.update(color="#b62020", weight=3, fillColor="#d65555", fillOpacity=.18)
    return {
        "centre": [-21.135, 55.526] if code == "edition" else ([-21.12, 55.53] if code in ("requetes", "statistiques") else [-21.1, 55.5]),
        "zoom": 10 if code == "statistiques" else 11,
        "recentrage": True,
        "zoom_cadrage": 18 if code == "edition" else (12 if code.endswith("_dn") else 15),
        "geometrie": geometrie,
        "couleur_densite": "#00695c",
        "controles": {
            "zoom": True, "molette": True, "fonds": True,
            "couches": code != "statistiques", "legende": False,
            "impression": code not in ("requetes", "statistiques"),
            **{cle: dessin for cle in CONTROLES if cle.startswith("draw") or cle in ("editMode", "removalMode")},
        },
    }


def sources_par_defaut():
    fonds = [
        ("ign", "Plan IGN", "https://data.geopf.fr/wmts?service=WMTS&request=GetTile&version=1.0.0&layer=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&style=normal&tilematrixset=PM&format=image/png&tilematrix={z}&tilerow={y}&tilecol={x}", "© IGN - Géoplateforme", 19),
        ("osm", "OpenStreetMap", "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap", 19),
        ("satellite", "Satellite", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "Esri & NASA", 19),
        ("topo", "OpenTopoMap", "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", "© OpenTopoMap", 18),
    ]
    sources = [{"code": code, "nom": nom, "format": "tuiles", "url": url, "attribution": attribution, "actif": True, "options": {"maxZoom": zoom}}
               for code, nom, url, attribution, zoom in fonds]
    for code, nom, fichier, style in [
        ("coeur", "Cœur du Parc national", "fond_coeur_de_parc.geojson", {"color": "#2E7D32", "fillColor": "#4CAF50", "weight": 2, "opacity": 1, "fillOpacity": .4}),
        ("adhesion", "Aire d’adhésion", "aire_adhesion.geojson", {"color": "#388E3C", "fillColor": "#A5D6A7", "weight": 2, "opacity": 1, "fillOpacity": .6}),
        ("mafate", "COT Mafate", "COT_MAFATE.geojson", {"color": "#1900ff", "fillColor": "#1848ce", "weight": 1.5, "opacity": 1, "fillOpacity": .7}),
        ("secteurs", "Secteurs", "perimetre_secteur.geojson", {"color": "#64748b", "fillColor": "#64748b", "weight": 2, "opacity": .9, "fillOpacity": .22}),
    ]:
        options = {"style": style, "popup": {"mode": "survol" if code == "secteurs" else "aucun", "texte": "", "propriete": "secteur" if code == "secteurs" else ""}}
        if code == "secteurs":
            options["categories"] = {"propriete": "secteur", "couleurs": COULEURS_SECTEURS.copy()}
        sources.append({"code": code, "nom": nom, "format": "geojson", "url": static(f"instruction/carto/{fichier}"), "attribution": "", "actif": True, "options": options})
    return sources


def configurations_par_defaut():
    sources = sources_par_defaut()
    profils = {}
    for code, nom in PROFILS.items():
        membres = []
        for source in sources:
            if source["format"] == "geojson" and (code == "statistiques" or (source["code"] == "mafate" and (code.endswith("_dm") or code == "requetes"))):
                continue
            membre = copy.deepcopy(source)
            membre.update(ordre=len(membres), visible=source["code"] == ("osm" if code == "statistiques" else "ign") or (source["code"] == "coeur" and code != "requetes"))
            membres.append(membre)
        profils[code] = {"code": code, "nom": nom, "options": options_par_defaut(code), "sources": membres}
    return profils


def sources_sans_geometries():
    return CartographieSource.objects.defer("geojson").annotate(
        importe=Case(When(geojson__isnull=False, then=Value(True)), default=Value(False), output_field=BooleanField())
    )


def serialiser_source(source):
    importe = source.importe if hasattr(source, "importe") else source.geojson is not None
    return {
        "id": source.pk, "code": source.code, "nom": source.nom, "format": source.format,
        "url": f'{reverse("cartographie_geojson", args=[source.pk])}?v={source.options.get("version", "1")}' if importe else source.url,
        "url_source": source.url, "importe": importe,
        "attribution": source.attribution, "actif": source.actif, "options": source.options,
    }


def charger_configurations():
    resultat = cache.get(CACHE_KEY)
    if resultat is not None:
        return resultat
    resultat = configurations_par_defaut()
    try:
        configurations = CartographieConfiguration.objects.prefetch_related(Prefetch(
            "sources", queryset=CartographieConfigurationSource.objects.prefetch_related(Prefetch("source", queryset=sources_sans_geometries()))
        ))
        for configuration in configurations:
            if configuration.code not in PROFILS:
                continue
            membres = []
            for liaison in configuration.sources.all():
                source = liaison.source
                if source.actif:
                    membre = serialiser_source(source)
                    membre.update(ordre=liaison.ordre, visible=liaison.visible)
                    membres.append(membre)
            resultat[configuration.code] = {"code": configuration.code, "nom": configuration.nom, "options": configuration.options, "sources": membres}
    except (ProgrammingError, OperationalError):
        logger.warning("[CARTOGRAPHIE] Configuration inaccessible : utilisation des réglages historiques.")
        # Courte durée pour ne pas masquer l'exécution ultérieure du SQL.
        cache.set(CACHE_KEY, resultat, 10)
        return resultat
    cache.set(CACHE_KEY, resultat, 60)
    return resultat


def couleur(valeur):
    if not isinstance(valeur, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", valeur):
        raise ValidationError("Une couleur doit être au format #RRGGBB.")
    return valeur


def nombre(valeur, minimum, maximum):
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not math.isfinite(valeur) or not minimum <= valeur <= maximum:
        raise ValidationError(f"Valeur numérique attendue entre {minimum} et {maximum}.")
    return valeur


def valider_style(style):
    if not isinstance(style, dict):
        raise ValidationError("Style invalide.")
    resultat = {}
    for cle in ("color", "fillColor"):
        if cle in style:
            resultat[cle] = couleur(style[cle])
    for cle, maximum in (("weight", 20), ("radius", 30), ("opacity", 1), ("fillOpacity", 1)):
        if cle in style:
            resultat[cle] = nombre(style[cle], 0, maximum)
    return resultat


def valider_options_carte(code, options):
    if code not in PROFILS or not isinstance(options, dict):
        raise ValidationError("Contexte cartographique invalide.")
    resultat = options_par_defaut(code)
    centre = options.get("centre", resultat["centre"])
    if not isinstance(centre, list) or len(centre) != 2:
        raise ValidationError("Centre attendu : latitude et longitude.")
    resultat["centre"] = [nombre(centre[0], -90, 90), nombre(centre[1], -180, 180)]
    for cle in ("zoom", "zoom_cadrage"):
        valeur = nombre(options.get(cle, resultat[cle]), 0, 22)
        if int(valeur) != valeur:
            raise ValidationError("Le zoom doit être entier.")
        resultat[cle] = int(valeur)
    if resultat["zoom"] > resultat["zoom_cadrage"]:
        raise ValidationError("Le zoom initial ne peut pas être supérieur au zoom maximal du cadrage.")
    resultat["recentrage"] = options.get("recentrage", True)
    if type(resultat["recentrage"]) is not bool:
        raise ValidationError("Recentrage invalide.")
    resultat["geometrie"].update(valider_style(options.get("geometrie", {})))
    resultat["couleur_densite"] = couleur(options.get("couleur_densite", resultat["couleur_densite"]))
    controles = options.get("controles", {})
    if not isinstance(controles, dict):
        raise ValidationError("Contrôles invalides.")
    for cle in CONTROLES:
        valeur = controles.get(cle, resultat["controles"][cle])
        if type(valeur) is not bool:
            raise ValidationError("Un contrôle doit être activé ou désactivé.")
        if cle.startswith("draw") or cle in ("editMode", "removalMode"):
            valeur = valeur and code in ("requetes", "edition")
        resultat["controles"][cle] = valeur
    return resultat


def valider_options_source(format_source, options):
    if not isinstance(options, dict):
        raise ValidationError("Options de source invalides.")
    if format_source == "tuiles":
        zoom = nombre(options.get("maxZoom", 19), 0, 22)
        if int(zoom) != zoom:
            raise ValidationError("Le zoom doit être entier.")
        return {"maxZoom": int(zoom)}
    popup = options.get("popup", {})
    if not isinstance(popup, dict) or popup.get("mode", "aucun") not in ("aucun", "survol", "clic"):
        raise ValidationError("Affichage au clic/survol invalide.")
    resultat = {"style": valider_style(options.get("style", {})), "popup": {"mode": popup.get("mode", "aucun"), "texte": str(popup.get("texte", ""))[:500], "propriete": str(popup.get("propriete", ""))[:100]}}
    categories = options.get("categories")
    if categories:
        if not isinstance(categories, dict) or not isinstance(categories.get("couleurs"), dict) or len(categories["couleurs"]) > 100:
            raise ValidationError("Coloration par catégories invalide.")
        resultat["categories"] = {"propriete": str(categories.get("propriete", ""))[:100], "couleurs": {str(k)[:100]: couleur(v) for k, v in categories["couleurs"].items()}}
    return resultat


def valider_url(url, *, fond=False):
    if not isinstance(url, str) or len(url) > 2000:
        raise ValidationError("URL invalide.")
    parsed = urlsplit(url)
    if url.startswith("/") and not url.startswith("//") and not fond:
        if not url.startswith(static("instruction/carto/")):
            raise ValidationError("Seuls les fichiers cartographiques existants sont autorisés en chemin relatif.")
    elif parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError("Une URL HTTP(S), sans identifiants, est attendue.")
    if fond and not all(token in url for token in ("{z}", "{x}", "{y}")):
        raise ValidationError("L’URL de tuiles doit contenir {z}, {x} et {y} (WMTS : tilematrix={z}, tilecol={x}, tilerow={y}).")
    return url


def valider_geojson(donnees):
    """Validation bornée : WGS84, géométries reconnues, aucun code/HTML exécuté."""
    compteur = 0

    def coordonnees(valeur, niveaux):
        nonlocal compteur
        if not isinstance(valeur, list) or not valeur:
            raise ValidationError("Coordonnées GeoJSON invalides.")
        if niveaux == 0:
            if len(valeur) < 2:
                raise ValidationError("Position GeoJSON incomplète.")
            nombre(valeur[0], -180, 180)
            nombre(valeur[1], -90, 90)
            for altitude in valeur[2:]:
                nombre(altitude, -1e9, 1e9)
            compteur += 1
            if compteur > 250000:
                raise ValidationError("Couche trop détaillée (250 000 positions maximum).")
        else:
            for enfant in valeur:
                coordonnees(enfant, niveaux - 1)

    def visiter(objet, profondeur=0):
        if profondeur > 8 or not isinstance(objet, dict):
            raise ValidationError("Structure GeoJSON invalide.")
        type_objet = objet.get("type")
        if type_objet in ("FeatureCollection", "GeometryCollection"):
            enfants = objet.get("features" if type_objet == "FeatureCollection" else "geometries")
            if not isinstance(enfants, list) or len(enfants) > 20000:
                raise ValidationError("Collection GeoJSON invalide ou trop volumineuse.")
            for enfant in enfants:
                visiter(enfant, profondeur + 1)
        elif type_objet == "Feature":
            if objet.get("geometry") is not None:
                visiter(objet["geometry"], profondeur + 1)
            if not isinstance(objet.get("properties") or {}, dict):
                raise ValidationError("Propriétés GeoJSON invalides.")
        elif type_objet in ("Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"):
            positions = objet.get("coordinates")
            niveaux = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}
            coordonnees(positions, niveaux[type_objet])
            lignes = [positions] if type_objet == "LineString" else (positions if type_objet == "MultiLineString" else [])
            if any(len(ligne) < 2 for ligne in lignes):
                raise ValidationError("Une ligne doit contenir au moins deux positions.")
            anneaux = positions if type_objet == "Polygon" else ([anneau for polygone in positions for anneau in polygone] if type_objet == "MultiPolygon" else [])
            if any(len(anneau) < 4 or anneau[0] != anneau[-1] for anneau in anneaux):
                raise ValidationError("Les anneaux d’un polygone doivent être fermés et contenir au moins quatre positions.")
        else:
            raise ValidationError("Type GeoJSON non pris en charge.")

    if not isinstance(donnees, dict):
        raise ValidationError("Un objet GeoJSON est attendu.")
    crs = donnees.get("crs")
    if crs and (not isinstance(crs, dict) or not any(code in str(crs.get("properties", {}).get("name", "")).upper() for code in ("CRS84", "4326"))):
        raise ValidationError("Importer une couche en WGS84 longitude/latitude, pas en EPSG:2975.")
    visiter(donnees)
    if not compteur:
        raise ValidationError("La couche ne contient aucune position.")
    return donnees
