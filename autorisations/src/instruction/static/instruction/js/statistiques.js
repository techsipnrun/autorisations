(() => {
    const dashboard = document.getElementById("statistiques-dashboard");
    const form = document.getElementById("statistiques-filtres");
    if (!dashboard || !form) return;

    const chargement = document.getElementById("statistiques-chargement");
    const erreur = document.getElementById("statistiques-erreur");
    const palette = ["#006131", "#e39a2d", "#3278b7", "#8a5a9f", "#cf5c4f", "#55a68a", "#7a8f3c", "#d2769a", "#4f6678", "#b76f2c", "#6b5ca5", "#2596a8"];
    let requeteEnCours = null;
    let requeteCarteEnCours = null;
    let cleCarteEnCours = "";
    let derniereCleCarte = "";
    let donneesTypes = [];
    let dernieresDonnees = null;
    let dernieresDonneesCarte = null;
    let carteDensite = null;
    let coucheDensite = null;
    let actualiserStyleDensite = null;
    let intensiteMaxCarteVisible = 1;
    const dossiersCarteMasques = new Set();
    const couleurEvolution = document.getElementById("couleur-evolution");
    const couleurCourbe = document.getElementById("couleur-courbe");
    const couleurGroupes = document.getElementById("couleur-groupes");
    const couleurCarte = document.getElementById("couleur-carte");
    const agentsParRole = JSON.parse(document.getElementById("statistiques-agents-par-role").textContent);
    const imagesStatistiques = new Map();
    const roleParDefaut = dashboard.dataset.defaultRole || "instructeur";
    const agentParDefaut = dashboard.dataset.defaultAgent || "";
    const selectTypeCarte = document.getElementById("stats-type-carte");
    const informationCarte = document.getElementById("statistiques-carte-information");
    const legendeCarte = document.getElementById("statistiques-carte-legende");
    const chargementCarte = document.getElementById("statistiques-carte-chargement");
    const detailCarte = document.getElementById("statistiques-carte-detail");
    const detailCarteTitre = document.getElementById("statistiques-carte-detail-titre");
    const detailCarteListe = document.getElementById("statistiques-carte-detail-liste");
    couleurEvolution.value = localStorage.getItem("agida-stats-couleur-evolution") || "#16814a";
    couleurCourbe.value = localStorage.getItem("agida-stats-couleur-courbe") || "#16814a";
    couleurGroupes.value = localStorage.getItem("agida-stats-couleur-groupes") || "#3278b7";
    couleurCarte.value = localStorage.getItem("agida-stats-couleur-carte") || "#00695c";

    const cleCouleur = (libelle) => `agida-stats-couleur-${encodeURIComponent(libelle).replaceAll("%", "_")}`;
    const couleurType = (libelle, index) => localStorage.getItem(cleCouleur(libelle)) || palette[index % palette.length];

    function chargerImageStatistiques(source) {
        if (imagesStatistiques.has(source)) return imagesStatistiques.get(source);
        const chargementImage = new Promise((resolve) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = () => resolve(null);
            image.src = source;
        });
        imagesStatistiques.set(source, chargementImage);
        return chargementImage;
    }

    function afficherVide(conteneur) {
        conteneur.replaceChildren();
        const message = document.createElement("p");
        message.className = "statistiques-vide";
        message.textContent = "Aucune donnée pour les filtres sélectionnés.";
        conteneur.appendChild(message);
    }

    function initialiserCarteDensite() {
        if (carteDensite || typeof L === "undefined") return;
        const fonds = {
            "IGN": L.tileLayer(
                "https://data.geopf.fr/wmts?service=WMTS&request=GetTile&version=1.0.0" +
                "&layer=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&style=normal&tilematrixset=PM" +
                "&format=image/png&tilematrix={z}&tilerow={y}&tilecol={x}",
                {maxZoom: 19, attribution: "© IGN - Géoplateforme", crossOrigin: true, updateWhenZooming: false, updateWhenIdle: true, keepBuffer: 2}
            ),
            "OpenStreetMap": L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                crossOrigin: true,
                referrerPolicy: "strict-origin-when-cross-origin",
            }),
            "Satellite": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {maxZoom: 19, attribution: "Esri & NASA", crossOrigin: true}),
            "Topo": L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {maxZoom: 18, attribution: "© OpenTopoMap", crossOrigin: true}),
        };
        carteDensite = L.map("statistiques-carte-leaflet", {preferCanvas: true}).setView([-21.12, 55.53], 10);
        fonds.OpenStreetMap.addTo(carteDensite);
        ajouterControleFondsCarte(carteDensite, fonds);
        setTimeout(() => carteDensite.invalidateSize({pan: false}), 0);
    }

    function ajouterControleFondsCarte(carte, fonds) {
        const fermer = () => carte.getContainer().querySelectorAll(".or-popover").forEach((element) => element.remove());
        const Controle = L.Control.extend({
            options: {position: "topright"},
            onAdd() {
                const conteneur = L.DomUtil.create("div", "leaflet-control or-mini");
                const pile = L.DomUtil.create("div", "or-stack", conteneur);
                const bouton = L.DomUtil.create("div", "or-btn", pile);
                bouton.title = "Fonds de carte";
                bouton.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 13.74a2 2 0 0 1-2 0L2.5 8.87a1 1 0 0 1 0-1.74L11 2.26a2 2 0 0 1 2 0l8.5 4.87a1 1 0 0 1 0 1.74z"/><path d="m20 14.285 1.5.845a1 1 0 0 1 0 1.74L13 21.74a2 2 0 0 1-2 0l-8.5-4.87a1 1 0 0 1 0-1.74l1.5-.845"/></svg>';
                L.DomEvent.disableClickPropagation(conteneur);
                bouton.addEventListener("click", () => {
                    fermer();
                    const menu = document.createElement("div");
                    menu.className = "or-popover";
                    menu.innerHTML = "<h4>Fonds de carte</h4>";
                    Object.entries(fonds).forEach(([nom, couche], index) => {
                        const id = `stats-fond-${index}`;
                        const ligne = document.createElement("div");
                        ligne.className = "or-row";
                        ligne.innerHTML = `<input type="radio" name="stats-fond-carte" id="${id}" ${carte.hasLayer(couche) ? "checked" : ""}><label for="${id}">${nom}</label>`;
                        ligne.querySelector("input").addEventListener("change", () => {
                            Object.values(fonds).forEach((fond) => carte.removeLayer(fond));
                            couche.addTo(carte).bringToBack();
                        });
                        menu.appendChild(ligne);
                    });
                    L.DomEvent.disableClickPropagation(menu);
                    carte.getContainer().appendChild(menu);
                    menu.style.top = `${bouton.offsetTop}px`;
                    menu.style.right = `${bouton.offsetWidth + 20}px`;
                    setTimeout(() => {
                        const fermerExterieur = (event) => {
                            if (menu.contains(event.target) || bouton.contains(event.target)) return;
                            menu.remove();
                            document.removeEventListener("mousedown", fermerExterieur);
                        };
                        document.addEventListener("mousedown", fermerExterieur);
                    }, 0);
                });
                return conteneur;
            },
        });
        new Controle().addTo(carte);
        carte.on("click", fermer);
    }

    function couleurDensite(valeur, maximum) {
        const ratio = maximum > 1 ? Math.log1p(valeur) / Math.log1p(maximum) : 0;
        const couleurs = paletteDensite();
        if (ratio < .2) return couleurs[0];
        if (ratio < .4) return couleurs[1];
        if (ratio < .6) return couleurs[2];
        if (ratio < .8) return couleurs[3];
        return couleurs[4];
    }

    function paletteDensite() {
        return [.22, .42, .62, .82, 1].map((intensite) => melangerCouleur(couleurCarte.value, "#e8f1ed", intensite));
    }

    function actualiserDegradeCarte() {
        const degrade = document.querySelector(".statistiques-carte-degrade");
        if (degrade) degrade.style.background = `linear-gradient(90deg, ${paletteDensite().join(", ")})`;
    }

    function viderCarteDensite(message = "Sélectionnez un type de dossier pour afficher la carte.") {
        initialiserCarteDensite();
        fermerTousPopupsCarte();
        if (coucheDensite) {
            coucheDensite.remove();
            coucheDensite = null;
        }
        dernieresDonneesCarte = null;
        legendeCarte.hidden = true;
        informationCarte.textContent = message;
    }

    function masquerDossierCarte(dossierId) {
        dossiersCarteMasques.add(dossierId);
        const couchesVides = [];
        let maximum = 1;
        coucheDensite?.eachLayer((couche) => {
            const proprietes = couche.feature.properties;
            proprietes.dossier_ids = (proprietes.dossier_ids || []).filter((id) => !dossiersCarteMasques.has(id));
            proprietes.nombre_dossiers = proprietes.dossier_ids.length;
            if (!proprietes.nombre_dossiers) couchesVides.push(couche);
            else maximum = Math.max(maximum, proprietes.nombre_dossiers);
        });
        couchesVides.forEach((couche) => coucheDensite.removeLayer(couche));
        intensiteMaxCarteVisible = maximum;
        coucheDensite?.eachLayer((couche) => {
            const nombre = couche.feature.properties.nombre_dossiers;
            couche.unbindTooltip().bindTooltip(`${nombre} dossier${nombre > 1 ? "s" : ""}`, {sticky: true});
        });
        actualiserStyleDensite?.();
        fermerTousPopupsCarte();
    }

    function creerListeDossiers(dossierIds, donnees = dernieresDonneesCarte, permettreMasquage = false) {
        const liste = document.createElement("ul");
        liste.className = "statistiques-carte-liste-dossiers";
        if (permettreMasquage) liste.classList.add("avec-masquage");
        dossierIds.forEach((dossierId) => {
            const dossier = donnees?.dossiers?.[dossierId];
            if (!dossier) return;
            const ligne = document.createElement("li");
            const lien = document.createElement("a");
            lien.href = dossier.url; lien.target = "_blank"; lien.rel = "noopener";
            const nom = document.createElement("strong"); nom.textContent = dossier.nom;
            const complement = document.createElement("span");
            complement.textContent = `N° ${dossier.numero} · ${dossier.type}`;
            lien.append(nom, complement); ligne.appendChild(lien); liste.appendChild(ligne);
            if (permettreMasquage) {
                const masquer = document.createElement("button");
                masquer.type = "button"; masquer.className = "statistiques-carte-masquer-dossier";
                masquer.title = "Masquer cette géométrie";
                masquer.setAttribute("aria-label", `Masquer la géométrie de ${dossier.nom}`);
                masquer.textContent = "×";
                masquer.addEventListener("click", (event) => {
                    event.preventDefault(); event.stopPropagation();
                    masquerDossierCarte(dossierId);
                });
                ligne.appendChild(masquer);
            }
        });
        return liste;
    }

    function fermerDetailCarte() {
        detailCarte.hidden = true;
        detailCarteListe.replaceChildren();
    }

    function fermerTousPopupsCarte() {
        fermerDetailCarte();
        carteDensite?.closePopup();
    }

    function ouvrirDetailCarte(titre, dossierIds) {
        carteDensite?.closePopup();
        detailCarteTitre.textContent = titre;
        detailCarteListe.replaceChildren(creerListeDossiers(dossierIds));
        detailCarte.hidden = false;
    }

    function boutonCompteurCarte(nombre, titre, dossierIds) {
        if (!nombre) {
            const valeur = document.createElement("strong");
            valeur.textContent = "0";
            return valeur;
        }
        const bouton = document.createElement("button");
        bouton.type = "button"; bouton.className = "statistiques-compteur-carte";
        bouton.textContent = nombre.toLocaleString("fr-FR");
        bouton.title = "Afficher les dossiers concernés";
        bouton.addEventListener("click", (event) => {
            event.stopPropagation();
            ouvrirDetailCarte(titre, dossierIds);
        });
        return bouton;
    }

    function afficherInformationCarte(donnees) {
        const details = donnees.details_compteurs || {};
        const representes = details.representes || [];
        const sansGeometrie = details.sans_geometrie || [];
        const geometriesVides = details.geometries_vides || [];
        const geometriesInvalides = details.geometries_invalides || [];
        const sansDonneeCartographique = [...sansGeometrie, ...geometriesVides];
        const nonRepresentes = [...sansDonneeCartographique, ...geometriesInvalides];
        informationCarte.replaceChildren();

        const ligneRepresentes = document.createElement("p");
        ligneRepresentes.append(
            boutonCompteurCarte(representes.length, `${representes.length} dossier${representes.length > 1 ? "s" : ""} représenté${representes.length > 1 ? "s" : ""}`, representes),
            ` dossier${representes.length > 1 ? "s" : ""} représenté${representes.length > 1 ? "s" : ""} sur ${donnees.total_dossiers}.`,
        );
        informationCarte.appendChild(ligneRepresentes);
        if (!nonRepresentes.length) return;

        const categories = [[sansDonneeCartographique, "sans donnée cartographique"], [geometriesInvalides, "avec une donnée cartographique invalide"]].filter(([ids]) => ids.length);
        if (categories.length === 1) {
            const [ids, libelle] = categories[0];
            const ligneCauseUnique = document.createElement("p");
            ligneCauseUnique.append(boutonCompteurCarte(ids.length, `${ids.length} dossier${ids.length > 1 ? "s" : ""} ${libelle}`, ids), ` dossier${ids.length > 1 ? "s" : ""} ${libelle}.`);
            informationCarte.appendChild(ligneCauseUnique);
            return;
        }

        const ligneNonRepresentes = document.createElement("p");
        ligneNonRepresentes.append(boutonCompteurCarte(nonRepresentes.length, `${nonRepresentes.length} dossiers non représentés`, nonRepresentes), ` non représentés faute de donnée cartographique exploitable.`);
        informationCarte.appendChild(ligneNonRepresentes);

        const causes = document.createElement("ul");
        categories.forEach(([ids, libelle]) => {
            if (!ids.length) return;
            const ligne = document.createElement("li");
            ligne.append(boutonCompteurCarte(ids.length, `${ids.length} dossier${ids.length > 1 ? "s" : ""} ${libelle}`, ids), ` dossier${ids.length > 1 ? "s" : ""} ${libelle}`);
            causes.appendChild(ligne);
        });
        informationCarte.appendChild(causes);
    }

    function synchroniserTypeCarteAvecFiltresGlobaux() {
        const typesSelectionnes = [...form.querySelectorAll('input[name="demarches"]:checked')];
        const ancienneValeur = selectTypeCarte.value;
        if (typesSelectionnes.length === 1) {
            selectTypeCarte.value = typesSelectionnes[0].value;
            return selectTypeCarte.value !== ancienneValeur;
        }
        if (typesSelectionnes.length > 1 && !typesSelectionnes.some((item) => item.value === selectTypeCarte.value)) {
            selectTypeCarte.value = typesSelectionnes[0].value;
        }
        return selectTypeCarte.value !== ancienneValeur;
    }

    function ajouterParametresCarte(parametres) {
        parametres.set("type_carte", selectTypeCarte.value);
        return parametres;
    }

    async function actualiserCarteDensite(forcer = false) {
        initialiserCarteDensite();
        if (!selectTypeCarte.value) {
            if (requeteCarteEnCours) requeteCarteEnCours.abort();
            viderCarteDensite();
            return;
        }
        if (sectionMasquee("carte")) return;

        const parametres = ajouterParametresCarte(new URLSearchParams(new FormData(form)));
        const cleCarte = parametres.toString();
        if (!forcer && (cleCarte === cleCarteEnCours || (cleCarte === derniereCleCarte && dernieresDonneesCarte))) return;
        if (requeteCarteEnCours) requeteCarteEnCours.abort();
        fermerTousPopupsCarte();

        const controleur = new AbortController();
        requeteCarteEnCours = controleur;
        cleCarteEnCours = cleCarte;
        chargementCarte.hidden = false;
        informationCarte.textContent = "Calcul de la densité cartographique…";
        legendeCarte.hidden = true;
        try {
            const reponse = await fetch(`${dashboard.dataset.carteUrl}?${parametres}`, {
                headers: {"X-Requested-With": "XMLHttpRequest"},
                signal: controleur.signal,
            });
            const typeReponse = reponse.headers.get("content-type") || "";
            if (!typeReponse.includes("application/json")) {
                throw new Error(`Le calcul cartographique a échoué côté serveur (erreur ${reponse.status}). Réessayez dans quelques instants.`);
            }
            const donnees = await reponse.json();
            if (!reponse.ok) throw new Error(donnees.erreur || "Impossible de calculer la densité cartographique.");
            dernieresDonneesCarte = donnees;
            derniereCleCarte = cleCarte;
            dossiersCarteMasques.clear();
            intensiteMaxCarteVisible = Math.max(donnees.intensite_max, 1);

            if (coucheDensite) coucheDensite.remove();
            const styleCellule = (feature) => ({
                    color: couleurDensite(feature.properties.nombre_dossiers, intensiteMaxCarteVisible),
                    fillColor: couleurDensite(feature.properties.nombre_dossiers, intensiteMaxCarteVisible),
                    fillOpacity: carteDensite.getZoom() <= 10 ? .72 : .62,
                    opacity: .92,
                    weight: carteDensite.getZoom() <= 10 ? (carteDensite.getContainer().clientWidth < 650 ? 2.4 : 1.7) : .8,
                });
            coucheDensite = L.geoJSON(donnees.cellules, {
                style: styleCellule,
                onEachFeature: (feature, layer) => {
                    const nombre = feature.properties.nombre_dossiers;
                    layer.bindTooltip(`${nombre} dossier${nombre > 1 ? "s" : ""}`, {sticky: true});
                    layer.on("click", (event) => {
                        L.DomEvent.stopPropagation(event.originalEvent);
                        fermerDetailCarte();
                        const dossiersIds = feature.properties.dossier_ids || [];
                        const contenu = document.createElement("div");
                        contenu.className = "statistiques-carte-popup";
                        const titre = document.createElement("strong");
                        titre.textContent = `${dossiersIds.length} dossier${dossiersIds.length > 1 ? "s" : ""}`;
                        contenu.appendChild(titre);
                        contenu.appendChild(creerListeDossiers(dossiersIds, donnees, true));
                        const largeurPopup = Math.max(240, Math.min(380, window.innerWidth - 60));
                        L.popup({minWidth: largeurPopup, maxWidth: largeurPopup, maxHeight: 280, className: "statistiques-popup-dossiers"})
                            .setLatLng(event.latlng)
                            .setContent(contenu)
                            .openOn(carteDensite);
                    });
                },
            }).addTo(carteDensite);
            if (actualiserStyleDensite) carteDensite.off("zoomend", actualiserStyleDensite);
            actualiserStyleDensite = () => coucheDensite?.setStyle(styleCellule);
            carteDensite.on("zoomend", actualiserStyleDensite);

            if (coucheDensite.getLayers().length) {
                carteDensite.fitBounds(coucheDensite.getBounds(), {padding: [18, 18], maxZoom: 15});
                carteDensite.setZoom(Math.min(carteDensite.getZoom() + 1, carteDensite.getMaxZoom()));
                legendeCarte.hidden = false;
            } else {
                carteDensite.setView([-21.12, 55.53], 10);
                legendeCarte.hidden = true;
            }
            afficherInformationCarte(donnees);
        } catch (exception) {
            if (exception.name === "AbortError") return;
            viderCarteDensite(exception.message);
        } finally {
            if (requeteCarteEnCours === controleur) {
                requeteCarteEnCours = null;
                cleCarteEnCours = "";
                chargementCarte.hidden = true;
            }
        }
    }

    function initialiserMultiselects() {
        document.querySelectorAll(".statistiques-multiselect").forEach((bloc) => {
            const bouton = bloc.querySelector(".statistiques-multiselect-trigger");
            const cases = [...bloc.querySelectorAll('input[type="checkbox"]')];
            const rafraichirLibelle = () => {
                const selection = cases.filter((item) => item.checked);
                bouton.textContent = selection.length === 0
                    ? bloc.dataset.placeholder
                    : selection.length === 1
                        ? selection[0].parentElement.textContent.trim()
                        : `${selection.length} sélectionnés`;
                bouton.classList.toggle("has-selection", selection.length > 0);
            };
            bouton.addEventListener("click", () => {
                const ouverture = !bloc.classList.contains("is-open");
                document.querySelectorAll(".statistiques-multiselect.is-open").forEach((autre) => {
                    autre.classList.remove("is-open");
                    autre.querySelector("button").setAttribute("aria-expanded", "false");
                });
                bloc.classList.toggle("is-open", ouverture);
                bouton.setAttribute("aria-expanded", String(ouverture));
            });
            cases.forEach((item) => item.addEventListener("change", rafraichirLibelle));
            bloc.rafraichirLibelle = rafraichirLibelle;
            rafraichirLibelle();
        });
        document.addEventListener("click", (event) => {
            if (event.target.closest(".statistiques-multiselect")) return;
            document.querySelectorAll(".statistiques-multiselect.is-open").forEach((bloc) => bloc.classList.remove("is-open"));
            if (!event.target.closest(".statistiques-export-ancre")) {
                document.querySelectorAll(".statistiques-export-menu").forEach((menu) => menu.remove());
            }
        });
    }

    function afficherIndicateurs(indicateurs) {
        document.getElementById("kpi-total").textContent = indicateurs.total.toLocaleString("fr-FR");
        document.getElementById("kpi-reception").textContent = indicateurs.reception.toLocaleString("fr-FR");
        document.getElementById("kpi-instruction").textContent = indicateurs.instruction.toLocaleString("fr-FR");
        document.getElementById("kpi-termines").textContent = indicateurs.termines.toLocaleString("fr-FR");
        document.getElementById("kpi-delai").textContent = indicateurs.delai_moyen_jours === null ? "—" : `${indicateurs.delai_moyen_jours.toLocaleString("fr-FR")} j`;
    }

    function coordonneesPolaires(angle, rayon) {
        const radians = (angle - 90) * Math.PI / 180;
        return {x: 50 + rayon * Math.cos(radians), y: 50 + rayon * Math.sin(radians)};
    }

    function cheminArc(debut, fin) {
        const depart = coordonneesPolaires(fin, 37);
        const arrivee = coordonneesPolaires(debut, 37);
        return `M ${depart.x} ${depart.y} A 37 37 0 ${fin - debut <= 180 ? 0 : 1} 0 ${arrivee.x} ${arrivee.y}`;
    }

    function libelleNombre(valeur) {
        return `${valeur.toLocaleString("fr-FR")} ${valeur === 1 ? "dossier" : "dossiers"}`;
    }

    function dessinerDonutDans(types, donutId, legendeId, memoriser = false) {
        if (memoriser) donneesTypes = types;
        const donut = document.getElementById(donutId);
        const legende = document.getElementById(legendeId);
        const total = types.reduce((somme, item) => somme + item.valeur, 0);
        donut.replaceChildren();
        legende.replaceChildren();
        if (!total) {
            donut.classList.add("is-empty");
            afficherVide(legende);
            return;
        }
        donut.classList.remove("is-empty");
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 100 100");
        svg.setAttribute("aria-label", `Répartition de ${total} dossiers par type`);
        let angle = 0;
        types.forEach((item, index) => {
            const portion = item.valeur / total * 360;
            const path = document.createElementNS(svg.namespaceURI, "path");
            path.setAttribute("d", cheminArc(angle, angle + Math.min(portion, 359.999)));
            path.setAttribute("stroke", couleurType(item.label, index));
            path.setAttribute("stroke-width", "22");
            path.setAttribute("fill", "none");
            const titre = document.createElementNS(svg.namespaceURI, "title");
            titre.textContent = `${item.label} : ${libelleNombre(item.valeur)} (${Math.round(item.valeur / total * 100)} %)`;
            path.appendChild(titre);
            svg.appendChild(path);
            angle += portion;

            const ligne = document.createElement("div");
            ligne.className = "statistiques-legende-ligne";
            const couleur = document.createElement("input");
            couleur.type = "color";
            couleur.value = couleurType(item.label, index);
            couleur.title = `Modifier la couleur de ${item.label}`;
            couleur.addEventListener("change", () => {
                localStorage.setItem(cleCouleur(item.label), couleur.value);
                dessinerDonutDans(donneesTypes, "graphique-types", "legende-types", true);
            });
            const libelle = document.createElement("span");
            libelle.className = "statistiques-legende-libelle";
            libelle.textContent = item.label;
            const valeur = document.createElement("span");
            valeur.className = "statistiques-legende-valeur";
            valeur.innerHTML = `<strong>${item.valeur.toLocaleString("fr-FR")}</strong> <span>(${Math.round(item.valeur / total * 100)} %)</span>`;
            ligne.append(couleur, libelle, valeur);
            legende.appendChild(ligne);
        });
        const totalTexte = document.createElement("strong");
        totalTexte.textContent = total.toLocaleString("fr-FR");
        donut.append(svg, totalTexte);
    }

    function dessinerDonut(types) {
        dessinerDonutDans(types, "graphique-types", "legende-types", true);
    }

    function dessinerEtapes(etapes) {
        const conteneur = document.getElementById("graphique-etapes");
        conteneur.replaceChildren();
        const total = etapes.reduce((somme, item) => somme + item.valeur, 0);
        if (!total) return afficherVide(conteneur);
        etapes.forEach((item) => {
            const ligne = document.createElement("div");
            ligne.className = "statistiques-etape";
            const entete = document.createElement("div");
            entete.className = "statistiques-barre-entete";
            const libelle = document.createElement("span");
            libelle.textContent = item.label;
            libelle.title = item.label;
            const valeur = document.createElement("strong");
            valeur.textContent = item.valeur.toLocaleString("fr-FR");
            entete.append(libelle, valeur);
            const piste = document.createElement("div");
            piste.className = "statistiques-barre-piste";
            const barre = document.createElement("div");
            barre.className = "statistiques-barre-valeur";
            barre.style.width = `${item.valeur / total * 100}%`;
            piste.appendChild(barre);
            ligne.append(entete, piste);
            conteneur.appendChild(ligne);
        });
    }

    function dessinerManifestations(donnees) {
        const carte = document.getElementById("carte-manifestations");
        const conteneur = document.getElementById("graphique-manifestations");
        carte.hidden = !donnees.visible;
        document.querySelector(".statistiques-grille").classList.toggle("statistiques-sans-ms", !donnees.visible);
        if (!donnees.visible) return;
        conteneur.replaceChildren();
        const categories = [
            ["Dossiers complets", donnees.complets, "Démarche Numérique + Déclaration Manifestations", "#006131", ["dn", "dm"]],
            ["Démarche Numérique orphelins", donnees.orphelins_dn, "Sans Déclaration Manifestations liée", "#3278b7", ["dn"]],
            ["Déclaration Manifestations orphelins", donnees.orphelins_dm, "Sans Démarche Numérique liée", "#e39a2d", ["dm"]],
        ];
        const total = categories.reduce((somme, item) => somme + item[1], 0);
        carte.classList.toggle("statistiques-sans-donnees-export", total === 0);
        categories.forEach(([label, valeur, aide, couleur, logos]) => {
            const bloc = document.createElement("div");
            bloc.className = "statistiques-ms-item";
            bloc.style.setProperty("--ms-color", couleur);
            const sources = {dn: "/static/instruction/img/icon_DS.png", dm: "/static/instruction/img/prefet_icon_color.svg"};
            const images = logos.map((logo) => `<img src="${sources[logo]}" alt="${logo.toUpperCase()}">`).join("");
            bloc.innerHTML = `<div class="statistiques-ms-titre"><span>${label}${total ? ` <small>(${Math.round(valeur / total * 100)} %)</small>` : ""}</span><span class="statistiques-ms-logos">${images}</span></div><strong>${valeur.toLocaleString("fr-FR")}</strong>`;
            conteneur.appendChild(bloc);
        });
    }

    function completerEvolution(evolution) {
        if (evolution.length < 2) return evolution;
        const valeurs = new Map(evolution.map((item) => [item.label, item.valeur]));
        const lireDate = (label) => { const [mois, annee] = label.split("/").map(Number); return new Date(annee, mois - 1, 1); };
        const curseur = lireDate(evolution[0].label);
        const fin = lireDate(evolution[evolution.length - 1].label);
        const resultat = [];
        while (curseur <= fin) {
            const label = `${String(curseur.getMonth() + 1).padStart(2, "0")}/${curseur.getFullYear()}`;
            resultat.push({label, valeur: valeurs.get(label) || 0});
            curseur.setMonth(curseur.getMonth() + 1);
        }
        return resultat;
    }

    function evolutionCumulative(evolution) {
        let cumul = 0;
        return completerEvolution(evolution).map((item) => ({...item, valeur: (cumul += item.valeur)}));
    }

    function libellePeriode(label, compact = false) {
        const anneesSelectionnees = form.querySelectorAll('input[name="annees"]:checked');
        if (anneesSelectionnees.length !== 1) return label;
        const nomsMois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
        const nomsMoisCourts = ["jan.", "fév.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
        const numeroMois = Number(label.split("/")[0]);
        return (compact ? nomsMoisCourts : nomsMois)[numeroMois - 1] || label;
    }

    function dessinerCourbe(evolutionBrute) {
        const conteneur = document.getElementById("graphique-courbe");
        conteneur.replaceChildren();
        const unSeulMois = form.querySelectorAll('input[name="mois"]:checked').length === 1;
        conteneur.closest(".statistiques-carte").classList.toggle("statistiques-sans-donnees-export", unSeulMois);
        if (unSeulMois) {
            const message = document.createElement("p");
            message.className = "statistiques-vide";
            message.textContent = "Sélectionnez au moins deux mois pour afficher la courbe cumulative.";
            conteneur.appendChild(message);
            return;
        }
        const evolution = evolutionCumulative(evolutionBrute);
        const maximum = Math.max(...evolution.map((item) => item.valeur), 0);
        if (!maximum) return afficherVide(conteneur);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 900 260");
        svg.setAttribute("preserveAspectRatio", "none");
        const marge = {gauche: 45, droite: 20, haut: 20, bas: 42};
        const largeur = 900 - marge.gauche - marge.droite;
        const hauteur = 260 - marge.haut - marge.bas;
        const points = evolution.map((item, index) => ({
            x: marge.gauche + (evolution.length === 1 ? largeur / 2 : index * largeur / (evolution.length - 1)),
            y: marge.haut + hauteur - item.valeur / maximum * hauteur,
            ...item,
        }));
        const libellesCompacts = points.length > 8 || conteneur.clientWidth / points.length < 72;
        const ligne = document.createElementNS(svg.namespaceURI, "polyline");
        ligne.setAttribute("points", points.map((p) => `${p.x},${p.y}`).join(" "));
        ligne.setAttribute("class", "statistiques-courbe-ligne");
        ligne.style.stroke = couleurCourbe.value;
        [...new Set(Array.from({length: 5}, (_, index) => Math.round(maximum * index / 4)))].forEach((valeur) => {
            const y = marge.haut + hauteur - valeur / maximum * hauteur;
            const repere = document.createElementNS(svg.namespaceURI, "line");
            repere.setAttribute("x1", marge.gauche); repere.setAttribute("x2", 900 - marge.droite);
            repere.setAttribute("y1", y); repere.setAttribute("y2", y); repere.setAttribute("class", "statistiques-courbe-repere");
            const texte = document.createElementNS(svg.namespaceURI, "text");
            texte.setAttribute("x", "28"); texte.setAttribute("y", String(y + 5)); texte.textContent = String(valeur);
            svg.append(repere, texte);
        });
        svg.appendChild(ligne);
        points.forEach((point, index) => {
            const cercle = document.createElementNS(svg.namespaceURI, "circle");
            cercle.setAttribute("cx", point.x); cercle.setAttribute("cy", point.y); cercle.setAttribute("r", "5"); cercle.style.stroke = couleurCourbe.value;
            const titre = document.createElementNS(svg.namespaceURI, "title");
            titre.textContent = `${point.label} : ${libelleNombre(point.valeur)}`;
            cercle.appendChild(titre); svg.appendChild(cercle);
            if (index % Math.max(1, Math.ceil(points.length / 12)) === 0 || index === points.length - 1) {
                const texte = document.createElementNS(svg.namespaceURI, "text");
                texte.setAttribute("x", point.x); texte.setAttribute("y", "250"); texte.textContent = libellePeriode(point.label, libellesCompacts);
                svg.appendChild(texte);
            }
        });
        conteneur.appendChild(svg);
    }

    function dessinerInstructeur(repartition) {
        document.getElementById("carte-instructeur").classList.toggle("statistiques-sans-donnees-export", repartition.length === 0);
        dessinerDonutDans(repartition, "graphique-instructeur", "legende-instructeur");
    }

    function dessinerAvis(repartition) {
        document.getElementById("carte-avis").classList.toggle("statistiques-sans-donnees-export", repartition.length === 0);
        dessinerDonutDans(repartition, "graphique-avis", "legende-avis");
    }

    function dessinerGroupes(groupes) {
        const conteneur = document.getElementById("graphique-groupes");
        conteneur.replaceChildren();
        const maximum = Math.max(...groupes.map((item) => item.valeur), 0);
        if (!maximum) return afficherVide(conteneur);
        groupes.forEach((item) => {
            const ligne = document.createElement("div"); ligne.className = "statistiques-etape";
            const entete = document.createElement("div"); entete.className = "statistiques-barre-entete";
            const label = document.createElement("span"); label.textContent = item.label; label.title = item.label;
            const valeur = document.createElement("strong"); valeur.textContent = item.valeur.toLocaleString("fr-FR");
            entete.append(label, valeur);
            const piste = document.createElement("div"); piste.className = "statistiques-barre-piste";
            const barre = document.createElement("div"); barre.className = "statistiques-barre-valeur";
            barre.style.width = `${item.valeur / maximum * 100}%`; barre.style.background = couleurGroupes.value;
            piste.appendChild(barre); ligne.append(entete, piste); conteneur.appendChild(ligne);
        });
    }

    function actualiserAgentsRole(conserverSelection = false, valeurDemandee = "") {
        const role = document.getElementById("stats-role").value;
        const select = document.getElementById("stats-instructeur");
        const ancienneValeur = valeurDemandee || (conserverSelection ? select.value : "");
        select.replaceChildren(new Option("Sélectionner un agent", ""));
        (agentsParRole[role] || []).forEach((agent) => select.add(new Option(agent.label, agent.id)));
        if (ancienneValeur && [...select.options].some((option) => option.value === ancienneValeur)) select.value = ancienneValeur;
    }

    function sectionMasquee(kind) {
        const section = document.querySelector(`.statistiques-carte[data-export-kind="${kind}"]`);
        return !section || section.classList.contains("statistiques-section-masquee");
    }

    function initialiserMasquageSections() {
        document.querySelectorAll(".statistiques-carte").forEach((carte) => {
            if (carte.querySelector(":scope > .statistiques-masquer-section")) return;
            const bouton = document.createElement("button");
            bouton.type = "button";
            bouton.className = "statistiques-masquer-section";
            bouton.title = "Masquer cette section";
            bouton.setAttribute("aria-label", "Masquer cette section");
            bouton.textContent = "×";
            bouton.addEventListener("click", () => {
                carte.classList.add("statistiques-section-masquee");
                if (carte.dataset.exportKind === "carte" && requeteCarteEnCours) {
                    requeteCarteEnCours.abort();
                    chargementCarte.hidden = true;
                }
                document.querySelectorAll(".statistiques-export-menu").forEach((menu) => menu.remove());
            });
            carte.appendChild(bouton);
        });
    }

    function melangerCouleur(couleurA, couleurB, ratio) {
        const rgb = (hex) => [1, 3, 5].map((position) => parseInt(hex.slice(position, position + 2), 16));
        const a = rgb(couleurA); const b = rgb(couleurB);
        return `rgb(${a.map((valeur, index) => Math.round(valeur * ratio + b[index] * (1 - ratio))).join(",")})`;
    }

    function dessinerEvolution(evolution) {
        const conteneur = document.getElementById("graphique-evolution");
        conteneur.replaceChildren();
        const maximum = Math.max(...evolution.map((item) => item.valeur), 0);
        if (!maximum) return afficherVide(conteneur);
        const libellesCompacts = evolution.length > 8 || conteneur.clientWidth / evolution.length < 68;
        evolution.forEach((item) => {
            const ratio = item.valeur / maximum;
            const colonne = document.createElement("div");
            colonne.className = "statistiques-colonne";
            colonne.title = `${item.label} : ${item.valeur} dossier(s)`;
            const valeur = document.createElement("strong");
            valeur.textContent = item.valeur.toLocaleString("fr-FR");
            const piste = document.createElement("div");
            piste.className = "statistiques-colonne-piste";
            const barre = document.createElement("div");
            barre.className = "statistiques-colonne-barre";
            barre.style.height = `${Math.max(ratio * 100, 1)}%`;
            barre.style.setProperty("--intensite", String(ratio));
            barre.style.backgroundColor = melangerCouleur(couleurEvolution.value, "#e4f0e8", .35 + ratio * .65);
            piste.appendChild(barre);
            const libelle = document.createElement("span");
            libelle.textContent = libellePeriode(item.label, libellesCompacts);
            colonne.append(valeur, piste, libelle);
            conteneur.appendChild(colonne);
        });
    }

    function filtresActifs() {
        const valeurs = [...form.querySelectorAll("input:checked")].map((item) => item.parentElement.textContent.trim());
        return valeurs.join(" · ") || "Tous les dossiers";
    }

    function telechargerCanvas(canvas, nom) {
        const lien = document.createElement("a");
        lien.download = `${nom}-${new Date().toISOString().slice(0, 10)}.png`;
        lien.href = canvas.toDataURL("image/png");
        lien.click();
    }

    function imprimerCanvas(canvas, titre) {
        const fenetre = window.open("", "_blank");
        if (!fenetre) return;
        fenetre.document.write(`<!doctype html><html lang="fr"><head><title>${titre}</title><style>@page{size:landscape;margin:8mm}html,body{margin:0}body{display:grid;place-items:center;min-height:100vh}img{display:block;max-width:100%;max-height:96vh}</style></head><body><img src="${canvas.toDataURL("image/png")}" alt="${titre}"></body></html>`);
        fenetre.document.close();
        fenetre.onload = () => { fenetre.focus(); fenetre.print(); };
    }

    function finaliserExport(canvas, nom, format, titre) {
        if (format === "pdf") imprimerCanvas(canvas, titre);
        else telechargerCanvas(canvas, nom);
    }

    function afficherChoixExport(bouton, callback, formats = [["PNG", "png"], ["PDF", "pdf"]]) {
        document.querySelectorAll(".statistiques-export-menu").forEach((menu) => menu.remove());
        const menu = document.createElement("div");
        menu.className = "statistiques-export-menu";
        formats.forEach(([libelle, format]) => {
            const choix = document.createElement("button");
            choix.type = "button"; choix.textContent = libelle;
            choix.addEventListener("click", () => { menu.remove(); callback(format); });
            menu.appendChild(choix);
        });
        bouton.parentElement.classList.add("statistiques-export-ancre");
        bouton.parentElement.appendChild(menu);
        requestAnimationFrame(() => menu.classList.add("is-visible"));
    }

    function telechargerTracesGeojson() {
        if (!selectTypeCarte.value) return;
        const parametres = new URLSearchParams(new FormData(form));
        parametres.set("type_carte", selectTypeCarte.value);
        ajouterParametresCarte(parametres);
        parametres.set("export", "geojson");
        const lien = document.createElement("a");
        lien.href = `${dashboard.dataset.carteUrl}?${parametres}`;
        lien.download = "";
        lien.click();
    }

    function ecrireTexteMultiligne(ctx, texte, x, y, largeurMaximum, hauteurLigne, maximumLignes = 3) {
        const mots = texte.split(/\s+/);
        let ligne = "";
        let numeroLigne = 0;
        mots.forEach((mot) => {
            const essai = ligne ? `${ligne} ${mot}` : mot;
            if (ctx.measureText(essai).width > largeurMaximum && ligne && numeroLigne < maximumLignes - 1) {
                ctx.fillText(ligne, x, y + numeroLigne * hauteurLigne);
                ligne = mot;
                numeroLigne += 1;
            } else {
                ligne = essai;
            }
        });
        if (ligne) ctx.fillText(ligne, x, y + numeroLigne * hauteurLigne);
    }

    function fondCarte(ctx, titre, x, y, largeur, hauteur) {
        ctx.fillStyle = "#fff"; ctx.fillRect(x, y, largeur, hauteur);
        ctx.strokeStyle = "#d8e0da"; ctx.strokeRect(x, y, largeur, hauteur);
        ctx.fillStyle = "#213129"; ctx.font = "bold 23px Segoe UI, Arial"; ctx.fillText(titre, x + 24, y + 38);
    }

    function dessinerBarresCanvas(ctx, items, x, y, largeur, hauteur, couleurs = false, couleurFixe = "#55a68a") {
        const maximum = Math.max(...items.map((item) => item.valeur), 1);
        const pas = Math.min(34, (hauteur - 20) / Math.max(items.length, 1));
        items.forEach((item, index) => {
            const ligneY = y + index * pas;
            ctx.fillStyle = "#65736b"; ctx.font = "14px Segoe UI, Arial"; ctx.fillText(item.label.slice(0, 43), x, ligneY);
            ctx.fillStyle = couleurs ? couleurType(item.label, index) : couleurFixe;
            ctx.fillRect(x + largeur * .56, ligneY - 12, largeur * .34 * item.valeur / maximum, 13);
            ctx.fillStyle = "#213129"; ctx.font = "bold 14px Segoe UI, Arial"; ctx.fillText(String(item.valeur), x + largeur * .93, ligneY);
        });
    }

    function dessinerDonutCanvas(ctx, items, x, y, rayon) {
        const total = items.reduce((somme, item) => somme + item.valeur, 0);
        if (!total) return;
        let angle = -Math.PI / 2;
        items.forEach((item, index) => {
            const fin = angle + item.valeur / total * Math.PI * 2;
            ctx.beginPath(); ctx.arc(x, y, rayon, angle, fin); ctx.arc(x, y, rayon * .56, fin, angle, true); ctx.closePath();
            ctx.fillStyle = couleurType(item.label, index); ctx.fill(); angle = fin;
        });
        ctx.fillStyle = "#213129"; ctx.font = "bold 24px Segoe UI, Arial"; ctx.textAlign = "center"; ctx.fillText(String(total), x, y + 8); ctx.textAlign = "left";
    }

    function dessinerLegendeCanvas(ctx, items, x, y, largeur, hauteur, valeursAdjacentes = false) {
        const total = items.reduce((somme, item) => somme + item.valeur, 0);
        const pas = Math.min(52, hauteur / Math.max(items.length, 1));
        const departY = y + Math.max(0, (hauteur - pas * items.length) / 2);
        items.forEach((item, index) => {
            const ligneY = departY + index * pas;
            ctx.fillStyle = couleurType(item.label, index); ctx.fillRect(x, ligneY + 2, 16, 16);
            const valeur = `${item.valeur}${total ? ` (${Math.round(item.valeur / total * 100)} %)` : ""}`;
            if (valeursAdjacentes) {
                ctx.fillStyle = "#213129"; ctx.font = "14px Segoe UI, Arial";
                ecrireTexteMultiligne(ctx, `${item.label}  ${valeur}`, x + 27, ligneY + 15, largeur - 30, 16, 2);
            } else {
                ctx.fillStyle = "#213129"; ctx.font = "14px Segoe UI, Arial";
                ecrireTexteMultiligne(ctx, item.label, x + 27, ligneY + 15, largeur - 145, 16, 2);
                ctx.fillStyle = "#213129"; ctx.font = "bold 14px Segoe UI, Arial"; ctx.textAlign = "right";
                ctx.fillText(valeur, x + largeur, ligneY + 15); ctx.textAlign = "left";
            }
        });
    }

    function dessinerColonnesCanvas(ctx, items, x, y, largeur, hauteur, couleur) {
        const maximum = Math.max(...items.map((item) => item.valeur), 1);
        const pas = largeur / Math.max(items.length, 1);
        const libellesCompacts = pas < 68;
        items.forEach((item, index) => {
            const h = item.valeur / maximum * (hauteur - 42);
            ctx.fillStyle = melangerCouleur(couleur, "#e4f0e8", .35 + item.valeur / maximum * .65);
            ctx.fillRect(x + index * pas + pas * .2, y + hauteur - 28 - h, pas * .6, h);
            ctx.fillStyle = "#65736b"; ctx.font = "11px Segoe UI, Arial"; ctx.textAlign = "center";
            ctx.fillText(libellePeriode(item.label, libellesCompacts), x + index * pas + pas / 2, y + hauteur - 8);
        });
        ctx.textAlign = "left";
    }

    function dessinerCourbeCanvas(ctx, items, x, y, largeur, hauteur, couleur) {
        const cumul = evolutionCumulative(items);
        const maximum = Math.max(...cumul.map((item) => item.valeur), 1);
        ctx.strokeStyle = "#dce5df"; ctx.beginPath(); ctx.moveTo(x, y + hauteur); ctx.lineTo(x + largeur, y + hauteur); ctx.stroke();
        ctx.strokeStyle = couleur; ctx.lineWidth = 4; ctx.beginPath();
        cumul.forEach((item, index) => {
            const px = x + (cumul.length === 1 ? largeur / 2 : index * largeur / (cumul.length - 1));
            const py = y + hauteur - item.valeur / maximum * hauteur;
            index ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
        });
        ctx.stroke();
        const intervalle = Math.max(1, Math.ceil(cumul.length / 10));
        const libellesCompacts = largeur / Math.max(cumul.length, 1) < 72;
        cumul.forEach((item, index) => {
            const px = x + (cumul.length === 1 ? largeur / 2 : index * largeur / (cumul.length - 1));
            const py = y + hauteur - item.valeur / maximum * hauteur;
            ctx.fillStyle = "#fff"; ctx.strokeStyle = couleur; ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
            if (index % intervalle === 0 || index === cumul.length - 1) {
                ctx.fillStyle = "#65736b"; ctx.font = "11px Segoe UI, Arial"; ctx.textAlign = "center"; ctx.fillText(libellePeriode(item.label, libellesCompacts), px, y + hauteur + 22);
            }
        });
        ctx.textAlign = "left"; ctx.lineWidth = 1;
    }

    function dessinerImageContenue(ctx, image, x, y, largeur, hauteur) {
        const largeurSource = image.naturalWidth || image.width || largeur;
        const hauteurSource = image.naturalHeight || image.height || hauteur;
        const ratio = Math.min(largeur / largeurSource, hauteur / hauteurSource);
        const largeurFinale = largeurSource * ratio;
        const hauteurFinale = hauteurSource * ratio;
        ctx.drawImage(
            image,
            x + (largeur - largeurFinale) / 2,
            y + (hauteur - hauteurFinale) / 2,
            largeurFinale,
            hauteurFinale,
        );
    }

    function dessinerTuilesCanvas(ctx, items, x, y, largeur, hauteur, logosParTuile = []) {
        const total = items.reduce((somme, item) => somme + item.valeur, 0);
        const colonnes = 2;
        const largeurTuile = (largeur - 16) / colonnes;
        items.forEach((item, index) => {
            const colonne = index % colonnes; const ligne = Math.floor(index / colonnes);
            const tx = x + colonne * (largeurTuile + 16); const ty = y + ligne * 125;
            ctx.fillStyle = "#f7faf8"; ctx.fillRect(tx, ty, largeurTuile, 105);
            ctx.fillStyle = "#213129"; ctx.font = "bold 14px Segoe UI, Arial";
            const logos = logosParTuile[index] || [];
            let debutLogos = tx + 12;
            if (logos.length) {
                ctx.fillText(item.label, tx + 12, ty + 31);
                debutLogos = tx + 12 + ctx.measureText(item.label).width + 9;
            } else {
                ecrireTexteMultiligne(ctx, item.label, tx + 12, ty + 24, largeurTuile - 24, 17, 2);
            }
            logos.forEach((logo, logoIndex) => {
                if (!logo) return;
                dessinerImageContenue(ctx, logo, debutLogos + logoIndex * 35, ty + 11, 28, 28);
            });
            ctx.fillStyle = "#006131"; ctx.font = "bold 27px Segoe UI, Arial"; ctx.fillText(String(item.valeur), tx + 12, ty + 82);
            if (total) { ctx.fillStyle = "#65736b"; ctx.font = "13px Segoe UI, Arial"; ctx.fillText(`(${Math.round(item.valeur / total * 100)} %)`, tx + 55, ty + 81); }
        });
    }

    async function exporterPng(format = "png") {
        if (!dernieresDonnees) return;
        const ms = dernieresDonnees.manifestations_sportives;
        const msItems = [{label: "Dossiers complets", valeur: ms.complets}, {label: "Démarche Numérique orphelins", valeur: ms.orphelins_dn}, {label: "Déclaration Manifestations orphelins", valeur: ms.orphelins_dm}];
        const afficherMs = !sectionMasquee("manifestations") && ms.visible && msItems.some((item) => item.valeur);
        const afficherCourbe = !sectionMasquee("courbe") && form.querySelectorAll('input[name="mois"]:checked').length !== 1;
        const cartesGauche = [
            ["types", 470], ["evolution", 350],
            ...(afficherCourbe ? [["courbe", 410]] : []),
            ...(dernieresDonnees.repartition_groupes.length ? [["groupes", 410]] : []),
        ].filter(([kind]) => !sectionMasquee(kind));
        const cartesDroite = [
            ["etapes", 470],
            ...(afficherMs ? [["manifestations", 350]] : []),
            ...(dernieresDonnees.repartition_instructeur.length ? [["instructeur", 410]] : []),
            ...(dernieresDonnees.repartition_avis.length ? [["avis", 410]] : []),
        ].filter(([kind]) => !sectionMasquee(kind));
        const hauteurColonne = (cartes) => cartes.reduce((total, [, hauteur]) => total + hauteur + 30, 0);
        const canvas = document.createElement("canvas");
        canvas.width = 1600;
        canvas.height = Math.max(775, 275 + hauteurColonne(cartesGauche), 275 + hauteurColonne(cartesDroite));
        const ctx = canvas.getContext("2d"); ctx.fillStyle = "#f3f6f4"; ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#213129"; ctx.font = "bold 40px Segoe UI, Arial"; ctx.fillText("Statistiques des dossiers", 50, 62);
        ctx.fillStyle = "#65736b"; ctx.font = "18px Segoe UI, Arial"; ecrireTexteMultiligne(ctx, `Filtres : ${filtresActifs()}`, 50, 100, 1500, 23, 2);
        const kpis = [["Total", dernieresDonnees.indicateurs.total], ["Réception", dernieresDonnees.indicateurs.reception], ["Instruction", dernieresDonnees.indicateurs.instruction], ["Terminés", dernieresDonnees.indicateurs.termines], ["Délai moyen", dernieresDonnees.indicateurs.delai_moyen_jours === null ? "—" : `${dernieresDonnees.indicateurs.delai_moyen_jours} j`]];
        kpis.forEach(([label, valeur], index) => { const x = 50 + index * 305; ctx.fillStyle = "#fff"; ctx.fillRect(x, 140, 285, 105); ctx.fillStyle = "#65736b"; ctx.font = "16px Segoe UI, Arial"; ctx.fillText(label, x + 18, 172); ctx.fillStyle = "#213129"; ctx.font = "bold 32px Segoe UI, Arial"; ctx.fillText(String(valeur), x + 18, 220); });

        let yGauche = 275;
        let yDroite = 275;
        if (!sectionMasquee("types")) {
            fondCarte(ctx, "Répartition par type de dossier", 50, yGauche, 930, 470);
            dessinerDonutCanvas(ctx, dernieresDonnees.repartition_types, 260, yGauche + 230, 145);
            dessinerLegendeCanvas(ctx, dernieresDonnees.repartition_types, 455, yGauche + 60, 490, 380);
            yGauche += 500;
        }
        if (!sectionMasquee("etapes")) {
            fondCarte(ctx, "Répartition par étape", 1010, yDroite, 540, 470);
            dessinerBarresCanvas(ctx, dernieresDonnees.repartition_etapes, 1035, yDroite + 60, 485, 380);
            yDroite += 500;
        }
        if (!sectionMasquee("evolution")) {
            fondCarte(ctx, "Nombre de dossiers déposés par mois", 50, yGauche, 930, 350);
            dessinerColonnesCanvas(ctx, dernieresDonnees.evolution, 80, yGauche + 60, 870, 250, couleurEvolution.value);
            yGauche += 380;
        }

        if (afficherMs) {
            fondCarte(ctx, "Composition des manifestations sportives", 1010, yDroite, 540, 350);
            dessinerTuilesCanvas(ctx, msItems, 1035, yDroite + 70, 485, 230);
            yDroite += 380;
        }
        if (afficherCourbe) {
            fondCarte(ctx, "Courbe cumulative des dossiers reçus", 50, yGauche, 930, 410);
            dessinerCourbeCanvas(ctx, dernieresDonnees.evolution_courbe, 90, yGauche + 70, 840, 270, couleurCourbe.value);
            yGauche += 440;
        }
        if (!sectionMasquee("instructeur") && dernieresDonnees.repartition_instructeur.length) {
            fondCarte(ctx, "Répartition par rôle et agent", 1010, yDroite, 540, 410);
            const select = document.getElementById("stats-instructeur");
            const role = document.getElementById("stats-role");
            if (select.value) { ctx.fillStyle = "#213129"; ctx.font = "bold 16px Segoe UI, Arial"; ctx.fillText(`Rôle : ${role.options[role.selectedIndex].text}   Agent : ${select.options[select.selectedIndex].text}`, 1035, yDroite + 83); }
            dessinerDonutCanvas(ctx, dernieresDonnees.repartition_instructeur, 1138, yDroite + 235, 94);
            dessinerLegendeCanvas(ctx, dernieresDonnees.repartition_instructeur, 1248, yDroite + 115, 277, 260);
            yDroite += 440;
        }
        if (!sectionMasquee("avis") && dernieresDonnees.repartition_avis.length) {
            fondCarte(ctx, "Répartition des demandes d’avis", 1010, yDroite, 540, 410);
            const expert = document.getElementById("stats-expert");
            if (expert.value) { ctx.fillStyle = "#213129"; ctx.font = "bold 16px Segoe UI, Arial"; ctx.fillText(`Expert : ${expert.options[expert.selectedIndex].text}`, 1035, yDroite + 65); }
            dessinerDonutCanvas(ctx, dernieresDonnees.repartition_avis, 1138, yDroite + 230, 94);
            dessinerLegendeCanvas(ctx, dernieresDonnees.repartition_avis, 1248, yDroite + 100, 277, 260);
            yDroite += 440;
        }
        if (!sectionMasquee("groupes") && dernieresDonnees.repartition_groupes.length) {
            fondCarte(ctx, "Répartition par groupe d’instruction", 50, yGauche, 930, 410);
            dessinerBarresCanvas(ctx, dernieresDonnees.repartition_groupes, 80, yGauche + 75, 850, 290, false, couleurGroupes.value);
            yGauche += 440;
        }
        finaliserExport(canvas, "statistiques-agida", format, "Statistiques AGIDA");
    }

    async function exporterModule(bloc, format = "png") {
        if (!dernieresDonnees) return;
        const kind = bloc.dataset.exportKind;
        let items = [];
        if (kind === "types") items = dernieresDonnees.repartition_types;
        if (kind === "etapes") items = dernieresDonnees.repartition_etapes;
        if (kind === "evolution") items = dernieresDonnees.evolution;
        if (kind === "courbe") items = evolutionCumulative(dernieresDonnees.evolution_courbe);
        if (kind === "instructeur") items = dernieresDonnees.repartition_instructeur;
        if (kind === "avis") items = dernieresDonnees.repartition_avis;
        if (kind === "groupes") items = dernieresDonnees.repartition_groupes;
        if (kind === "manifestations") {
            const ms = dernieresDonnees.manifestations_sportives;
            items = [{label: "Dossiers complets", valeur: ms.complets}, {label: "Démarche Numérique orphelins", valeur: ms.orphelins_dn}, {label: "Déclaration Manifestations orphelins", valeur: ms.orphelins_dm}];
        }
        let logosManifestations = [];
        if (kind === "manifestations") {
            const [logoDn, logoDm] = await Promise.all([
                chargerImageStatistiques("/static/instruction/img/icon_DS.png"),
                chargerImageStatistiques("/static/instruction/img/prefet_icon_color.svg"),
            ]);
            logosManifestations = [[logoDn, logoDm], [logoDn], [logoDm]];
        }
        const canvas = document.createElement("canvas");
        canvas.width = 1100; canvas.height = 650;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#213129"; ctx.font = "bold 30px Segoe UI, Arial"; ctx.fillText(bloc.dataset.exportTitle, 45, 55);
        ctx.fillStyle = "#65736b"; ctx.font = "16px Segoe UI, Arial"; ecrireTexteMultiligne(ctx, `Filtres : ${filtresActifs()}`, 45, 88, 1000, 21, 2);
        if (kind === "instructeur") {
            const select = document.getElementById("stats-instructeur");
            const role = document.getElementById("stats-role");
            if (select.value) { ctx.fillStyle = "#213129"; ctx.font = "bold 18px Segoe UI, Arial"; ctx.fillText(`Rôle : ${role.options[role.selectedIndex].text}   Agent : ${select.options[select.selectedIndex].text}`, 45, 125); }
        }
        if (kind === "avis") {
            const expert = document.getElementById("stats-expert");
            if (expert.value) { ctx.fillStyle = "#213129"; ctx.font = "bold 18px Segoe UI, Arial"; ctx.fillText(`Expert : ${expert.options[expert.selectedIndex].text}`, 45, 125); }
        }
        if (kind === "types" || kind === "instructeur" || kind === "avis") {
            dessinerDonutCanvas(ctx, items, 260, 365, 155);
            dessinerLegendeCanvas(ctx, items, 480, 155, 565, 420, kind === "instructeur" || kind === "avis");
        } else if (kind === "evolution") {
            dessinerColonnesCanvas(ctx, items, 65, 145, 970, 420, couleurEvolution.value);
        } else if (kind === "courbe") {
            // La fonction applique elle-même le cumul aux données mensuelles brutes.
            dessinerCourbeCanvas(ctx, dernieresDonnees.evolution_courbe, 75, 155, 950, 385, couleurCourbe.value);
        } else if (kind === "manifestations") {
            dessinerTuilesCanvas(ctx, items, 55, 145, 990, 400, logosManifestations);
        } else {
            dessinerBarresCanvas(ctx, items, 55, 145, 990, 440, false, kind === "groupes" ? couleurGroupes.value : "#55a68a");
        }
        finaliserExport(canvas, `statistiques-${kind}`, format, bloc.dataset.exportTitle);
    }

    async function actualiser() {
        if (requeteEnCours) requeteEnCours.abort();
        const controleur = new AbortController();
        requeteEnCours = controleur;
        chargement.hidden = false;
        erreur.hidden = true;
        try {
            const parametres = new URLSearchParams(new FormData(form));
            const instructeur = document.getElementById("stats-instructeur").value;
            if (instructeur) parametres.append("instructeur", instructeur);
            parametres.append("role", document.getElementById("stats-role").value);
            const expert = document.getElementById("stats-expert").value;
            if (expert) parametres.append("expert", expert);
            const reponse = await fetch(`${dashboard.dataset.url}?${parametres}`, {headers: {"X-Requested-With": "XMLHttpRequest"}, signal: controleur.signal});
            if (!reponse.ok) throw new Error("Impossible de charger les statistiques.");
            const donnees = await reponse.json();
            dernieresDonnees = donnees;
            document.getElementById("statistiques-resume-impression").textContent = `Filtres : ${filtresActifs()}`;
            afficherIndicateurs(donnees.indicateurs);
            dessinerDonut(donnees.repartition_types);
            dessinerEtapes(donnees.repartition_etapes);
            dessinerManifestations(donnees.manifestations_sportives);
            dessinerEvolution(donnees.evolution);
            dessinerCourbe(donnees.evolution_courbe);
            dessinerInstructeur(donnees.repartition_instructeur);
            dessinerAvis(donnees.repartition_avis);
            dessinerGroupes(donnees.repartition_groupes);
        } catch (exception) {
            if (exception.name === "AbortError") return;
            erreur.textContent = exception.message;
            erreur.hidden = false;
        } finally {
            if (requeteEnCours === controleur) chargement.hidden = true;
        }
    }

    initialiserMultiselects();
    initialiserMasquageSections();
    initialiserCarteDensite();
    detailCarte.querySelector(".statistiques-carte-detail-fermer").addEventListener("click", fermerDetailCarte);
    detailCarte.addEventListener("click", (event) => event.stopPropagation());
    document.addEventListener("click", (event) => {
        if (event.target.closest(".statistiques-carte-detail, .leaflet-popup, .statistiques-compteur-carte")) return;
        fermerTousPopupsCarte();
    });
    form.addEventListener("change", () => {
        const typeCarteModifie = synchroniserTypeCarteAvecFiltresGlobaux();
        actualiser();
        actualiserCarteDensite(typeCarteModifie);
    });
    document.getElementById("statistiques-reset").addEventListener("click", () => {
        form.querySelectorAll('input[type="checkbox"]').forEach((item) => { item.checked = item.defaultChecked; });
        form.querySelectorAll("select").forEach((select) => { select.selectedIndex = 0; });
        document.querySelectorAll(".statistiques-section-masquee").forEach((section) => section.classList.remove("statistiques-section-masquee"));
        document.getElementById("stats-role").value = roleParDefaut;
        selectTypeCarte.value = "";
        actualiserAgentsRole(false, agentParDefaut);
        document.querySelectorAll(".statistiques-multiselect").forEach((bloc) => bloc.rafraichirLibelle());
        actualiser();
        actualiserCarteDensite();
    });
    document.getElementById("stats-export-dashboard").addEventListener("click", (event) => afficherChoixExport(event.currentTarget, (format) => exporterPng(format)));
    document.querySelectorAll(".statistiques-download-card").forEach((bouton) => bouton.addEventListener("click", () => {
        const bloc = bouton.closest(".statistiques-section-exportable");
        const estCarte = bloc.dataset.exportKind === "carte";
        if (estCarte) {
            afficherChoixExport(bouton, (format) => {
                if (format === "geojson") telechargerTracesGeojson();
            }, [["GeoJSON", "geojson"]]);
            return;
        }
        afficherChoixExport(bouton, (format) => {
            exporterModule(bloc, format);
        });
    }));
    document.getElementById("stats-role").addEventListener("change", () => { actualiserAgentsRole(true); actualiser(); });
    document.getElementById("stats-instructeur").addEventListener("change", actualiser);
    document.getElementById("stats-expert").addEventListener("change", actualiser);
    selectTypeCarte.addEventListener("change", () => actualiserCarteDensite(true));
    couleurEvolution.addEventListener("change", () => { localStorage.setItem("agida-stats-couleur-evolution", couleurEvolution.value); if (dernieresDonnees) dessinerEvolution(dernieresDonnees.evolution); });
    couleurCourbe.addEventListener("change", () => { localStorage.setItem("agida-stats-couleur-courbe", couleurCourbe.value); if (dernieresDonnees) dessinerCourbe(dernieresDonnees.evolution_courbe); });
    couleurGroupes.addEventListener("change", () => { localStorage.setItem("agida-stats-couleur-groupes", couleurGroupes.value); if (dernieresDonnees) dessinerGroupes(dernieresDonnees.repartition_groupes); });
    couleurCarte.addEventListener("change", () => {
        localStorage.setItem("agida-stats-couleur-carte", couleurCarte.value);
        actualiserDegradeCarte();
        actualiserStyleDensite?.();
    });
    window.addEventListener("resize", () => {
        carteDensite?.invalidateSize({pan: false});
        actualiserStyleDensite?.();
    });
    document.getElementById("stats-role").value = roleParDefaut;
    actualiserDegradeCarte();
    actualiserAgentsRole(false, agentParDefaut);
    synchroniserTypeCarteAvecFiltresGlobaux();
    actualiser();
    actualiserCarteDensite();
})();
