(() => {
    "use strict";
    const racine = document.getElementById("bo-cartographie");
    if (!racine) return;
    const panneau = racine.closest("[data-panel]");
    const $ = selecteur => racine.querySelector(selecteur);
    const configurationForm = $("[data-carto-config-form]");
    const sourceForm = $("[data-carto-source-form]");
    let donnees, profil, membres = [], carteApercu, chargement = false, charge = false, modifie = false, sourceModifie = false;
    let lectureProprietes = 0, lectureApercu = 0;
    const conversions = new WeakMap();
    const clone = valeur => JSON.parse(JSON.stringify(valeur));
    const csrf = $("[name=csrfmiddlewaretoken]").value;
    const styles = {color: ["Couleur du contour", "color"], fillColor: ["Couleur de remplissage", "color"], weight: ["Épaisseur du contour", "number", 20], opacity: ["Opacité du contour", "number", 1], fillOpacity: ["Opacité de remplissage", "number", 1], radius: ["Rayon des points", "number", 30]};

    function message(element, texte, erreur = false) {
        element.textContent = texte;
        element.classList.toggle("is-error", erreur);
        element.classList.toggle("is-success", !erreur && !!texte);
    }
    function element(tag, texte, classe) {
        const noeud = document.createElement(tag);
        if (texte) noeud.textContent = texte;
        if (classe) noeud.className = classe;
        return noeud;
    }
    function caseACocher(texte, coche, changement) {
        const label = element("label", "", "bo-carto-check");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = coche;
        input.addEventListener("change", () => changement(input.checked));
        label.append(input, document.createTextNode(texte));
        return label;
    }
    function modifier() {
        modifie = true;
        configurationForm.classList.add("is-dirty");
        message($("[data-carto-config-status]"), "Modifications à enregistrer.");
    }
    async function appeler(url, options = {}) {
        const reponse = await fetch(url, {credentials: "same-origin", ...options, headers: {"X-CSRFToken": csrf, ...options.headers}});
        const resultat = await reponse.json().catch(() => { throw new Error(`Réponse inattendue (HTTP ${reponse.status}).`); });
        if (!reponse.ok) throw new Error(resultat.erreur || `Erreur HTTP ${reponse.status}.`);
        return resultat;
    }
    function dessinerStyle(conteneur, valeurs) {
        conteneur.className = "bo-carto-grid";
        conteneur.replaceChildren();
        Object.entries(styles).forEach(([cle, [titre, type, maximum]]) => {
            const label = element("label", titre);
            const input = document.createElement("input");
            input.dataset.style = cle;
            input.type = type;
            input.value = valeurs[cle] ?? (type === "color" ? "#64748b" : (cle.includes("Opacity") || cle === "opacity" ? 1 : 2));
            // Les styles acceptent les décimales, notamment l’opacité initiale 0,28.
            if (type === "number") { input.min = 0; input.max = maximum; input.step = "any"; input.required = true; }
            label.append(input);
            conteneur.append(label);
        });
    }
    function lireStyle(conteneur) {
        return Object.fromEntries([...conteneur.querySelectorAll("[data-style]")].map(input => [input.dataset.style, input.type === "color" ? input.value : Number(input.value)]));
    }
    function afficherSources() {
        for (const format of ["tuiles", "geojson"]) {
            const zone = $(`[data-carto-sources="${format}"]`);
            zone.replaceChildren();
            const selection = membres.filter(membre => donnees.sources.find(source => source.id === membre.id)?.format === format);
            const disponibles = donnees.sources.filter(source => source.actif && source.format === format && !membres.some(membre => membre.id === source.id));
            const liste = [...selection.map(membre => ({source: donnees.sources.find(source => source.id === membre.id), membre})), ...disponibles.map(source => ({source}))];
            if (!liste.length) zone.append(element("p", "Aucune source de ce type dans le catalogue.", "bo-carto-hint"));
            liste.forEach(({source, membre}, index) => {
                const ligne = element("div", "", "bo-carto-source-row");
                ligne.append(element("span", membre ? String(index + 1) : "—"));
                const contenu = element("div");
                contenu.append(element("strong", source.nom));
                contenu.append(caseACocher("Disponible", !!membre, disponible => {
                    if (disponible) membres.push({id: source.id, visible: false});
                    else membres = membres.filter(item => item.id !== source.id);
                    modifier(); afficherSources();
                }));
                if (membre) contenu.append(caseACocher("Visible par défaut", membre.visible, visible => {
                    if (visible && format === "tuiles") membres.forEach(item => {
                        if (donnees.sources.find(s => s.id === item.id)?.format === "tuiles") item.visible = false;
                    });
                    membre.visible = visible; modifier(); afficherSources();
                }));
                ligne.append(contenu);
                const boutons = element("div", "", "bo-carto-row-buttons");
                if (membre) [-1, 1].forEach(delta => {
                    const bouton = element("button", delta < 0 ? "↑" : "↓");
                    bouton.type = "button";
                    bouton.title = delta < 0 ? "Monter dans la liste" : "Descendre dans la liste";
                    bouton.disabled = index + delta < 0 || index + delta >= selection.length;
                    bouton.addEventListener("click", () => {
                        const depart = membres.indexOf(membre);
                        const arrivee = membres.indexOf(selection[index + delta]);
                        [membres[depart], membres[arrivee]] = [membres[arrivee], membres[depart]];
                        modifier(); afficherSources();
                    });
                    boutons.append(bouton);
                });
                ligne.append(boutons); zone.append(ligne);
            });
        }
    }
    function afficherCatalogue(selection = "0") {
        for (const format of ["tuiles", "geojson"]) {
            const liste = $(`[data-carto-catalogue-sources="${format}"]`);
            liste.replaceChildren();
            const sources = donnees.sources.filter(source => source.format === format).sort((a, b) => a.nom.localeCompare(b.nom, "fr"));
            sources.forEach(source => {
                const bouton = element("button", `${source.nom}${source.actif ? "" : " (désactivée)"}`, "bo-carto-catalogue-source");
                bouton.type = "button";
                bouton.dataset.cartoSourceId = source.id;
                bouton.setAttribute("aria-pressed", String(String(source.id) === String(selection)));
                bouton.addEventListener("click", () => {
                    if (sourceModifie && !confirm("Abandonner les modifications de cette source ?")) return;
                    ouvrirSource(source.id);
                });
                liste.append(bouton);
            });
            if (!sources.length) liste.append(element("p", "Aucune source enregistrée.", "bo-carto-hint"));
        }
    }
    function actualiserVue() {
        if (panneau.hidden) return;
        if (!charge) { charger(); return; }
        const vue = panneau.dataset.cartoVue === "cartes" ? "cartes" : "catalogue";
        const changement = racine.dataset.vue !== vue;
        racine.dataset.vue = vue;
        racine.querySelectorAll("[data-carto-screen]").forEach(section => {
            section.hidden = section.dataset.cartoScreen !== vue || (section === configurationForm && !profil);
        });
        $("[data-carto-title]").textContent = vue === "catalogue" ? "Catalogue" : "Personnaliser les cartes";
        $("[data-carto-description]").textContent = vue === "catalogue" ? "Gérer les fonds et les couches partagés par les cartes." : "Adapter les fonds, les couches et les outils à chaque usage.";
        if (changement) {
            if (vue === "catalogue") apercuSource();
            else if (profil) apercu();
            else fermerProfil();
        }
        requestAnimationFrame(() => carteApercu?.invalidateSize());
    }
    function fermerProfil() {
        profil = null;
        membres = [];
        configurationForm.hidden = true;
        configurationForm.classList.remove("is-dirty");
        modifie = false;
        message($("[data-carto-config-status]"), "");
        if (carteApercu) {
            carteApercu.remove();
            carteApercu = null;
        }
        $("[data-carto-preview-label]").textContent = "Sélectionnez un contexte pour afficher son aperçu.";
        message($("[data-carto-preview-status]"), "");
    }
    function ouvrirProfil(code) {
        if (!code || !donnees.configurations[code]) {
            fermerProfil();
            return;
        }
        profil = code;
        const configuration = donnees.configurations[code];
        const options = configuration.options;
        membres = configuration.sources.map(source => ({id: source.id, visible: source.visible}));
        for (const [nom, valeur] of Object.entries({latitude: options.centre[0], longitude: options.centre[1], zoom: options.zoom, zoom_cadrage: options.zoom_cadrage, couleur_densite: options.couleur_densite})) configurationForm.elements[nom].value = valeur;
        configurationForm.elements.recentrage.checked = options.recentrage;
        dessinerStyle($("[data-carto-geometry]"), options.geometrie);
        $("[data-carto-density-label]").hidden = $("[data-carto-density-hint]").hidden = code !== "statistiques";
        const zone = $("[data-carto-controls]");
        zone.replaceChildren();
        Object.entries(donnees.controles).forEach(([cle, libelle]) => {
            if ((cle.startsWith("draw") || ["editMode", "removalMode"].includes(cle)) && !["edition", "requetes"].includes(code)) return;
            if (cle === "impression" && ["requetes", "statistiques"].includes(code)) return;
            const label = caseACocher(libelle, options.controles[cle], modifier);
            label.querySelector("input").dataset.controle = cle;
            zone.append(label);
        });
        afficherSources();
        configurationForm.hidden = false;
        modifie = false;
        configurationForm.classList.remove("is-dirty");
        message($("[data-carto-config-status]"), "");
        if (charge && racine.dataset.vue === "cartes") apercu();
    }
    function lireConfiguration(code = profil) {
        const options = clone(donnees.configurations[code].options);
        // Sans contexte sélectionné, le Catalogue emprunte les réglages du
        // premier profil uniquement pour son aperçu. Il doit aussi reprendre
        // ses sources (notamment le fond IGN), pas la sélection vide du
        // formulaire « Personnaliser les cartes ».
        const membresConfiguration = profil === code
            ? membres
            : donnees.configurations[code].sources.map(source => ({id: source.id, visible: source.visible}));
        if (profil === code) {
            options.centre = [Number(configurationForm.elements.latitude.value), Number(configurationForm.elements.longitude.value)];
            options.zoom = Number(configurationForm.elements.zoom.value);
            options.zoom_cadrage = Number(configurationForm.elements.zoom_cadrage.value);
            options.recentrage = configurationForm.elements.recentrage.checked;
            options.couleur_densite = configurationForm.elements.couleur_densite.value;
            options.geometrie = lireStyle($("[data-carto-geometry]"));
            $("[data-carto-controls]").querySelectorAll("[data-controle]").forEach(input => { options.controles[input.dataset.controle] = input.checked; });
        }
        return {code, nom: donnees.configurations[code].nom, options, sources: membresConfiguration.map((membre, ordre) => ({...clone(donnees.sources.find(source => source.id === membre.id)), visible: membre.visible, ordre}))};
    }
    function apercu(source = null) {
        if (!donnees || typeof L === "undefined") return;
        const codeProfil = profil || Object.keys(donnees.configurations)[0];
        if (!codeProfil) return;
        message($("[data-carto-preview-status]"), "");
        const configuration = lireConfiguration(codeProfil);
        if (racine.dataset.vue === "catalogue") {
            // L’espace de travail du catalogue n’hérite pas des couches visibles
            // d’un contexte. Seule une source explicitement choisie sera affichée.
            const fond = configuration.sources.find(item => item.format === "tuiles" && item.visible);
            configuration.sources = donnees.sources.filter(item => item.actif).map((item, ordre) => ({...clone(item), ordre, visible: item.format === "tuiles" && item.id === fond?.id}));
            configuration.options.controles.fonds = configuration.options.controles.couches = true;
        }
        if (source) {
            configuration.sources = configuration.sources.filter(item => item.id !== source.id);
            if (source.format === "tuiles") configuration.sources.forEach(item => { if (item.format === "tuiles") item.visible = false; });
            configuration.sources.push({...source, ordre: configuration.sources.length, visible: true});
        }
        if (carteApercu) carteApercu.remove();
        AGIDACarto.configurations[codeProfil] = configuration;
        carteApercu = AGIDACarto.creerCarte("bo-carto-preview-map", codeProfil);
        AGIDACarto.configurer(carteApercu, codeProfil, configuration);
        const style = configuration.options.geometrie;
        if (carteApercu.pm && ["edition", "requetes"].includes(codeProfil)) {
            carteApercu.pm.addControls(AGIDACarto.controlesDessin(codeProfil, {
                position: "topleft", drawMarker: true, drawPolyline: true, drawPolygon: true,
                drawRectangle: true, editMode: true, removalMode: true,
                drawCircle: false, drawCircleMarker: false, drawText: false,
                dragMode: false, cutPolygon: false, rotateMode: false,
            }));
            carteApercu.pm.setPathOptions(style);
        }
        L.polygon([[-21.12, 55.49], [-21.10, 55.52], [-21.14, 55.54]], style).addTo(carteApercu);
        L.polyline([[-21.11, 55.48], [-21.09, 55.51], [-21.12, 55.55]], style).addTo(carteApercu);
        L.marker([-21.10, 55.53], {icon: AGIDACarto.pointIcon(codeProfil)}).addTo(carteApercu);
        $("[data-carto-preview-label]").textContent = `${configuration.nom} · ${source ? "source non enregistrée" : "configuration de travail"}`;
        requestAnimationFrame(() => carteApercu?.invalidateSize());
    }
    function ajouterCategorie(nom = "", couleur = "#64748b") {
        const ligne = element("div", "", "bo-carto-category");
        const texte = document.createElement("input"); texte.placeholder = "Valeur du champ"; texte.value = nom;
        const teinte = document.createElement("input"); teinte.type = "color"; teinte.value = couleur;
        const supprimer = element("button", "×"); supprimer.type = "button"; supprimer.title = "Retirer cette valeur";
        supprimer.addEventListener("click", () => ligne.remove());
        ligne.append(texte, teinte, supprimer); $("[data-carto-categories]").append(ligne);
    }
    function ouvrirSource(id, formatCreation = null) {
        ++lectureApercu;
        sourceForm.reset();
        message($("[data-carto-import-status]"), "");
        const source = donnees.sources.find(source => source.id === Number(id));
        sourceForm.dataset.id = source?.id || "0";
        sourceModifie = false;
        sourceForm.hidden = !source && !formatCreation;
        const titre = $("[data-carto-source-heading]");
        titre.hidden = sourceForm.hidden;
        titre.textContent = source ? `Modifier · ${source.nom}` : (formatCreation === "tuiles" ? "Ajouter un fond" : "Ajouter une couche");
        racine.querySelectorAll("[data-carto-source-id]").forEach(bouton => {
            bouton.setAttribute("aria-pressed", String(bouton.dataset.cartoSourceId === String(id)));
        });
        $("[data-carto-source-delete]").hidden = !source;
        for (const nom of ["nom", "format", "attribution"]) if (source) sourceForm.elements[nom].value = source[nom];
        if (formatCreation) sourceForm.elements.format.value = formatCreation;
        sourceForm.elements.format.disabled = !!source;
        sourceForm.elements.actif.checked = source?.actif ?? true;
        sourceForm.elements.url.value = source?.url_source || "";
        sourceForm.elements.maxZoom.value = source?.options.maxZoom ?? 19;
        dessinerStyle($("[data-carto-source-style]"), source?.options.style || {color: "#64748b", fillColor: "#94a3b8", opacity: 1, fillOpacity: .3, weight: 2, radius: 5});
        sourceForm.elements.popup_mode.value = source?.options.popup?.mode || "aucun";
        sourceForm.elements.popup_texte.value = source?.options.popup?.texte || "";
        sourceForm.elements.popup_propriete.value = source?.options.popup?.propriete || "";
        sourceForm.elements.categories_propriete.value = source?.options.categories?.propriete || "";
        $("[data-carto-categories]").replaceChildren();
        Object.entries(source?.options.categories?.couleurs || {}).forEach(([nom, couleur]) => ajouterCategorie(nom, couleur));
        ajusterFormat();
        ajusterInformations();
        actualiserProprietes();
        if (charge && racine.dataset.vue === "catalogue") apercuSource();
        message($("[data-carto-source-status]"), source?.importe ? "Une couche est déjà importée. Sans nouveau fichier ni URL, elle est conservée." : "");
    }
    function ajusterFormat() {
        const fond = sourceForm.elements.format.value === "tuiles";
        $("[data-carto-tile-fields]").hidden = !fond;
        $("[data-carto-layer-fields]").hidden = fond;
        sourceForm.elements.attribution.required = fond;
        const exempleGeojson = sourceForm.elements.url.dataset.geojsonExample;
        const exempleFond = donnees.sources.find(source => source.code === "ign" && source.format === "tuiles");
        sourceForm.elements.url.placeholder = fond ? "https://…/{z}/{x}/{y}" : exempleGeojson;
        $("[data-carto-url-hint]").textContent = fond
            ? `URL de tuiles contenant {z}, {x} et {y}.`
            : `Alternative à l’import : chemin d’un GeoJSON existant dans les fichiers cartographiques de l’application ou URL HTTP(S).\n Une source distante doit autoriser l’accès depuis le navigateur. Laisser vide pour importer un fichier.`;
    }
    function ajusterInformations() {
        const desactive = sourceForm.elements.popup_mode.value === "aucun";
        sourceForm.elements.popup_texte.disabled = desactive;
        sourceForm.elements.popup_propriete.disabled = desactive;
    }
    function urlSourceApercu(source) {
        if (!source?.importe) return source?.url;
        const url = new URL(source.url, window.location.href);
        url.searchParams.set("apercu", "1");
        return url.href;
    }
    function convertirFichier(fichier) {
        if (!conversions.has(fichier)) {
            const promesse = (async () => {
                if (fichier.size > 5 * 1024 * 1024) throw new Error("Le fichier dépasse la limite de 5 Mo.");
                const formulaire = new FormData(); formulaire.append("fichier", fichier);
                const resultat = await appeler(racine.dataset.convertUrl, {method: "POST", body: formulaire});
                return resultat.geojson;
            })().catch(erreur => { conversions.delete(fichier); throw erreur; });
            conversions.set(fichier, promesse);
        }
        const actuel = () => !sourceForm.hidden && sourceForm.elements.format.value === "geojson" && sourceForm.elements.fichier.files[0] === fichier;
        if (actuel()) message($("[data-carto-import-status]"), "Conversion et validation du fichier en GeoJSON…");
        return conversions.get(fichier).then(geojson => {
            if (actuel()) message($("[data-carto-import-status]"), "Fichier converti et validé en GeoJSON. Cliquez sur « Actualiser l’aperçu ». Rien n’est enregistré avant « Enregistrer la source ».");
            return geojson;
        }).catch(erreur => {
            if (actuel()) message($("[data-carto-import-status]"), `Import impossible : ${erreur.message}`, true);
            throw erreur;
        });
    }
    async function actualiserProprietes() {
        const lecture = ++lectureProprietes;
        const liste = $("#bo-carto-properties");
        const statut = $("[data-carto-properties-status]");
        liste.replaceChildren(); statut.textContent = "";
        if (sourceForm.hidden || sourceForm.elements.format.value !== "geojson") return;
        const fichier = sourceForm.elements.fichier.files[0];
        const source = donnees.sources.find(item => item.id === Number(sourceForm.dataset.id));
        const url = sourceForm.elements.url.value.trim() || urlSourceApercu(source);
        if (!fichier && !url) {
            statut.textContent = "Les propriétés seront proposées après import d’une couche ou saisie d’une URL GeoJSON.";
            return;
        }
        statut.textContent = "Recherche des propriétés…";
        try {
            let geojson;
            if (fichier) geojson = await convertirFichier(fichier);
            else geojson = await AGIDACarto.chargerGeoJSON(url);
            if (lecture !== lectureProprietes) return;
            const proprietes = new Set();
            const features = geojson?.type === "FeatureCollection" ? geojson.features : (geojson?.type === "Feature" ? [geojson] : []);
            for (const feature of features || []) {
                Object.keys(feature?.properties || {}).forEach(nom => proprietes.add(nom));
            }
            [...proprietes].sort((a, b) => a.localeCompare(b, "fr")).forEach(nom => {
                const option = document.createElement("option"); option.value = nom; liste.append(option);
            });
            statut.textContent = proprietes.size ? `${proprietes.size} propriété(s) détectée(s) · choisir une suggestion ou saisir un nom.` : "Aucune propriété détectée. La saisie manuelle reste possible.";
        } catch (erreur) {
            if (lecture === lectureProprietes) statut.textContent = fichier ? `Lecture impossible : ${erreur.message}` : "Propriétés inaccessibles (URL ou accès réseau/CORS). La saisie manuelle reste possible.";
        }
    }
    function lireSource() {
        const options = sourceForm.elements.format.value === "tuiles" ? {maxZoom: Number(sourceForm.elements.maxZoom.value)} : {
            style: lireStyle($("[data-carto-source-style]")),
            popup: {mode: sourceForm.elements.popup_mode.value, texte: sourceForm.elements.popup_texte.value, propriete: sourceForm.elements.popup_propriete.value},
        };
        if (sourceForm.elements.categories_propriete.value.trim()) options.categories = {propriete: sourceForm.elements.categories_propriete.value.trim(), couleurs: Object.fromEntries([...$("[data-carto-categories]").children].map(ligne => [ligne.querySelector("input").value, ligne.querySelector('[type=color]').value]).filter(([nom]) => nom))};
        return {id: Number(sourceForm.dataset.id), nom: sourceForm.elements.nom.value.trim(), format: sourceForm.elements.format.value, url: sourceForm.elements.url.value.trim(), attribution: sourceForm.elements.attribution.value.trim(), actif: sourceForm.elements.actif.checked, options};
    }
    async function charger() {
        if (chargement) return;
        chargement = true;
        message($("[data-carto-status]"), "Chargement des configurations…");
        try {
            donnees = await appeler(racine.dataset.url);
            Object.assign(AGIDACarto.configurations, clone(donnees.configurations));
            const select = $("[data-carto-profil]"); select.replaceChildren();
            const vide = element("option", "----"); vide.value = ""; select.append(vide);
            Object.values(donnees.configurations).forEach(configuration => { const option = element("option", configuration.nom); option.value = configuration.code; select.append(option); });
            // Le catalogue n'ouvre aucune fiche au chargement, mais rend bien
            // identifiable le fond actuellement prévisualisé.
            const fondCatalogueInitial = donnees.sources.find(source => source.format === "tuiles" && source.code === "ign");
            $(".bo-carto-workspace").hidden = false;
            select.value = "";
            fermerProfil();
            ouvrirSource(0);
            afficherCatalogue(fondCatalogueInitial?.id);
            charge = true;
            actualiserVue();
            message($("[data-carto-status]"), "");
        } catch (erreur) { message($("[data-carto-status]"), erreur.message, true); }
        finally { chargement = false; }
    }
    configurationForm.addEventListener("input", modifier);
    [configurationForm, sourceForm].forEach(form => form.addEventListener("invalid", event => {
        const champ = event.target;
        for (let parent = champ.parentElement; parent && parent !== form; parent = parent.parentElement) {
            if (parent.tagName === "DETAILS") parent.open = true;
        }
        const libelle = champ.labels?.[0]?.textContent.trim() || champ.name || "Champ";
        message($(form === configurationForm ? "[data-carto-config-status]" : "[data-carto-source-status]"), `Enregistrement impossible : ${libelle} — ${champ.validationMessage}`, true);
    }, true));
    $("[data-carto-profil]").addEventListener("change", event => {
        if (modifie && !confirm("Quitter cette carte sans enregistrer les modifications ?")) { event.target.value = profil || ""; return; }
        ouvrirProfil(event.target.value);
    });
    $("[data-carto-preview]").addEventListener("click", () => {
        if (racine.dataset.vue === "catalogue" && !sourceForm.hidden) apercuSource(true);
        else if (profil) apercu();
        else message($("[data-carto-preview-status]"), "Sélectionnez un contexte avant d’actualiser l’aperçu.");
    });
    sourceForm.addEventListener("input", () => { sourceModifie = true; });
    racine.querySelectorAll("[data-carto-new-source]").forEach(bouton => bouton.addEventListener("click", () => {
        if (sourceModifie && !confirm("Abandonner les modifications de cette source ?")) return;
        ouvrirSource(0, bouton.dataset.cartoNewSource);
        sourceForm.elements.nom.focus();
    }));
    sourceForm.elements.format.addEventListener("change", () => { ajusterFormat(); actualiserProprietes(); });
    sourceForm.elements.popup_mode.addEventListener("change", ajusterInformations);
    sourceForm.elements.fichier.addEventListener("change", () => {
        ++lectureApercu;
        message($("[data-carto-import-status]"), "");
        message($("[data-carto-source-status]"), "");
        if (racine.dataset.vue === "catalogue") apercu();
        actualiserProprietes();
    });
    sourceForm.elements.url.addEventListener("change", actualiserProprietes);
    $("[data-carto-add-category]").addEventListener("click", () => ajouterCategorie());
    async function apercuSource(explicite = false) {
        const lecture = ++lectureApercu;
        try {
            const source = lireSource();
            if (!source.actif) {
                apercu();
                message($("[data-carto-preview-status]"), `${source.format === "geojson" ? "La couche" : "Le fond"} « ${source.nom} » n’est pas ${source.format === "geojson" ? "active" : "actif"}. Cocher « Source active » pour afficher son aperçu.`, true);
                return;
            }
            const fichier = sourceForm.elements.fichier.files[0];
            if (fichier && source.format === "geojson") {
                source.donnees = await convertirFichier(fichier);
            } else if (!source.url) source.url = urlSourceApercu(donnees.sources.find(item => item.id === source.id));
            if (!source.url && !source.donnees) {
                if (!explicite) { apercu(); return; }
                throw new Error("Renseigner une URL GeoJSON ou importer un fichier GeoJSON, GPX ou KML.");
            }
            // Une lecture de fichier peut terminer après un changement de rubrique.
            if (lecture !== lectureApercu || racine.dataset.vue !== "catalogue") return;
            apercu(source);
            if (explicite) message($("[data-carto-source-status]"), "Aperçu actualisé, source non enregistrée.");
        } catch (erreur) {
            if (lecture === lectureApercu) {
                message($("[data-carto-source-status]"), erreur.message, true);
                message($("[data-carto-preview-status]"), `Aperçu impossible : ${erreur.message}`, true);
            }
        }
    }
    $("[data-carto-source-delete]").addEventListener("click", async event => {
        const id = Number(sourceForm.dataset.id);
        const source = donnees.sources.find(item => item.id === id);
        if (!source || !confirm(`Supprimer définitivement « ${source.nom} » du catalogue ? Cette action est irréversible. Une source encore utilisée par une carte ne peut pas être supprimée.`)) return;
        const bouton = event.currentTarget; bouton.disabled = true;
        try {
            await appeler(`${racine.dataset.sourceUrl}${id}/supprimer/`, {method: "POST"});
            donnees.sources = donnees.sources.filter(item => item.id !== id);
            if (membres.some(item => item.id === id)) { membres = membres.filter(item => item.id !== id); modifier(); }
            Object.values(donnees.configurations).forEach(configuration => { configuration.sources = configuration.sources.filter(item => item.id !== id); });
            afficherCatalogue(); ouvrirSource(0); afficherSources();
            message($("[data-carto-source-status]"), "Source supprimée du catalogue.");
        } catch (erreur) { message($("[data-carto-source-status]"), erreur.message, true); }
        finally { bouton.disabled = false; }
    });
    configurationForm.addEventListener("submit", async event => {
        event.preventDefault();
        const bouton = configurationForm.querySelector('[type=submit]'); bouton.disabled = true;
        try {
            const configuration = lireConfiguration();
            await appeler(`${racine.dataset.url}carte/${profil}/`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({options: configuration.options, sources: membres})});
            donnees.configurations[profil] = clone(configuration);
            modifie = false; configurationForm.classList.remove("is-dirty");
            apercu(); message($("[data-carto-config-status]"), "Configuration enregistrée. Elle sera utilisée au prochain chargement des cartes.");
        } catch (erreur) { message($("[data-carto-config-status]"), erreur.message, true); }
        finally { bouton.disabled = false; }
    });
    sourceForm.addEventListener("submit", async event => {
        event.preventDefault();
        const bouton = sourceForm.querySelector('[type=submit]'); bouton.disabled = true;
        try {
            const source = lireSource();
            const formulaire = new FormData(); formulaire.append("configuration", JSON.stringify(source));
            const fichier = sourceForm.elements.fichier.files[0];
            if (fichier && source.format === "geojson") {
                await convertirFichier(fichier);
                // Le serveur reconvertit l’original lors de la sauvegarde : ne pas
                // faire confiance au GeoJSON ou à la validation du navigateur.
                formulaire.append("fichier", fichier);
            }
            const resultat = await appeler(source.id ? `${racine.dataset.sourceUrl}${source.id}/` : racine.dataset.sourceUrl, {method: "POST", body: formulaire});
            const index = donnees.sources.findIndex(item => item.id === resultat.source.id);
            if (index >= 0) donnees.sources[index] = resultat.source;
            else donnees.sources.push(resultat.source);
            afficherCatalogue(resultat.source.id);
            ouvrirSource(resultat.source.id); afficherSources();
            message($("[data-carto-source-status]"), "Source enregistrée. Pour une nouvelle source, cochez « Disponible » puis enregistrez chaque carte concernée.");
        } catch (erreur) { message($("[data-carto-source-status]"), erreur.message, true); }
        finally { bouton.disabled = false; }
    });
    window.addEventListener("beforeunload", event => { if (modifie || sourceModifie) { event.preventDefault(); event.returnValue = ""; } });
    new MutationObserver(actualiserVue).observe(panneau, {attributes: true, attributeFilter: ["hidden", "data-carto-vue"]});
    if (!panneau.hidden) charger();
})();
