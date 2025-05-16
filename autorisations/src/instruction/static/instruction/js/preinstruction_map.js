document.addEventListener("DOMContentLoaded", () => {
    const fond_coeur_de_Parc = window._coeurData;
    const cartes = document.querySelectorAll(".carte");

    if (cartes.length === 0) {
        console.warn("Aucune carte à afficher.");
        return;
    }

    cartes.forEach((div) => {
        const data = div.dataset.geojson;

        if (!data || data.trim() === "") {
            console.warn("Pas de GeoJSON pour :", div);
            return; // on ignore cette carte
        }

        let geojson = null;
        try {
            geojson = JSON.parse(data);
        } catch (e) {
            console.error("GeoJSON invalide :", data);
            return;
        }

        const map = L.map(div).setView([-21.1, 55.5], 10);

        // Fond satellite ESRI
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; Esri & NASA',
            maxZoom: 19
        }).addTo(map);


        // Couches de fond : cœur + adhésion
        const overlayMaps = {};

        if (fond_coeur_de_Parc) {
            const fondLayer = L.geoJSON(fond_coeur_de_Parc, {
                style: {
                    color: "#3182bd",
                    weight: 2,
                    opacity: 1,
                    fillColor: "#6baed6",
                    fillOpacity: 0.3
                }
            });
            overlayMaps["Cœur du Parc National"] = fondLayer;
            fondLayer.addTo(map); // visible par défaut
        }

        if (window._adhesionData) {
            const adhesionLayer = L.geoJSON(window._adhesionData, {
                style: {
                    color: "#388E3C",
                    weight: 1.5,
                    fillColor: "#A5D6A7",
                    fillOpacity: 0.4
                }
            });
            overlayMaps["Aire d’adhésion"] = adhesionLayer;
            // adhesionLayer.addTo(map); // visible par défaut
        }

        L.control.layers(null, overlayMaps, {
            collapsed: false,
            position: "topright"
        }).addTo(map);


        // 4. Ajouter la géométrie du pétitionnaire
        const layer = L.geoJSON(geojson, {
            style: {
                color: "red",
                weight: 3,
                fillColor: "#f03",
                fillOpacity: 0.5
            },
            pointToLayer: (feature, latlng) => {
                return L.circleMarker(latlng, {
                    radius: 3,
                    color: "#800",
                    fillColor: "#d00",
                    fillOpacity: 1,
                    weight: 2
                });
            }
        }).addTo(map);

        // 6. Calcul d'intersection entre fond et géométrie pétitionnaire
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
                    L.popup()
                        .setLatLng(layer.getBounds().getCenter())
                        .setContent("Cette géométrie intersecte le cœur de parc.")
                        .openOn(map);
                }

            } catch (e) {
                console.error("Erreur d'intersection avec Turf.js :", e);
            }
        }


        // 5. Centrer sur la géométrie pétitionnaire
        map.fitBounds(layer.getBounds(), {
            maxZoom: 12,
            padding: [20, 20]  //espace autour de la géométrie
        });
    });
});


// Copier l'emplacement du Dossier
function copierChemin(chemin) {
    navigator.clipboard.writeText(chemin).then(() => {
        alert("Chemin copié dans le presse-papiers :\n" + chemin);
    }).catch(err => {
        console.error("Erreur copie chemin :", err);
        alert("Impossible de copier le chemin");
    });
}
