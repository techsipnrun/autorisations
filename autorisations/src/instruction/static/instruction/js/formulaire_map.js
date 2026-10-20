// ****
// Script JS pour l'affichage carto dans le formulaire
// ***

document.addEventListener("DOMContentLoaded", () => {
    const fond_coeur_de_Parc = window._coeurData;
    const cartes = document.querySelectorAll(".carte-container .carte");

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
        const contexteCarte = AGIDACarto.code("dn");
        const map = AGIDACarto.creerCarte(div, contexteCarte);

        const updatePointIconScale = () => {
            const zoomDifference = Math.max(0, defaultDisplayZoom - map.getZoom());
            const scale = Math.max(0.4, 1 - zoomDifference * 0.18);
            div.style.setProperty("--petitionnaire-point-scale", scale);
        };
        map.on("zoomend", updatePointIconScale);
        updatePointIconScale();
        

        // Attacher l’instance Leaflet au <div> DOM (pour le téléchargement pdf)
        div._leaflet_map = map;

        AGIDACarto.configurer(map, contexteCarte);

        const isPointGeometry = (feature) =>
            ["Point", "MultiPoint"].includes(feature.geometry.type);

        const coucheTraces = L.geoJSON(geojson, {
            filter: (feature) => !isPointGeometry(feature),
            style: () => AGIDACarto.style(contexteCarte)
        }).addTo(map);

        // --- Couches points seulement
        const couchePoints = L.geoJSON(geojson, {
            filter: isPointGeometry,
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

                const iconPoint = AGIDACarto.pointIcon(contexteCarte);
                return L.marker(latlng, { icon: iconPoint });
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
                    showCartoBanner(div, "Cette géométrie intersecte le cœur de parc.");
                } else {
                    hideCartoBanner(div);
                }

            } catch (e) {
                console.error("Erreur d'intersection avec Turf.js :", e);
            }
        }

        // --------------------------------------
        // Centrer sur la géométrie pétitionnaire
        // --------------------------------------
        // map.fitBounds(coucheTraces.getBounds(), {
        //     maxZoom: 12,
        //     padding: [20, 20]
        // });
        const groupeGlobal = L.featureGroup([coucheTraces, couchePoints]);
        const bounds = groupeGlobal.getBounds();

        if (bounds.isValid() && AGIDACarto.config(contexteCarte).options.recentrage) {
            const optionsCarto = AGIDACarto.config(contexteCarte).options;
            // Leaflet peut animer fitBounds : attendre moveend avant de
            // garantir le zoom minimal, sinon l'animation le remplace.
            map.once("moveend", () => {
                if (map.getZoom() < optionsCarto.zoom) map.setZoom(optionsCarto.zoom);
            });
            map.fitBounds(bounds, {
                maxZoom: optionsCarto.zoom_cadrage,
                padding: [20, 20]
            });
        } else {
            map.setView(AGIDACarto.config(contexteCarte).options.centre, AGIDACarto.config(contexteCarte).options.zoom);
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



function showCartoBanner(carteDiv, message) {
    const container = carteDiv.closest(".carte-container");
    if (!container) return;

    const banner = container.previousElementSibling;

    if (!banner || !banner.classList.contains("carto-banner")) return;

    banner.textContent = message;
    banner.style.display = "inline-block";
}

function hideCartoBanner(carteDiv) {
    const container = carteDiv.closest(".carte-container");
    if (!container) return;

    const banner = container.previousElementSibling;

    if (!banner || !banner.classList.contains("carto-banner")) return;

    banner.textContent = "";
    banner.style.display = "none";
}
