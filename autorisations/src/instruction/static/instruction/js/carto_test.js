// ****
// Script JS pour l'affichage et l'édition de la carto (edit_carto.html)
// ***


(function main() {

    console.log("✅ Début Script carto_test.js");
    
    // ------------------------------------------------------------------------
    // Récupération des données
    // ------------------------------------------------------------------------
    const fondData = window._fondDeCarteData;
    const adhesionData = window._adhesionData;
    const mafateData = window._mafateData;
    const cartes = document.querySelectorAll(".carte");

    if (!cartes.length) {
        console.warn("Aucune carte détectée.");
        return;
    }


    // ------------------------------------------------------------------------
    // On initialise une carte pour chaque div.carte
    // ------------------------------------------------------------------------
    cartes.forEach((div) => {


        // Parsing du GeoJSON pétitionnaire
        const geojson = parseGeoJSON(div.dataset.geojson);

        // Mesure du poids du GeoJSON (KB)
        let geoSizeKB = 0;
        if (div.dataset.geojson) {
            geoSizeKB = (div.dataset.geojson.length / 1024).toFixed(2);
            console.log("📦 Taille GeoJSON pétitionnaire :", geoSizeKB, "KB");
        }


        // Initialisation de notre map
        const map = initializeMap(div);


        // Ajout des fonds et overlays
        const overlayMaps = addBackgroundLayers(map, fondData, adhesionData, mafateData);
        addLayerControl(map, overlayMaps);



        // Blocage des modes d’édition si GeoJSON > 100 KB
        setTimeout(() => {
            if (geoSizeKB <= 100) return; // OK, rien à bloquer

            console.warn("⛔ Géométrie trop lourde, blocage des modes d'édition");

            const buttons = [
                ".leaflet-pm-icon-edit",   // Edit
                // ".leaflet-pm-icon-drag",   // Drag
                // ".leaflet-pm-icon-cut",    // Cut
                // ".leaflet-pm-icon-delete"  // Remove
            ];

            buttons.forEach(selector => {
                const btn = document.querySelector(selector);
                if (!btn) return;

                btn.addEventListener("click", (e) => {

                    // Empêche Geoman de recevoir l’événement
                    e.stopImmediatePropagation();
                    e.preventDefault();

                    alert("⚠️ La géométrie du pétitionnaire est trop volumineuse (> 100 KB).\nImpossible d'activer les outils d’édition.");

                }, true); // CAPTURE=TRUE => intercepte AVANT Geoman
            });

        }, 50);



        // On désactive les boutons d'édition en cours si on dé(coche) des fonds de carte
        setTimeout(() => {
            const layerControl = div.querySelector(".leaflet-control-layers");
            if (!layerControl) return;

            layerControl.addEventListener("click", (e) => {

                // Ferme les modes immédiatement
                map.pm.disableGlobalEditMode();
                map.pm.disableGlobalDragMode();
                map.pm.disableGlobalRemovalMode();
                map.pm.disableGlobalCutMode();

            }, true); // <-- CAPTURE TRUE
        }, 0);



        // --------------------------------------
        // Rendu de la géométrie du pétitionnaire
        // --------------------------------------
        const layer = geojson ? renderExistingGeometry(map, geojson) : null;

        if (layer && layer.getBounds().isValid()) {
            map.fitBounds(layer.getBounds(), {
                padding: [30, 30],  
                maxZoom: 18     
            });
        } else {
            map.setView([-21.135, 55.526], 11);
        }

        // Activation des outils de dessin
        enableDrawing(map);
    });



    // ---------------------------------//
    //       Fonctions utilitaires      //
    // ---------------------------------//

    // Parse JSON sécurisé
    function parseGeoJSON(raw) {
        if (!raw) return null;
        try {
            return JSON.parse(raw);
        } catch {
            console.error("GeoJSON invalide :", raw);
            return null;
        }
    }

    // Initialisation carte
    function initializeMap(container) {
        const map = L.map(container);

        if (!map.pm) {
            console.error("❌ Leaflet-Geoman non initialisé");
        } else {
            console.log("✅ Leaflet-Geoman initialisé");
        }

        // Bouton impression PDF
        L.control.browserPrint({
            title: "📥 Télécharger en PDF",
            position: "topleft",  // coin haut gauche comme zoom
            closePopupsOnPrint: true,
            printModes: ["Landscape", "Portrait"] // propose les 2
        }).addTo(map);

        // Menu d'édition - Outils Geoman
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
        
        // Log Geoman events (debug)
        [
            'pm:globaleditmodetoggled',
            'pm:edit',
            'pm:remove',
            'pm:drawstart',
            'pm:drawend',
            'pm:create',
            'pm:globaldragmodetoggled',
            'pm:globalremovalmodetoggled'
        ].forEach(evt => {
            map.on(evt, (e) => {
                console.log(`📣 Evénement: ${evt}`, e);
            });
        });

        
        

        // On retire les fonds de carte trop lourds avant l'édition.
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




        // ----------------------------------------------------//
        //       Bloquer l'édition sur les fonds de carte      //
        // ----------------------------------------------------//

        // Empêche l'édition pour les couches avec le filtre pmIgnore
        map.on('pm:globaleditmodetoggled', (e) => {
            map.eachLayer((layer) => {
                // Empêcher les couches protégées d'être éditables
                if (layer.pm && layer.pmIgnore) {
                    layer.pm.disable();
                }
            });
        });

        // Empêcher tout DRAG sur les couches protégées
        map.on('pm:globaldragmodetoggled', () => {
            map.eachLayer(layer => {
                if (layer.pmIgnore && layer.pm && layer.pm.disableLayerDrag) {
                    layer.pm.disableLayerDrag();
                }
            });
        });

        // Empêcher toute SUPPRESSION sur les couches protégées
        map.on('pm:remove', e => {
            if (e.layer && e.layer.pmIgnore) {
                console.warn("Remove interdit sur couche protégée");
                // réinjecte la couche dans la map
                map.addLayer(e.layer);
            }
        });

        // Empêcher toute COUPE sur les couches protégées
        map.on('pm:cut', e => {
            if (e.layer && e.layer.pmIgnore) {
                console.warn("Cut interdit sur couche protégée");

                // restaure la couche originale
                if (e.originalLayer) {
                    map.addLayer(e.originalLayer);
                }

                // retire la couche coupée
                map.removeLayer(e.layer);
            }
        });




        // -------------------------------------
        // Ajout d'une couche sur la carte
        // -------------------------------------
        map.on('layeradd', (e) => {
            const layer = e.layer;
            
            // if (
            //     layer instanceof L.GeoJSON &&
            //     layer.options?.name === "COT Mafate" &&
            //     map.pm.globalEditEnabled()
            // ) {
            //     map.removeLayer(layer);
            //     alert("Impossible d'ajouter la couche COT Mafate pendant l'édition.\nVeuillez désactiver le mode édition pour l'afficher.");
            //     console.warn("⛔ COT Mafate bloquée pendant édition");

            //     // Forcer le décochage visuel de la case COT Mafate
            //     const checkboxLabels = document.querySelectorAll('.leaflet-control-layers-overlays label');
            //     checkboxLabels.forEach(label => {
            //         if (label.textContent.includes("COT Mafate")) {
            //             const input = label.querySelector('input[type="checkbox"]');
            //             if (input && input.checked) {
            //                 input.checked = false;
            //             }
            //         }
            //     });
            //     return; // on ne continue pas
            // }

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
    



    // ---------------------------------
    // Paramétrage des Fonds de carte
    // ---------------------------------
    function addBackgroundLayers(map, fond, adhesion, mafate_cot) {
        const overlays = {};

        // Coeur de Parc
        if (fond) {
            const fondLayer = L.geoJSON(fond, {
                style: { 
                    color: "#2E7D32", 
                    fillColor: "#4CAF50", 
                    weight: 2, 
                    fillOpacity: 0.4, 
                    opacity: 1
                },
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
            fondLayer.pmIgnore = true;
        }


        // Aire d'adhésion
        if (adhesion) {
            const adhesionLayer = L.geoJSON(adhesion, {
                style: {
                    color: "#388E3C",
                    weight: 2,
                    fillColor: "#A5D6A7",
                    fillOpacity: 0.6,
                    opacity: 1,
                },
            });

            adhesionLayer.eachLayer(l => {
                l.options._isBackgroundLayer = true;
                l.pmIgnore = true;
            });

            adhesionLayer.options._isBackgroundLayer = true;
            adhesionLayer.pmIgnore = true;
            // Ajoute uniquement dans le panneau de calques, pas sur la carte
            overlays["Aire d’adhésion"] = adhesionLayer;
        }

        // COT Mafate
        if (mafate_cot) {
            const mafateLayer = L.geoJSON(mafate_cot, {
                style: {
                    color: "#2614c5ff",
                    weight: 1.5,
                    fillColor: "#4b6abeff",
                    fillOpacity: 0.6,
                    opacity: 1,
                }
            });

            mafateLayer.options.name = "COT Mafate";

            mafateLayer.eachLayer(l => {
                l.options._isBackgroundLayer = true;
                l.pmIgnore = true;
            });

            mafateLayer.options._isBackgroundLayer = true;
            mafateLayer.pmIgnore = true;
            // Ajoute uniquement dans le panneau de calques, pas sur la carte
            overlays["COT Mafate"] = mafateLayer;
        }

        return overlays;
    }




    // ------------------------------------------------------------------------
    // Ajout du panneau de couches
    // ------------------------------------------------------------------------
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



    // Paramétrage Géométrie du pétitionnaire
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




    // -----------------------------------
    // Nouveau Dessin Geoman
    // -----------------------------------
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




// ========================================
//  VALIDATION GEOJSON
// ========================================
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

