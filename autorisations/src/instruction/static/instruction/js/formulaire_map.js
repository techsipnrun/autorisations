// ****
// Script JS pour l'affichage carto dans le formulaire
// ***

document.addEventListener("DOMContentLoaded", () => {
    const fond_coeur_de_Parc = window._coeurData;
    const cartes = document.querySelectorAll(".carte");

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

        L.control.layers(null, overlayMaps, {
            collapsed: false,
            position: "topright"
        }).addTo(map);




        // Insérer fond de carte DANS le bon panneau Leaflet
        setTimeout(() => {
            const allPanels = div.closest(".carte-container")?.querySelectorAll(".leaflet-control-layers");
            let leafletContainer = null;

            allPanels?.forEach(p => {
                if (map.getContainer().contains(p)) {
                    leafletContainer = p;
                }
            });

            if (!leafletContainer) return;

            if (!leafletContainer.querySelector('.layer-title')) {
                const title = document.createElement('div');
                title.className = 'layer-title';
                title.innerText = "Couches disponibles";
                leafletContainer.insertBefore(title, leafletContainer.firstChild);
            }

            if (!leafletContainer.querySelector('.fond-control')) {
                const fondMenu = document.createElement("div");
                fondMenu.className = "fond-control";
                fondMenu.innerHTML = `
                    <label class="fond-label">Fond de carte :</label>
                    <select class="fond-select">
                        <option value="osm">OpenStreetMap</option>
                        <option value="satellite">Satellite</option>
                        <option value="opentopomap">OpenTopoMap</option>
                    </select>
                `;

                const overlaySection = leafletContainer.querySelector(".leaflet-control-layers-overlays");
                if (overlaySection) {
                    overlaySection.insertAdjacentElement("afterend", fondMenu);
                } else {
                    leafletContainer.appendChild(fondMenu);
                }

                fondMenu.querySelector(".fond-select").addEventListener("change", (e) => {
                    const valeur = e.target.value;
                    if (fonds[valeur]) {
                        map.removeLayer(fondActif);
                        fondActif = fonds[valeur];
                        fondActif.addTo(map);
                    }
                });
            }
        }, 100);



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






// Copier l'emplacement du Dossier
// function copierChemin(chemin) {
//     navigator.clipboard.writeText(chemin).then(() => {
//         alert("Chemin copié dans le presse-papiers :\n" + chemin);
//     }).catch(err => {
//         console.error("Erreur copie chemin :", err);
//         alert("Impossible de copier le chemin");
//     });
// }

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
