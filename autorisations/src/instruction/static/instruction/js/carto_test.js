// ****
// Script JS pour l'affichage et l'édition de la carto (edit_carto.html)
// ***


// Fonction principale

(function main() {

    console.log("✅ Début Script carto_test.js");
    
    // Fond coeur de Parc et Aire d'adhésion
    const fondData = window._fondDeCarteData;
    const adhesionData = window._adhesionData;
    const mafateData = window._mafateData;
    const cartes = document.querySelectorAll(".carte");

    if (!cartes.length) {
        console.warn("Aucune carte détectée.");
        return;
    }

    cartes.forEach((div) => {

        // Parsing du geojson
        const geojson = parseGeoJSON(div.dataset.geojson);

        // Initialisation de notre map
        const map = initializeMap(div);

        // Menu dynamique Fond coeur de Parc et Aire d'adhésion
        const overlayMaps = addBackgroundLayers(map, fondData, adhesionData, mafateData);
        addLayerControl(map, overlayMaps);

        const layer = geojson ? renderExistingGeometry(map, geojson) : null;

        if (layer && layer.getBounds().isValid()) {
            map.fitBounds(layer.getBounds(), {
                padding: [30, 30],  
                maxZoom: 18     
            });
        } else {
            map.setView([-21.135, 55.526], 11);
        }


        enableDrawing(map);
    });



    // ---------------------------------//
    //       Fonctions utilitaires      //
    // ---------------------------------//

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

        if (!map.pm) {
            console.error("❌ Leaflet-Geoman non initialisé");
        } else {
            console.log("✅ Leaflet-Geoman initialisé");
        }

        // Ajout du bouton impression PDF
        L.control.browserPrint({
            title: "📥 Télécharger en PDF",
            position: "topleft",  // coin haut gauche comme zoom
            closePopupsOnPrint: true,
            printModes: ["Landscape", "Portrait"] // propose les 2
        }).addTo(map);

        // Menu d'édition
        map.pm.addControls({
            position: 'topleft',
            drawCircleMarker: false,
            drawPolyline: true,
            drawMarker: true,
            drawCircle: false,
            drawRectangle: true,
            drawPolygon: true,
            editMode: true,
            rotateMode: false,
            removalMode: true
        });

        [
            'pm:globaleditmodetoggled',
            'pm:edit',
            'pm:remove',
            'pm:drawstart',
            'pm:drawend',
            'pm:create',
            'pm:globalremovalmodetoggled'
        ].forEach(evt => {
            map.on(evt, (e) => {
                console.log(`📣 Evénement: ${evt}`, e);
            });
        });


        setTimeout(() => {
            const editBtn = document.querySelector(".leaflet-pm-icon-edit");

            if (editBtn) {
                editBtn.addEventListener("click", () => {
                    map.eachLayer((layer) => {
                        if (
                            layer instanceof L.GeoJSON &&
                            layer.options?.name === "COT Mafate" &&
                            map.hasLayer(layer)
                        ) {
                            map.removeLayer(layer);
                            console.info("COT Mafate retirée AVANT activation du mode édition");
                            alert("La couche COT Mafate a été retirée temporairement pour éviter les ralentissements pendant l'édition.");
                        }
                    });
                }, { capture: true }); // 👈 capture true = intercepter AVANT Leaflet-Geoman
            }
        }, 0);


        // Empêche l'édition pour les couches avec le filtre pmIgnore
        map.on('pm:globaleditmodetoggled', (e) => {
            
            map.eachLayer((layer) => {

                // Empêcher les couches protégées d'être éditables
                if (layer.pm && layer.pmIgnore) {
                    layer.pm.disable();
                }
            });


        });

        // Ajout couche
        map.on('layeradd', (e) => {
            const layer = e.layer;
            
            if (
                layer instanceof L.GeoJSON &&
                layer.options?.name === "COT Mafate" &&
                map.pm.globalEditEnabled()
            ) {
                map.removeLayer(layer);
                alert("Impossible d'ajouter la couche COT Mafate pendant l'édition.\nVeuillez désactiver le mode édition pour l'afficher.");
                console.warn("⛔ COT Mafate bloquée pendant édition");

                // Forcer le décochage visuel de la case COT Mafate
                const checkboxLabels = document.querySelectorAll('.leaflet-control-layers-overlays label');
                checkboxLabels.forEach(label => {
                    if (label.textContent.includes("COT Mafate")) {
                        const input = label.querySelector('input[type="checkbox"]');
                        if (input && input.checked) {
                            input.checked = false;
                        }
                    }
                });
                return; // on ne continue pas
            }

            // Si c'est un GeoJSON avec plusieurs couches
            if (layer.eachLayer) {
                layer.eachLayer(subLayer => {
                    if (subLayer?.options?._isBackgroundLayer) {
                        subLayer.pmIgnore = true;
                        if (subLayer.pm) {
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

    // Fond Coeur de Parc et Aire d'adhésion
    function addBackgroundLayers(map, fond, adhesion, mafate_cot) {
        const overlays = {};

        // Coeur de Parc
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
            // Affichage du fond par défaut
            fondLayer.bringToBack();
        }


        // Aire d'adhésion
        if (adhesion) {
            const adhesionLayer = L.geoJSON(adhesion, {
                style: {
                    color: "#388E3C",
                    weight: 1.5,
                    fillColor: "#A5D6A7",
                    fillOpacity: 0.6
                },
                // onEachFeature: (feature, layer) => {
                //     // const { Type = "N/A", Decret = "Non renseigné" } = feature.properties || {};
                //     // layer.bindPopup(`<strong>${Type}</strong><br/><small>${Decret}</small>`);
                //     layer.pmIgnore = true;
                // } 
            });

            adhesionLayer.eachLayer(l => {
                l.options._isBackgroundLayer = true;
                l.pmIgnore = true;
            });

            adhesionLayer.options._isBackgroundLayer = true;
            // Ajoute uniquement dans le panneau de calques, pas sur la carte
            overlays["Aire d’adhésion"] = adhesionLayer;
        }

        // COT Mafate
        if (mafate_cot) {
            const mafateLayer = L.geoJSON(mafate_cot, {
                style: {
                    color: "#1900ffff",
                    weight: 1.5,
                    fillColor: "#1848ceff",
                    fillOpacity: 0.7
                }
            });

            mafateLayer.options.name = "COT Mafate";

            mafateLayer.eachLayer(l => {
                l.options._isBackgroundLayer = true;
                l.pmIgnore = true;
            });

            mafateLayer.options._isBackgroundLayer = true;
            // Ajoute uniquement dans le panneau de calques, pas sur la carte
            overlays["COT Mafate"] = mafateLayer;
            // mafateLayer.addTo(map);
        }

        return overlays;
    }



    function addLayerControl(map, overlays) {
        // Menu de sélection des couches Coeur et Adhésion
        const control = L.control.layers(null, overlays, { collapsed: false, position: "topright" }).addTo(map);

        
        setTimeout(() => {

            // Titre du menu de sélection
            const container = document.querySelector('.leaflet-control-layers');
            if (container && !container.querySelector('.layer-title')) {
                const title = document.createElement('div');
                title.className = 'layer-title';
                title.innerText = "Couches disponibles";
                container.insertBefore(title, container.firstChild);
            }


            // Menu des fonds de carte
            const fondMenu = document.createElement("div");
            fondMenu.className = "fond-control";
            fondMenu.innerHTML = `
            <label class="fond-label">Fond de carte :</label>
            <select class="fond-select">
                <option value="osm">OSM</option>
                <option value="satellite">Satellite</option>
                <option value="topo">Topo</option>
            </select>
            `;
            container.appendChild(fondMenu);

            // Gestionnaires Leaflet
            const fonds = {
            satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Esri & NASA', maxZoom: 19
            }),
            osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap', maxZoom: 19
            }),
            topo: L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenTopoMap', maxZoom: 18
            })
            };

            let fondActif = fonds.osm.addTo(map);  // fond par défaut

            fondMenu.querySelector(".fond-select").addEventListener("change", (e) => {
                const nouveauFond = fonds[e.target.value];
                if (nouveauFond) {
                    map.removeLayer(fondActif);
                    fondActif = nouveauFond;
                    fondActif.addTo(map);
                }
            });
        }, 100);
    }


    // Construction de la couche 
    function renderExistingGeometry(map, geojson) {

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
        
        //Affichage
        layer.bringToFront();

        return layer;
    }


    function enableDrawing(map) {


        map.on('pm:create', e => {

            // Récupère la géométrie nouvellement dessinée.
            const layer = e.layer;
            
            // Ajout de la géométrie à la carte
            layer.addTo(map).bringToFront();

            const geojson = layer.toGeoJSON();

            // Désactive immédiatement l’outil actif après créaton de la géométrie
            map.pm.disableDraw();
        });
    }

})();



function setupValidationButton() {
    const cartes = document.querySelectorAll(".carte");

    // Clic sur le bouton "Valider la géométrie"
    document.getElementById('valider-geom')?.addEventListener('click', () => {
        const confirmMessage = "Souhaitez-vous vraiment valider et exporter la géométrie actuelle ?";
        if (!confirm(confirmMessage)) return;

        const geojsonInput = document.getElementById('geom-result');
        const allFeatures = [];

        cartes.forEach(div => {
            const map = div._leaflet_map;
            if (!map) return;
            
            // On récupère la géométrie saisie/modifiée (pas de filtre pmIgnore)
            const layers = map.pm.getGeomanLayers().filter(l => !l.pmIgnore);
            // console.log('Les couches avec pm ignore = False :')
            // console.log(layers)
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

        console.log("Geojson injecté :", geojsonStr.length > 200 ? geojsonStr.slice(0, 200) + "..." : geojsonStr);

        // Enregistrement du GeoJSON en base (view enregistrer_geom)
        document.getElementById("form-geom").submit();
    });
}



// Expose bien la fonction globalement
window.setupValidationButton = setupValidationButton;

