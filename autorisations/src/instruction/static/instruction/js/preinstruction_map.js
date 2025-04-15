document.addEventListener("DOMContentLoaded", () => {
    const fondDeCarte = window._fondDeCarteData;
    const cartes = document.querySelectorAll(".carte");

    if (cartes.length === 0) {
        console.warn("Aucune carte à afficher.");
        return;
    }

    cartes.forEach((div) => {
        let geojson = null;

        try {
            geojson = JSON.parse(div.dataset.geojson);
        } catch (e) {
            console.error("GeoJSON invalide :", div.dataset.geojson);
            return;
        }

        const map = L.map(div).setView([-21.1, 55.5], 10);

        // Fond OpenStreetMap
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap'
        }).addTo(map);

        // 1. Créer la couche du cœur de parc
        let fondLayer = null;
        if (fondDeCarte) {
            fondLayer = L.geoJSON(fondDeCarte, {
                style: feature => ({
                    color: "#3182bd",
                    weight: 2,
                    opacity: 1,
                    fillColor: "#6baed6",
                    fillOpacity: 0.4
                }),
                onEachFeature: (feature, layer) => {
                    if (feature.properties) {
                        let popupContent = "<strong>Informations :</strong><br>";
                        for (const [key, value] of Object.entries(feature.properties)) {
                            popupContent += `<strong>${key}</strong> : ${value}<br>`;
                        }
                        layer.bindPopup(popupContent);
                    }
                }
            });
            fondLayer.addTo(map);
        }

        // 2. Ajouter le contrôle de visibilité (checkbox)
        if (fondLayer) {
            const overlayMaps = {
                "Cœur du Parc National": fondLayer
            };
            L.control.layers(null, overlayMaps, {
                collapsed: false,
                position: "topright"
            }).addTo(map);
        }

        // 3. Ajouter une légende
        // const legend = L.control({ position: "bottomright" });
        // legend.onAdd = function (map) {
        //     const div = L.DomUtil.create("div", "legend");
        //     div.innerHTML += `
        //         <i style="background: #6baed6; border: 2px solid #3182bd; display:inline-block; width: 18px; height: 18px; margin-right: 8px;"></i>
        //         Cœur du Parc National
        //     `;
        //     return div;
        // };
        // legend.addTo(map);

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
        if (fondDeCarte && geojson) {
            try {
                const featuresFond = fondDeCarte.features;
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
        map.fitBounds(layer.getBounds());
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
