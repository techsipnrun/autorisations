(() => {
    "use strict";
    const attente = document.querySelector("[data-notes-loading]");
    let enCours = false;

    function afficherChargement(titre) {
        if (!attente) return;
        // Sortir des colonnes pour couvrir toute la page, comme le retour en instruction.
        document.body.appendChild(attente);
        attente.querySelector("[data-notes-loading-titre]").textContent = titre;
        attente.hidden = false;
    }

    window.addEventListener("pageshow", event => {
        if (!event.persisted) return;
        if (attente) attente.hidden = true;
        enCours = false;
        document.querySelectorAll(".notes_instructeurs .form-ajout-annexe").forEach(form => {
            form.removeAttribute("aria-busy");
            form.querySelector("label").removeAttribute("aria-disabled");
            form.querySelector(".annexe-input").disabled = false;
        });
    });

    document.querySelectorAll(".notes_instructeurs .form-note, .notes_instructeurs .form-supprimer-annexe").forEach(form => {
        form.addEventListener("submit", event => {
            if (event.defaultPrevented) return;
            if (enCours) {
                event.preventDefault();
                return;
            }
            enCours = true;
            const titre = form.classList.contains("form-supprimer-annexe")
                ? "Suppression de l’annexe en cours…"
                : event.submitter?.classList.contains("note-action-delete")
                    ? "Suppression de la note en cours…" : "Enregistrement de la note en cours…";
            afficherChargement(titre);
            // Soumission native : conserver les redirections et formaction existants.
        });
    });

    document.querySelectorAll(".notes_instructeurs .form-ajout-annexe").forEach(form => {
        const input = form.querySelector(".annexe-input");
        const bloc = form.closest(".notes_instructeurs");
        const statut = bloc.querySelector("[data-annexe-upload-status]");
        let emplacements = [];
        try {
            emplacements = JSON.parse(document.getElementById("emplacements-existants")?.textContent || "[]");
        } catch (erreur) {
            console.warn("Impossible de lire les annexes existantes.", erreur);
        }
        input.addEventListener("change", () => {
            if (!input.files[0] || enCours) return;
            const emplacement = `${input.dataset.dossier.replace(/\/?$/, "/")}Annexes/${input.files[0].name}`;
            if (emplacements.includes(emplacement) && !confirm(`Un fichier nommé « ${input.files[0].name} » existe déjà. Voulez-vous le remplacer ?`)) {
                input.value = "";
                return;
            }
            form.requestSubmit();
        });
        form.addEventListener("submit", async event => {
            event.preventDefault();
            if (enCours || !input.files[0]) return;
            const donnees = new FormData(form);
            enCours = true;
            input.disabled = true;
            form.setAttribute("aria-busy", "true");
            form.querySelector("label").setAttribute("aria-disabled", "true");
            statut.hidden = true;
            statut.classList.remove("is-error");
            afficherChargement("Ajout de l’annexe en cours…");
            let navigationEnCours = false;
            try {
                const response = await fetch(form.action, {
                    method: "POST", body: donnees,
                    headers: {"Accept": "application/json"}, credentials: "same-origin",
                });
                if (response.redirected || !response.headers.get("content-type")?.includes("application/json")) {
                    throw new Error("Réponse inattendue du serveur. Vérifiez votre session puis réessayez.");
                }
                const resultat = await response.json();
                if (!response.ok || !resultat.success) throw new Error(resultat.error || "L’annexe n’a pas pu être ajoutée.");
                try {
                    sessionStorage.setItem(`notes-scroll:${window.location.pathname}`, String(window.scrollY));
                } catch { /* Le stockage navigateur ne doit pas bloquer un upload réussi. */ }
                window.location.reload();
                navigationEnCours = true;
            } catch (erreur) {
                statut.hidden = false;
                statut.classList.add("is-error");
                statut.querySelector("span").textContent = erreur.message || "Impossible d’ajouter l’annexe. Réessayez.";
            } finally {
                // Ne pas retirer le chargement avant que la nouvelle page soit affichée.
                if (!navigationEnCours) {
                    if (attente) attente.hidden = true;
                    form.removeAttribute("aria-busy");
                    form.querySelector("label").removeAttribute("aria-disabled");
                    input.disabled = false;
                    input.value = "";
                    enCours = false;
                }
            }
        });
    });
})();
