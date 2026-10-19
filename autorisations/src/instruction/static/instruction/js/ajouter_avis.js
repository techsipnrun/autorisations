document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("form-avis");
    if (!form) return;
    const actions = form.querySelector(".avis-form-actions");
    const moteur = window.AvisFormulaires?.initialiser(form);
    if (!moteur) return;
    let enCours = false;
    const attente = form.querySelector("[data-avis-loading]");
    function chargement(message) {
        if (!attente) return;
        document.body.appendChild(attente);
        attente.querySelector("[data-avis-loading-titre]").textContent = message;
        attente.hidden = false;
        form.setAttribute("aria-busy", "true");
    }
    function terminerChargement() {
        if (attente) attente.hidden = true;
        form.removeAttribute("aria-busy");
    }
    window.addEventListener("pageshow", event => {
        if (!event.persisted) return;
        terminerChargement();
        enCours = false;
        form.querySelectorAll("button").forEach(button => { button.disabled = false; });
    });
    function soumettre(button, intention) {
        if (enCours || !button || button.hidden) return;
        form.querySelectorAll("[required]").forEach(champ => { champ.required = false; });
        moteur.obligations(intention === "brouillon" ? "brouillon" : "envoi");
        if (!form.checkValidity()) { form.reportValidity(); return; }
        if (intention === "confirmer" && !confirm("Voulez-vous vraiment envoyer la demande d'avis ?")) return;
        form.action = button.getAttribute("formaction").trim();
        window.fermerApercuDocument?.();
        enCours = true;
        form.querySelectorAll("button").forEach(item => { item.disabled = true; });
        chargement(intention === "brouillon" ? "Enregistrement du brouillon…" : "Envoi de la demande…");
        try {
            form.submit();
        } catch (erreur) {
            terminerChargement();
            enCours = false;
            form.querySelectorAll("button").forEach(item => { item.disabled = false; });
            const message = form.querySelector(".avis-form-erreur");
            message.textContent = "L'enregistrement n'a pas pu être lancé. Réessayez.";
            message.hidden = false;
        }
    }

    form.querySelector(".btn-confirmer-envoi").addEventListener("click", event => soumettre(event.currentTarget, "confirmer"));
    form.querySelector(".btn-brouillon").addEventListener("click", event => soumettre(event.currentTarget, "brouillon"));
    form.addEventListener("submit", event => {
        event.preventDefault();
        if (!actions.hidden) soumettre(form.querySelector(".btn-confirmer-envoi"), "confirmer");
    });

    form.querySelectorAll("[data-remplacer-pj]").forEach(button => {
        button.addEventListener("click", () => {
            window.fermerApercuDocument?.();
            document.getElementById(button.dataset.remplacerPj).click();
        });
    });
    form.querySelectorAll("[data-pj-controle] input").forEach(input => {
        input.addEventListener("change", () => {
            const controle = input.closest("[data-pj-controle]");
            const titre = controle.querySelector("[data-pj-titre]");
            const apercu = controle.querySelector(".document-apercu-trigger");
            if (apercu) {
                window.fermerApercuDocument?.();
                apercu.hidden = Boolean(input.files.length);
            }
            if (titre && input.files[0]) {
                titre.textContent = input.files[0].name;
                titre.title = input.files[0].name;
            }
        });
    });
    document.addEventListener("click", event => {
        const controle = event.target.closest("[data-pj-controle]");
        if (!controle?.classList.contains("is-preview-open") || event.target.closest(".avis-pj-action:not(.document-apercu-trigger)")) {
            window.fermerApercuDocument?.();
        }
    });
    const nouvellesPJ = form.querySelector("#pj_lie_avis");
    const listePJ = form.querySelector("[data-pj-a-enregistrer]");
    let fichiersEnAttente = [];
    function afficherNouvellesPJ() {
        const transfert = new DataTransfer();
        fichiersEnAttente.forEach(fichier => transfert.items.add(fichier));
        nouvellesPJ.files = transfert.files;
        listePJ.replaceChildren();
        listePJ.hidden = !fichiersEnAttente.length;
        fichiersEnAttente.forEach((fichier, index) => {
            const ligne = document.createElement("div");
            ligne.className = "avis-pj-ligne avis-pj-nouvelle";
            const titre = document.createElement("span");
            titre.className = "avis-pj-titre";
            titre.textContent = fichier.name;
            titre.title = fichier.name + " — À enregistrer";
            const retirer = document.createElement("button");
            retirer.type = "button";
            retirer.className = "avis-pj-action avis-pj-supprimer";
            retirer.title = "Retirer de la sélection";
            retirer.setAttribute("aria-label", "Retirer " + fichier.name + " de la sélection");
            retirer.addEventListener("click", () => {
                fichiersEnAttente.splice(index, 1);
                afficherNouvellesPJ();
            });
            ligne.append(titre, retirer);
            listePJ.append(ligne);
        });
    }
    nouvellesPJ.addEventListener("change", () => {
        // Le sélecteur natif remplace sa sélection : conserver les ajouts précédents.
        for (const fichier of nouvellesPJ.files) {
            const index = fichiersEnAttente.findIndex(ancien => ancien.name === fichier.name);
            if (index === -1) fichiersEnAttente.push(fichier);
            else fichiersEnAttente[index] = fichier;
        }
        afficherNouvellesPJ();
    });
    form.querySelectorAll("[data-supprimer-pj]").forEach(button => {
        button.addEventListener("click", async () => {
            if (enCours) return;
            if (!confirm("Supprimer ce document ?")) return;
            window.fermerApercuDocument?.();
            const erreur = form.querySelector(".avis-form-erreur");
            erreur.hidden = true;
            enCours = true;
            button.disabled = true;
            chargement("Suppression de la pièce jointe…");
            try {
                const response = await fetch(button.dataset.supprimerPj, {
                    method: "POST", credentials: "same-origin",
                    headers: {"X-CSRFToken": getCookie("csrftoken"), "Accept": "application/json"},
                    body: new URLSearchParams({source: button.dataset.pjSource}),
                });
                const resultat = await response.json();
                if (!response.ok || !resultat.success) throw new Error(resultat.error || "La pièce jointe n'a pas pu être retirée.");
                window.location.reload();
            } catch (e) {
                terminerChargement();
                enCours = false;
                erreur.textContent = e.message || "La suppression a échoué. Réessayez.";
                erreur.hidden = false;
                button.disabled = false;
            }
        });
    });
});

// ---- Fonctions utilitaires ----
// function copierChemin(chemin) {
//     navigator.clipboard.writeText(chemin)
//         .then(() => alert("Chemin copié dans le presse-papiers :\n" + chemin))
//         .catch(err => alert("Impossible de copier le chemin : " + err));
// }

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

// function supprimerDoc(avisId, champ) {
//     if (!confirm("Supprimer ce document ?")) return;
//     fetch(`/avis/${avisId}/supprimer-doc/${champ}/`, {
//         method: "POST",
//         headers: { "X-CSRFToken": "{{ csrf_token }}" }
//     })
//     .then(resp => resp.ok ? location.reload() : alert("Erreur suppression : " + resp.status))
//     .catch(err => alert("Erreur réseau : " + err));
// }

function getCookie(name) {
    return document.cookie
        .split("; ")
        .find(row => row.startsWith(name + "="))
        ?.split("=")[1];
}

function supprimerDoc(avisId, documentId) {
    if (!confirm("Supprimer ce document ?")) return;

    fetch(`/avis/${avisId}/pj/${documentId}/supprimer/`, {
        method: "POST",
        headers: {
            "X-CSRFToken": getCookie("csrftoken")
        }
    })
    .then(resp => resp.ok ? location.reload() : alert("Erreur suppression : " + resp.status))
    .catch(err => alert("Erreur réseau : " + err));
}




