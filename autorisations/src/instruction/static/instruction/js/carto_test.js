/**
 * carto_test.js - Refactorisé pour plus de lisibilité, modularité et clarté.
 */

(function main() {
  const fondData = window._fondDeCarteData;
  const adhesionData = window._adhesionData;
  const cartes = document.querySelectorAll(".carte");

  if (!cartes.length) {
    console.warn("Aucune carte détectée.");
    return;
  }

  cartes.forEach((div) => {
    const geojson = parseGeoJSON(div.dataset.geojson);
    const map = initializeMap(div);
    const overlayMaps = addBackgroundLayers(map, fondData, adhesionData);
    addLayerControl(map, overlayMaps);

    const layer = geojson ? renderExistingGeometry(map, geojson, fondData, adhesionData) : null;

    if (layer && layer.getBounds().isValid()) {
        map.fitBounds(layer.getBounds(), {
            padding: [30, 30],    // espace en pixels autour
            maxZoom: 12           // limite le zoom max si trop serré
        });
    } else {
        map.setView([-21.135, 55.526], 11);
    }



    enableDrawing(map, fondData, adhesionData);
  });

  // setupValidationButton();



  // --- Fonctions utilitaires ---

  function parseGeoJSON(raw) {
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      console.error("GeoJSON invalide :", raw);
      return null;
    }
  }


  function initializeMap(container) {
    const map = L.map(container);
  
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri & NASA',
        maxZoom: 19
    }).addTo(map);


    map.pm.addControls({
      position: 'topleft',
      drawCircleMarker: false,
      drawPolyline: true,
      drawMarker: true,
      drawCircle: false,
      drawRectangle: true,
      drawPolygon: true,
      editMode: true,
      removalMode: true
    });

    map.on('pm:globaleditmodetoggled', (e) => {
      map.eachLayer((layer) => {
        if (layer.pm && layer.pmIgnore) {
          layer.pm.disable(); // Empêche l'édition
        }
      });
    });

   

    map.on('layeradd', (e) => {
      const layer = e.layer;

      // 1. Si c'est un groupe GeoJSON avec sous-couches
      if (layer.eachLayer) {
        layer.eachLayer(subLayer => {
          if (subLayer?.options?._isBackgroundLayer) {
            subLayer.pmIgnore = true;
            if (map.pm.globalEditEnabled() && subLayer.pm) {
              subLayer.pm.disable();
            }
            subLayer.bringToBack();
          }
        });
      }

      // 2. Si c’est une couche simple
      if (layer?.options?._isBackgroundLayer) {
        layer.pmIgnore = true;
        if (map.pm.globalEditEnabled() && layer.pm) {
          layer.pm.disable();
        }
        layer.bringToBack();
      }
    });

    container._leaflet_map = map;

    return map;
  }


   function addBackgroundLayers(map, fond, adhesion) {
    const overlays = {};

    if (fond) {
      const fondLayer = L.geoJSON(fond, {
        style: { color: "#2E7D32", fillColor: "#4CAF50", weight: 2, fillOpacity: 0.5, opacity: 0.1 },
        onEachFeature: (feature, layer) => {
          layer.bindPopup("<strong>Cœur du Parc national</strong>");
          layer.pmIgnore = true;
        }
      }).addTo(map);
      fondLayer.eachLayer(l => {
        l.options._isBackgroundLayer = true;
        l.pmIgnore = true;
      });

      overlays["Cœur du Parc National"] = fondLayer;
      fondLayer.bringToBack();
    }

   if (adhesion) {
      const adhesionLayer = L.geoJSON(adhesion, {
        style: {
          color: "#388E3C",
          fillColor: "#A5D6A7",
          weight: 1,
          fillOpacity: 0.5,
          opacity: 0.1
        },
        onEachFeature: (feature, layer) => {
          const { Type = "N/A", Decret = "Non renseigné" } = feature.properties || {};
          layer.bindPopup(`<strong>${Type}</strong><br/><small>${Decret}</small>`);
          layer.pmIgnore = true;
        }
        
    });

  adhesionLayer.eachLayer(l => {
    l.options._isBackgroundLayer = true;
    l.pmIgnore = true;
  });

  adhesionLayer.options._isBackgroundLayer = true;


  // ✅ Ajoute uniquement dans le panneau de calques, pas sur la carte
  overlays["Aire d’adhésion"] = adhesionLayer;
}


    return overlays;
  }


  function addLayerControl(map, overlays) {
    const control = L.control.layers(null, overlays, { collapsed: false, position: "topright" }).addTo(map);

    setTimeout(() => {
      const container = document.querySelector('.leaflet-control-layers');
      if (container && !container.querySelector('.layer-title')) {
        const title = document.createElement('div');
        title.className = 'layer-title';
        title.innerText = "Les aires du Parc national";
        container.insertBefore(title, container.firstChild);
      }
    }, 100);
  }


  function renderExistingGeometry(map, geojson, fond, adhesion) {
    const layer = L.geoJSON(geojson, {
      style: { color: "red", weight: 3, fillColor: "#f03", fillOpacity: 0.5 },
      pointToLayer: (f, latlng) => L.circleMarker(latlng, {
        radius: 3,
        color: "#800",
        fillColor: "#d00",
        fillOpacity: 1,
        weight: 2
      })
    }).addTo(map);

    layer.bringToFront();
    // checkIntersection(map, geojson, fond, adhesion, layer);
    return layer;
  }


  function enableDrawing(map, fond, adhesion) {
    map.on('pm:create', e => {
        const layer = e.layer;
        layer.addTo(map).bringToFront();

        const geojson = layer.toGeoJSON();
        // checkIntersection(map, geojson, fond, adhesion, layer);

        // ✅ Désactive immédiatement l’outil actif (ex : polygone, rectangle, etc.)
        map.pm.disableDraw();
    });
  }

  
  function defaultBounds() {
    return L.latLngBounds([-21.39, 55.21], [-20.85, 55.84]);
  }

 
})();

function setupValidationButton() {
  const cartes = document.querySelectorAll(".carte");  // ✅ Ajoute cette ligne

  document.getElementById('valider-geom')?.addEventListener('click', () => {
    const confirmMessage = "Souhaitez-vous vraiment valider et exporter la géométrie actuelle ?";
    if (!confirm(confirmMessage)) return;

    const geojsonInput = document.getElementById('geom-result');
    const allFeatures = [];

    cartes.forEach(div => {
      const map = div._leaflet_map;
      if (!map) return;

      const layers = map.pm.getGeomanLayers().filter(l => !l.pmIgnore);
      layers.forEach(layer => {
        const geo = layer.toGeoJSON();
        if (geo.type === 'FeatureCollection') {
          allFeatures.push(...geo.features);
        } else {
          allFeatures.push(geo);
        }
      });
    });

    if (allFeatures.length === 0) {
      alert("Aucune géométrie à exporter.");
      return;
    }

    const featureCollection = {
      type: "FeatureCollection",
      features: allFeatures
    };

    const geojsonStr = JSON.stringify(featureCollection, null, 2);
    geojsonInput.value = geojsonStr;

    console.log("✅ Valeur injectée :", geojsonStr);
    document.getElementById("form-geom").submit();
  });
}


// 💡 Expose bien la fonction globalement
window.setupValidationButton = setupValidationButton;

