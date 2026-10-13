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
        const contexteCarte = AGIDACarto.code("dm");
        const map = AGIDACarto.creerCarte(div, contexteCarte);

        // Attacher l’instance Leaflet au <div> DOM (pour le téléchargement pdf)
        div._leaflet_map = map;

        AGIDACarto.configurer(map, contexteCarte);

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
                ...AGIDACarto.style(contexteCarte),
                radius: AGIDACarto.style(contexteCarte).radius,
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
            style: () => AGIDACarto.style(contexteCarte)
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
            if (b.isValid() && AGIDACarto.config(contexteCarte).options.recentrage) {
                map.fitBounds(b, { padding: [20, 20], maxZoom: AGIDACarto.config(contexteCarte).options.zoom_cadrage });
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
            if (allBounds.isValid() && AGIDACarto.config(contexteCarte).options.recentrage) {
                map.fitBounds(allBounds, {
                    padding: [20, 20],
                    maxZoom: AGIDACarto.config(contexteCarte).options.zoom_cadrage,
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
        if (AGIDACarto.config(contexteCarte).options.recentrage && allCoursesGroup.getBounds().isValid()) {
            map.fitBounds(allCoursesGroup.getBounds(), {maxZoom: AGIDACarto.config(contexteCarte).options.zoom_cadrage, padding: [20, 20]});
            if (map.getZoom() < Math.min(defaultDisplayZoom, AGIDACarto.config(contexteCarte).options.zoom_cadrage)) {
                map.setZoom(Math.min(defaultDisplayZoom, AGIDACarto.config(contexteCarte).options.zoom_cadrage));
            }
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
