// ****
// Script JS pour l'affichage carto dans le formulaire
// ***

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


document.addEventListener("DOMContentLoaded", () => {
    const fond_coeur_de_Parc = window._coeurData;
    const cartes = document.querySelectorAll(".carte-container .carte");

    if (cartes.length === 0) {
        console.info("Aucune carte à afficher.");
        return;
    }

    cartes.forEach((div) => {
        console.info(`Nombre de cartes : ${cartes.length}`);
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
        const map = L.map(div).setView([-21.1, 55.5], 10);

        // Attacher l’instance Leaflet au <div> DOM (pour le téléchargement pdf)
        div._leaflet_map = map;

        // Ajout du bouton impression PDF
        L.control.browserPrint({
            title: "📥 Télécharger en PDF",
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
                maxZoom: 19
            }),
            opentopomap: L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenTopoMap',
                maxZoom: 18,
                tileSize: 256
            })

        };

        // Fond par défaut
        let fondActif = fonds.osm.addTo(map);


        // ---------------------------------
        // Couches de fond : cœur + adhésion + COT Mafate
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

        if (window._mafateData) {
            const mafateLayer = L.geoJSON(window._mafateData, {
                style: {
                    color: "#1900ffff",
                    weight: 1.5,
                    fillColor: "#1848ceff",
                    fillOpacity: 0.7
                }
            });
            overlayMaps["COT Mafate"] = mafateLayer;
            // mafateLayer.addTo(map); 
            mafateLayer.eachLayer(l => l.options._isBackgroundLayer = true);
        }
        // ---------------------------------
        // Menus "Fonds" et "Couches" (mini popovers en haut à droite)
        // ---------------------------------
        const baseLayers = {
            "OpenStreetMap": fonds.osm,
            "Satellite": fonds.satellite,
            "OpenTopoMap": fonds.opentopomap,
        };
        const overlays = overlayMaps;

        createMiniLayersControl(map, baseLayers, overlays).addTo(map);

        // -----------------------------------
        // Ajouter le geojson du pétitionnaire + pop up métadonnées 
        // -----------------------------------
        // --- Couches lignes / polygones (pas les points)
        const coucheTraces = L.geoJSON(geojson, {
            filter: (feature) => feature.geometry.type !== "Point",  // 👈 filtrer
            style: () => ({
                color: "red",
                weight: 3,
                fillColor: "#f03",
                fillOpacity: 0.5
            })
        }).addTo(map);

        // --- Couches points seulement
        const couchePoints = L.geoJSON(geojson, {
            filter: (feature) => feature.geometry.type === "Point",  // 👈 filtrer
            pointToLayer: (feature, latlng) => {
                const props = feature.properties;

                // Si c'est un point "Ravitaillement"
                if (props?.title?.toLowerCase().includes("ravitaillement")) {
                    const iconRavito = L.icon({
                        iconUrl: window._iconRavito ,
                        iconSize: [32, 32],
                        popupAnchor: [0, -16]
                    });
                    return L.marker(latlng, { icon: iconRavito });
                }
                // Si c'est un point "Ravitaillement"
                if (props?.title?.toLowerCase().includes("signaleur")) {
                    const iconSignaleur = L.icon({
                        iconUrl: window._iconSignaleur ,
                        iconSize: [32, 32], 
                        popupAnchor: [0, -16]
                    });
                    return L.marker(latlng, { icon: iconSignaleur });
                }

                return L.circleMarker(latlng, {
                    radius: 5,
                    fillColor: "#c27579ff",
                    color: "#ff000dff",
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

                    if (props.tooltip?.show) {
                        layer.bindTooltip(content, { permanent: false });
                    } else {
                        layer.bindPopup(content);
                    }
                }

                if (typeof layer.bringToFront === "function") {
                    layer.bringToFront();
                }

            }
        }).addTo(map);



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

                // POP UP Intersection
                if (intersecte) {
                    L.popup()
                        .setLatLng(coucheTraces.getBounds().getCenter())
                        .setContent("Cette géométrie intersecte le cœur de parc.")
                        .openOn(map);
                }

            } catch (e) {
                console.error("Erreur d'intersection avec Turf.js :", e);
            }
        }

        // --------------------------------------
        // Centrer sur la géométrie pétitionnaire
        // --------------------------------------
        map.fitBounds(coucheTraces.getBounds(), {
            maxZoom: 12,
            padding: [20, 20]
        });

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
