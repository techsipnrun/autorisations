// ****
// Script JS pour l'affichage et l'édition de la carto (edit_carto.html)
// ***


(function main() {

    const PETITIONNAIRE_PATH_STYLE = AGIDACarto.style("edition");
    const PETITIONNAIRE_DEFAULT_ZOOM = 11;

    function createPetitionnairePointIcon() {
        return AGIDACarto.pointIcon("edition");
    }

    // ------------------------------------------------------------------------
    // Récupération des données
    // ------------------------------------------------------------------------
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
        const updatePointIconScale = () => {
            if (typeof map.getZoom() !== "number") return;
            const zoomDifference = Math.max(0, PETITIONNAIRE_DEFAULT_ZOOM - map.getZoom());
            const scale = Math.max(0.4, 1 - zoomDifference * 0.18);
            div.style.setProperty("--petitionnaire-point-scale", scale);
        };
        map.on("zoomend", updatePointIconScale);
        updatePointIconScale();


        // Ajout des fonds et overlays
        AGIDACarto.configurer(map, "edition");

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



        // --------------------------------------
        // Rendu de la géométrie du pétitionnaire
        // --------------------------------------
        const layer = geojson ? renderExistingGeometry(map, geojson) : null;

        if (layer && layer.getBounds().isValid() && AGIDACarto.config("edition").options.recentrage) {
            map.fitBounds(layer.getBounds(), {
                padding: [30, 30],  
                maxZoom: AGIDACarto.config("edition").options.zoom_cadrage
            });
        } else {
            map.setView(AGIDACarto.config("edition").options.centre, AGIDACarto.config("edition").options.zoom);
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
        const map = AGIDACarto.creerCarte(container, "edition");

        if (!map.pm) {
            console.error("❌ Leaflet-Geoman non initialisé");
        } else {
            console.log("✅ Leaflet-Geoman initialisé");
        }

        // Menu d'édition - Outils Geoman
        map.pm.addControls(AGIDACarto.controlesDessin("edition", {
            position: 'topleft',
            drawCircleMarker: false,
            drawPolyline: true,
            drawMarker: true,
            drawCircle: false,
            drawRectangle: true,
            drawPolygon: true,
            drawText: false,
            editMode: true,
            rotateMode: false,
            removalMode: true
        }));
        map.pm.setPathOptions(PETITIONNAIRE_PATH_STYLE);
        
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
    function renderExistingGeometry(map, geojson) {

        const layer = L.geoJSON(geojson, {
            style: PETITIONNAIRE_PATH_STYLE,
            pointToLayer: (feature, latlng) => L.marker(latlng, {
                icon: createPetitionnairePointIcon()
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

            if (layer instanceof L.Marker) {
                layer.setIcon(createPetitionnairePointIcon());
            } else if (typeof layer.setStyle === "function") {
                layer.setStyle(PETITIONNAIRE_PATH_STYLE);
            }
            
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

