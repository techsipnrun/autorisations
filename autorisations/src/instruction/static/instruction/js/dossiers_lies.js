document.addEventListener("DOMContentLoaded", () => {
    const panel = document.getElementById("dossiers-lies-panel");
    const ouvrir = document.querySelector(".btn-lier-dossiers");

    function statut(element, texte, etat = "") {
        element.textContent = texte;
        element.classList.toggle("is-error", etat === "error");
        element.classList.toggle("is-loading", etat === "loading");
    }

    function afficherChargement(visible, titre = "", detail = "") {
        const loader = document.querySelector(".dossiers-liens-loading");
        if (!loader) return;
        if (visible) document.body.appendChild(loader);
        loader.hidden = !visible;
        if (titre) loader.querySelector("[data-dossiers-liens-loading-titre]").textContent = titre;
        if (detail) loader.querySelector("[data-dossiers-liens-loading-detail]").textContent = detail;
    }

    async function lireReponse(response) {
        if (!response.headers.get("content-type")?.includes("application/json")) {
            throw new Error("Session expirée ou réponse inattendue. Actualisez la page.");
        }
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "L'opération n'a pas pu aboutir.");
        return data;
    }

    async function envoyer(url, csrf, cibleId, jeton) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
            body: new URLSearchParams({ cible_id: cibleId, jeton }),
        });
        return lireReponse(response);
    }

    if (panel && ouvrir) {
        document.body.appendChild(panel);
        const form = panel.querySelector("form");
        const message = panel.querySelector(".dossiers-liens-statut");
        const resultats = panel.querySelector(".dossiers-liens-resultats");
        const validation = panel.querySelector(".dossiers-liens-validation");
        const confirmer = panel.querySelector("[data-confirmer-liaison]");
        const pagination = panel.querySelector(".dossiers-liens-pagination");
        const precedent = panel.querySelector("[data-page-precedente]");
        const suivant = panel.querySelector("[data-page-suivante]");
        const demandeur = form.elements.demandeur;
        const demandeurLibelle = form.elements.demandeur_libelle;
        const listeDemandeurs = panel.querySelector("#dossiers-liens-demandeurs");
        let suggestionsDemandeurs = new Map();
        let rechercheDemandeur = null;
        let page = 1;
        let selection = null;
        let requete = null;
        let enregistrement = false;

        function positionner() {
            const navbar = document.querySelector(".navigation_header");
            const bas = Math.max(0, navbar?.getBoundingClientRect().bottom || 80);
            panel.style.setProperty("--dossiers-liens-top", `${bas + 10}px`);
            panel.style.setProperty("--dossiers-liens-centre", `${bas + 10 + (window.innerHeight - bas - 10) / 2}px`);
        }

        function fermer(rendreFocus = true) {
            if (enregistrement) return;
            panel.hidden = true;
            ouvrir.setAttribute("aria-expanded", "false");
            requete?.abort();
            if (rendreFocus) ouvrir.focus();
        }

        async function suggererDemandeurs() {
            rechercheDemandeur?.abort();
            const controleur = new AbortController();
            rechercheDemandeur = controleur;
            try {
                const params = new URLSearchParams({ term: demandeurLibelle.value.trim() });
                const response = await fetch(`${panel.dataset.demandeursUrl}?${params}`, {
                    signal: controleur.signal,
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                const suggestions = await lireReponse(response);
                if (rechercheDemandeur !== controleur) return;
                suggestionsDemandeurs = new Map(suggestions.map((item) => [item.label, String(item.id)]));
                listeDemandeurs.replaceChildren(...suggestions.map((item) => {
                    const option = document.createElement("option");
                    option.value = item.label;
                    return option;
                }));
                demandeur.value = suggestionsDemandeurs.get(demandeurLibelle.value.trim()) || "";
            } catch (error) {
                if (error.name !== "AbortError") listeDemandeurs.replaceChildren();
            }
        }

        async function rechercher(nouvellePage = 1) {
            if (enregistrement) return;
            requete?.abort();
            const controleur = new AbortController();
            requete = controleur;
            selection = null;
            validation.hidden = true;
            pagination.hidden = true;
            resultats.replaceChildren();
            statut(message, "Recherche en cours…", "loading");
            resultats.setAttribute("aria-busy", "true");
            const params = new URLSearchParams({ page: nouvellePage });
            ["demandeur", "recherche", "demarche", "etape"].forEach((nom) => {
                params.set(nom, form.elements[nom].value);
            });
            try {
                const response = await fetch(`${panel.dataset.searchUrl}?${params}`, {
                    signal: controleur.signal,
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                const data = await lireReponse(response);
                if (requete !== controleur) return;
                page = data.page;
                data.resultats.forEach((resultat) => {
                    const bouton = document.createElement("button");
                    bouton.type = "button";
                    bouton.className = "dossiers-liens-resultat";
                    bouton.setAttribute("aria-pressed", "false");
                    const titre = document.createElement("strong");
                    titre.textContent = `${resultat.dossiers.length > 1 ? "Dossiers" : "Dossier"} `
                        + resultat.dossiers.map((d) => d.numero).join(" - ");
                    bouton.append(titre);
                    resultat.dossiers.forEach((dossier) => {
                        const detail = document.createElement("small");
                        detail.textContent = `${dossier.nom} · ${dossier.demarche}`
                            + ` · ${dossier.etape} · ${dossier.demandeur}`;
                        bouton.append(detail);
                    });
                    bouton.addEventListener("click", () => {
                        if (enregistrement) return;
                        resultats.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
                        bouton.setAttribute("aria-pressed", "true");
                        selection = resultat;
                        const numeros = [...data.source, ...resultat.dossiers].map((d) => d.numero);
                        panel.querySelector("[data-resume-liaison]").textContent =
                            `Les ${numeros.length} dossiers suivants seront liés entre eux : ${numeros.join(", ")}.`;
                        validation.hidden = false;
                    });
                    resultats.append(bouton);
                });
                statut(message, data.resultats.length
                    ? "Sélectionnez un dossier ou un ensemble de dossiers."
                    : "Aucun dossier ne correspond aux filtres. Vous pouvez sélectionner « Tous les demandeurs ».");
                pagination.hidden = !(page > 1 || data.suite);
                precedent.disabled = page <= 1;
                suivant.disabled = !data.suite;
                panel.querySelector("[data-page-libelle]").textContent = `Page ${page}`;
            } catch (error) {
                if (error.name !== "AbortError" && requete === controleur) statut(message, error.message, "error");
            } finally {
                if (requete === controleur) resultats.setAttribute("aria-busy", "false");
            }
        }

        ouvrir.addEventListener("click", () => {
            if (!panel.hidden) return fermer();
            document.querySelectorAll(".notification-agents-panel").forEach((p) => { p.hidden = true; });
            document.querySelectorAll(".btn-notifier-agents[aria-expanded]").forEach((b) => b.setAttribute("aria-expanded", "false"));
            positionner();
            panel.hidden = false;
            panel.scrollTop = 0;
            ouvrir.setAttribute("aria-expanded", "true");
            form.elements.recherche.focus({ preventScroll: true });
            rechercher();
        });
        panel.querySelector("[data-fermer-liens]").addEventListener("click", () => fermer());
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !panel.hidden) fermer();
        });
        document.addEventListener("click", (event) => {
            if (!panel.hidden && !panel.contains(event.target) && !ouvrir.contains(event.target)) fermer(false);
        });
        window.addEventListener("resize", positionner);
        const navbar = document.querySelector(".navigation_header");
        if (navbar && window.ResizeObserver) new ResizeObserver(positionner).observe(navbar);
        form.addEventListener("submit", (event) => { event.preventDefault(); rechercher(); });
        demandeurLibelle.addEventListener("focus", suggererDemandeurs);
        demandeurLibelle.addEventListener("input", () => {
            demandeur.value = suggestionsDemandeurs.get(demandeurLibelle.value.trim()) || "";
            suggererDemandeurs();
        });
        demandeurLibelle.addEventListener("change", () => {
            demandeur.value = suggestionsDemandeurs.get(demandeurLibelle.value.trim()) || "";
        });
        form.addEventListener("input", () => {
            requete?.abort();
            selection = null;
            validation.hidden = true;
            resultats.replaceChildren();
            pagination.hidden = true;
            statut(message, "Cliquez sur Rechercher pour appliquer les filtres.");
        });
        precedent.addEventListener("click", () => rechercher(page - 1));
        suivant.addEventListener("click", () => rechercher(page + 1));
        confirmer.addEventListener("click", async () => {
            if (!selection || enregistrement) return;
            if (!window.confirm("Confirmez-vous la liaison de ces dossiers ?")) return;
            enregistrement = true;
            panel.querySelectorAll("button, input, select").forEach((element) => { element.disabled = true; });
            statut(message, "Enregistrement des liens…", "loading");
            afficherChargement(true, "Liaison des dossiers en cours…", "Veuillez patienter pendant l’enregistrement des liens.");
            try {
                // Laisse au navigateur le temps de peindre le calque avant l'appel réseau.
                await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                await envoyer(panel.dataset.addUrl, form.elements.csrfmiddlewaretoken.value,
                    selection.cible_id, selection.jeton);
                window.location.reload();
            } catch (error) {
                enregistrement = false;
                afficherChargement(false);
                panel.querySelectorAll("button, input, select").forEach((element) => { element.disabled = false; });
                selection = null;
                validation.hidden = true;
                resultats.replaceChildren();
                pagination.hidden = true;
                statut(message, `${error.message} Relancez la recherche.`, "error");
            }
        });
    }

    document.querySelectorAll(".dossiers-lies-bloc").forEach((bloc) => {
        let enregistrement = false;
        bloc.querySelectorAll("[data-retirer-dossier]").forEach((bouton) => {
            bouton.addEventListener("click", async () => {
                if (enregistrement) return;
                if (!window.confirm(`Retirer le lien avec le dossier ${bouton.dataset.numero} ?\n\n`
                    + "Ce dossier sera retiré de l'ensemble. Les autres dossiers resteront liés entre eux s'ils sont plusieurs.")) return;
                enregistrement = true;
                bloc.querySelectorAll("button").forEach((b) => { b.disabled = true; });
                const message = bloc.querySelector(".dossiers-liens-statut");
                statut(message, "Retrait du lien…", "loading");
                afficherChargement(true, "Retrait du lien en cours…", "Veuillez patienter pendant la mise à jour des dossiers.");
                try {
                    // Laisse au navigateur le temps de peindre le calque avant l'appel réseau.
                    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    await envoyer(bloc.dataset.retirerUrl, bloc.querySelector("[name=csrfmiddlewaretoken]").value,
                        bouton.dataset.retirerDossier, bloc.dataset.jeton);
                    window.location.reload();
                } catch (error) {
                    enregistrement = false;
                    afficherChargement(false);
                    bloc.querySelectorAll("button").forEach((b) => { b.disabled = false; });
                    statut(message, error.message, "error");
                }
            });
        });
    });
});
