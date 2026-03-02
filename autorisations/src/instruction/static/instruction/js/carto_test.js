// ****
// Script JS pour l'affichage et l'édition de la carto (edit_carto.html)
// ***


(function main() {

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
        const baseLayers = buildBaseLayers();
        // Fond de carte par défaut
        let activeBaseLayer = baseLayers.IGN.addTo(map);
        // Mini menus "Fonds" + "Couches"
        createMiniLayersControl(map, baseLayers, overlayMaps).addTo(map);



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
            drawText: false,
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


    // ---------------------------------
    // Fonds de carte (tiles)
    // ---------------------------------
    function buildBaseLayers() {
        return {
            "IGN" : L.tileLayer(
                "https://data.geopf.fr/wmts?" +
                    "service=WMTS&request=GetTile&version=1.0.0" +
                    "&layer=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2" +
                    "&style=normal" +
                    "&tilematrixset=PM" +
                    "&format=image/png" +
                    "&tilematrix={z}&tilerow={y}&tilecol={x}",
                {
                    maxZoom: 19,
                    tileSize: 256,
                    attribution: "© IGN - Géoplateforme",

                    // perf
                    updateWhenZooming: false,
                    updateWhenIdle: true,
                    keepBuffer: 2,
                }
            ),
            "OSM": L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap', maxZoom: 19
            }),
            "Satellite": L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Esri & NASA', maxZoom: 19
            }),
            "Topo": L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenTopoMap', maxZoom: 18
            }),
        };
    }


    // ------------------------------------------------------------------------
    // Mini menus : Fonds + Couches (remplace leaflet-control-layers)
    // ------------------------------------------------------------------------
    function createMiniLayersControl(map, baseLayers, overlays) {
            function svgIcon(type) {
                if (type === "base") {
                    return `
                        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-layers2-icon lucide-layers-2">
                            <path d="M13 13.74a2 2 0 0 1-2 0L2.5 8.87a1 1 0 0 1 0-1.74L11 2.26a2 2 0 0 1 2 0l8.5 4.87a1 1 0 0 1 0 1.74z"/>
                            <path d="m20 14.285 1.5.845a1 1 0 0 1 0 1.74L13 21.74a2 2 0 0 1-2 0l-8.5-4.87a1 1 0 0 1 0-1.74l1.5-.845"/>
                        </svg>`;
                }
                return `
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-layers-plus-icon lucide-layers-plus">
                    <path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 .83.18 2 2 0 0 0 .83-.18l8.58-3.9a1 1 0 0 0 0-1.831z"/><path d="M16 17h6"/><path d="M19 14v6"/><path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 .825.178"/>
                    <path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l2.116-.962"/>
                </svg>`;
            }

            function closeAllPopovers() {
                document.querySelectorAll(".or-popover").forEach(p => p.remove());
            }

            // Ferme les popovers si la fenêtre est redimensionnée
            window.addEventListener("resize", () => {
            closeAllPopovers();
            });


            function makePopover(title, rowsHtml, anchorEl) {
                closeAllPopovers();

                const pop = document.createElement("div");
                pop.className = "or-popover";
                pop.innerHTML = `<h4>${title}</h4>${rowsHtml}`;

                // Empêche Leaflet de capter les interactions quand on est dans le menu
                L.DomEvent.disableClickPropagation(pop);
                L.DomEvent.disableScrollPropagation(pop);

                // // Et pour être sûr sur le drag (mouse/touch)
                ["mousedown","mousemove","mouseup","touchstart","touchmove","touchend","wheel","dblclick","contextmenu"]
                .forEach(evt => pop.addEventListener(evt, (e) => e.stopPropagation(), { passive: false }));


                const anchorRect = anchorEl.getBoundingClientRect();
                const mapRect = map.getContainer().getBoundingClientRect();
                
                // Ajoute d'abord au DOM pour mesurer sa vraie taille
                map.getContainer().appendChild(pop);

                const gap = 10;

                // Mesure réelle (plus fiable que popWidth/popHeight “approx”)
                const popRect = pop.getBoundingClientRect();
                const popW = popRect.width;
                const popH = popRect.height;

                // Position préférée : à GAUCHE du bouton (donc jamais dessus)
                let left = (anchorRect.left - mapRect.left) - popW - gap;
                // Aligné en haut du bouton (ton bord haut est déjà OK)
                let top = (anchorRect.top - mapRect.top);

                // Si pas assez de place à gauche, on ouvre à droite du bouton
                if (left < gap) {
                left = (anchorRect.right - mapRect.left) + gap;
                }

                // Clamp dans la carte
                left = Math.max(gap, Math.min(left, mapRect.width - popW - gap));
                top  = Math.max(gap, Math.min(top,  mapRect.height - popH - gap));

                pop.style.left = `${left}px`;
                pop.style.top  = `${top}px`;

                setTimeout(() => {
                function onDocClick(e) {
                    if (!pop.contains(e.target) && !anchorEl.contains(e.target)) {
                    pop.remove();
                    document.removeEventListener("mousedown", onDocClick);
                    }
                }
                document.addEventListener("mousedown", onDocClick);
                }, 0);

                return pop;
            }

            function makeRowsClickable(pop) {
                pop.querySelectorAll(".or-row").forEach((row) => {
                    row.addEventListener("click", (e) => {

                    // Si clic direct sur INPUT ou LABEL : on laisse le comportement natif
                    if (e.target.closest("input") || e.target.closest("label")) return;


                    const input = row.querySelector("input");
                    if (!input) return;

                    if (input.type === "checkbox") {
                        input.checked = !input.checked;
                    } else if (input.type === "radio") {
                        input.checked = true;
                    }

                    // Déclenche ton code existant (addTo / removeLayer)
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                    });
                });
            }


            const Mini = L.Control.extend({
                options: { position: "topright" },
                onAdd: function () {
                const container = L.DomUtil.create("div", "leaflet-control or-mini");
                const stack = L.DomUtil.create("div", "or-stack", container);

                const btnBase = L.DomUtil.create("div", "or-btn", stack);
                btnBase.innerHTML = svgIcon("base");
                btnBase.title = "Fonds de carte";

                const btnOver = L.DomUtil.create("div", "or-btn", stack);
                btnOver.innerHTML = svgIcon("overlays");
                btnOver.title = "Couches";

                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.disableScrollPropagation(container);

                btnBase.addEventListener("click", () => {

                    const entries = Object.entries(baseLayers);

                    const rows = entries.map(([name, layer], idx) => {
                    const id = `base_${idx}_${Math.random().toString(16).slice(2)}`;
                    const checked = map.hasLayer(layer) ? "checked" : "";
                    return `
                        <div class="or-row">
                        <input type="radio" name="or-base" id="${id}" ${checked}>
                        <label for="${id}">${name}</label>
                        </div>
                    `;
                    }).join("");

                    const pop = makePopover("Fonds de carte", rows, btnBase);
                    makeRowsClickable(pop);


                    entries.forEach(([name, layer], idx) => {
                    const input = pop.querySelectorAll("input[type='radio']")[idx];
                    input.addEventListener("change", () => {
                        Object.values(baseLayers).forEach(l => map.removeLayer(l));
                        layer.addTo(map);
                    });
                    });
                });

                btnOver.addEventListener("click", () => {
                    const entries = Object.entries(overlays);

                    const rows = entries.length
                    ? entries.map(([name, layer], idx) => {
                        const id = `ov_${idx}_${Math.random().toString(16).slice(2)}`;
                        const checked = map.hasLayer(layer) ? "checked" : "";
                        return `
                            <div class="or-row">
                            <input type="checkbox" id="${id}" ${checked}>
                            <label for="${id}">${name}</label>
                            </div>
                        `;
                        }).join("")
                    : `<div class="or-muted">Aucune couche.</div>`;

                    const pop = makePopover("Couches", rows, btnOver);
                    makeRowsClickable(pop);


                    entries.forEach(([name, layer], idx) => {
                    const input = pop.querySelectorAll("input[type='checkbox']")[idx];
                    input.addEventListener("change", () => {
                        if (input.checked) layer.addTo(map);
                        else map.removeLayer(layer);
                    });
                    });
                });

                return container;
                }
            });

            return new Mini();
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

