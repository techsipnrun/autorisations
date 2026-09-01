// ****
// Script JS pour l'affichage carto dans le formulaire
// ***


function decodeHtmlCode(htmlCode) {
  if (!htmlCode) return null;
  const span = document.createElement("span");
  span.innerHTML = htmlCode.endsWith(";") ? htmlCode : htmlCode + ";";
  return span.textContent;
}

const POI_MAP = (() => {
  const map = {};
  const results = window._poisData?.results || [];

  results.forEach(poi => {
    map[String(poi.id)] = {
      char: decodeHtmlCode(poi.html_code), // ex: "U", "B", "C"
      classes: poi.classes,                // ex: openscop-police-municipale
      i18n: poi.i18n,
      type: poi.type,
      categorie: poi.categorie?.title_i18n
    };
  });

  return map;
})();



document.addEventListener("DOMContentLoaded", () => {
    const fond_coeur_de_Parc = window._coeurData;
    const cartes = document.querySelectorAll(".carte-container-trail .carte");


    function poiDivIcon(char, extraClass = "") {
        return L.divIcon({
            className: "", // important : éviter le style par défaut leaflet-div-icon
            html: `
            <div class="poi-marker ${extraClass}">
                <span class="poi">${char}</span>
            </div>
            `,
            iconSize: [32, 32],
            iconAnchor: [16, 16],
            popupAnchor: [0, -16],
        });
    }

    function startEndDivIcon(letter, extraClass = "") {
        return L.divIcon({
            className: "",
            html: `<div class="or-poi ${extraClass}"><span class="or-poi-number">${letter}</span></div>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11],
            popupAnchor: [0, -11],
        });
    }


    cartes.forEach((div) => {

        const data = div.dataset.geojson;

        // ---------------------------------
        // Vérification de la présence et qualité du GeoJSON
        // ---------------------------------

        // Si GeoJSON non trouvé
        if (!data || data.trim() === "") {
            console.warn("Pas de GeoJSON pour :", div);
            return;
        }

        let geojson = null;
        try {
            const cleanedData = data.replace(/^\uFEFF/, '');
            geojson = JSON.parse(cleanedData);
        } catch (e) {
            console.error(data)
            console.error("GeoJSON invalide (erreur lors du parsing) : ", e);
            return;
        }

        // Si GeoJSON vide
        if (geojson && typeof geojson === 'object' && Object.keys(geojson).length === 0) {
            console.warn("Le GeoJSON est vide");
            return;
        }

        // Si GeoJSON mal formé
        else if (!geojson || (!geojson.type && !geojson.features)) {
            console.error("❌ Objet GeoJSON mal formé :", geojson);
            return;
        }


        // ---------------------------------
        // Initialisation de la carte Leaflet
        // ---------------------------------
        const defaultDisplayZoom = 11;
        const map = L.map(div).setView([-21.1, 55.5], defaultDisplayZoom);

        // Attacher l’instance Leaflet au <div> DOM (pour le téléchargement pdf)
        div._leaflet_map = map;

        // Ajout du bouton impression PDF
        L.control.browserPrint({
            title: "Télécharger en PDF",
            position: "topleft",  // coin haut gauche comme zoom
            closePopupsOnPrint: true,
            printModes: ["Landscape", "Portrait"] // propose les 2
        }).addTo(map);



        // Pour faire passer les fonds de carte derrière la géométrie du pétitionnaire
        map.on("layeradd", (e) => {
            const layer = e.layer;

            // Cas 1 : geojson avec sous-couches
            if (layer.eachLayer) {
                layer.eachLayer(sub => {
                    if (sub?.options?._isBackgroundLayer) {
                        sub.bringToBack();
                    }
                });
            }

            // Cas 2 : couche simple
            if (layer?.options?._isBackgroundLayer) {
                layer.bringToBack();
            }
        });


        // ---------------------------------
        // Menu de sélection du fond de carte
        // ---------------------------------

        // Liste des fonds disponibles
        const fonds = {
            satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Esri & NASA',
                maxZoom: 19
            }),
            osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap',
                maxZoom: 19,
                referrerPolicy: "strict-origin-when-cross-origin"
            }),
            opentopomap: L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenTopoMap',
                maxZoom: 18,
                tileSize: 256
            }),

            planign: L.tileLayer(
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
            )

        };

        // Fond par défaut
        let fondActif = fonds.planign.addTo(map);


        // ---------------------------------
        // Couches de fond : cœur + adhésion
        // ---------------------------------
        const overlayMaps = {};

        if (fond_coeur_de_Parc) {
            const fondLayer = L.geoJSON(fond_coeur_de_Parc, {
                style: { 
                    color: "#2E7D32", 
                    fillColor: "#4CAF50", 
                    weight: 2, 
                    fillOpacity: 0.4, 
                    opacity: 1
                },
            });
            overlayMaps["Cœur du Parc National"] = fondLayer;
            fondLayer.addTo(map); // visible par défaut

            fondLayer.eachLayer(l => l.options._isBackgroundLayer = true);
        }

        if (window._adhesionData) {
            const adhesionLayer = L.geoJSON(window._adhesionData, {
                style: {
                    color: "#388E3C",
                    weight: 2,
                    fillColor: "#A5D6A7",
                    fillOpacity: 0.6,
                    opacity: 1,
                },
            });
            overlayMaps["Aire d’adhésion"] = adhesionLayer;

            adhesionLayer.eachLayer(l => l.options._isBackgroundLayer = true);
        }

        if (window._secteursData) {
            const sectorColors = {
                sud: "#e63946",
                ouest: "#f59e0b",
                est: "#2563eb",
                nord: "#7c3aed"
            };
            const secteursLayer = L.geoJSON(window._secteursData, {
                style: feature => {
                    const color = sectorColors[feature.properties?.secteur?.toLowerCase()] || "#64748b";
                    return { color, fillColor: color, weight: 2, opacity: 0.9, fillOpacity: 0.22 };
                },
                onEachFeature: (feature, layer) => {
                    const secteur = feature.properties?.secteur;
                    if (secteur) {
                        layer.bindTooltip(`Secteur ${secteur.charAt(0).toUpperCase()}${secteur.slice(1).toLowerCase()}`, {
                            sticky: true,
                            direction: "top"
                        });
                    }
                    layer.options._isBackgroundLayer = true;
                }
            });
            overlayMaps["Secteurs"] = secteursLayer;
        }


        // ---------------------------
        // Nouveau menu moderne (2 boutons)
        // ---------------------------

        // Base layers (fonds de carte)
        const baseLayers = {
            "Plan IGN v2": fonds.planign,
            "OpenStreetMap": fonds.osm,
            "Satellite": fonds.satellite,
            "OpenTopoMap": fonds.opentopomap,
        };

        // Overlays (couches)
        const overlays = overlayMaps; // coeur/adhésion/mafate déjà dedans

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

        
        createMiniLayersControl(map, baseLayers, overlays).addTo(map);






        // L.control.layers(null, overlayMaps, {
        //     collapsed: false,
        //     position: "topright"
        // }).addTo(map);




        // Insérer fond de carte DANS le bon panneau Leaflet
        // setTimeout(() => {
        //     const allPanels = div.closest(".carte-container")?.querySelectorAll(".leaflet-control-layers");
        //     let leafletContainer = null;

        //     allPanels?.forEach(p => {
        //         if (map.getContainer().contains(p)) {
        //             leafletContainer = p;
        //         }
        //     });

        //     if (!leafletContainer) return;

        //     if (!leafletContainer.querySelector('.layer-title')) {
        //         const title = document.createElement('div');
        //         title.className = 'layer-title';
        //         title.innerText = "Couches disponibles";
        //         leafletContainer.insertBefore(title, leafletContainer.firstChild);
        //     }

        //     if (!leafletContainer.querySelector('.fond-control')) {
        //         const fondMenu = document.createElement("div");
        //         fondMenu.className = "fond-control";
        //         fondMenu.innerHTML = `
        //             <label class="fond-label">Fond de carte :</label>
        //             <select class="fond-select">
        //                 <option value="osm">OpenStreetMap</option>
        //                 <option value="satellite">Satellite</option>
        //                 <option value="opentopomap">OpenTopoMap</option>
        //             </select>
        //         `;

        //         const overlaySection = leafletContainer.querySelector(".leaflet-control-layers-overlays");
        //         if (overlaySection) {
        //             overlaySection.insertAdjacentElement("afterend", fondMenu);
        //         } else {
        //             leafletContainer.appendChild(fondMenu);
        //         }

        //         fondMenu.querySelector(".fond-select").addEventListener("change", (e) => {
        //             const valeur = e.target.value;
        //             if (fonds[valeur]) {
        //                 map.removeLayer(fondActif);
        //                 fondActif = fonds[valeur];
        //                 fondActif.addTo(map);
        //             }
        //         });
        //     }
        // }, 100);



        // -----------------------------------
        // Courses : menu à droite (hors Leaflet) + afficher/masquer par pk+name
        // -----------------------------------

        // 1) Regrouper les features par course, clé = "pk - name"
        const featuresByCourse = new Map();

        (geojson.features || []).forEach((f) => {
        const props = f?.properties || {};

        // D’après ton exemple : props.pk / props.name
        // (fallback si parfois c’est nommé autrement)
        const pk = props.pk ?? props.parcours_pk ?? props.parcours_id ?? null;
        const name = props.name ?? props.parcours_name ?? props.parcours ?? null;

        const key = (pk && name) ? `${name}` : (name ? String(name) : "Course");

        if (!featuresByCourse.has(key)) featuresByCourse.set(key, []);
        featuresByCourse.get(key).push(f);
        });

        // 2) Construire une couche Leaflet par course : traces + points dans un featureGroup
        const layersByCourse = new Map(); // key -> L.FeatureGroup

        function makePointsLayer(featureCollection) {
        return L.geoJSON(featureCollection, {
            filter: (feature) => feature.geometry?.type === "Point",
            pointToLayer: (feature, latlng) => {
            const props = feature.properties || {};
            const poiId = String(props?.icon?.id || "");
            const meta = POI_MAP[poiId];

            if (meta?.char) {
                return L.marker(latlng, { icon: poiDivIcon(meta.char) });
            }

            // ✅ Cas VTM / autres classes CSS
            if (meta?.classes) {
            return L.marker(latlng, {
                icon: L.divIcon({
                className: "",
                html: `<span class="${meta.classes}"></span>`,
                iconSize: [27, 27],
                iconAnchor: [13, 13],
                popupAnchor: [0, -13],
                })
            });
            }

            // fallback
            return L.circleMarker(latlng, {
                radius: 5,
                fillOpacity: 1,
                weight: 2
            });
            },
            onEachFeature: (feature, layer) => {
            const props = feature.properties;
            if (props) {
                let content = "";
                if (props.title) content += `<strong>${props.title}</strong><br>`;
                if (props.icon?.i18n) content += `Type : ${props.icon.i18n}<br>`;

                if (props.tooltip?.show) layer.bindTooltip(content, { permanent: false });
                else layer.bindPopup(content);
            }
            if (typeof layer.bringToFront === "function") layer.bringToFront();
            }
        });
        }

        function makeTracesLayer(featureCollection) {
        return L.geoJSON(featureCollection, {
            filter: (feature) => feature.geometry?.type !== "Point",
            style: () => ({
            weight: 3,
            fillOpacity: 0.5
            })
        });
        }

        for (const [courseKey, feats] of featuresByCourse.entries()) {
            const fc = { type: "FeatureCollection", features: feats };

            const traces = makeTracesLayer(fc);
            const points = makePointsLayer(fc);

            // On récupère uniquement les géométries linéaires (Départ et Arrivée)
            const lineFeatures = feats.filter(f =>
            f.geometry &&
            (f.geometry.type === "LineString" || f.geometry.type === "MultiLineString")
            );

            let startLatLng = null;
            let endLatLng = null;

            if (lineFeatures.length > 0) {
                const geom = lineFeatures[0].geometry;

                if (geom.type === "LineString") {
                    const coords = geom.coordinates;
                    startLatLng = [coords[0][1], coords[0][0]];
                    endLatLng   = [coords[coords.length - 1][1], coords[coords.length - 1][0]];
                }

                if (geom.type === "MultiLineString") {
                    const firstLine = geom.coordinates[0];
                    const lastLine  = geom.coordinates[geom.coordinates.length - 1];

                    startLatLng = [firstLine[0][1], firstLine[0][0]];
                    endLatLng   = [
                    lastLine[lastLine.length - 1][1],
                    lastLine[lastLine.length - 1][0]
                    ];
                }
            }

            const startEndMarkers = [];

            if (startLatLng) {
                startEndMarkers.push(
                    L.marker(startLatLng, {
                    icon: startEndDivIcon("D", "or-start"),
                    interactive: false
                    })
                );
                }

                if (endLatLng) {
                startEndMarkers.push(
                    L.marker(endLatLng, {
                    icon: startEndDivIcon("A", "or-end"),
                    interactive: false
                    })
                );
            }




            const group = L.featureGroup([
                traces,
                points,
                ...startEndMarkers
            ]);

            layersByCourse.set(courseKey, group);
        }

        // Groupe global de toutes les courses (pour fitBounds / centre)
        const allCoursesGroup = L.featureGroup(
        Array.from(layersByCourse.values())
        );


        // 3) Créer / récupérer le panneau à droite (dans .carte-container-trail)
        const carteContainer = div.closest(".carte-container-trail") || div.parentElement;
        let panel = carteContainer.querySelector(".course-panel");
        if (!panel) {
        panel = document.createElement("div");
        panel.className = "course-panel";
        carteContainer.appendChild(panel);
        }

        // 4) UI panneau
        panel.innerHTML = `
        <h2 id="titre_pannel_courses">Courses</h2>
        <div class="course-actions">
            <button type="button" class="btn-show-all">Tout afficher</button>
            <button type="button" class="btn-hide-all">Tout masquer</button>
        </div>
        <div class="course-list"></div>
        `;

        const list = panel.querySelector(".course-list");

        // (helper) fitBounds sur les courses visibles
        function fitToVisibleCourses() {
            const visibleGroups = [];
            layersByCourse.forEach((g) => { if (map.hasLayer(g)) visibleGroups.push(g); });

            if (visibleGroups.length === 0) return;

            const all = L.featureGroup(visibleGroups);
            const b = all.getBounds();
            if (b.isValid()) {
                map.fitBounds(b, { padding: [20, 20], maxZoom: 15 });
            }
        }

        // 5) Remplir la liste de checkboxes
        for (const [courseKey, group] of layersByCourse.entries()) {
        const id = `course_${Math.random().toString(16).slice(2)}`;

        const row = document.createElement("div");
        row.className = "course-item";
        row.innerHTML = `
            <input type="checkbox" id="${id}">
            <label for="${id}">${courseKey}</label>
        `;

        const checkbox = row.querySelector("input");

        checkbox.addEventListener("change", () => {
            if (checkbox.checked) group.addTo(map);
            else map.removeLayer(group);

            fitToVisibleCourses();
        });

        list.appendChild(row);
        }

        // 6) Boutons tout afficher/masquer
        panel.querySelector(".btn-show-all").addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            map.stop();

            panel.querySelectorAll("input[type='checkbox']").forEach((cb) => {
                cb.checked = true;
            });

            layersByCourse.forEach((group) => {
                if (!map.hasLayer(group)) group.addTo(map);
            });

            const allBounds = allCoursesGroup.getBounds();
            if (allBounds.isValid()) {
                map.fitBounds(allBounds, {
                    padding: [20, 20],
                    maxZoom: 15,
                    animate: false
                });
            }
        });

        panel.querySelector(".btn-hide-all").addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            map.stop();

            panel.querySelectorAll("input[type='checkbox']").forEach((cb) => {
                cb.checked = false;
            });

            layersByCourse.forEach((group) => {
                if (map.hasLayer(group)) map.removeLayer(group);
            });
        });


        

        // --- Couches lignes / polygones (pas les points)
        // const coucheTraces = L.geoJSON(geojson, {
        //     filter: (feature) => feature.geometry.type !== "Point",  // 👈 filtrer
        //     style: () => ({
        //         color: "red",
        //         weight: 3,
        //         fillColor: "#f03",
        //         fillOpacity: 0.5
        //     })
        // }).addTo(map);

        // --- Couches points seulement
        // const couchePoints = L.geoJSON(geojson, {
        //     filter: (feature) => feature.geometry.type === "Point",  // 👈 filtrer
        //     pointToLayer: (feature, latlng) => {
        //         const props = feature.properties || {};
        //         const poiId = String(props?.icon?.id || "");
        //         const meta = POI_MAP[poiId];

        //         // 1) POI "font" (html_code -> char)
        //         if (meta?.char) {
        //             return L.marker(latlng, { icon: poiDivIcon(meta.char) });
        //         }

        //         // 2) fallback (en attendant picto-vtm / classes)
        //         return L.circleMarker(latlng, {
        //             radius: 5,
        //             fillColor: "#c27579ff",
        //             color: "#ff000dff",
        //             fillOpacity: 1,
        //             weight: 2
        //         });
        //     },
        //     onEachFeature: (feature, layer) => {
        //         const props = feature.properties;
        //         if (props) {
        //             let content = "";
        //             if (props.title) content += `<strong>${props.title}</strong><br>`;
        //             if (props.icon?.i18n) content += `Type : ${props.icon.i18n}<br>`;

        //             if (props.tooltip?.show) {
        //                 layer.bindTooltip(content, { permanent: false });
        //             } else {
        //                 layer.bindPopup(content);
        //             }
        //         }

        //         if (typeof layer.bringToFront === "function") {
        //             layer.bringToFront();
        //         }

        //     }
        // }).addTo(map);



        // ------------------------------------------------------------------
        // Calcul d'intersection entre le coeur de Parc et la géométrie pétitionnaire
        // ------------------------------------------------------------------
        if (fond_coeur_de_Parc && geojson) {
            try {
                const featuresFond = fond_coeur_de_Parc.features;
                const petitionnaireFeatures = geojson.features || [geojson];

                let intersecte = false;

                petitionnaireFeatures.forEach(petFeature => {
                    featuresFond.forEach(fondFeature => {
                        if (
                            petFeature.geometry.type === "Point" &&
                            turf.booleanPointInPolygon(petFeature, fondFeature)
                        ) {
                            intersecte = true;
                        }
                        else if (
                            turf.booleanIntersects(petFeature, fondFeature) ||
                            turf.booleanWithin(petFeature, fondFeature)
                        ) {
                            intersecte = true;
                        }
                    });
                });

                console.log("Intersection avec le cœur de parc :", intersecte);

                if (intersecte) {
                    showCartoBannerTrail(div, "Cette manifestation intersecte le cœur de parc.");
                } else {
                    hideCartoBannerTrail(div);
                }

            } catch (e) {
                console.error("Erreur d'intersection avec Turf.js :", e);
            }
        }

        // --------------------------------------
        // Centrer sur la géométrie pétitionnaire
        // --------------------------------------
        map.fitBounds(allCoursesGroup.getBounds(), {
            maxZoom: 15, padding: [20, 20]
        });
        if (map.getZoom() < defaultDisplayZoom) {
            map.setZoom(defaultDisplayZoom);
        }


    });
});


function copierChemin(chemin) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(chemin)
            .then(() => alert("Chemin copié dans le presse-papiers :\n" + chemin))
            .catch(err => alert("Erreur de copie : " + err));
    } else {
        // Fallback : création d’un input caché
        const input = document.createElement("textarea");
        input.value = chemin;
        document.body.appendChild(input);
        input.select();
        try {
            document.execCommand("copy");
            alert("Chemin copié dans le presse-papiers :\n" + chemin);
        } catch (err) {
            alert("Impossible de copier le chemin : " + err);
        }
        document.body.removeChild(input);
    }
}


function showCartoBannerTrail(carteDiv, message) {
    const container = carteDiv.closest(".carte-container-trail");
    if (!container) return;

    const banner = container.previousElementSibling;

    if (!banner || !banner.classList.contains("carto-banner")) return;

    banner.textContent = message;
    banner.style.display = "inline-block";
}

function hideCartoBannerTrail(carteDiv) {
    const container = carteDiv.closest(".carte-container-trail");
    if (!container) return;

    const banner = container.previousElementSibling;

    if (!banner || !banner.classList.contains("carto-banner")) return;

    banner.textContent = "";
    banner.style.display = "none";
}
