(() => {
    "use strict";
    const menu = document.querySelector("[data-contacts-menu]");
    if (!menu) return;
    const recherche = menu.querySelector("input[type=search]");
    const options = menu.querySelector("[data-contacts-options]");
    const statut = menu.querySelector("[data-contacts-status]");
    let timer, controller;
    let generation = 0;

    function retirerSuggestions() {
        options.querySelectorAll("label").forEach(label => {
            if (!label.querySelector("input").checked) label.remove();
        });
    }

    recherche.addEventListener("input", () => {
        clearTimeout(timer);
        controller?.abort();
        const lecture = ++generation;
        retirerSuggestions();
        const terme = recherche.value.trim();
        if (!terme) {
            statut.textContent = "Saisissez un nom pour ajouter une sélection.";
            return;
        }
        statut.textContent = "Recherche…";
        timer = setTimeout(async () => {
            controller = new AbortController();
            try {
                const reponse = await fetch(`${menu.dataset.url}?term=${encodeURIComponent(terme)}`, {
                    signal: controller.signal,
                    credentials: "same-origin",
                });
                if (!reponse.ok) throw new Error("Recherche indisponible");
                const suggestions = await reponse.json();
                if (lecture !== generation) return;
                const presents = new Set([...options.querySelectorAll("input")].map(input => input.value.toLocaleLowerCase("fr")));
                let ajoutes = 0;
                suggestions.forEach(({value}) => {
                    if (!value || presents.has(value.toLocaleLowerCase("fr"))) return;
                    presents.add(value.toLocaleLowerCase("fr"));
                    const label = document.createElement("label");
                    const input = document.createElement("input");
                    input.type = "checkbox";
                    input.name = "nom";
                    input.value = value;
                    label.append(input, document.createTextNode(value));
                    options.append(label);
                    ajoutes++;
                });
                statut.textContent = ajoutes
                    ? "Cochez les noms souhaités. Vous pouvez poursuivre la recherche."
                    : "Aucune autre proposition. Vos sélections sont conservées.";
            } catch (erreur) {
                if (erreur.name !== "AbortError" && lecture === generation) {
                    statut.textContent = "Impossible de récupérer les propositions. Réessayez.";
                }
            }
        }, 200);
    });

    // Entrée dans la recherche ne doit pas soumettre le formulaire sans sélection.
    recherche.addEventListener("keydown", event => {
        if (event.key === "Enter") event.preventDefault();
    });
    menu.addEventListener("toggle", () => {
        if (menu.open) recherche.focus();
    });
})();
