document.addEventListener("DOMContentLoaded", () => {
    const racine = document.querySelector("[data-avis-thematiques]");
    if (!racine) return;
    const liste = racine.querySelector("[data-theme-liste]");
    const ajout = racine.querySelector("[data-theme-ajout]");
    const recherche = racine.querySelector("[data-theme-recherche]");
    const filtre = racine.querySelector("[data-theme-filtre]");
    const statut = racine.querySelector("[data-theme-statut]");
    let charge = false, enCours = false, categories = [];
    function signaler(cible, texte, erreur = false) {
        cible.textContent = texte;cible.className = erreur ? "is-error" : "is-success";
    }
    function remplir(select, valeur) {
        select.replaceChildren(...categories.map(c => new Option(c.libelle, c.valeur)));
        select.value = valeur;
    }
    function filtrer() {
        let visibles = 0;
        liste.querySelectorAll("form").forEach(form => {
            const trouve = form.elements.thematique.value.toLocaleLowerCase("fr").includes(recherche.value.trim().toLocaleLowerCase("fr"));
            form.hidden = !trouve || (filtre.value !== "__tous__" && form.elements.demarche.value !== filtre.value);
            if (!form.hidden) visibles++;
        });
        signaler(statut, `${visibles} thématique(s) affichée(s).`);
        liste.hidden = visibles === 0;
        racine.querySelector("[data-theme-vide]").hidden = visibles !== 0;
    }
    async function enregistrer(form, id = null) {
        const bouton = form.querySelector("button[type=submit]");
        const message = form.querySelector("[data-theme-message]");
        bouton.disabled = true;form.dataset.enCours = "true";signaler(message, "Enregistrement…");
        try {
            const reponse = await fetch(racine.dataset.url, {method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": racine.querySelector("[name=csrfmiddlewaretoken]").value},
                body: JSON.stringify({id, thematique: form.elements.thematique.value, demarche: form.elements.demarche.value})});
            const resultat = await reponse.json();
            if (!reponse.ok || !resultat.success) throw new Error(resultat.error || "Enregistrement impossible.");
            window.dispatchEvent(new Event("avis-thematiques-modifiees"));
            form.classList.remove("is-dirty");
            if (id === null) {
                liste.append(ligne(resultat.thematique));form.reset();remplir(form.elements.demarche, "Autre");
                filtrer();signaler(message, "Thématique ajoutée.");
            } else {
                form.elements.thematique.value = resultat.thematique.thematique;
                signaler(message, "Thématique enregistrée. Les formulaires utiliseront ce rattachement à leur prochaine ouverture.");
            }
        } catch (erreur) {signaler(message, erreur.message || "La requête a échoué. Votre saisie est conservée.", true);}
        finally {bouton.disabled = false;delete form.dataset.enCours;}
    }
    function ligne(theme) {
        const form = document.createElement("form");form.className = "bo-avis-theme-form";form.dataset.themeId = theme.id;
        const nom = document.createElement("label");nom.textContent = "Thématique";
        const input = document.createElement("input");input.name = "thematique";input.value = theme.thematique;input.maxLength = 180;input.required = true;nom.append(input);
        const rattachement = document.createElement("label");rattachement.textContent = "Rattachement";
        const select = document.createElement("select");select.name = "demarche";remplir(select, theme.demarche);rattachement.append(select);
        const bouton = document.createElement("button");bouton.type = "submit";bouton.textContent = "Enregistrer";
        bouton.className = "bo-avis-theme-save";
        const message = document.createElement("p");message.dataset.themeMessage = "";message.setAttribute("role", "status");message.setAttribute("aria-live", "polite");
        form.append(nom, rattachement, bouton, message);
        form.addEventListener("submit", event => {event.preventDefault();if (!form.dataset.enCours) enregistrer(form, theme.id);});
        return form;
    }
    async function charger() {
        if (charge || enCours || location.hash !== "#avis/thematiques") return;
        enCours = true;signaler(statut, "Chargement…");
        try {
            const reponse = await fetch(racine.dataset.url, {credentials: "same-origin"});
            if (!reponse.ok) throw new Error("Impossible de charger les thématiques. Vérifiez votre session.");
            const donnees = await reponse.json();categories = donnees.categories;
            const fragment = document.createDocumentFragment();donnees.thematiques.forEach(theme => fragment.append(ligne(theme)));
            liste.replaceChildren(fragment);remplir(ajout.elements.demarche, "Autre");
            categories.forEach(c => filtre.append(new Option(c.libelle, c.valeur)));
            ajout.querySelector("button").disabled = false;charge = true;filtrer();
        } catch (erreur) {signaler(statut, erreur.message, true);}
        finally {enCours = false;}
    }
    const marquerModification = event => {
        const form = event.target.closest("form");if (form) form.classList.add("is-dirty");
    };
    racine.addEventListener("input", marquerModification);racine.addEventListener("change", marquerModification);
    ajout.addEventListener("submit", event => {event.preventDefault();if (!ajout.dataset.enCours) enregistrer(ajout);});
    recherche.addEventListener("input", filtrer);filtre.addEventListener("change", filtrer);
    window.addEventListener("beforeunload", event => {if (racine.querySelector("form.is-dirty")) {event.preventDefault();event.returnValue = "";}});
    window.addEventListener("hashchange", charger);charger();
});
