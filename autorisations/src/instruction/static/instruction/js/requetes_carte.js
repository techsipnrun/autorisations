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

    function rendreNonEditable(couche) {
        couche.options._isBackgroundLayer = true;
        couche.options.pmIgnore = true;
        couche.pmIgnore = true;
        if (couche.eachLayer) couche.eachLayer(rendreNonEditable);
        return couche;
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
            L.geoJSON(JSON.parse(champGeojson.value), {style: AGIDACarto.style("requetes"), pointToLayer: (_feature, latlng) => L.marker(latlng), onEachFeature: (_feature, layer) => dessins.addLayer(layer)});
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
        carte = AGIDACarto.creerCarte("requete-carte", "requetes", {preferCanvas: true});
        AGIDACarto.configurer(carte, "requetes");
        dessins = L.featureGroup().addTo(carte);
        carte.pm.addControls(AGIDACarto.controlesDessin("requetes", {position: "topleft", drawMarker: true, drawCircleMarker: false, drawPolyline: true, drawRectangle: true, drawPolygon: true, drawCircle: false, drawText: false, editMode: true, dragMode: false, cutPolygon: false, removalMode: true, rotateMode: false}));
        carte.pm.setPathOptions(AGIDACarto.style("requetes"));
        carte.on("pm:create", (event) => { dessins.addLayer(event.layer); actualiserStatut(); });
        carte.on("pm:remove", (event) => {
            if (dessins.hasLayer(event.layer)) dessins.removeLayer(event.layer);
            actualiserStatut();
        });
        carte.on("pm:edit", actualiserStatut);
        restaurerDessins();
        try {
            donneesCarto = await chargerDonneesCarto();
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
