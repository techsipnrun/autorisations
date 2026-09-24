(() => {
    const navigation = window.performance?.getEntriesByType?.("navigation")?.[0];
    if (navigation?.type === "reload" && window.location.search) {
        window.location.replace(window.location.pathname);
        return;
    }

    const panneau = document.getElementById("requete-carte-panel");
    const boutonAfficher = document.getElementById("btn-filtrer-carte");
    const boutonMasquer = document.getElementById("requete-carte-masquer");
    const boutonEffacer = document.getElementById("requete-carte-effacer");
    const formulaire = document.getElementById("recherche-form");
    if (!panneau || !boutonAfficher || !formulaire || typeof L === "undefined") return;

    const champActif = document.getElementById("carte-active");
    const champGeojson = document.getElementById("carte-geojson");
    const statut = document.getElementById("requete-carte-statut");
    const casesSecteurs = [...panneau.querySelectorAll('input[name="carte_secteurs"]')];
    const casesPerimetres = [...panneau.querySelectorAll('input[name="carte_perimetres"]')];
    const tailleMaxGeojson = 6000;
    const couleursSecteurs = {sud: "#e63946", ouest: "#f59e0b", est: "#2563eb", nord: "#7c3aed"};
    let carte = null;
    let dessins = null;
    let donneesCarto = null;
    let couchesFiltre = [];
    let fermerPopoverAuClicExterieur = null;

    function ajusterHauteurCarte() {
        if (!carte || panneau.hidden) return;
        const conteneur = carte.getContainer();
        const hauteurFenetre = window.visualViewport?.height || window.innerHeight;
        const hauteurNavbar = document.querySelector(".navigation_header")?.getBoundingClientRect().height || 80;
        const hauteurDisponible = Math.max(1, Math.floor(hauteurFenetre - hauteurNavbar - 32));
        const hauteurDossier = Math.floor(hauteurFenetre * .6);
        conteneur.style.setProperty("--requete-carte-hauteur", `${Math.min(hauteurDossier, hauteurDisponible)}px`);
        carte.invalidateSize({pan: false});
    }

    function fondDeCartes() {
        return {
            "IGN": L.tileLayer(
                "https://data.geopf.fr/wmts?service=WMTS&request=GetTile&version=1.0.0" +
                "&layer=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&style=normal&tilematrixset=PM" +
                "&format=image/png&tilematrix={z}&tilerow={y}&tilecol={x}",
                {maxZoom: 19, tileSize: 256, attribution: "© IGN - Géoplateforme", updateWhenZooming: false, updateWhenIdle: true, keepBuffer: 2}
            ),
            "OpenStreetMap": L.tileLayer(
                "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                {
                    maxZoom: 19,
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                    referrerPolicy: "strict-origin-when-cross-origin",
                    updateWhenZooming: false,
                    updateWhenIdle: true,
                    keepBuffer: 2,
                }
            ),
            "Satellite": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {maxZoom: 19, attribution: "Esri & NASA"}),
            "Topo": L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {maxZoom: 18, attribution: "© OpenTopoMap"}),
        };
    }

    function rendreNonEditable(couche) {
        couche.options._isBackgroundLayer = true;
        couche.options.pmIgnore = true;
        couche.pmIgnore = true;
        if (couche.eachLayer) couche.eachLayer(rendreNonEditable);
        return couche;
    }

    function couchesDisponibles(donnees) {
        return {
            "Cœur du Parc national": rendreNonEditable(L.geoJSON(donnees.coeur, {interactive: false, style: {color: "#2E7D32", fillColor: "#4CAF50", weight: 2, fillOpacity: .4, opacity: 1}})),
            "Aire d’adhésion": rendreNonEditable(L.geoJSON(donnees.adhesion, {interactive: false, style: {color: "#388E3C", fillColor: "#81C784", weight: 2, fillOpacity: .78, opacity: 1}})),
            "Secteurs": rendreNonEditable(L.geoJSON(donnees.secteurs, {
                interactive: false,
                style: (feature) => {
                    const couleur = couleursSecteurs[String(feature.properties?.secteur || "").toLowerCase()] || "#64748b";
                    return {color: couleur, fillColor: couleur, weight: 2, opacity: .9, fillOpacity: .22};
                },
            })),
        };
    }

    function iconeMini(type) {
        if (type === "base") return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 13.74a2 2 0 0 1-2 0L2.5 8.87a1 1 0 0 1 0-1.74L11 2.26a2 2 0 0 1 2 0l8.5 4.87a1 1 0 0 1 0 1.74z"/><path d="m20 14.285 1.5.845a1 1 0 0 1 0 1.74L13 21.74a2 2 0 0 1-2 0l-8.5-4.87a1 1 0 0 1 0-1.74l1.5-.845"/></svg>`;
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.831z"/><path d="M16 17h6M19 14v6M2 12a1 1 0 0 0 .58.91l8.6 3.91M2 17a1 1 0 0 0 .58.91l8.6 3.91"/></svg>`;
    }

    function ajouterControleCouches(baseLayers, overlays) {
        const fermerMenus = () => {
            carte.getContainer().querySelectorAll(".or-popover").forEach((element) => element.remove());
            if (fermerPopoverAuClicExterieur) {
                document.removeEventListener("mousedown", fermerPopoverAuClicExterieur);
                fermerPopoverAuClicExterieur = null;
            }
        };
        function ouvrirMenu(titre, entrees, type, ancre) {
            fermerMenus();
            const menu = document.createElement("div");
            menu.className = "or-popover requete-carte-popover";
            menu.innerHTML = `<h4>${titre}</h4>`;
            entrees.forEach(([nom, couche], index) => {
                const ligne = document.createElement("div");
                ligne.className = "or-row";
                const input = document.createElement("input");
                input.type = type;
                input.name = type === "radio" ? "requete-fond-carte" : `requete-couche-${index}`;
                input.id = `${input.name}-${Math.random().toString(16).slice(2)}`;
                input.checked = carte.hasLayer(couche);
                const label = document.createElement("label");
                label.htmlFor = input.id;
                label.textContent = nom;
                ligne.append(input, label);
                ligne.addEventListener("click", (event) => { if (event.target !== input && event.target !== label) input.click(); });
                input.addEventListener("change", () => {
                    if (type === "radio") {
                        Object.values(baseLayers).forEach((fond) => carte.removeLayer(fond));
                        couche.addTo(carte);
                    } else if (input.checked) couche.addTo(carte).bringToBack();
                    else carte.removeLayer(couche);
                });
                menu.appendChild(ligne);
            });
            L.DomEvent.disableClickPropagation(menu);
            L.DomEvent.disableScrollPropagation(menu);
            carte.getContainer().appendChild(menu);
            const rectAncre = ancre.getBoundingClientRect();
            const rectCarte = carte.getContainer().getBoundingClientRect();
            menu.style.top = `${Math.max(10, rectAncre.top - rectCarte.top)}px`;
            menu.style.right = `${rectCarte.right - rectAncre.left + 8}px`;
            setTimeout(() => {
                fermerPopoverAuClicExterieur = (event) => {
                    if (!menu.contains(event.target) && !ancre.contains(event.target)) fermerMenus();
                };
                document.addEventListener("mousedown", fermerPopoverAuClicExterieur);
            }, 0);
        }
        const Mini = L.Control.extend({
            options: {position: "topright"},
            onAdd() {
                const conteneur = L.DomUtil.create("div", "leaflet-control or-mini");
                const pile = L.DomUtil.create("div", "or-stack", conteneur);
                const boutonFonds = L.DomUtil.create("div", "or-btn", pile);
                boutonFonds.innerHTML = iconeMini("base");
                boutonFonds.title = "Fonds de carte";
                const boutonCouches = L.DomUtil.create("div", "or-btn", pile);
                boutonCouches.innerHTML = iconeMini("overlay");
                boutonCouches.title = "Couches";
                L.DomEvent.disableClickPropagation(conteneur);
                L.DomEvent.disableScrollPropagation(conteneur);
                boutonFonds.addEventListener("click", () => ouvrirMenu("Fonds de carte", Object.entries(baseLayers), "radio", boutonFonds));
                boutonCouches.addEventListener("click", () => ouvrirMenu("Couches", Object.entries(overlays), "checkbox", boutonCouches));
                return conteneur;
            },
        });
        new Mini().addTo(carte);
        carte.on("click", fermerMenus);
    }

    function actualiserStatut() {
        const dessinsActifs = dessins ? dessins.getLayers().length : 0;
        const zones = [...casesSecteurs, ...casesPerimetres].filter((item) => item.checked).map((item) => item.parentElement.textContent.trim());
        const morceaux = [];
        if (dessinsActifs) morceaux.push(`${dessinsActifs} dessin${dessinsActifs > 1 ? "s" : ""}`);
        if (zones.length) morceaux.push(zones.join(", "));
        statut.textContent = morceaux.length ? `Zone active : ${morceaux.join(" et ")}.` : "";
    }

    function effacerCouchesFiltre() {
        couchesFiltre.forEach((couche) => carte.removeLayer(couche));
        couchesFiltre = [];
    }

    function actualiserZonesFiltre() {
        if (!carte || !donneesCarto) return;
        effacerCouchesFiltre();
        casesSecteurs.filter((item) => item.checked).forEach((checkbox) => {
            const features = donneesCarto.secteurs.features.filter((feature) => String(feature.properties?.secteur || "").toLowerCase() === checkbox.value);
            couchesFiltre.push(rendreNonEditable(L.geoJSON({type: "FeatureCollection", features}, {interactive: false, style: {color: couleursSecteurs[checkbox.value], fillColor: couleursSecteurs[checkbox.value], weight: 4, opacity: 1, fillOpacity: .28}})).addTo(carte));
        });
        casesPerimetres.filter((item) => item.checked).forEach((checkbox) => {
            const estCoeur = checkbox.value === "coeur";
            couchesFiltre.push(rendreNonEditable(L.geoJSON(donneesCarto[checkbox.value], {
                interactive: false,
                style: estCoeur ? {color: "#145c2e", fillColor: "#35a657", weight: 4, opacity: 1, fillOpacity: .3} : {color: "#5d7c2b", fillColor: "#9fca5f", weight: 4, opacity: 1, fillOpacity: .48},
            })).addTo(carte));
        });
        couchesFiltre.forEach((couche) => couche.bringToFront());
        if (dessins) dessins.bringToFront();
        actualiserStatut();
    }

    function restaurerDessins() {
        if (!champGeojson.value.trim()) return;
        try {
            L.geoJSON(JSON.parse(champGeojson.value), {pointToLayer: (_feature, latlng) => L.marker(latlng), onEachFeature: (_feature, layer) => dessins.addLayer(layer)});
        } catch (erreur) {
            console.warn("GeoJSON de recherche invalide", erreur);
            champGeojson.value = "";
        }
    }

    async function chargerDonneesCarto() {
        const charger = async (url) => {
            const reponse = await fetch(url, {cache: "force-cache"});
            if (!reponse.ok) throw new Error(`HTTP ${reponse.status}`);
            return reponse.json();
        };
        const [secteurs, coeur, adhesion] = await Promise.all([charger(panneau.dataset.secteursUrl), charger(panneau.dataset.coeurUrl), charger(panneau.dataset.adhesionUrl)]);
        return {secteurs, coeur, adhesion};
    }

    async function initialiserCarte() {
        if (carte) { setTimeout(ajusterHauteurCarte, 0); return; }
        carte = L.map("requete-carte", {preferCanvas: true}).setView([-21.12, 55.53], 11);
        const baseLayers = fondDeCartes();
        baseLayers.IGN.addTo(carte);
        dessins = L.featureGroup().addTo(carte);
        carte.pm.addControls({position: "topleft", drawMarker: true, drawCircleMarker: false, drawPolyline: true, drawRectangle: true, drawPolygon: true, drawCircle: false, drawText: false, editMode: true, dragMode: false, cutPolygon: false, removalMode: true, rotateMode: false});
        carte.pm.setPathOptions({color: "#b62020", weight: 3, fillColor: "#d65555", fillOpacity: .18});
        carte.on("pm:create", (event) => { dessins.addLayer(event.layer); actualiserStatut(); });
        carte.on("pm:remove", (event) => {
            if (dessins.hasLayer(event.layer)) dessins.removeLayer(event.layer);
            actualiserStatut();
        });
        carte.on("pm:edit", actualiserStatut);
        restaurerDessins();
        try {
            donneesCarto = await chargerDonneesCarto();
            ajouterControleCouches(baseLayers, couchesDisponibles(donneesCarto));
            actualiserZonesFiltre();
        } catch (erreur) {
            console.error("Impossible de charger les périmètres cartographiques", erreur);
            statut.textContent = "Les périmètres n’ont pas pu être chargés. Le dessin manuel reste disponible.";
        }
        setTimeout(ajusterHauteurCarte, 0);
    }

    function ouvrirCarte() {
        panneau.hidden = false;
        champActif.value = "1";
        boutonAfficher.setAttribute("aria-expanded", "true");
        initialiserCarte();
        panneau.scrollIntoView({behavior: "smooth", block: "nearest"});
        setTimeout(ajusterHauteurCarte, 350);
    }
    function masquerCarte() {
        panneau.hidden = true;
        champActif.value = "0";
        boutonAfficher.setAttribute("aria-expanded", "false");
    }
    function serialiserDessins() {
        if (!dessins) return champGeojson.value || "";
        const features = dessins.getLayers().map((layer) => layer.toGeoJSON());
        return features.length ? JSON.stringify({type: "FeatureCollection", features}) : "";
    }

    boutonAfficher.addEventListener("click", () => panneau.hidden ? ouvrirCarte() : masquerCarte());
    boutonMasquer.addEventListener("click", masquerCarte);
    [...casesSecteurs, ...casesPerimetres].forEach((checkbox) => checkbox.addEventListener("change", actualiserZonesFiltre));
    boutonEffacer.addEventListener("click", () => {
        [...casesSecteurs, ...casesPerimetres].forEach((checkbox) => { checkbox.checked = false; });
        if (dessins) dessins.clearLayers();
        champGeojson.value = "";
        actualiserZonesFiltre();
    });
    formulaire.addEventListener("submit", (event) => {
        if (panneau.hidden) { champActif.value = "0"; return; }
        champActif.value = "1";
        const geojson = serialiserDessins();
        if (geojson.length > tailleMaxGeojson) {
            event.preventDefault();
            window.alert("Le dessin est trop détaillé pour lancer la recherche. Simplifiez-le ou supprimez quelques formes.");
            return;
        }
        champGeojson.value = geojson;
    });
    window.addEventListener("resize", ajusterHauteurCarte);
    window.visualViewport?.addEventListener("resize", ajusterHauteurCarte);
    if (!panneau.hidden) initialiserCarte();
})();
