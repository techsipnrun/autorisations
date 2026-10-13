/* Moteur commun : fonds, couches de référence et présentation uniquement. */
(() => {
    "use strict";
    const bloc = document.getElementById("agida-cartographie-config");
    const configurations = bloc ? JSON.parse(bloc.textContent) : {};
    const contexte = bloc?.dataset.contexte || "instruction";
    const chargements = new Map();
    const code = (variante = "dn") => ["preinstruction", "instruction"].includes(contexte) ? `${contexte}_${variante}` : contexte;
    const config = (cle = code()) => configurations[cle];
    const style = (cle = code()) => ({...config(cle).options.geometrie});

    function creerCarte(element, cle, options = {}) {
        const reglages = config(cle).options;
        return L.map(element, {...options, zoomControl: reglages.controles.zoom, scrollWheelZoom: reglages.controles.molette})
            .setView(reglages.centre, reglages.zoom);
    }

    function pointIcon(cle) {
        const couleurs = style(cle);
        const echelle = (couleurs.radius ?? 5) / 5;
        return L.divIcon({className: "petitionnaire-point-icon", html: `<svg viewBox="0 0 18 24" width="${18 * echelle}" height="${24 * echelle}" aria-hidden="true"><path d="M9 .75A8.25 8.25 0 0 0 .75 9C.75 14.5 9 23.25 9 23.25S17.25 14.5 17.25 9A8.25 8.25 0 0 0 9 .75Z" fill="${couleurs.fillColor}" stroke="${couleurs.color}" stroke-width="1.25"/><circle cx="9" cy="9" r="3" fill="#fff"/></svg>`, iconSize: [18 * echelle, 24 * echelle], iconAnchor: [9 * echelle, 23 * echelle], popupAnchor: [0, -22 * echelle]});
    }

    function controlesDessin(cle, options) {
        const controles = config(cle).options.controles;
        return Object.fromEntries(Object.entries(options).map(([nom, valeur]) => [nom, nom in controles ? controles[nom] : valeur]));
    }

    function charger(url) {
        if (!chargements.has(url)) {
            const requete = fetch(url, {credentials: "same-origin"}).then(reponse => {
                if (!reponse.ok) throw new Error(`HTTP ${reponse.status}`);
                return reponse.json();
            }).catch(erreur => { chargements.delete(url); throw erreur; });
            chargements.set(url, requete);
        }
        return chargements.get(url);
    }

    function configurer(map, cle, brouillon = null) {
        const configuration = brouillon || config(cle);
        const controles = configuration.options.controles;
        const sources = configuration.sources.filter(source => source.actif !== false).sort((a, b) => a.ordre - b.ordre);
        const entrees = [];
        const statut = document.createElement("div");
        statut.className = "agida-map-status";
        statut.setAttribute("role", "status");
        const fonds = sources.filter(source => source.format === "tuiles");
        const fondInitial = fonds.find(source => source.visible) || fonds[0];
        const attentes = [];
        let legendControl;

        function actualiserLegende() {
            if (!legendControl) return;
            const conteneur = legendControl.getContainer();
            conteneur.replaceChildren();
            entrees.filter(entree => entree.source.format === "geojson" && entree.layer && map.hasLayer(entree.layer)).forEach(entree => {
                const categories = entree.source.options.categories?.couleurs;
                const couleurs = categories ? Object.entries(categories) : [[entree.source.nom, entree.source.options.style?.fillColor || "#64748b"]];
                couleurs.forEach(([nom, couleur]) => {
                    const ligne = document.createElement("div");
                    const pastille = document.createElement("span");
                    pastille.style.backgroundColor = couleur;
                    ligne.append(pastille, document.createTextNode(categories ? `${entree.source.nom} · ${nom}` : nom));
                    conteneur.append(ligne);
                });
            });
            conteneur.hidden = !conteneur.childNodes.length;
        }

        sources.forEach((source, index) => {
            const entree = {source, layer: null, input: null};
            entrees.push(entree);
            const credit = document.createElement("span");
            credit.textContent = source.attribution || "";
            if (source.format === "tuiles") {
                entree.layer = L.tileLayer(source.url, {maxZoom: source.options.maxZoom ?? 19, attribution: credit.innerHTML, crossOrigin: cle === "statistiques", referrerPolicy: "strict-origin-when-cross-origin", updateWhenZooming: false, updateWhenIdle: true, keepBuffer: 2});
                if (source === fondInitial) entree.layer.addTo(map);
                return;
            }
            const pane = `agida-reference-${index}`;
            map.createPane(pane).style.zIndex = String(300 + Math.min(index, 99));
            const attente = (source.donnees ? Promise.resolve(source.donnees) : charger(source.url)).then(donnees => {
                const popup = source.options.popup || {};
                const categories = source.options.categories;
                const styleCouche = feature => {
                    const resultat = {...source.options.style, pane};
                    const valeur = feature?.properties?.[categories?.propriete];
                    const couleur = categories?.couleurs?.[String(valeur).toLowerCase()] || categories?.couleurs?.[valeur];
                    if (couleur) resultat.color = resultat.fillColor = couleur;
                    return resultat;
                };
                entree.layer = L.geoJSON(donnees, {
                    pane, pmIgnore: true, snapIgnore: true, name: source.nom, attribution: credit.innerHTML, interactive: popup.mode !== "aucun",
                    style: styleCouche,
                    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {...styleCouche(feature), pmIgnore: true, radius: source.options.style?.radius ?? 5}),
                    onEachFeature: (feature, layer) => {
                        layer.options.pmIgnore = true;
                        layer.pmIgnore = true;
                        layer.options.snapIgnore = true;
                        layer.options._isBackgroundLayer = true;
                        const propriete = feature.properties?.[popup.propriete];
                        const texte = [popup.texte, propriete == null ? "" : String(propriete)].filter(Boolean).join(" · ");
                        if (texte && popup.mode !== "aucun") {
                            const contenu = document.createElement("span");
                            contenu.textContent = texte;
                            if (popup.mode === "survol") layer.bindTooltip(contenu, {sticky: true});
                            else layer.bindPopup(contenu);
                        }
                    },
                });
                if (entree.input) entree.input.disabled = false;
                if (source.visible) entree.layer.addTo(map);
                actualiserLegende();
            }).catch(erreur => {
                statut.hidden = false;
                statut.textContent = `Couche « ${source.nom} » indisponible (${erreur.message}).`;
                console.warn("[CARTOGRAPHIE] Couche indisponible", source.nom);
            });
            attentes.push(attente);
        });

        const Menu = L.Control.extend({
            options: {position: "topright"},
            onAdd() {
                const conteneur = L.DomUtil.create("div", "agida-map-menus");
                L.DomEvent.disableClickPropagation(conteneur);
                L.DomEvent.disableScrollPropagation(conteneur);
                [["tuiles", "Fonds de carte", controles.fonds], ["geojson", "Couches", controles.couches]].forEach(([format, titre, afficher]) => {
                    if (!afficher) return;
                    const details = document.createElement("details");
                    details.name = `agida-map-menu-${map._leaflet_id}`;
                    details.addEventListener("toggle", () => {
                        if (details.open) conteneur.querySelectorAll("details").forEach(autre => {
                            if (autre !== details) autre.open = false;
                        });
                    });
                    const bouton = document.createElement("summary");
                    bouton.title = titre;
                    bouton.setAttribute("aria-label", titre);
                    bouton.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/></svg>';
                    const liste = document.createElement("div");
                    liste.className = "agida-map-choices";
                    const entete = document.createElement("strong");
                    entete.textContent = titre;
                    liste.append(entete);
                    entrees.filter(entree => entree.source.format === format).forEach(entree => {
                        const ligne = document.createElement("label");
                        const input = document.createElement("input");
                        input.type = format === "tuiles" ? "radio" : "checkbox";
                        input.name = `fond-${map._leaflet_id}`;
                        // Comparer les identifiants plutôt que les objets : les sources
                        // peuvent provenir d'une copie de la configuration de travail.
                        input.checked = format === "tuiles"
                            ? entree.source.id === fondInitial?.id
                            : entree.source.visible;
                        input.disabled = !entree.layer;
                        entree.input = input;
                        input.addEventListener("change", () => {
                            if (!entree.layer) return;
                            if (format === "tuiles") entrees.filter(item => item.source.format === "tuiles" && item.layer).forEach(item => map.removeLayer(item.layer));
                            if (input.checked) entree.layer.addTo(map);
                            else map.removeLayer(entree.layer);
                            actualiserLegende();
                        });
                        ligne.append(input, document.createTextNode(entree.source.nom));
                        liste.append(ligne);
                    });
                    details.append(bouton, liste);
                    conteneur.append(details);
                });
                statut.hidden = true;
                conteneur.append(statut);
                map.on("click", () => conteneur.querySelectorAll("details").forEach(details => { details.open = false; }));
                return conteneur;
            },
        });
        new Menu().addTo(map);
        if (controles.legende) {
            const Legende = L.Control.extend({options: {position: "bottomright"}, onAdd: () => L.DomUtil.create("div", "agida-map-legend")});
            legendControl = new Legende().addTo(map);
            actualiserLegende();
        }
        if (controles.impression && L.control.browserPrint) L.control.browserPrint({title: "Télécharger en PDF", position: "topleft", closePopupsOnPrint: true, printModes: ["Landscape", "Portrait"]}).addTo(map);
        return {ready: Promise.all(attentes), entrees};
    }

    window.AGIDACarto = {code, config, configurations, style, creerCarte, configurer, pointIcon, controlesDessin, chargerGeoJSON: charger};
})();
